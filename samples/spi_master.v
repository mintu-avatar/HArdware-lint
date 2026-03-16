// =============================================================================
// spi_master.v
// SPI Master Controller — port hygiene, FSM, and CDC anti-patterns
// =============================================================================

`default_nettype none

// SPI Master: generates SCLK, MOSI from clk_sys; samples MISO
// Demonstrates: FSM lockup, undriven ports, unconnected sub-instances,
//               missing default_nettype between modules, positional ports.

module spi_master (
    input  wire        i_clk,
    input  wire        i_rst_n,
    input  wire        i_start,
    input  wire [7:0]  i_tx_data,
    input  wire        i_miso,        // MISO from slave
    output reg         o_sclk,
    output reg         o_mosi,
    output reg         o_cs_n,
    output reg  [7:0]  o_rx_data,
    output reg         o_done,
    output wire        o_busy         // VLG031: never driven — left as wire, never assigned
);

    // -----------------------------------------------------------------------
    // FSM: 8 states using binary encoding (VLG028: consider one-hot for FPGA)
    // -----------------------------------------------------------------------
    localparam IDLE      = 4'd0;
    localparam CS_ASSERT = 4'd1;
    localparam CLK_HI_0  = 4'd2;
    localparam CLK_LO_0  = 4'd3;
    localparam CLK_HI_1  = 4'd4;
    localparam CLK_LO_1  = 4'd5;
    localparam CLK_HI_2  = 4'd6;
    localparam CLK_LO_2  = 4'd7;
    localparam CS_DEASSERT = 4'd8;

    reg [3:0] state, next_state;
    reg [7:0] shift_reg;
    reg [3:0] bit_idx;

    // -----------------------------------------------------------------------
    // State register — async reset, correct style
    // -----------------------------------------------------------------------
    always @(posedge i_clk or negedge i_rst_n) begin
        if (!i_rst_n) begin
            state    <= IDLE;
            bit_idx  <= 4'd0;
        end else begin
            state   <= next_state;
            bit_idx <= (state == IDLE && i_start) ? 4'd7
                     : (o_sclk && state != IDLE)  ? bit_idx - 1
                     :                              bit_idx;
        end
    end

    // -----------------------------------------------------------------------
    // Shift register (separate always for clarity)
    // VLG026: shift_reg block has no reset    
    // -----------------------------------------------------------------------
    always @(posedge i_clk) begin       // VLG026: no reset branch
        if (state == CS_ASSERT)
            shift_reg <= i_tx_data;
        else if (!o_sclk && state != IDLE && state != CS_ASSERT && state != CS_DEASSERT)
            shift_reg <= {shift_reg[6:0], i_miso};
    end

    // -----------------------------------------------------------------------
    // Next-state + output combinational decode
    // VLG027: no default in FSM case (state lockup risk)
    // VLG030: outputs driven combinationally from state (glitchy)
    // -----------------------------------------------------------------------
    always @(*) begin
        next_state = state;
        o_cs_n     = 1'b1;
        o_sclk     = 1'b0;
        o_mosi     = 1'b0;
        o_done     = 1'b0;

        case (state)                   // VLG027: no default!
            IDLE: begin
                o_cs_n = 1'b1;
                if (i_start) next_state = CS_ASSERT;
            end
            CS_ASSERT: begin
                o_cs_n     = 1'b0;
                next_state = CLK_HI_0;
            end
            CLK_HI_0: begin
                o_cs_n     = 1'b0;
                o_sclk     = 1'b1;
                o_mosi     = shift_reg[7];
                next_state = CLK_LO_0;
            end
            CLK_LO_0: begin
                o_cs_n     = 1'b0;
                o_sclk     = 1'b0;
                next_state = CLK_HI_1;
            end
            CLK_HI_1: begin
                o_cs_n     = 1'b0;
                o_sclk     = 1'b1;
                o_mosi     = shift_reg[7];
                next_state = CLK_LO_1;
            end
            CLK_LO_1: begin
                o_cs_n     = 1'b0;
                o_sclk     = 1'b0;
                next_state = CLK_HI_2;
            end
            CLK_HI_2: begin
                o_cs_n     = 1'b0;
                o_sclk     = 1'b1;
                o_mosi     = shift_reg[7];
                next_state = CLK_LO_2;
            end
            CLK_LO_2: begin
                o_cs_n     = 1'b0;
                next_state = CS_DEASSERT;
            end
            CS_DEASSERT: begin
                o_cs_n     = 1'b1;
                o_done     = 1'b1;      // VLG030: glitchy combinational done pulse
                next_state = IDLE;
            end
            // No default: if bit_idx wraps unexpectedly → lockup   VLG027
        endcase
    end

    // -----------------------------------------------------------------------
    // RX data register
    // -----------------------------------------------------------------------
    always @(posedge i_clk or negedge i_rst_n) begin
        if (!i_rst_n)
            o_rx_data <= 8'h00;
        else if (state == CS_DEASSERT)
            o_rx_data <= shift_reg;
    end

    // -----------------------------------------------------------------------
    // VLG032: Submodule instantiation with unconnected input port
    // -----------------------------------------------------------------------
    // Instantiate a prescaler to generate slower SPI clock
    spi_clk_div u_prescaler (
        .i_clk    (i_clk),
        .i_rst_n  (i_rst_n),
        .i_div    (),            // VLG032: input left unconnected → driven to 0!
        .o_clk_en ()             // VLG032: output also unconnected
    );

    // -----------------------------------------------------------------------
    // VLG034: Positional port connection (don't do this!)
    // -----------------------------------------------------------------------
    // spi_fifo u_rx_fifo (i_clk, i_rst_n, shift_reg, o_rx_data); // positional

endmodule


// Stub for the prescaler (so tool can elaborate)
module spi_clk_div (
    input  wire       i_clk,
    input  wire       i_rst_n,
    input  wire [7:0] i_div,
    output wire       o_clk_en
);
    // Intentionally minimal stub — real implementation omitted
    assign o_clk_en = 1'b0;
endmodule

`default_nettype wire
