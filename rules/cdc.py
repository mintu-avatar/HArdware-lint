"""
rules/cdc.py — Clock Domain Crossing rules
==========================================
VLG019  Multi-bit signal crossing clock domains without synchronizer
VLG020  Single-bit CDC without double-flop synchronizer
VLG021  Clock used as data (in non-clock position)
VLG022  Combinational logic on clock path (gated clock)
"""

from __future__ import annotations
import re
from typing import List, Set, Dict
from engine.rule_base import RuleBase, Severity, Finding, ParseContext, register_rule


# Helpers to identify clock signals by name convention
_CLK_NAME_RE = re.compile(r'\bclk\w*\b|\bclock\w*\b', re.IGNORECASE)


def _get_clock_signals(ctx: ParseContext) -> Set[str]:
    """Return set of signal names that look like clocks."""
    clocks: Set[str] = set()
    for port in ctx.port_decls:
        if _CLK_NAME_RE.search(port['name']):
            clocks.add(port['name'])
    for sig in ctx.signal_decls:
        if _CLK_NAME_RE.search(sig['name']):
            clocks.add(sig['name'])
    return clocks


def _get_block_clock(blk: dict) -> str:
    """Extract the clock signal name from an always block's sensitivity list."""
    m = re.search(r'(?:posedge|negedge)\s+(\w+)', blk['sensitivity'])
    return m.group(1) if m else ''


# ---------------------------------------------------------------------------
@register_rule
class VLG019(RuleBase):
    """
    Multi-bit signals crossing between clock domains must be treated with
    special synchronization (gray-coded counters, handshake, FIFO).
    A naive double-flop synchronizer is NOT sufficient for multi-bit data.
    RTL reason: all bits of a multi-bit bus may not transition simultaneously,
    so the receiving clock domain may capture a mixed/glitched value.
    This heuristic flags multi-bit signals driven in one clock domain and
    read in another.
    """
    rule_id     = "VLG019"
    category    = "CDC"
    severity    = Severity.ERROR
    description = "Multi-bit signal may cross clock domains without proper synchronization"

    def check(self, ctx: ParseContext) -> List[Finding]:
        findings = []
        # Group always blocks by their driving clock
        clock_to_lhs: Dict[str, Set[str]] = {}
        for blk in ctx.always_blocks:
            clk = _get_block_clock(blk)
            if not clk:
                continue
            clock_to_lhs.setdefault(clk, set())
            # Collect LHS names assigned in this block
            for ln in blk['body_lines']:
                m = re.match(r'\s*(\w+)\s*(?:\[[^\]]*\])?\s*<=', ln)
                if m:
                    clock_to_lhs[clk].add(m.group(1))

        # For each signal, check if it appears on the LHS of two different clocks
        clocks = list(clock_to_lhs.keys())
        for i in range(len(clocks)):
            for j in range(i + 1, len(clocks)):
                shared = clock_to_lhs[clocks[i]] & clock_to_lhs[clocks[j]]
                for sig in shared:
                    # Find width from declarations
                    width = 1
                    for decl in ctx.port_decls + ctx.signal_decls:
                        if decl['name'] == sig:
                            w = decl.get('width', '[0:0]')
                            m = re.search(r'\[(\d+)', w)
                            if m:
                                width = int(m.group(1)) + 1
                    if width > 1:
                        # Find originating line
                        line = 1
                        for blk in ctx.always_blocks:
                            if _get_block_clock(blk) in (clocks[i], clocks[j]):
                                line = blk['start_line']
                                break
                        findings.append(Finding(
                            rule_id=self.rule_id,
                            severity=self.severity,
                            category=self.category,
                            description=self.description,
                            file=ctx.filepath,
                            line=line,
                            snippet=f"Signal '{sig}' ({width}-bit) driven by both '{clocks[i]}' and '{clocks[j]}' domains",
                            suggestion="Use gray-coded counter, async FIFO, or handshake protocol for multi-bit CDC."
                        ))
        return findings


# ---------------------------------------------------------------------------
@register_rule
class VLG020(RuleBase):
    """
    Single-bit signals crossing between clock domains need a double-flop
    (two-stage) synchronizer to reduce metastability probability.
    RTL reason: a single flip-flop synchronizer has ~50% chance of latching
    metastable output; two stages reduce MTBF to acceptable silicon lifetime.
    This rule flags signals that appear in sensitivity lists of two differently-
    clocked blocks without a recognizable synchronizer naming pattern.
    """
    rule_id     = "VLG020"
    category    = "CDC"
    severity    = Severity.WARNING
    description = "Single-bit signal may cross clock domains without double-flop synchronizer"

    # Synchronizer naming conventions to suppress false positives
    _SYNC_RE = re.compile(r'sync|ff2|meta|cdc|dff2', re.IGNORECASE)

    def check(self, ctx: ParseContext) -> List[Finding]:
        findings = []
        clock_to_lhs: Dict[str, Set[str]] = {}
        for blk in ctx.always_blocks:
            clk = _get_block_clock(blk)
            if not clk:
                continue
            clock_to_lhs.setdefault(clk, set())
            for ln in blk['body_lines']:
                m = re.match(r'\s*(\w+)\s*<=', ln)
                if m:
                    clock_to_lhs[clk].add(m.group(1))

        clocks = list(clock_to_lhs.keys())
        for i in range(len(clocks)):
            for j in range(i + 1, len(clocks)):
                shared = clock_to_lhs[clocks[i]] & clock_to_lhs[clocks[j]]
                for sig in shared:
                    if self._SYNC_RE.search(sig):
                        continue   # likely a sync register — skip
                    # Check if single-bit
                    width = 1
                    for decl in ctx.port_decls + ctx.signal_decls:
                        if decl['name'] == sig:
                            w = decl.get('width', '[0:0]')
                            m = re.search(r'\[(\d+)', w)
                            if m:
                                width = int(m.group(1)) + 1
                    if width == 1:
                        line = next(
                            (blk['start_line'] for blk in ctx.always_blocks
                             if _get_block_clock(blk) == clocks[j]),
                            1
                        )
                        findings.append(Finding(
                            rule_id=self.rule_id,
                            severity=self.severity,
                            category=self.category,
                            description=self.description,
                            file=ctx.filepath,
                            line=line,
                            snippet=f"1-bit signal '{sig}' crosses '{clocks[i]}' → '{clocks[j]}'",
                            suggestion="Instantiate a 2-FF synchronizer: sig_meta → sig_sync before use."
                        ))
        return findings


# ---------------------------------------------------------------------------
@register_rule
class VLG021(RuleBase):
    """
    Using a clock signal in a non-clock position (e.g., as a data input to
    combinational logic) creates gated or muxed clocks, which cause glitches.
    RTL reason: clock signals must only drive clock pins of flip-flops. Any
    combinational gating must happen through a dedicated clock-gating cell (ICG).
    """
    rule_id     = "VLG021"
    category    = "CDC"
    severity    = Severity.WARNING
    description = "Clock signal used as data (non-clock position) — potential gated clock hazard"

    def check(self, ctx: ParseContext) -> List[Finding]:
        findings = []
        clock_signals = _get_clock_signals(ctx)
        if not clock_signals:
            return findings

        # Check assign statements where clock appears on RHS in logic context
        for stmt in ctx.assign_stmts:
            for clk in clock_signals:
                # clock used in AND/OR/MUX on RHS of assign
                if re.search(rf'\b{re.escape(clk)}\b', stmt['rhs']):
                    if re.search(r'[&|^~]', stmt['rhs']):
                        findings.append(self._finding(
                            ctx, stmt['line'],
                            snippet=stmt['full'],
                            suggestion=(
                                f"'{clk}' is being gated combinationally. "
                                "Use a dedicated ICG (Integrated Clock Gating) cell instead."
                            )
                        ))
        return findings


# ---------------------------------------------------------------------------
@register_rule
class VLG022(RuleBase):
    """
    Gating a clock with combinational logic (e.g., 'assign gated_clk = clk & en')
    creates clock glitches and potential hold violations — especially dangerous
    in ASIC flows where the clock tree is built from a single dedicated net.
    RTL reason: clock glitches can corrupt registers; use ICG standard cells
    or FPGA-specific clock enable signals (CE pin) instead.
    """
    rule_id     = "VLG022"
    category    = "CDC"
    severity    = Severity.ERROR
    description = "Combinational logic found on clock path (gated clock) — glitch risk"

    def check(self, ctx: ParseContext) -> List[Finding]:
        findings = []
        clock_signals = _get_clock_signals(ctx)

        for stmt in ctx.assign_stmts:
            lhs = stmt['lhs']
            rhs = stmt['rhs']
            # LHS looks like a new clock (gated_clk, clk_en, etc.)
            lhs_is_clk = bool(_CLK_NAME_RE.search(lhs))
            # RHS contains an actual clock AND logic operators
            for clk in clock_signals:
                if re.search(rf'\b{re.escape(clk)}\b', rhs):
                    if lhs_is_clk and re.search(r'[&|^]', rhs):
                        findings.append(self._finding(
                            ctx, stmt['line'],
                            snippet=stmt['full'],
                            suggestion=(
                                "Avoid combinational clock gating. Use clock enable (CE) pins on FFs, "
                                "or instantiate tech-library ICG cells for ASIC."
                            )
                        ))
        return findings
