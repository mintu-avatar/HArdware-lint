// =============================================================================
// good_counter.v
// A clean, well-written parameterized counter that should pass lint.
// =============================================================================

// Module: good_counter
// Description : N-bit synchronous up-counter with synchronous reset and
//               terminal count output. Demonstrates clean RTL style.
// Author      : Hardware-Lint Demo
// Date        : 2026-03-01

`default_nettype none

module good_counter #(
    parameter WIDTH = 8  // counter width — named parameter, not magic number
)(
    input  wire               i_clk,     // system clock
    input  wire               i_rst_n,   // active-low synchronous reset
    input  wire               i_en,      // count enable
    output reg  [WIDTH-1:0]   o_count,   // current count value
    output reg                o_tc       // terminal count (count == MAX)
);

    localparam MAX = (1 << WIDTH) - 1;

    // -------------------------------------------------------------------------
    // Clocked logic — non-blocking assignments, proper reset, scan-friendly
    // -------------------------------------------------------------------------
    always @(posedge i_clk) begin
        if (!i_rst_n) begin
            o_count <= {WIDTH{1'b0}};
            o_tc    <= 1'b0;
        end else if (i_en) begin
            o_count <= (o_count == MAX[WIDTH-1:0]) ? {WIDTH{1'b0}} : o_count + 1'b1;
            o_tc    <= (o_count == MAX[WIDTH-1:0] - 1);  // registered output
        end
    end

endmodule
`default_nettype wire
