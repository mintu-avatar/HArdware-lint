// =============================================================================
// pwm_controller.v
// PWM generator with tri-state output and CDC issues
// =============================================================================

module pwm_controller (
    input  clk_sys,            // 100 MHz
    input  clk_cfg,            // 10 MHz configuration clock (different domain!)
    input  rst_n,

    // Config bus (clk_cfg domain)
    input  [7:0] cfg_duty,     // duty cycle 0-255
    input        cfg_wr,       // config write strobe

    // PWM output
    output pwm_out,
    output pwm_n,

    // Tri-state pin (bidirectional)
    output dut_io,             // VLG012: z assigned without enable pattern
    input  dut_io_in
);

// VLG033: no `default_nettype none

    reg [7:0] duty_reg;       // VLG003: no prefix convention (r_duty_reg)
    reg [7:0] counter;        // VLG003
    reg       pwm_r;          // VLG003
    reg [7:0] duty_sync;      // CDC sync register

    // -----------------------------------------------------------------------
    // VLG019: 8-bit cfg_duty crossing from clk_cfg → clk_sys without sync
    // -----------------------------------------------------------------------
    always @(posedge clk_cfg) begin
        if (!rst_n)
            duty_reg <= 8'h0;
        else if (cfg_wr)
            duty_reg <= cfg_duty;
    end

    // Direct use of duty_reg in clk_sys domain without synchronizer!
    // VLG019: 8-bit bus crossing two clock domains
    always @(posedge clk_sys) begin
        if (!rst_n) begin
            counter  <= 8'h0;
            pwm_r    <= 1'b0;
        end else begin
            counter  <= counter + 1;
            pwm_r    <= (counter < duty_reg);   // VLG019: duty_reg from clk_cfg!
        end
    end

    assign pwm_out = pwm_r;
    assign pwm_n   = ~pwm_r;

    // -----------------------------------------------------------------------
    // VLG012: 1'bz assigned without explicit tri-state enable (no ternary)
    // -----------------------------------------------------------------------
    assign dut_io = 1'bz;  // VLG012: always driving Z — missing oe enable pin

    // -----------------------------------------------------------------------
    // VLG022: Gated clock using PWM output as clock enable on clock path
    // -----------------------------------------------------------------------
    wire gated_cfg_clk;
    assign gated_cfg_clk = clk_cfg & pwm_r;  // VLG022: combinational clock gate!

    always @(posedge gated_cfg_clk) begin     // Using the glitch-prone gated clock
        duty_sync <= cfg_duty;
    end

    // -----------------------------------------------------------------------
    // VLG009: Explicit (incomplete) sensitivity list
    // -----------------------------------------------------------------------
    reg [7:0] duty_display;
    always @(duty_reg) begin               // VLG009: missing counter from sensitivity
        if (counter == 8'hFF)
            duty_display = duty_reg;
        // counter not in sensitivity list — simulation will not update properly
    end

    // -----------------------------------------------------------------------
    // VLG015: Mixed blocking and non-blocking in same always block
    // -----------------------------------------------------------------------
    reg [7:0] mixed_reg;
    always @(posedge clk_sys) begin
        if (!rst_n) begin
            mixed_reg  = 8'h0;           // VLG015: blocking
        end else begin
            mixed_reg <= duty_reg + 1;   // VLG015: non-blocking — MIXED!
        end
    end

    // -----------------------------------------------------------------------
    // VLG004: module with ports listed without directions in port list header
    // -----------------------------------------------------------------------

endmodule
