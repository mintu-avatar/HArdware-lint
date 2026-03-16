// =============================================================================
// alu.v
// 32-bit Arithmetic Logic Unit — packed with synthesis & assignment issues
// =============================================================================
// NO header block comment above module (VLG001)

module alu (
    clk, rst, op, a, b, result, zero, overflow, carry_out
);

    // Non-ANSI port declarations without explicit directions on some (VLG004)
    input         clk;
    input         rst;
    input  [3:0]  op;
    input  [31:0] a;          // VLG002: magic number 31
    input  [31:0] b;          // VLG002: magic number 31
    output [31:0] result;     // VLG002: magic number 31
    output        zero;
    output        overflow;
    output        carry_out;  // VLG031: never driven!

    // VLG033: no `default_nettype none at top of file

    // Internal registers
    reg [31:0]    alu_out;    // VLG002
    reg           ov_flag;
    reg           z_flag;

    // VLG037: reg driven by continuous assign
    reg [31:0] partial_sum;
    assign partial_sum = a + b;  // VLG037: partial_sum is reg, use wire

    // -----------------------------------------------------------------------
    // VLG013: Blocking assignments inside clocked always block
    // VLG026: No reset condition
    // -----------------------------------------------------------------------
    always @(posedge clk) begin        // VLG026: no reset
        case (op)
            4'h0: alu_out = a + b;     // VLG013: blocking in clocked block
            4'h1: alu_out = a - b;     // VLG013
            4'h2: alu_out = a & b;     // VLG013
            4'h3: alu_out = a | b;     // VLG013
            4'h4: alu_out = a ^ b;     // VLG013
            4'h5: alu_out = ~a;        // VLG013
            4'h6: alu_out = a << b[4:0]; // VLG013
            4'h7: alu_out = a >> b[4:0]; // VLG013
            4'h8: alu_out = a <<< b[4:0];// VLG013
            4'h9: alu_out = a >>> b[4:0];// VLG013
            4'hA: alu_out = (a < b)  ? 32'd1 : 32'd0; // VLG013
            4'hB: alu_out = ($signed(a) < $signed(b)) ? 32'd1 : 32'd0; // VLG013
            // no default in clocked block - fine here but missing overflow logic
        endcase
    end

    // -----------------------------------------------------------------------
    // VLG016 + VLG017: Latch inference — combinational block with incomplete case
    // -----------------------------------------------------------------------
    always @(*) begin
        case (op)                      // VLG017: no default → latch on ov_flag
            4'h0: begin
                ov_flag = (a[31] == b[31]) && (alu_out[31] != a[31]);
            end
            4'h1: begin
                ov_flag = (a[31] != b[31]) && (alu_out[31] != a[31]);
            end
            // All other ops: ov_flag unassigned → LATCH!          VLG017
        endcase
        // z_flag not assigned in any branch either!                VLG018
    end

    // -----------------------------------------------------------------------
    // VLG011: $display / system task in RTL
    // -----------------------------------------------------------------------
    always @(posedge clk) begin
        if (ov_flag)
            $display("[ALU] Overflow detected! op=%0h a=%0h b=%0h", op, a, b); // VLG011
    end

    // -----------------------------------------------------------------------
    // VLG006: initial block
    // -----------------------------------------------------------------------
    initial begin                      // VLG006
        alu_out = 32'hDEAD_BEEF;
        ov_flag = 0;
        z_flag  = 0;
    end

    // -----------------------------------------------------------------------
    // VLG035: Combinational feedback loop
    // -----------------------------------------------------------------------
    wire fb_loop;
    assign fb_loop = fb_loop ^ alu_out[0];  // VLG035: fb_loop drives itself

    // -----------------------------------------------------------------------
    // VLG036: Deeply nested ternary (6 levels)
    // -----------------------------------------------------------------------
    wire [31:0] deep_mux;
    assign deep_mux = (op == 4'h0) ? alu_out :
                      (op == 4'h1) ? a :
                      (op == 4'h2) ? b :
                      (op == 4'h3) ? (a + b) :
                      (op == 4'h4) ? (a - b) :
                      (op == 4'h5) ? 32'hFFFF_FFFF : 32'h0; // VLG036: 6 levels

    assign result   = alu_out;
    assign zero     = (alu_out == 32'd0);
    assign overflow = ov_flag;
    // carry_out intentionally left undriven (VLG031)

    // -----------------------------------------------------------------------
    // VLG007: timing delay in assign
    // -----------------------------------------------------------------------
    wire dbg_zero;
    assign #10 dbg_zero = (alu_out == 32'd0);  // VLG007

endmodule
