// =============================================================================
// mem_ctrl.v
// Simple DRAM-like memory controller FSM
// Triggers: FSM lockup, mixed reset, undriven ports, latch inference
// =============================================================================

`default_nettype none

// Memory Controller FSM — arbitrates read/write requests to a SDRAM-like bus
// Issues: 10 states (binary encoded), many missing defaults, mixed resets.

module mem_ctrl (
    input  wire        i_clk,
    input  wire        i_rst,         // active-high SYNC reset
    input  wire        i_rst_n,       // active-low ASYNC reset — VLG025: mixed polarity!

    // Request interface
    input  wire        i_req,
    input  wire        i_wr,          // 1=write, 0=read
    input  wire [23:0] i_addr,        // VLG002: magic 23
    input  wire [63:0] i_wdata,       // VLG002: magic 63
    output reg  [63:0] o_rdata,       // VLG002: magic 63
    output reg         o_ack,

    // DRAM bus (output)
    output reg         o_dram_cs_n,
    output reg         o_dram_ras_n,
    output reg         o_dram_cas_n,
    output reg         o_dram_we_n,
    output reg  [23:0] o_dram_addr,   // VLG002: magic 23
    output reg  [63:0] o_dram_dq_out, // VLG002: magic 63
    output wire        o_dram_dq_oe,  // VLG031: output enable — never driven!
    output wire        o_error        // VLG031: error flag — never driven!
);

    // -----------------------------------------------------------------------
    // FSM states — 10 states in binary encoding (VLG028: one-hot better here)
    // -----------------------------------------------------------------------
    localparam IDLE       = 4'd0;
    localparam PRECHARGE  = 4'd1;
    localparam ACT_ROW    = 4'd2;
    localparam RCD_WAIT   = 4'd3;
    localparam READ_CMD   = 4'd4;
    localparam CAS_WAIT1  = 4'd5;
    localparam CAS_WAIT2  = 4'd6;
    localparam DATA_RD    = 4'd7;
    localparam WRITE_CMD  = 4'd8;
    localparam DATA_WR    = 4'd9;

    reg [3:0] state, next_state;
    reg [3:0] timer;

    // -----------------------------------------------------------------------
    // VLG023: Mixed reset — state uses ASYNC rst_n, timer uses SYNC rst
    // -----------------------------------------------------------------------
    always @(posedge i_clk or negedge i_rst_n) begin  // async
        if (!i_rst_n)
            state <= IDLE;
        else
            state <= next_state;
    end

    always @(posedge i_clk) begin                      // sync reset
        if (i_rst)
            timer <= 4'd0;
        else if (state != next_state)
            timer <= 4'd0;
        else
            timer <= timer + 1;
    end

    // -----------------------------------------------------------------------
    // Next-state / output decode — combinational
    // VLG027: no default in FSM → illegal state lockup
    // VLG030: all outputs driven combinationally (glitchy on transitions)
    // VLG018: o_ack not assigned in all paths
    // -----------------------------------------------------------------------
    always @(*) begin
        next_state   = state;
        o_dram_cs_n  = 1'b1;
        o_dram_ras_n = 1'b1;
        o_dram_cas_n = 1'b1;
        o_dram_we_n  = 1'b1;
        o_dram_addr  = 24'h0;
        o_dram_dq_out= 64'h0;
        o_ack        = 1'b0;

        case (state)                    // VLG027: no default!
            IDLE: begin
                if (i_req) begin
                    next_state = PRECHARGE;
                end
            end

            PRECHARGE: begin
                o_dram_cs_n  = 1'b0;
                o_dram_ras_n = 1'b0;
                o_dram_we_n  = 1'b0;
                o_dram_addr  = {8'h0, 1'b1, 15'h0}; // all-bank precharge
                if (timer >= 4'd3)
                    next_state = ACT_ROW;
            end

            ACT_ROW: begin
                o_dram_cs_n  = 1'b0;
                o_dram_ras_n = 1'b0;
                o_dram_addr  = i_addr[23:0];
                if (timer >= 4'd2)
                    next_state = RCD_WAIT;
            end

            RCD_WAIT: begin
                if (timer >= 4'd2)
                    next_state = i_wr ? WRITE_CMD : READ_CMD;
            end

            READ_CMD: begin
                o_dram_cs_n  = 1'b0;
                o_dram_cas_n = 1'b0;
                o_dram_addr  = {8'h0, i_addr[15:0]};
                next_state   = CAS_WAIT1;
            end

            CAS_WAIT1: next_state = CAS_WAIT2;
            CAS_WAIT2: next_state = DATA_RD;

            DATA_RD: begin
                // o_rdata assigned in separate clocked block — ok
                o_ack      = 1'b1;   // VLG030: combinational ack pulse — glitchy
                next_state = IDLE;
            end

            WRITE_CMD: begin
                o_dram_cs_n  = 1'b0;
                o_dram_cas_n = 1'b0;
                o_dram_we_n  = 1'b0;
                o_dram_addr  = {8'h0, i_addr[15:0]};
                next_state   = DATA_WR;
            end

            DATA_WR: begin
                o_dram_cs_n   = 1'b0;
                o_dram_dq_out = i_wdata;
                o_ack         = 1'b1;  // VLG030: combinational ack
                next_state    = IDLE;
            end
            // Missing default → if state becomes 4'd10..15 → lock forever! (VLG027)
        endcase
    end

    // -----------------------------------------------------------------------
    // Read data capture
    // VLG024: rst_n used inside but SYNC block (see timer block above)
    // -----------------------------------------------------------------------
    always @(posedge i_clk) begin
        if (i_rst)
            o_rdata <= 64'h0;
        else if (state == DATA_RD)
            o_rdata <= 64'hDEAD_BEEF_CAFE_BABE; // placeholder for real DQ input
    end

    // -----------------------------------------------------------------------
    // VLG011: $monitor for DRAM state trace in RTL — should be in testbench!
    // -----------------------------------------------------------------------
    always @(posedge i_clk) begin
        if (state != next_state)
            $monitor("[MEMCTRL] state %0d -> %0d at time %0t", state, next_state, $time); // VLG011
    end

    // -----------------------------------------------------------------------
    // VLG039: $urandom in RTL (for "stress test" data — shouldn't be here)
    // -----------------------------------------------------------------------
    wire [63:0] rand_data;
    assign rand_data = {$random, $random};  // VLG039

endmodule

`default_nettype wire
