"""
rules/assignments.py — Blocking vs Non-Blocking Assignment rules
================================================================
VLG013  Blocking assignment in clocked always block
VLG014  Non-blocking assignment in combinational always block
VLG015  Mixed blocking/non-blocking in same always block
"""

from __future__ import annotations
import re
from typing import List
from engine.rule_base import RuleBase, Severity, Finding, ParseContext, register_rule


# Matches `<=` (non-blocking) — must come before blocking check
_NBA_RE = re.compile(r'<=(?!=)')             # <= but NOT <==

# Matches `=` used as assignment (not ==, !=, <=)
# Strategy: strip all <= and == first, then look for plain =
def _has_blocking(line: str) -> bool:
    """True if the line contains a blocking assignment `=` (not `<=` or `==` or `!=`)."""
    # Remove string literals and known non-assignment = patterns
    s = re.sub(r'==|!=|<=|>=', '##', line)
    return bool(re.search(r'(?<![#<>!])=(?![>=])', s))

def _has_nonblocking(line: str) -> bool:
    return bool(_NBA_RE.search(line))


# ---------------------------------------------------------------------------
@register_rule
class VLG013(RuleBase):
    """
    Blocking assignments (=) inside clocked always blocks create race
    conditions when multiple blocks share signals. The order of block
    evaluation in a simulator is non-deterministic.
    RTL reason: clocked blocks model flip-flops — use <= (non-blocking)
    so all updates happen atomically at the clock edge.
    """
    rule_id     = "VLG013"
    category    = "Assignments"
    severity    = Severity.ERROR
    description = "Blocking assignment '=' used in clocked always block — use '<=' for FFs"

    def check(self, ctx: ParseContext) -> List[Finding]:
        findings = []
        for blk in ctx.always_blocks:
            if blk['block_type'] not in ('clocked_posedge', 'clocked_negedge'):
                continue
            for j, body_ln in enumerate(blk['body_lines']):
                clean = ctx.clean_lines[blk['start_line'] + j]  # aligned clean line
                # Skip lines that are just 'begin', 'end', 'if', 'else', 'case'
                stripped = clean.strip()
                if re.match(r'^(begin|end|if|else|case|endcase|default)\b', stripped):
                    continue
                if _has_blocking(clean) and not _has_nonblocking(clean):
                    abs_line = blk['start_line'] + j + 1
                    findings.append(self._finding(
                        ctx, abs_line,
                        suggestion="Change '=' to '<=' for all register assignments in clocked always blocks."
                    ))
        return findings


# ---------------------------------------------------------------------------
@register_rule
class VLG014(RuleBase):
    """
    Non-blocking assignments (<=) in combinational always blocks cause
    one-delta-cycle delays, making the simulation model wrong and causing
    hard-to-find functional bugs.
    RTL reason: combinational logic has no state — use = (blocking)
    so signal values are immediately available to dependent logic.
    """
    rule_id     = "VLG014"
    category    = "Assignments"
    severity    = Severity.ERROR
    description = "Non-blocking assignment '<=' used in combinational always block — use '='"

    def check(self, ctx: ParseContext) -> List[Finding]:
        findings = []
        for blk in ctx.always_blocks:
            if blk['block_type'] != 'combinational':
                continue
            for j, body_ln in enumerate(blk['body_lines']):
                idx = blk['start_line'] + j
                if idx >= len(ctx.clean_lines):
                    break
                clean = ctx.clean_lines[idx]
                if _has_nonblocking(clean):
                    abs_line = blk['start_line'] + j + 1
                    findings.append(self._finding(
                        ctx, abs_line,
                        suggestion="Change '<=' to '=' in combinational always blocks."
                    ))
        return findings


# ---------------------------------------------------------------------------
@register_rule
class VLG015(RuleBase):
    """
    Mixing blocking and non-blocking assignments in the same block creates
    complex and unpredictable simulation scheduling behavior.
    RTL reason: the Verilog event scheduling algorithm creates non-obvious
    orderings when both assignment types appear in one block.
    """
    rule_id     = "VLG015"
    category    = "Assignments"
    severity    = Severity.WARNING
    description = "Mixed blocking and non-blocking assignments in same always block"

    def check(self, ctx: ParseContext) -> List[Finding]:
        findings = []
        for blk in ctx.always_blocks:
            has_blk = False
            has_nba = False
            for j, _ in enumerate(blk['body_lines']):
                idx = blk['start_line'] + j
                if idx >= len(ctx.clean_lines):
                    break
                clean = ctx.clean_lines[idx]
                stripped = clean.strip()
                if re.match(r'^(begin|end|if|else|case|endcase)\b', stripped):
                    continue
                if _has_nonblocking(clean):
                    has_nba = True
                elif _has_blocking(clean):
                    has_blk = True
                if has_blk and has_nba:
                    break
            if has_blk and has_nba:
                findings.append(self._finding(
                    ctx, blk['start_line'],
                    suggestion="Use exclusively '<=' in clocked blocks and '=' in combinational blocks. Never mix."
                ))
        return findings
