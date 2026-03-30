`default_nettype none

// not_good
// Purpose:
//   Minimal NOT gate (inverter).
// Function:
//   y = ~a
module not_good (
    input  wire a,
    output wire y
);
    assign y = ~a;
endmodule

`default_nettype wire