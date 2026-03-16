"""
rules/reliability.py — Reliability & Robustness rules
======================================================
VLG041  FSM without timeout / watchdog — FSM can hang forever
VLG042  Unregistered module output — combinational path directly to output port
VLG043  Comparison width mismatch — implicit sign/width extension risk
VLG044  Shift amount may exceed signal width — undefined/unintended behaviour
VLG045  Unprotected clock-enable feedback — CE signal depends on its own output

None of these are flagged by Vivado, Quartus, or typical synthesis tools.
They detect logical reliability holes that only surface post-silicon.
"""

from __future__ import annotations
import re
from typing import List, Set
from engine.rule_base import RuleBase, Severity, Finding, ParseContext, register_rule


# ---------------------------------------------------------------------------
@register_rule
class VLG041(RuleBase):
    """
    An FSM with no timeout / watchdog counter can lock-up in an unreachable
    state forever because of SEU (Single Event Upset), metastability, or
    firmware bugs. The module should have a watchdog timer or an explicit
    illegal-state recovery path.

    Heuristic: if a module has a case statement with a state variable AND no
    signal name containing 'timeout', 'watchdog', 'wdt', or 'timer' in the
    same module, flag it.
    """
    rule_id     = "VLG041"
    category    = "Reliability"
    severity    = Severity.WARNING
    description = "FSM has no timeout / watchdog — stuck-state lockup risk"

    _STATE_RE   = re.compile(r'\b(?:state|fsm_state|st_\w+)\b', re.I)
    _WDT_RE     = re.compile(r'\b(?:timeout|watchdog|wdt|wd_timer|timer_cnt)\b', re.I)
    _CASE_RE    = re.compile(r'\b(?:case|casez|casex)\b')

    def check(self, ctx: ParseContext) -> List[Finding]:
        findings: List[Finding] = []

        for mod in ctx.modules:
            sl, el = mod['start_line'], mod['end_line']
            mod_text = '\n'.join(ctx.clean_lines[sl - 1 : el])

            has_fsm_case = False
            case_line = sl
            for i in range(sl - 1, min(el, len(ctx.clean_lines))):
                ln = ctx.clean_lines[i]
                if self._CASE_RE.search(ln) and self._STATE_RE.search(ln):
                    has_fsm_case = True
                    case_line = i + 1
                    break

            if not has_fsm_case:
                continue

            if not self._WDT_RE.search(mod_text):
                findings.append(self._finding(
                    ctx, case_line,
                    snippet=f"Module '{mod['name']}' has FSM but no timeout/watchdog signal",
                    suggestion=(
                        "Add a watchdog counter that resets the FSM to IDLE after N cycles "
                        "of inactivity. This prevents permanent lockup from SEU or firmware bugs."
                    ),
                ))
        return findings


# ---------------------------------------------------------------------------
@register_rule
class VLG042(RuleBase):
    """
    An output port driven purely by combinational logic (never registered)
    creates a long, fragile timing path. A glitch on any input propagates
    immediately to the consumer module, violating output-registered design
    best practice.

    Heuristic: output ports that are driven by continuous assign or
    combinational always blocks only (never appear as LHS in a clocked block)
    are flagged.
    """
    rule_id     = "VLG042"
    category    = "Reliability"
    severity    = Severity.INFO
    description = "Unregistered output — combinational path to port, glitch & timing risk"

    def check(self, ctx: ParseContext) -> List[Finding]:
        findings: List[Finding] = []

        output_ports = {
            p['name'] for p in ctx.port_decls if p['direction'] == 'output'
        }
        if not output_ports:
            return findings

        # Signals assigned in clocked always blocks (registered)
        registered: Set[str] = set()
        _LHS = re.compile(r'(\w+)\s*<=')
        for blk in ctx.always_blocks:
            if blk['block_type'] in ('clocked_posedge', 'clocked_negedge'):
                for bln in blk['body_lines']:
                    for m in _LHS.finditer(bln):
                        registered.add(m.group(1))

        # Signals driven by continuous assign
        comb_driven: Set[str] = set()
        for a in ctx.assign_stmts:
            comb_driven.add(a['lhs'].split('[')[0])

        # Signals assigned in combinational always blocks
        _ASSIGN = re.compile(r'(\w+)\s*=')
        for blk in ctx.always_blocks:
            if blk['block_type'] == 'combinational':
                for bln in blk['body_lines']:
                    for m in _ASSIGN.finditer(bln):
                        comb_driven.add(m.group(1))

        for p in ctx.port_decls:
            if p['direction'] == 'output' and p['name'] in comb_driven and p['name'] not in registered:
                findings.append(self._finding(
                    ctx, p['line'],
                    snippet=f"Output port '{p['name']}' is driven combinationally, never registered",
                    suggestion=(
                        "Register this output with a flip-flop before driving it to the port. "
                        "This eliminates glitches and eases timing closure."
                    ),
                ))
        return findings


# ---------------------------------------------------------------------------
@register_rule
class VLG043(RuleBase):
    """
    Comparing signals of different declared widths without explicit extension
    is legal Verilog but silently zero-extends or sign-extends, which is a
    frequent source of bugs — especially around unsigned vs. signed arithmetic.

    Heuristic: in any comparison (==, !=, <, >, <=, >=) where both operands
    are identifiers, check their declared widths. If they differ and the
    difference is ≥ 4 bits, flag it.
    """
    rule_id     = "VLG043"
    category    = "Reliability"
    severity    = Severity.WARNING
    description = "Width mismatch in comparison — implicit extension may hide bugs"

    _CMP_RE = re.compile(r'(\w+)\s*(==|!=|>=|<=|[<>])\s*(\w+)')

    @staticmethod
    def _width_of(name: str, ctx: ParseContext) -> int:
        """Return bit-width of a signal/port, or -1 if unknown."""
        for p in ctx.port_decls:
            if p['name'] == name:
                return VLG043._parse_width(p['width'])
        for s in ctx.signal_decls:
            if s['name'] == name:
                return VLG043._parse_width(s['width'])
        return -1

    @staticmethod
    def _parse_width(w: str) -> int:
        """[N:M] -> N-M+1; [0:0] -> 1."""
        m = re.match(r'\[\s*(\d+)\s*:\s*(\d+)\s*\]', w)
        if m:
            return abs(int(m.group(1)) - int(m.group(2))) + 1
        return 1

    def check(self, ctx: ParseContext) -> List[Finding]:
        findings: List[Finding] = []
        for i, ln in enumerate(ctx.clean_lines):
            for m in self._CMP_RE.finditer(ln):
                lhs, rhs = m.group(1), m.group(3)
                # Skip constants / numbers
                if lhs.isdigit() or rhs.isdigit():
                    continue
                lw = self._width_of(lhs, ctx)
                rw = self._width_of(rhs, ctx)
                if lw > 0 and rw > 0 and abs(lw - rw) >= 4:
                    findings.append(self._finding(
                        ctx, i + 1,
                        snippet=f"'{lhs}' ({lw}b) vs '{rhs}' ({rw}b) — {abs(lw-rw)} bit mismatch",
                        suggestion=(
                            f"Explicitly extend the narrower signal or use a sized comparison: "
                            f"{{{{ {{abs(lw-rw)}}'b0, {lhs if lw < rw else rhs} }}}} to avoid implicit extension."
                        ),
                    ))
        return findings


# ---------------------------------------------------------------------------
@register_rule
class VLG044(RuleBase):
    """
    Shifting a signal by an amount >= its width produces zero (logical shift)
    or is undefined (arithmetic shift) in many simulators. This is typically
    a copy-paste bug.

    Heuristic: detect `sig << N` or `sig >> N` where N is a literal integer
    and sig has a declared width that is ≤ N.
    """
    rule_id     = "VLG044"
    category    = "Reliability"
    severity    = Severity.ERROR
    description = "Shift amount may exceed signal width — result is always zero or undefined"

    _SHIFT_RE = re.compile(r'(\w+)\s*(<<|>>)\s*(\d+)')

    def check(self, ctx: ParseContext) -> List[Finding]:
        findings: List[Finding] = []
        for i, ln in enumerate(ctx.clean_lines):
            for m in self._SHIFT_RE.finditer(ln):
                sig, shift_amt = m.group(1), int(m.group(3))
                w = VLG043._width_of(sig, ctx)
                if w > 0 and shift_amt >= w:
                    findings.append(self._finding(
                        ctx, i + 1,
                        snippet=f"'{sig}' is {w} bits wide but shifted by {shift_amt}",
                        suggestion=(
                            f"The shift amount ({shift_amt}) >= signal width ({w}). "
                            f"This always produces zero. Reduce the shift or widen the signal."
                        ),
                    ))
        return findings


# ---------------------------------------------------------------------------
@register_rule
class VLG045(RuleBase):
    """
    A clock-enable (CE) signal whose own registered output feeds back into
    its enable logic can create a self-disabling livelock: the CE disasserts,
    the FF stops updating, and nothing can re-assert CE.

    Heuristic: find `if (<ce_signal>)` guarding a clocked block where
    <ce_signal> is assigned inside the same block.
    """
    rule_id     = "VLG045"
    category    = "Reliability"
    severity    = Severity.WARNING
    description = "Clock-enable feedback — CE depends on its own registered output, livelock risk"

    _IF_CE = re.compile(r'\bif\s*\(\s*!?\s*(\w+)\s*\)')

    def check(self, ctx: ParseContext) -> List[Finding]:
        findings: List[Finding] = []
        _LHS_NB = re.compile(r'(\w+)\s*<=')

        for blk in ctx.always_blocks:
            if blk['block_type'] not in ('clocked_posedge', 'clocked_negedge'):
                continue

            body_text = '\n'.join(blk['body_lines'])

            # Collect all CE guard signals from `if (ce)` at the outer level
            ce_signals = set()
            for bln in blk['body_lines'][:5]:  # look at first few lines
                m = self._IF_CE.search(bln)
                if m:
                    ce_signals.add(m.group(1))

            # Collect all LHS non-blocking assignments
            assigned = set()
            for bln in blk['body_lines']:
                for m in _LHS_NB.finditer(bln):
                    assigned.add(m.group(1))

            # Flag if CE guard is also assigned inside the block
            for ce in ce_signals:
                if ce in assigned:
                    findings.append(self._finding(
                        ctx, blk['start_line'],
                        snippet=f"CE signal '{ce}' is both the if-guard and assigned inside this clocked block",
                        suggestion=(
                            f"Ensure '{ce}' has an external re-assertion path (e.g. from a "
                            f"different always block or external input) to avoid livelock."
                        ),
                    ))
        return findings
