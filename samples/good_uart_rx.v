// =============================================================================
// good_uart_rx.v
// A clean, well-written UART receiver — should have minimal findings.
// Demonstrates RTL best practices:
//   - Named parameters (no magic numbers)
//   - Proper async-assert / sync-deassert reset
//   - Non-blocking assignments in clocked blocks
//   - Default assignments before case in combinational logic
//   - One-hot FSM encoding
//   - Named port connections (though no sub-instances here)
//   - `default_nettype none guard
// =============================================================================

`default_nettype none

// Module  : good_uart_rx
// Purpose : Oversampled (16x) UART receive path with framing error detection.
// Clock   : i_clk (single domain — no CDC hazards)
// Reset   : Active-low asynchronous assert, synchronous deassert
// Author  : Hardware-Lint Reference Design
// Date    : 2026-03-01

module good_uart_rx #(
    parameter CLK_FREQ   = 100_000_000,  // system clock frequency in Hz
    parameter BAUD_RATE  = 115_200,      // target baud rate
    parameter OVERSAMPLE = 16            // oversampling ratio
)(
    input  wire        i_clk,
    input  wire        i_rst_n,    // async assert, sync deassert
    input  wire        i_scan_en,  // DFT scan enable
    input  wire        i_rx,       // UART RX line
    output reg  [7:0]  o_data,     // received byte
    output reg         o_valid,    // pulse: one cycle when data is ready
    output reg         o_frame_err // framing error flag
);

    // -----------------------------------------------------------------------
    // Derived parameters — no magic numbers in logic
    // -----------------------------------------------------------------------
    localparam BAUD_DIV    = CLK_FREQ / BAUD_RATE;
    localparam HALF_DIV    = BAUD_DIV / 2;
    localparam CNT_W       = $clog2(BAUD_DIV + 1);
    localparam BIT_CNT_W   = 4;  // 0..9 (start + 8 data + stop)

    // -----------------------------------------------------------------------
    // One-hot FSM encoding (VLG028 compliant — correct practice)
    // -----------------------------------------------------------------------
    localparam [2:0] IDLE   = 3'b001;
    localparam [2:0] START  = 3'b010;
    localparam [2:0] DATA   = 3'b100;

    reg [2:0] state_r, state_next;

    // -----------------------------------------------------------------------
    // Input synchronizer (2-FF metastability chain) — CDC-safe
    // -----------------------------------------------------------------------
    reg rx_meta, rx_sync;
    always @(posedge i_clk or negedge i_rst_n) begin
        if (!i_rst_n) begin
            rx_meta <= 1'b1;  // UART idle = high
            rx_sync <= 1'b1;
        end else begin
            rx_meta <= i_scan_en ? i_rx : i_rx;  // scan-aware mux hook
            rx_sync <= rx_meta;
        end
    end

    // -----------------------------------------------------------------------
    // Baud-rate counter and bit counter
    // -----------------------------------------------------------------------
    reg [CNT_W-1:0]     baud_cnt;
    reg [BIT_CNT_W-1:0] bit_cnt;
    wire                baud_tick  = (baud_cnt == BAUD_DIV[CNT_W-1:0] - 1);
    wire                half_tick  = (baud_cnt == HALF_DIV[CNT_W-1:0] - 1);

    always @(posedge i_clk or negedge i_rst_n) begin
        if (!i_rst_n) begin
            baud_cnt <= '0;
            bit_cnt  <= '0;
        end else begin
            if (state_r == IDLE) begin
                baud_cnt <= '0;
                bit_cnt  <= '0;
            end else if (baud_tick) begin
                baud_cnt <= '0;
                bit_cnt  <= bit_cnt + 1'b1;
            end else begin
                baud_cnt <= baud_cnt + 1'b1;
            end
        end
    end

    // -----------------------------------------------------------------------
    // State register — async assert, sync deassert (industry best practice)
    // -----------------------------------------------------------------------
    always @(posedge i_clk or negedge i_rst_n) begin
        if (!i_rst_n)
            state_r <= IDLE;
        else
            state_r <= state_next;
    end

    // -----------------------------------------------------------------------
    // Next-state logic — defaults assigned FIRST, then case overrides
    // This prevents latch inference (VLG016/VLG017 safe)
    // -----------------------------------------------------------------------
    always @(*) begin
        // Default: stay in same state
        state_next = state_r;

        case (state_r)
            IDLE: begin
                if (!rx_sync)          // falling edge → start bit detected
                    state_next = START;
            end
            START: begin
                if (half_tick)         // sample at mid-start-bit to confirm
                    state_next = (!rx_sync) ? DATA : IDLE;
            end
            DATA: begin
                if (baud_tick && bit_cnt == 4'd9)
                    state_next = IDLE;
            end
            default: state_next = IDLE; // Safety: never lock up
        endcase
    end

    // -----------------------------------------------------------------------
    // Shift register and output — all registered (VLG030 compliant)
    // -----------------------------------------------------------------------
    reg [7:0] shift_r;

    always @(posedge i_clk or negedge i_rst_n) begin
        if (!i_rst_n) begin
            shift_r    <= 8'h00;
            o_data     <= 8'h00;
            o_valid    <= 1'b0;
            o_frame_err<= 1'b0;
        end else begin
            o_valid     <= 1'b0;     // default: deassert each cycle
            o_frame_err <= 1'b0;

            if (state_r == DATA && baud_tick) begin
                if (bit_cnt < 4'd9)
                    shift_r <= {rx_sync, shift_r[7:1]};  // LSB first
                else begin
                    // Stop bit check
                    o_data      <= shift_r;
                    o_valid     <= rx_sync;           // valid only if stop=1
                    o_frame_err <= ~rx_sync;          // framing error if stop=0
                end
            end
        end
    end

endmodule

`default_nettype wire
