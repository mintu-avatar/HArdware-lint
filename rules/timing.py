"""
rules/timing.py — Timing & Combinational Loop rules
=====================================================
VLG035  Combinational feedback loop (signal feeds itself via assign)
VLG036  Deep combinational nesting (long logic chain)
VLG037  Combinational assign to a reg-type signal
"""

from __future__ import annotations
import re
from typing import List
from engine.rule_base import RuleBase, Severity, Finding, ParseContext, register_rule


# ---------------------------------------------------------------------------
@register_rule
class VLG035(RuleBase):
    """
    A combinational feedback loop occurs when a signal's assignment depends
    (directly or transitively) on itself without an intervening flip-flop.
    RTL reason: combinational loops cause oscillation in simulation (delta-cycle
    storm) and synthesis tools will either fail or insert a latch to break the loop,
    leading to undefined timing closure behavior.
    """
    rule_id     = "VLG035"
    category    = "Timing"
    severity    = Severity.ERROR
    description = "Combinational feedback loop detected — signal appears on both LHS and RHS of assign"

    def check(self, ctx: ParseContext) -> List[Finding]:
        findings = []
        for stmt in ctx.assign_stmts:
            lhs = re.sub(r'\[.*?\]', '', stmt['lhs']).strip()
            rhs = stmt['rhs']
            # Check if LHS signal name appears in RHS
            if re.search(rf'\b{re.escape(lhs)}\b', rhs):
                findings.append(self._finding(
                    ctx, stmt['line'],
                    snippet=stmt['full'],
                    suggestion=(
                        f"'{lhs}' feeds itself — insert a register (flip-flop) to break the loop: "
                        "use a clocked always block with '<='."
                    )
                ))
        return findings


# ---------------------------------------------------------------------------
@register_rule
class VLG036(RuleBase):
    """
    Deep nesting of ternary operators or large case/if trees creates long
    combinational paths that are hard to meet timing on, especially at
    high frequencies.
    RTL reason: each level of ternary (?:) adds a MUX delay in the
    critical path. Deep trees (>4 levels) should be pipelined or restructured.
    """
    rule_id     = "VLG036"
    category    = "Timing"
    severity    = Severity.WARNING
    description = "Deeply nested ternary operator (>4 levels) — long combinational path, timing risk"

    _TERNARY_THRESH = 4

    def check(self, ctx: ParseContext) -> List[Finding]:
        findings = []
        for i, ln in enumerate(ctx.clean_lines):
            count = ln.count('?')
            if count > self._TERNARY_THRESH:
                findings.append(self._finding(
                    ctx, i + 1,
                    snippet=f"[{count} ternary operators] " + ln.strip()[:80],
                    suggestion=(
                        "Refactor deeply nested ternary chains into a 'case' statement "
                        "or pipeline the computation across clock cycles."
                    )
                ))
        return findings


# ---------------------------------------------------------------------------
@register_rule
class VLG037(RuleBase):
    """
    Using 'assign' (continuous assignment) to drive a signal declared as 'reg'
    is semantically confusing and can hide intent. 'reg' implies procedural
    assignment; using 'assign' on it means it's actually a wire.
    RTL reason: in SystemVerilog, use 'logic' for both. In Verilog-2001,
    'reg' with 'assign' creates a trireg by default in some tools — dangerous.
    """
    rule_id     = "VLG037"
    category    = "Timing"
    severity    = Severity.WARNING
    description = "Continuous 'assign' drives a 'reg'-declared signal — use 'wire' instead"

    def check(self, ctx: ParseContext) -> List[Finding]:
        findings = []
        reg_names = {d['name'] for d in ctx.signal_decls if d['dtype'] == 'reg'}
        for stmt in ctx.assign_stmts:
            lhs_clean = re.sub(r'\[.*?\]', '', stmt['lhs']).strip()
            if lhs_clean in reg_names:
                findings.append(self._finding(
                    ctx, stmt['line'],
                    snippet=stmt['full'],
                    suggestion=(
                        f"Change 'reg {lhs_clean}' declaration to 'wire {lhs_clean}' "
                        "since it's driven by continuous assignment, not a procedural block."
                    )
                ))
        return findings
