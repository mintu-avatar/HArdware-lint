// ============================================================================
// power_timing_sample.v — Deliberately buggy design to trigger new rules
// VLG061-VLG095 (Power, Reset Integrity, Reusability, Structural Complexity,
// Verifiability, Clock Domain, Timing Complexity)
// ============================================================================

`define GLOBAL_ADDR_WIDTH 16
`define GLOBAL_TIMEOUT    1000

// --- Module 1: Power + Reset Integrity + Reusability + Verifiability --------
module data_processor (
    input         clk,
    input         clk_fast,       // second clock domain → VLG086
    input         rst,
    input         rst_n,          // mixed polarity → VLG066
    input  [31:0] data_in,        // hardcoded width → VLG071
    input  [31:0] coeff,
    input         i_valid,        // mixed naming: i_ prefix vs plain → VLG074
    output [31:0] data_out,       // hardcoded width
    output        valid,
    output        ready,
    input         tdi,            // JTAG debug port → VLG052 (from security)
    output        tdo
);

    // No parameters at all → VLG071 triggers
    // Uses `GLOBAL_ADDR_WIDTH → VLG072
    reg [`GLOBAL_ADDR_WIDTH-1:0] addr_reg;
    reg [31:0] result;
    reg [31:0] pipe_a;
    reg [31:0] pipe_b;
    reg [31:0] pipe_c;
    reg [31:0] pipe_d;
    reg [31:0] accum;
    reg [15:0] count;
    reg        valid_reg;
    reg        done_flag;
    reg        busy;
    reg        start;
    reg [7:0]  status;
    reg [31:0] data_reg;
    wire [31:0] mult_result;

    // Memory without chip-enable → VLG064
    reg [31:0] mem_buf [0:255];

    // No clock gating signal → VLG061
    // No sleep/power-down signal → VLG063
    // No assertion hooks → VLG081

    // --- Clocked block with active-high reset (rst) ---
    always @(posedge clk) begin
        if (rst) begin
            result <= 32'b0;
            // pipe_a NOT reset → VLG067 (incomplete reset)
            pipe_b <= 32'b0;
        end else begin
            result <= data_in + coeff;
            pipe_a <= data_in;
            pipe_b <= pipe_a;
        end
    end

    // --- Clocked block with active-low reset (rst_n) → mixed polarity VLG066 ---
    always @(posedge clk) begin
        if (!rst_n) begin
            accum <= 32'b0;
        end else begin
            accum <= accum + result;
        end
    end

    // --- Clocked block with NO reset at all → VLG070 ---
    // Contains control signals (valid_reg, done_flag, busy, start, count)
    always @(posedge clk) begin
        valid_reg <= i_valid;
        done_flag <= (count == 16'hFFFF);
        busy      <= ~done_flag;
        start     <= i_valid & ~busy;
        count     <= count + 1;
    end

    // --- Wide bus updated every cycle without enable → VLG062 ---
    always @(posedge clk) begin
        if (rst) begin
            data_reg <= 32'b0;
        end else begin
            data_reg <= data_in;       // 32-bit, no enable guard
            pipe_c   <= data_reg;
            pipe_d   <= pipe_c;
        end
    end

    // --- Reset used as data → VLG069 ---
    always @(posedge clk) begin
        if (rst) begin
            status <= 8'b0;
        end else begin
            status <= {7'b0, rst};  // rst on RHS in normal path
        end
    end

    // --- Second clock domain in same module → VLG086 ---
    reg [31:0] fast_reg;
    always @(posedge clk_fast) begin
        fast_reg <= data_in;
    end

    // --- Async reset without synchronizer → VLG068 ---
    reg [7:0] async_cnt;
    always @(posedge clk or posedge rst) begin
        if (rst)
            async_cnt <= 8'b0;
        else
            async_cnt <= async_cnt + 1;
    end

    // --- Redundant toggling → VLG065 ---
    reg [7:0] rd_tog;
    always @(posedge clk) begin
        if (rst) begin
            rd_tog <= 8'b0;
        end else begin
            if (i_valid)
                rd_tog <= 8'hAA;
            else
                rd_tog <= 8'hAA;  // same value in both branches
        end
    end

    // --- Combinational block with feedback loop → VLG093 ---
    reg [7:0] fb_sig;
    always @(*) begin
        fb_sig = fb_sig + 1;   // feedback: fb_sig on both sides
    end

    // --- Long combinational chain → VLG091 ---
    assign mult_result = (data_in & coeff) ^ (data_in | coeff) + (data_in - coeff) * (data_in >> 2) + accum;

    // --- High-complexity always block → VLG076 (CC>15), VLG080 ---
    reg [7:0] complex_out;
    always @(*) begin
        complex_out = 8'b0;
        if (data_in[0])
            if (data_in[1])
                if (data_in[2])
                    if (data_in[3])
                        complex_out = 8'h01;
                    else
                        complex_out = 8'h02;
                else
                    if (data_in[4])
                        complex_out = 8'h03;
                    else
                        complex_out = 8'h04;
            else
                if (data_in[5])
                    if (data_in[6])
                        complex_out = 8'h05;
                    else
                        complex_out = 8'h06;
                else
                    if (data_in[7])
                        complex_out = 8'h07;
                    else
                        complex_out = 8'h08;
        else
            if (data_in[8])
                if (data_in[9])
                    if (data_in[10])
                        if (data_in[11])
                            complex_out = 8'h09;
                        else
                            complex_out = 8'h0A;
                    else
                        complex_out = 8'h0C;
                else
                    if (data_in[12])
                        complex_out = 8'h0D;
                    else if (data_in[13])
                        complex_out = 8'h0E;
                    else
                        complex_out = 8'h0F;
            else
                if (data_in[14])
                    complex_out = 8'h10;
                else
                    complex_out = 8'h0B;
    end

    // --- Deep if/else-if chain → VLG077 ---
    reg [3:0] prio_out;
    always @(*) begin
        if (data_in[31])
            prio_out = 4'hF;
        else if (data_in[30])
            prio_out = 4'hE;
        else if (data_in[29])
            prio_out = 4'hD;
        else if (data_in[28])
            prio_out = 4'hC;
        else if (data_in[27])
            prio_out = 4'hB;
        else if (data_in[26])
            prio_out = 4'hA;
        else if (data_in[25])
            prio_out = 4'h9;
        else if (data_in[24])
            prio_out = 4'h8;
        else
            prio_out = 4'h0;
    end

    // --- Handshake without back-pressure → VLG084 ---
    assign valid    = valid_reg;
    assign ready    = 1'b1;          // always ready — no flow control
    assign data_out = result;

    // --- Extra internal signals to push interconnect ratio → VLG079 ---
    reg [7:0] int_sig_a;
    reg [7:0] int_sig_b;
    reg [7:0] int_sig_c;
    reg [7:0] int_sig_d;
    reg [7:0] int_sig_e;
    reg [7:0] int_sig_f;
    reg [7:0] int_sig_g;
    reg [7:0] int_sig_h;
    reg [7:0] int_sig_i;
    reg [7:0] int_sig_j;
    reg [7:0] int_sig_k;
    reg [7:0] int_sig_l;
    reg [7:0] int_sig_m;
    reg [7:0] int_sig_n;
    reg [7:0] int_sig_o;
    reg [7:0] int_sig_p;
    reg [7:0] int_sig_q;
    reg [7:0] int_sig_r;
    reg [7:0] int_sig_s;
    reg [7:0] int_sig_t;
    reg [7:0] int_sig_u;
    reg [7:0] int_sig_v;
    reg [7:0] int_sig_w;
    reg [7:0] int_sig_x;
    reg [7:0] int_sig_y;
    reg [7:0] int_sig_z;
    reg [7:0] int_sig_aa;
    reg [7:0] int_sig_bb;
    reg [7:0] int_sig_cc;
    reg [7:0] int_sig_dd;
    reg [7:0] int_sig_ee;
    reg [7:0] int_sig_ff;
    reg [7:0] int_sig_gg;
    reg [7:0] int_sig_hh;
    reg [7:0] int_sig_ii;
    reg [7:0] int_sig_jj;
    reg [7:0] int_sig_kk;
    reg [7:0] int_sig_ll;
    reg [7:0] int_sig_mm;
    reg [7:0] int_sig_nn;

    // Instantiation without parameter override → VLG073
    SubHelper sub_inst (.a(data_in), .b(coeff), .y(mult_result));

endmodule


// --- Module 2: Clock domain + Timing complexity ---
module clock_manager (
    input        clk_a,
    input        clk_b,
    input        sel,
    output       clk_out,
    output [7:0] dbg_cnt
);

    // --- Clock mux without glitch protection → VLG089 ---
    assign clk_out = sel ? clk_a : clk_b;

    // --- Generated clock → VLG088 + VLG090 ---
    reg [7:0]  div_cnt;
    reg        clk_div;
    always @(posedge clk_a) begin
        div_cnt <= div_cnt + 1;
    end
    // Clock from counter bit → VLG090
    always @(posedge clk_a) begin
        clk_div <= div_cnt[3];
    end

    // --- Clock toggle → VLG090 ---
    reg clk_half;
    always @(posedge clk_a) begin
        clk_half <= ~clk_half;
    end

    // --- Clock used as data → VLG087 ---
    reg clk_sample;
    always @(posedge clk_b) begin
        clk_sample <= clk_a;  // clock on RHS
    end

    // --- Use clk_div as actual clock → VLG088 (generated clock no constraint) ---
    reg [7:0] slow_data;
    always @(posedge clk_div) begin
        slow_data <= div_cnt;
    end

    assign dbg_cnt = div_cnt;

endmodule


// --- Module 3: Structural complexity + latch mix + wide arithmetic ---
module complex_alu (
    input             clk,
    input             rst_n,
    input      [31:0] op_a,
    input      [31:0] op_b,
    input      [3:0]  opcode,
    input      [3:0]  mode,
    input             start,
    input             cfg_a,
    input             cfg_b,
    input             cfg_c,
    input             cfg_d,
    input             cfg_e,
    output reg [31:0] result,
    output reg        done,
    output     [31:0] comb_result
);

    reg [31:0] internal_a;
    reg [31:0] internal_b;
    reg [31:0] temp;
    reg [3:0]  state;

    // --- Large comb cone → VLG083 ---
    // --- Latch-like pattern (if without else) mixed with FF → VLG092 ---
    always @(*) begin
        if (opcode == 4'h0) temp = op_a + op_b;
        if (opcode == 4'h1) temp = op_a - op_b;
        if (opcode == 4'h2) temp = op_a & op_b;
        if (opcode == 4'h3) temp = op_a | op_b;
        if (opcode == 4'h4) temp = op_a ^ op_b;
        if (opcode == 4'h5) temp = op_a << mode;
        if (opcode == 4'h6) temp = op_a >> mode;
        if (opcode == 4'h7) temp = ~op_a;
        if (opcode == 4'h8) temp = op_a * op_b;
        if (opcode == 4'h9) temp = {op_a[15:0], op_b[15:0]};
        if (opcode == 4'hA) temp = op_a + op_b + cfg_a + cfg_b + cfg_c + cfg_d + cfg_e + mode + start;
    end

    // FSM — state not observable → VLG082
    always @(posedge clk) begin
        if (!rst_n) begin
            state  <= 4'b0;
            result <= 32'b0;
            done   <= 1'b0;
        end else begin
            case (state)
                4'h0: begin
                    if (start) state <= 4'h1;
                    done <= 1'b0;
                end
                4'h1: begin
                    result <= temp;
                    state  <= 4'h2;
                end
                4'h2: begin
                    done  <= 1'b1;
                    state <= 4'h0;
                end
                default: state <= 4'h0;
            endcase
        end
    end

    // --- Wide arithmetic in comb path → VLG095 ---
    assign comb_result = op_a + op_b;

    // --- High fan-in assign → VLG078 ---
    wire [31:0] fan_in_sig;
    assign fan_in_sig = op_a ^ op_b ^ {28'b0, opcode} ^ {28'b0, mode} ^ internal_a ^ internal_b ^ temp ^ result ^ {31'b0, start};

    // --- Generate block without label → VLG075 ---
    genvar gi;
    generate
        for (gi = 0; gi < 4; gi = gi + 1) begin
            // no label on begin → VLG075
            assign comb_result[gi] = op_a[gi] & op_b[gi];
        end
    endgenerate

    // --- Wide mux without pipeline → VLG094 ---
    reg [31:0] wide_mux_out;
    always @(*) begin
        case (opcode)
            4'h0: wide_mux_out = op_a;
            4'h1: wide_mux_out = op_b;
            4'h2: wide_mux_out = internal_a;
            4'h3: wide_mux_out = internal_b;
            4'h4: wide_mux_out = temp;
            4'h5: wide_mux_out = result;
            4'h6: wide_mux_out = op_a + op_b;
            4'h7: wide_mux_out = op_a - op_b;
            4'h8: wide_mux_out = op_a ^ op_b;
            4'h9: wide_mux_out = ~op_a;
            default: wide_mux_out = 32'b0;
        endcase
    end

endmodule


// Third module in same file → VLG059 (already triggered by data_processor & clock_manager)
module SubHelper (
    input  [31:0] a,
    input  [31:0] b,
    output [31:0] y
);
    assign y = a + b;
endmodule
