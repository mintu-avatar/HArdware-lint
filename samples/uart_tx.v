`default_nettype none
// =============================================================================
// uart_tx.v
// UART Transmitter — intentionally has CDC, reset, FSM, and port hygiene issues
// =============================================================================

// VLG001: No block comment above module — missing documentation

module uart_tx #(
    parameter BAUD_DIV = 868  // 100MHz / 115200
)(
    input        clk_sys,     // 100 MHz system clock
    input        clk_uart,    // 1.8432 MHz UART baud clock (DIFFERENT DOMAIN!)
    input        rst_n,
    input  [7:0] tx_data,
    input        tx_valid,
    output reg   tx_out,
    output reg   tx_busy
);

    // -------------------------------------------------------------------------
    // FSM state encoding — binary, 7 states (VLG028: should consider one-hot)
    // -------------------------------------------------------------------------
    localparam IDLE    = 3'd0;
    localparam START   = 3'd1;
    localparam D0      = 3'd2;
    localparam D1      = 3'd3;
    localparam D2      = 3'd4;
    localparam D3      = 3'd5;
    localparam STOP    = 3'd6;

    reg [2:0] state;
    reg [2:0] next_state;     // next state computed in combinational block
    reg [7:0] shift_reg;
    reg [3:0] bit_cnt;

    // -------------------------------------------------------------------------
    // CDC hazard: tx_valid comes from clk_sys domain, sampled on clk_uart edge
    // No synchronizer! VLG020: single-bit CDC without double-flop synchronizer
    // -------------------------------------------------------------------------
    reg tx_valid_uart;
    always @(posedge clk_uart) begin
        tx_valid_uart <= tx_valid;  // VLG020: missing meta -> sync synchronizer
    end

    // -------------------------------------------------------------------------
    // VLG023: MIXED reset strategy!
    // State register uses async reset (rst_n in sensitivity list)...
    // -------------------------------------------------------------------------
    always @(posedge clk_uart or negedge rst_n) begin
        if (!rst_n)
            state <= IDLE;
        else
            state <= next_state;
    end

    // -------------------------------------------------------------------------
    // ...but shift register uses SYNCHRONOUS reset — VLG023 pattern
    // -------------------------------------------------------------------------
    always @(posedge clk_uart) begin
        if (!rst_n)                       // sync reset — no rst_n in sensitivity
            shift_reg <= 8'h00;
        else if (state == IDLE && tx_valid_uart)
            shift_reg <= tx_data;        // VLG019: tx_data is clk_sys domain!
        else if (state != IDLE)
            shift_reg <= shift_reg >> 1;
    end

    // -------------------------------------------------------------------------
    // Next-state combinational logic
    // VLG027: FSM case with no default — lockup on illegal state
    // VLG030: Output decoded combinationally from state (glitchy tx_out)
    // -------------------------------------------------------------------------
    always @(*) begin
        next_state = state;  // VLG029: next_state = in comb block is OK for next_state...
        tx_out     = 1'b1;   // VLG030: output driven combinationally
        tx_busy    = 1'b0;

        case (state)         // VLG027: no default!
            IDLE:  begin
                       tx_busy = 1'b0;
                       if (tx_valid_uart) next_state = START;
                   end
            START: begin
                       tx_out  = 1'b0;
                       tx_busy = 1'b1;
                       next_state = D0;
                   end
            D0:    begin tx_out = shift_reg[0]; tx_busy=1'b1; next_state = D1; end
            D1:    begin tx_out = shift_reg[0]; tx_busy=1'b1; next_state = D2; end
            D2:    begin tx_out = shift_reg[0]; tx_busy=1'b1; next_state = D3; end
            D3:    begin tx_out = shift_reg[0]; tx_busy=1'b1; next_state = STOP; end
            STOP:  begin
                       tx_out = 1'b1;
                       tx_busy = 1'b1;
                       next_state = IDLE;
                   end
            // Missing: default → if state corrupts, FSM hangs forever! VLG027
        endcase
    end

    // -------------------------------------------------------------------------
    // VLG022 + VLG021: Gated clock — combining clk_uart with enable
    // -------------------------------------------------------------------------
    wire gated_clk;
    assign gated_clk = clk_uart & tx_busy;  // VLG022: combinational clock gate!

    // -------------------------------------------------------------------------
    // VLG038: Sequential module — no scan_en port for DFT
    // -------------------------------------------------------------------------

    // -------------------------------------------------------------------------
    // VLG039: $urandom in RTL (leftover debug code)
    // -------------------------------------------------------------------------
    // assign debug_junk = $urandom;   // Commented but still worth noting pattern

    // VLG031: undriven output — bit_cnt is computed but never connected out
    // (internal signal, but illustrates dangling internal signals)

endmodule
`default_nettype wire
