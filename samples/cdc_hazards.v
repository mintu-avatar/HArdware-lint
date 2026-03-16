// =============================================================================
// cdc_hazards.v
// Demonstrates multiple CDC anti-patterns
// =============================================================================
module cdc_hazards (
    input  clk_a,
    input  clk_b,
    input  rst,

    // Data from clock domain A
    input  [7:0] bus_from_a,
    input        flag_from_a,

    // Outputs in clock domain B  
    output reg [7:0] bus_in_b,
    output reg       flag_in_b,
    output reg       processed
);

    // -----------------------------------------------------------------------
    // VLG019: 8-bit bus crossing from clk_a to clk_b with no synchronizer
    // A double-flop is not safe for multi-bit buses — bits may skew!
    // -----------------------------------------------------------------------
    reg [7:0] bus_sync1, bus_sync2;
    always @(posedge clk_a) bus_sync1 <= bus_from_a;
    always @(posedge clk_b) bus_sync2 <= bus_sync1;   // VLG019: 8-bit, wrong!

    // -----------------------------------------------------------------------
    // VLG020: Single-bit flag with only ONE synchronizer FF (should be two)
    // -----------------------------------------------------------------------
    reg flag_meta;
    always @(posedge clk_b) begin
        flag_meta <= flag_from_a;  // only 1 FF — metastability not resolved
        flag_in_b <= flag_meta;    // this looks like 2 FFs but both are in
                                   // the same always block — actually OK here
                                   // The real VLG020 case is when only 1 FF total
    end

    // Deliberate single-flip-flop CDC (VLG020 trigger):
    reg single_ff_sync;
    always @(posedge clk_b) begin
        single_ff_sync <= flag_from_a;  // VLG020: only 1 FF for CDC
    end

    // -----------------------------------------------------------------------
    // VLG021: Clock used as data — in assign RHS logic expression
    // -----------------------------------------------------------------------
    wire clk_gated;
    assign clk_gated = clk_a & processed;  // VLG022: comb gate on clock!

    // -----------------------------------------------------------------------
    // Consume gated clock in an always block (compounds the error)
    // -----------------------------------------------------------------------
    always @(posedge clk_gated) begin      // Using gated clock
        bus_in_b <= bus_sync2;
    end

    // -----------------------------------------------------------------------
    // VLG023: Mixed reset — some blocks use rst (active-high, sync),
    // others would use rst_n (active-low, async) in a real mixed design
    // -----------------------------------------------------------------------
    always @(posedge clk_b) begin
        if (rst)                           // VLG024: rst not in sensitivity for async
            processed <= 1'b0;
        else
            processed <= flag_in_b;
    end

endmodule
