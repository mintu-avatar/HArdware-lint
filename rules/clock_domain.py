"""
rules/clock_domain.py — Clock Domain Complexity rules
=======================================================
VLG086  Multiple clock domains in single module — partition into separate modules
VLG087  Clock signal used in data logic — clock treated as data, timing risk
VLG088  Generated clock without constraint hint — synthesis may not constrain
VLG089  Clock mux without glitch protection — glitch-free switching required
VLG090  Derived clock from counter bit — fragile, jitter-prone clock generation

No synthesis tool flags these as warnings. They catch clock architecture
issues that cause intermittent silicon failures.
"""

from __future__ import annotations
import re
from typing import List, Set
from engine.rule_base import RuleBase, Severity, Finding, ParseContext, register_rule


_CLK_RE = re.compile(r'\b(\w*cl?k\w*)\b', re.I)


# ---------------------------------------------------------------------------
@register_rule
class VLG086(RuleBase):
    """
    A module with always blocks sensitive to multiple distinct clock signals
    creates an implicit CDC boundary inside the module. Each clock domain
    should be in its own module with explicit synchronizers at the boundary.
    """
    rule_id     = "VLG086"
    category    = "Clock Domain"
    severity    = Severity.WARNING
    description = "Multiple clock domains in one module — partition for clean CDC"

    def check(self, ctx: ParseContext) -> List[Finding]:
        findings: List[Finding] = []
        for mod in ctx.modules:
            sl, el = mod['start_line'], mod['end_line']
            clocks: Set[str] = set()
            for blk in ctx.always_blocks:
                if not (sl <= blk['start_line'] <= el):
                    continue
                if blk['block_type'] in ('clocked_posedge', 'clocked_negedge'):
                    # Extract clock name from sensitivity list
                    for m in re.finditer(r'(?:posedge|negedge)\s+(\w+)', blk['sensitivity']):
                        sig = m.group(1)
                        # Skip reset signals
                        if re.search(r'rst|reset', sig, re.I):
                            continue
                        clocks.add(sig)
            if len(clocks) > 1:
                findings.append(self._finding(
                    ctx, sl,
                    snippet=f"Module '{mod['name']}' has {len(clocks)} clock domains: {sorted(clocks)}",
                    suggestion=(
                        "Move each clock domain into its own module. Add explicit "
                        "CDC synchronizers (2-FF, pulse sync, or async FIFO) at boundaries."
                    ),
                ))
        return findings


# ---------------------------------------------------------------------------
@register_rule
class VLG087(RuleBase):
    """
    Using a clock signal as data (on RHS of an assignment or in an
    expression outside sensitivity lists) creates a path from the clock
    tree to the data path, which violates timing assumptions and causes
    hold-time violations.
    """
    rule_id     = "VLG087"
    category    = "Clock Domain"
    severity    = Severity.ERROR
    description = "Clock signal used in data logic — timing model violation"

    def check(self, ctx: ParseContext) -> List[Finding]:
        findings: List[Finding] = []
        # Collect all clock signal names from sensitivity lists
        clock_sigs: Set[str] = set()
        for blk in ctx.always_blocks:
            if blk['block_type'] in ('clocked_posedge', 'clocked_negedge'):
                for m in re.finditer(r'(?:posedge|negedge)\s+(\w+)', blk['sensitivity']):
                    sig = m.group(1)
                    if not re.search(r'rst|reset', sig, re.I):
                        clock_sigs.add(sig)
        if not clock_sigs:
            return findings
        # Check if any clock signal appears on RHS of assignments
        for i, ln in enumerate(ctx.clean_lines):
            # Skip sensitivity list lines
            if re.search(r'always\s*@', ln):
                continue
            # Check assigns
            assign_m = re.search(r'(?:<=|(?<!=)=(?!=))\s*(.+?)(?:;|$)', ln)
            if assign_m:
                rhs = assign_m.group(1)
                for clk in clock_sigs:
                    if re.search(r'\b' + re.escape(clk) + r'\b', rhs):
                        findings.append(self._finding(
                            ctx, i + 1,
                            snippet=f"Clock signal '{clk}' used as data in expression",
                            suggestion=(
                                f"Never use clock '{clk}' as data. If you need clock status, "
                                f"use a clock-detect circuit with a separate reference clock."
                            ),
                        ))
        return findings


# ---------------------------------------------------------------------------
@register_rule
class VLG088(RuleBase):
    """
    A clock signal generated internally (assigned from combinational logic
    or a register) without a timing constraint comment or attribute carries
    the risk of being unconstrained in synthesis. SDC/XDC constraints for
    generated clocks must be explicitly added.
    """
    rule_id     = "VLG088"
    category    = "Clock Domain"
    severity    = Severity.WARNING
    description = "Generated clock without constraint hint — may be unconstrained"

    _GEN_CLK = re.compile(r'(\w*cl?k\w*)\s*(?:<=|=)', re.I)
    _CONSTRAINT_HINT = re.compile(r'create_generated_clock|set_clock|synopsys|pragma', re.I)

    def check(self, ctx: ParseContext) -> List[Finding]:
        findings: List[Finding] = []
        for i, ln in enumerate(ctx.clean_lines):
            m = self._GEN_CLK.search(ln)
            if m:
                clk_name = m.group(1)
                # Verify it's actually used as a clock somewhere
                is_used_as_clk = any(
                    re.search(r'(?:posedge|negedge)\s+' + re.escape(clk_name), blk['sensitivity'])
                    for blk in ctx.always_blocks
                )
                if not is_used_as_clk:
                    continue
                # Check surrounding lines for constraint hint
                context_start = max(0, i - 3)
                context_end = min(len(ctx.lines), i + 3)
                context = '\n'.join(ctx.lines[context_start:context_end])
                if not self._CONSTRAINT_HINT.search(context):
                    findings.append(self._finding(
                        ctx, i + 1,
                        snippet=f"Generated clock '{clk_name}' has no constraint hint",
                        suggestion=(
                            f"Add an SDC constraint: create_generated_clock -source [get_ports clk] "
                            f"-divide_by N [get_pins {clk_name}]. Or add a comment noting the "
                            f"constraint file entry."
                        ),
                    ))
                    break  # one per file
        return findings


# ---------------------------------------------------------------------------
@register_rule
class VLG089(RuleBase):
    """
    A clock multiplexer (sel ? clk_a : clk_b) without glitch protection
    can create runt pulses during switching that corrupt downstream FFs.
    Use ICG-based clock mux or a glitch-free switching cell.
    """
    rule_id     = "VLG089"
    category    = "Clock Domain"
    severity    = Severity.ERROR
    description = "Clock mux without glitch protection — runt pulse risk"

    _CLK_MUX = re.compile(
        r'(\w*cl?k\w*)\s*(?:<=|=)\s*.*\?\s*(\w*cl?k\w*)\s*:\s*(\w*cl?k\w*)',
        re.I
    )
    _CLK_ASSIGN = re.compile(
        r'assign\s+(\w*cl?k\w*)\s*=\s*.*\b(sel|select|mux)\b.*\b(\w*cl?k\w*)\b',
        re.I
    )

    def check(self, ctx: ParseContext) -> List[Finding]:
        findings: List[Finding] = []
        for i, ln in enumerate(ctx.clean_lines):
            m = self._CLK_MUX.search(ln) or self._CLK_ASSIGN.search(ln)
            if m:
                findings.append(self._finding(
                    ctx, i + 1,
                    snippet=f"Clock mux detected: {ln.strip()}",
                    suggestion=(
                        "Use a glitch-free clock mux cell (ICG-based). "
                        "A bare ternary or assign mux can produce runt pulses "
                        "that violate hold times on downstream FFs."
                    ),
                ))
        return findings


# ---------------------------------------------------------------------------
@register_rule
class VLG090(RuleBase):
    """
    Deriving a clock by taking a bit of a counter (e.g. clk_div <= count[2])
    produces a clock with high jitter and asymmetric duty cycle. Use a
    dedicated clock divider with proper duty-cycle correction.
    """
    rule_id     = "VLG090"
    category    = "Clock Domain"
    severity    = Severity.WARNING
    description = "Clock derived from counter bit — jitter & duty-cycle risk"

    _COUNTER_CLK = re.compile(
        r'(\w*cl?k\w*)\s*(?:<=|=)\s*(\w+)\s*\[\s*\d+\s*\]',
        re.I
    )
    _COUNTER_CLK2 = re.compile(
        r'(\w*cl?k\w*)\s*(?:<=|=)\s*~\s*\1',
        re.I
    )

    def check(self, ctx: ParseContext) -> List[Finding]:
        findings: List[Finding] = []
        for i, ln in enumerate(ctx.clean_lines):
            m = self._COUNTER_CLK.search(ln)
            if m:
                clk_name = m.group(1)
                counter = m.group(2)
                findings.append(self._finding(
                    ctx, i + 1,
                    snippet=f"'{clk_name}' derived from '{counter}' bit-select",
                    suggestion=(
                        f"Use a dedicated clock divider with enable: "
                        f"'always @(posedge clk) clk_en <= (count == N);' "
                        f"A counter-bit clock has high jitter and 50% duty cycle is not guaranteed."
                    ),
                ))
            m2 = self._COUNTER_CLK2.search(ln)
            if m2:
                findings.append(self._finding(
                    ctx, i + 1,
                    snippet=f"Clock toggle: '{m2.group(1)} <= ~{m2.group(1)}'",
                    suggestion=(
                        "Prefer a clock-enable architecture over toggling a register as clock. "
                        "Toggled clocks have routing-dependent skew and are hard to constrain."
                    ),
                ))
        return findings
