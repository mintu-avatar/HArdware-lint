// ============================================================================
// samples/security_ctrl.v — Intentionally buggy security controller
// ============================================================================
// This design showcases all 20 NEW lint rules (VLG041–VLG060) that no
// commercial HDL tool (Vivado, Quartus, Spyglass) would flag.
//
// Categories exercised:
//   Reliability      : VLG041, VLG042, VLG043, VLG044, VLG045
//   Maintainability  : VLG046, VLG047, VLG048, VLG049, VLG050
//   Security         : VLG051, VLG052, VLG053, VLG054, VLG055
//   Cognitive        : VLG056, VLG057, VLG058, VLG059, VLG060
// ============================================================================

module security_ctrl #(
    parameter DATA_W    = 32,
    parameter ADDR_W    = 16,
    parameter KEY_WIDTH = 128
) (
    input                  i_clk,
    input                  i_rst_n,
    input  [DATA_W-1:0]    i_data,
    input  [ADDR_W-1:0]    i_addr,
    input                  i_wr_en,
    input                  i_rd_en,
    input  [7:0]           i_cmd,
    output [DATA_W-1:0]    o_rdata,       // VLG042: comb output — never registered
    output                 o_valid,       // VLG042: comb output
    output                 o_error,

    // --- VLG052: Debug ports in production RTL ---
    input                  i_jtag_tdi,
    input                  i_jtag_tms,
    input                  i_jtag_tck,
    output                 o_jtag_tdo,     // VLG052

    // --- VLG047: explode port count past 20 ---
    input                  i_priv_mode,
    input  [3:0]           i_region_sel,
    output                 o_grant,        // VLG055: security signal driven combinationally
    output                 o_secure_ok,    // VLG055
    input                  i_timer_en,
    output [7:0]           o_status,
    input  [1:0]           i_burst_type,
    output                 o_irq
);

    // ===================== PARAMETERS / CONSTANTS =========================

    // VLG054: hardcoded cryptographic key in RTL
    localparam [127:0] AES_KEY    = 128'hDEAD_BEEF_CAFE_BABE_0123_4567_89AB_CDEF;
    localparam [127:0] SECRET_KEY = 128'h0000_1111_2222_3333_4444_5555_6666_7777;

    // FSM states
    localparam S_IDLE     = 4'd0,
               S_READ     = 4'd1,
               S_WRITE    = 4'd2,
               S_CRYPT    = 4'd3,
               S_AUTH     = 4'd4,
               S_RESP     = 4'd5,
               S_ERR      = 4'd6,
               S_FLUSH    = 4'd7,
               S_LOCK     = 4'd8,
               S_UNLOCK   = 4'd9,
               S_KEY_LOAD = 4'd10,
               S_KEY_CHK  = 4'd11,
               S_DMA      = 4'd12,
               S_DMA_DONE = 4'd13;  // 14 states total → VLG056 (>12 branches)

    // === VLG053: key register never zeroed on reset ===
    reg [127:0] cipher_key;

    // VLG051: memory array never cleared on reset
    reg [DATA_W-1:0] sec_mem [0:255];

    // FSM registers
    reg [3:0] state, next_state;
    reg [DATA_W-1:0] data_buf;
    reg [ADDR_W-1:0] addr_buf;
    reg        valid_r;
    reg        error_r;
    reg [7:0]  status_r;

    // VLG043: width-mismatched comparison later
    reg [7:0]  narrow_cnt;
    reg [31:0] wide_threshold;

    // VLG044: shift target
    reg [7:0] shift_reg;

    // VLG045: clock-enable feedback
    reg ce_active;

    // VLG050: repeated magic constant
    wire [DATA_W-1:0] mask0 = 32'hFF00_FF00;
    wire [DATA_W-1:0] mask1 = 32'hFF00_FF00;
    wire [DATA_W-1:0] mask2 = 32'hFF00_FF00;
    wire [DATA_W-1:0] mask3 = 32'hFF00_FF00;  // 4th repetition → VLG050

    // === VLG055 + VLG042: security signals driven combinationally ===
    assign o_grant     = i_priv_mode & (state == S_AUTH);
    assign o_secure_ok = (state != S_ERR);

    // === VLG042: unregistered data outputs ===
    assign o_rdata = data_buf;
    assign o_valid = valid_r;

    // === VLG044: shift by 10, but shift_reg is only 8 bits ===
    wire [7:0] shifted_out = shift_reg >> 10;

    // ===================== FSM — STATE REGISTER ==========================
    always @(posedge i_clk or negedge i_rst_n) begin
        if (!i_rst_n)
            state <= S_IDLE;
        else
            state <= next_state;
    end

    // ===================== FSM — NEXT STATE (VLG041: no timeout) =========
    // VLG048: deeply nested control flow (>3 levels)
    always @(*) begin
        next_state = state;
        case (state)
            S_IDLE: begin
                if (i_wr_en) begin
                    if (i_addr[15]) begin
                        if (i_priv_mode) begin
                            if (i_cmd[7])           // VLG048: 4 levels deep
                                next_state = S_CRYPT;
                            else
                                next_state = S_WRITE;
                        end
                    end else begin
                        next_state = S_READ;
                    end
                end
            end
            S_READ:     next_state = S_RESP;
            S_WRITE:    next_state = S_RESP;
            S_CRYPT:    next_state = S_KEY_LOAD;
            S_AUTH:     next_state = S_RESP;
            S_RESP:     next_state = S_IDLE;
            S_ERR:      next_state = S_IDLE;
            S_FLUSH:    next_state = S_IDLE;
            S_LOCK:     next_state = S_IDLE;
            S_UNLOCK:   next_state = S_IDLE;
            S_KEY_LOAD: next_state = S_KEY_CHK;
            S_KEY_CHK:  next_state = S_AUTH;
            S_DMA:      next_state = S_DMA_DONE;
            S_DMA_DONE: next_state = S_IDLE;
            // VLG056: 14 case branches — exceeds 12 threshold
        endcase
    end

    // ===================== DATA PATH =====================================
    always @(posedge i_clk or negedge i_rst_n) begin
        if (!i_rst_n) begin
            data_buf  <= {DATA_W{1'b0}};
            addr_buf  <= {ADDR_W{1'b0}};
            valid_r   <= 1'b0;
            error_r   <= 1'b0;
            status_r  <= 8'h0;
            // NOTE: cipher_key is NOT zeroed here → VLG053
        end else begin
            case (state)
                S_READ:  data_buf  <= sec_mem[i_addr[7:0]];
                S_WRITE: sec_mem[i_addr[7:0]] <= i_data;
                S_CRYPT: data_buf  <= data_buf ^ cipher_key[DATA_W-1:0];
                default: ;
            endcase
        end
    end

    // VLG045: clock-enable that writes its own CE flag
    always @(posedge i_clk or negedge i_rst_n) begin
        if (!i_rst_n)
            ce_active <= 1'b0;
        else if (ce_active)      // self-referencing CE guard
            ce_active <= ~ce_active;   // livelock: can toggle forever but may also stall
    end

    // VLG043: comparing 8-bit counter against 32-bit threshold (width mismatch ≥4)
    always @(posedge i_clk or negedge i_rst_n) begin
        if (!i_rst_n)
            narrow_cnt <= 8'h0;
        else if (narrow_cnt <= wide_threshold)   // VLG043: 8b vs 32b
            narrow_cnt <= narrow_cnt + 1'b1;
    end

    // VLG057: complex boolean expression (>4 operators)
    wire complex_cond = (i_wr_en & i_rd_en) | (~i_rst_n & i_priv_mode) ^ (i_cmd[0] | i_cmd[1]) & i_addr[0];

    // VLG058: chained ternaries (>2 deep)
    wire [1:0] priority_level = i_priv_mode ? 2'b11 : i_wr_en ? 2'b10 : i_rd_en ? 2'b01 : 2'b00;

    // VLG060: structural instantiation mixed with behavioral always blocks
    dummy_sub u_dummy (
        .clk  (i_clk),
        .data (i_data[7:0])
    );

    assign o_error  = error_r;
    assign o_status = status_r;
    assign o_irq    = error_r;

    // === Extra always blocks to push count past 10 → VLG049 ===
    always @(posedge i_clk) shift_reg    <= i_data[7:0];
    always @(posedge i_clk) wide_threshold <= {24'b0, i_data[7:0]};
    always @(posedge i_clk) cipher_key   <= {i_data, i_data, i_data, i_data};

    // Additional padding always blocks
    reg dummy1, dummy2, dummy3, dummy4, dummy5, dummy6;
    always @(posedge i_clk) dummy1 <= i_data[0];
    always @(posedge i_clk) dummy2 <= i_data[1];
    always @(posedge i_clk) dummy3 <= i_data[2];
    always @(posedge i_clk) dummy4 <= i_data[3];
    always @(posedge i_clk) dummy5 <= i_data[4];
    always @(posedge i_clk) dummy6 <= i_data[5];

endmodule

// ==========================================================================
// VLG059: second module in same file
// ==========================================================================
module dummy_sub (
    input        clk,
    input  [7:0] data
);
    reg [7:0] buf_r;
    always @(posedge clk) buf_r <= data;
endmodule
