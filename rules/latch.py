"""
rules/latch.py — Latch Inference rules
=======================================
VLG016  Incomplete if without else in combinational block
VLG017  case without default in combinational block
VLG018  Signal not assigned on all paths (general latch risk)
"""

from __future__ import annotations
import re
from typing import List, Set
from engine.rule_base import RuleBase, Severity, Finding, ParseContext, register_rule


def _body_text(blk: dict) -> str:
    return '\n'.join(blk['body_lines'])


# ---------------------------------------------------------------------------
@register_rule
class VLG016(RuleBase):
    """
    In a combinational always block, an 'if' without a matching 'else' means
    the output retains its previous value when the condition is false —
    the synthesizer infers a LATCH to preserve state.
    RTL reason: unintentional latches cause hold-time violations in ASIC flows
    and consume extra logic in FPGAs. They are hard to test for stuck-at faults.
    """
    rule_id     = "VLG016"
    category    = "Latch"
    severity    = Severity.ERROR
    description = "Incomplete 'if' without 'else' in combinational block — latch may be inferred"

    _DEFAULT_ASSIGN_RE = re.compile(r'^\s*(\w+)\s*=\s*')
    _CONTROL_RE = re.compile(r'\b(if|case|casez|casex)\b')

    def check(self, ctx: ParseContext) -> List[Finding]:
        findings = []
        for blk in ctx.always_blocks:
            if blk['block_type'] != 'combinational':
                continue
            body = _body_text(blk)

            # Check for top-of-block default assignments before any if/case.
            # If defaults exist, if-without-else is safe (no latch inferred).
            has_top_defaults = False
            for bln in blk['body_lines']:
                stripped = bln.strip()
                if not stripped or stripped == 'begin':
                    continue
                if self._DEFAULT_ASSIGN_RE.match(stripped) and not self._CONTROL_RE.search(stripped):
                    has_top_defaults = True
                    continue
                break  # first non-assignment, non-blank line

            if has_top_defaults:
                continue

            # Count top-level if vs else — heuristic: more 'if' than 'else'
            if_count   = len(re.findall(r'\bif\b', body))
            else_count = len(re.findall(r'\belse\b', body))
            if if_count > else_count:
                findings.append(self._finding(
                    ctx, blk['start_line'],
                    suggestion=(
                        "Add an 'else' clause covering all outputs, or assign defaults at "
                        "the top of the block before the if statement."
                    )
                ))
        return findings


# ---------------------------------------------------------------------------
@register_rule
class VLG017(RuleBase):
    """
    A 'case' statement in a combinational block without a 'default' branch
    leaves outputs undefined (and latched) for unspecified input combinations.
    RTL reason: synthesis tools infer a latch for signals that have no
    assignment in the unmatched case items.
    """
    rule_id     = "VLG017"
    category    = "Latch"
    severity    = Severity.ERROR
    description = "'case' statement missing 'default' in combinational block — latch inferred"

    _CASE_RE    = re.compile(r'\bcase\b\s*\(')
    _DEFAULT_RE = re.compile(r'\bdefault\b')

    def check(self, ctx: ParseContext) -> List[Finding]:
        findings = []
        for blk in ctx.always_blocks:
            if blk['block_type'] != 'combinational':
                continue
            body = _body_text(blk)
            case_count    = len(self._CASE_RE.findall(body))
            default_count = len(self._DEFAULT_RE.findall(body))
            if case_count > 0 and default_count < case_count:
                findings.append(self._finding(
                    ctx, blk['start_line'],
                    suggestion="Add 'default: <output> = <safe_value>;' to every case statement."
                ))
        return findings


# ---------------------------------------------------------------------------
@register_rule
class VLG018(RuleBase):
    """
    More general latch detector: if a signal appears on the LHS of an
    assignment only in some branches of a combinational block but not all,
    it will be latched.
    RTL reason: the standard fix is to assign defaults to all outputs at
    the very first line of the combinational block.
    """
    rule_id     = "VLG018"
    category    = "Latch"
    severity    = Severity.WARNING
    description = "Output not assigned on all paths in combinational block — possible latch"

    # Simple heuristic: check for any conditional without a default assignment
    _LHS_RE = re.compile(r'^\s*(\w+)\s*(?:\[[^\]]*\])?\s*=(?!=)')

    def check(self, ctx: ParseContext) -> List[Finding]:
        findings = []
        for blk in ctx.always_blocks:
            if blk['block_type'] != 'combinational':
                continue
            # Collect all LHS signals
            lhs_signals: Set[str] = set()
            for ln in blk['body_lines']:
                m = self._LHS_RE.match(ln)
                if m:
                    lhs_signals.add(m.group(1))
            # Check if there's conditional logic but no default assignment
            body = _body_text(blk)
            has_conditional = bool(re.search(r'\b(if|case)\b', body))
            # Look for default assignment pattern: signal = val; at top of block (before any if/case)
            lines_before_cond: List[str] = []
            for ln in blk['body_lines']:
                if re.search(r'\b(if|case)\b', ln):
                    break
                lines_before_cond.append(ln)

            pre_assigned: Set[str] = set()
            for ln in lines_before_cond:
                m = self._LHS_RE.match(ln)
                if m:
                    pre_assigned.add(m.group(1))

            if has_conditional:
                missing = lhs_signals - pre_assigned
                for sig in sorted(missing):
                    # Only flag if signal doesn't have a // safe default bypass
                    findings.append(self._finding(
                        ctx, blk['start_line'],
                        snippet=f"Signal '{sig}' may not be assigned on all paths",
                        suggestion=f"Add default assignment '{sig} = <safe_val>;' at the top of the combinational block."
                    ))
        return findings
