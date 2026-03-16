// bad_fifo.v
// Intentionally bad RTL — triggers many lint rules for demonstration.
// A simple FIFO with numerous RTL anti-patterns.

module bad_fifo (
    clk, rst,
    wr_en, rd_en,
    data_in,
    data_out,
    full, empty
);
    // Missing `default_nettype none

    input         clk;
    input         rst;
    input         wr_en, rd_en;
    input  [31:0] data_in;   // VLG002: magic number 31
    output [31:0] data_out;  // VLG002: magic number 31
    output        full;
    output        empty;

    // VLG033: no `default_nettype none at top
    reg [31:0] mem [0:15];   // VLG002: magic number 31
    reg [3:0]  wr_ptr;
    reg [3:0]  rd_ptr;
    reg [4:0]  count;

    // -------------------------------------------------------
    // VLG006: initial block — not synthesizable
    // -------------------------------------------------------
    initial begin
        wr_ptr  = 0;
        rd_ptr  = 0;
        count   = 0;
    end

    // -------------------------------------------------------
    // VLG013: blocking assignment in clocked always block
    // -------------------------------------------------------
    always @(posedge clk) begin
        if (wr_en && !full) begin
            mem[wr_ptr] = data_in;     // VLG013: should be <=
            wr_ptr      = wr_ptr + 1;  // VLG013: should be <=
            count       = count + 1;   // VLG013: should be <=
        end
    end

    // -------------------------------------------------------
    // VLG009: explicit sensitivity list (incomplete — missing count)
    // -------------------------------------------------------
    always @(wr_ptr, rd_ptr) begin
        if (count == 0)
            ; // empty flag logic missing
    end

    // -------------------------------------------------------
    // VLG016 + VLG018: combinational if without else (latch!)
    // -------------------------------------------------------
    reg rd_valid;
    always @(*) begin
        if (rd_en && !empty) begin     // VLG016: no else — rd_valid latches
            rd_valid = 1'b1;
        end
        // rd_valid not assigned when condition is false → LATCH
    end

    // -------------------------------------------------------
    // VLG017: case without default in combinational block
    // -------------------------------------------------------
    reg [1:0] state;
    always @(*) begin
        case (state)                   // VLG017: no default
            2'b00: data_out_reg = 32'h0;
            2'b01: data_out_reg = mem[rd_ptr];
            2'b10: data_out_reg = 32'hDEAD;
            // 2'b11: unspecified — LATCH inferred!
        endcase
    end

    reg [31:0] data_out_reg;
    assign data_out = data_out_reg;

    // -------------------------------------------------------
    // VLG026: no reset in clocked block
    // -------------------------------------------------------
    always @(posedge clk) begin       // VLG026: no rst check
        if (rd_en && !empty)
            rd_ptr <= rd_ptr + 1;
    end

    // -------------------------------------------------------
    // VLG007: #delay in RTL
    // -------------------------------------------------------
    assign #5 full  = (count == 5'd16); // VLG007: synthesis-illegal delay
    assign     empty = (count == 5'd0);

    // -------------------------------------------------------
    // VLG011: $display in RTL
    // -------------------------------------------------------
    always @(posedge clk) begin
        if (wr_en && full)
            $display("FIFO overflow at time %0t", $time); // VLG011
    end

    // -------------------------------------------------------
    // VLG035: combinational feedback loop
    // -------------------------------------------------------
    wire loop_sig;
    assign loop_sig = ~loop_sig;   // VLG035: feeds itself!

    // -------------------------------------------------------
    // VLG008: casez usage
    // -------------------------------------------------------
    reg [3:0] priority_out;
    always @(*) begin
        casez (count[3:0])           // VLG008
            4'b1???: priority_out = 4'd3;
            4'b01??: priority_out = 4'd2;
            4'b001?: priority_out = 4'd1;
            default: priority_out = 4'd0;
        endcase
    end

endmodule
