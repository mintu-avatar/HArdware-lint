`default_nettype none

// nand_good
// Purpose:
//   Minimal 2-input NAND gate.
// Function:
//   y = ~(a & b)
module nand_good (
    input  wire a,
    input  wire b,
    output wire y
);
    assign y = ~(a & b);
endmodule

`default_nettype wire