// =============================================================================
// pipeline_hazards.v
// 4-stage pipeline with multiple RTL hazards
// Triggers: CDC, blocking assignments, latch inference, incomplete sensitivity
// =============================================================================

module pipeline_hazards (
    input  clk_fast,          // 200 MHz processing clock
    input  clk_slow,          // 50 MHz output/bus clock
    input  rst,               // active-high sync reset
    input  [15:0] data_in,    // VLG002: magic number
    input         valid_in,
    output reg [31:0] result, // VLG002: magic number
    output reg        valid_out
);

// No `default_nettype none (VLG033)

    // -----------------------------------------------------------------------
    // Stage 1: Input registration — correct style
    // -----------------------------------------------------------------------
    reg [15:0] stage1_data;
    reg        stage1_valid;

    always @(posedge clk_fast) begin
        if (rst) begin
            stage1_data  <= 16'h0;
            stage1_valid <= 1'b0;
        end else begin
            stage1_data  <= data_in;
            stage1_valid <= valid_in;
        end
    end

    // -----------------------------------------------------------------------
    // Stage 2: Multiply — but uses BLOCKING assignments (VLG013)
    // -----------------------------------------------------------------------
    reg [31:0] stage2_product;
    reg        stage2_valid;

    always @(posedge clk_fast) begin
        if (rst) begin
            stage2_product = 32'h0;   // VLG013: blocking in clocked block
            stage2_valid   = 1'b0;    // VLG013
        end else if (stage1_valid) begin
            stage2_product = stage1_data * stage1_data; // VLG013: blocking
            stage2_valid   = stage1_valid;               // VLG013
        end
    end

    // -----------------------------------------------------------------------
    // Stage 3: Accumulator — combinational with latch risk (VLG016, VLG018)
    // -----------------------------------------------------------------------
    reg [31:0] accum;
    reg        accum_valid;

    always @(*) begin                  // VLG009 candidate: explicit sensitivity
        if (stage2_valid) begin        // VLG016: no else → latch on accum
            accum = stage2_product + 32'hAAAA_0000;
            // accum_valid not assigned in else branch! → VLG018 / latch risk
        end
        // Missing: else accum = <default>; → LATCH
    end

    // -----------------------------------------------------------------------
    // Stage 4: CDC crossing — result goes from clk_fast to clk_slow domain
    // VLG019: 32-bit bus crossing without proper synchronization
    // VLG020: valid signal single-FF sync
    // -----------------------------------------------------------------------
    reg [31:0] result_cdc_a;  // clk_fast domain copy
    reg        valid_cdc_a;

    always @(posedge clk_fast) begin
        if (rst) begin
            result_cdc_a <= 32'h0;
            valid_cdc_a  <= 1'b0;
        end else begin
            result_cdc_a <= accum;
            valid_cdc_a  <= accum_valid;
        end
    end

    // BAD: Direct sample on clk_slow — 32-bit CDC without gray-code or FIFO
    always @(posedge clk_slow) begin   // VLG019: 32-bit CDC crossing!
        if (rst) begin
            result    <= 32'h0;
            valid_out <= 1'b0;
        end else begin
            result    <= result_cdc_a;  // 32-bit — needs async FIFO or gray-code
            valid_out <= valid_cdc_a;   // VLG020: single-bit CDC, needs 2-FF sync
        end
    end

    // -----------------------------------------------------------------------
    // VLG010: force/release in RTL (leftover debug)
    // -----------------------------------------------------------------------
    // force result = 32'hDEAD_BEEF;   // VLG010 — would fire if uncommented

    // -----------------------------------------------------------------------
    // VLG008: casez for priority selection
    // -----------------------------------------------------------------------
    reg [1:0] priority_level;
    always @(*) begin
        casez (stage2_product[31:30])  // VLG008: casez used
            2'b1?: priority_level = 2'd3;
            2'b01: priority_level = 2'd2;
            2'b00: priority_level = 2'd1;
            default: priority_level = 2'd0;
        endcase
    end

    // -----------------------------------------------------------------------
    // VLG038: Sequential module, no scan_en port
    // -----------------------------------------------------------------------

    // -----------------------------------------------------------------------
    // VLG021: Clock used as data in logic expression
    // -----------------------------------------------------------------------
    wire debug_clk_xor;
    assign debug_clk_xor = clk_fast ^ clk_slow;  // VLG021: clocks XOR'd as data

    // -----------------------------------------------------------------------
    // VLG006: Initial block
    // -----------------------------------------------------------------------
    initial begin                       // VLG006
        result    = 32'h0;
        valid_out = 1'b0;
    end

endmodule
