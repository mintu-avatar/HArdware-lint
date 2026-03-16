"""
rules/structural_complexity.py — Structural Complexity rules
==============================================================
VLG076  High RTL cyclomatic complexity — too many decision points per block
VLG077  Deep multiplexer chain — long priority-select chain
VLG078  Excessive signal fan-in — single signal depends on too many sources
VLG079  High module interconnect ratio — too many internal signals vs ports
VLG080  Excessive always-block decision depth without decomposition

These rules compute an RTL equivalent of software cyclomatic complexity,
measuring the structural difficulty of the design. No synthesis tool checks
for these — they predict verification effort and bug density.
"""

from __future__ import annotations
import re
from typing import List, Set
from engine.rule_base import RuleBase, Severity, Finding, ParseContext, register_rule


# ---------------------------------------------------------------------------
@register_rule
class VLG076(RuleBase):
    """
    RTL Cyclomatic Complexity: count decision points (if, case, ternary)
    inside a single always block. If the count exceeds a threshold, the
    block is too complex to verify exhaustively and should be decomposed.

    CC = 1 + number_of_decision_points
    Threshold: CC > 15
    """
    rule_id     = "VLG076"
    category    = "Structural"
    severity    = Severity.WARNING
    description = "High RTL cyclomatic complexity (>15) — decompose always block"

    THRESHOLD = 15
    _DECISION_RE = re.compile(r'\b(if|case|casez|casex)\b|\?')

    def check(self, ctx: ParseContext) -> List[Finding]:
        findings: List[Finding] = []
        for blk in ctx.always_blocks:
            body = '\n'.join(blk['body_lines'])
            decisions = len(self._DECISION_RE.findall(body))
            cc = 1 + decisions
            if cc > self.THRESHOLD:
                findings.append(self._finding(
                    ctx, blk['start_line'],
                    snippet=f"RTL cyclomatic complexity = {cc} (threshold: {self.THRESHOLD})",
                    suggestion=(
                        "Split this always block into smaller blocks or extract "
                        "sub-expressions into named wires. CC > 15 strongly predicts "
                        "verification gaps and late-found bugs."
                    ),
                ))
        return findings


# ---------------------------------------------------------------------------
@register_rule
class VLG077(RuleBase):
    """
    A chain of if/else-if/else-if without a case statement creates a
    priority-encoded multiplexer chain. Beyond 6 levels, this becomes a
    timing bottleneck and is hard to read.
    """
    rule_id     = "VLG077"
    category    = "Structural"
    severity    = Severity.WARNING
    description = "Deep if/else-if chain (>6) — long priority mux, split or use case"

    THRESHOLD = 6
    _ELSE_IF = re.compile(r'\belse\s+if\b')

    def check(self, ctx: ParseContext) -> List[Finding]:
        findings: List[Finding] = []
        for blk in ctx.always_blocks:
            chain_len = 0
            max_chain = 0
            chain_start = blk['start_line']
            for bln in blk['body_lines']:
                if self._ELSE_IF.search(bln):
                    chain_len += 1
                    max_chain = max(max_chain, chain_len)
                elif re.search(r'\bif\b', bln) and not self._ELSE_IF.search(bln):
                    chain_len = 1
                    max_chain = max(max_chain, chain_len)
            if max_chain > self.THRESHOLD:
                findings.append(self._finding(
                    ctx, blk['start_line'],
                    snippet=f"if/else-if chain depth: {max_chain} (threshold: {self.THRESHOLD})",
                    suggestion=(
                        "Convert long if/else-if chains to case statements for parallel "
                        "decoding. Priority mux chains create O(n) timing paths."
                    ),
                ))
        return findings


# ---------------------------------------------------------------------------
@register_rule
class VLG078(RuleBase):
    """
    When a single signal's RHS expression references many other signals
    (high fan-in), it indicates tightly coupled logic that is hard to
    test and likely to have long combinational paths.
    """
    rule_id     = "VLG078"
    category    = "Structural"
    severity    = Severity.INFO
    description = "High fan-in — single assign depends on >8 distinct signals"

    THRESHOLD = 8
    _IDENT = re.compile(r'\b([a-zA-Z_]\w*)\b')
    _KEYWORDS = {
        'if', 'else', 'begin', 'end', 'case', 'endcase', 'assign',
        'wire', 'reg', 'logic', 'input', 'output', 'inout',
        'posedge', 'negedge', 'always', 'module', 'endmodule',
        'parameter', 'localparam', 'default',
    }

    def check(self, ctx: ParseContext) -> List[Finding]:
        findings: List[Finding] = []
        for a in ctx.assign_stmts:
            rhs = a['rhs']
            idents = set(self._IDENT.findall(rhs)) - self._KEYWORDS
            # Remove numeric-like tokens
            idents = {i for i in idents if not i[0].isdigit()}
            if len(idents) > self.THRESHOLD:
                findings.append(self._finding(
                    ctx, a['line'],
                    snippet=f"assign '{a['lhs']}' depends on {len(idents)} signals: {sorted(idents)[:5]}...",
                    suggestion=(
                        "Break this assign into intermediate wires to reduce fan-in. "
                        "High fan-in causes long combinational paths and hinders testability."
                    ),
                ))
        return findings


# ---------------------------------------------------------------------------
@register_rule
class VLG079(RuleBase):
    """
    A module with many more internal signals than ports suggests that the
    module is doing too much. A high internal-signal-to-port ratio indicates
    poor decomposition.
    """
    rule_id     = "VLG079"
    category    = "Structural"
    severity    = Severity.INFO
    description = "High interconnect ratio — internal signals >> ports, consider splitting"

    RATIO_THRESHOLD = 5  # internal signals / port count

    def check(self, ctx: ParseContext) -> List[Finding]:
        findings: List[Finding] = []
        for mod in ctx.modules:
            sl, el = mod['start_line'], mod['end_line']
            port_count = sum(1 for p in ctx.port_decls if sl <= p['line'] <= el)
            sig_count  = sum(1 for s in ctx.signal_decls if sl <= s['line'] <= el)
            if port_count > 0 and sig_count > self.RATIO_THRESHOLD * port_count:
                findings.append(self._finding(
                    ctx, sl,
                    snippet=f"Module '{mod['name']}': {sig_count} internal signals vs {port_count} ports (ratio {sig_count/port_count:.1f}x)",
                    suggestion=(
                        "Consider splitting this module into smaller sub-modules. "
                        "A high signal-to-port ratio indicates monolithic design."
                    ),
                ))
        return findings


# ---------------------------------------------------------------------------
@register_rule
class VLG080(RuleBase):
    """
    An always block with many sequential decision levels (nested if/case
    inside if/case) without being decomposed into functions or sub-modules
    is extremely hard to formally verify or review.
    """
    rule_id     = "VLG080"
    category    = "Structural"
    severity    = Severity.WARNING
    description = "Always block has >5 distinct decision paths — decompose for verifiability"

    THRESHOLD = 5

    def check(self, ctx: ParseContext) -> List[Finding]:
        findings: List[Finding] = []
        for blk in ctx.always_blocks:
            # Count distinct decision keywords in the body
            body = '\n'.join(blk['body_lines'])
            ifs   = len(re.findall(r'\bif\b', body))
            cases = len(re.findall(r'\b(?:case|casez|casex)\b', body))
            paths = ifs + cases
            if paths > self.THRESHOLD:
                findings.append(self._finding(
                    ctx, blk['start_line'],
                    snippet=f"{paths} decision constructs (if/case) in single always block",
                    suggestion=(
                        "Extract sub-logic into functions, named always blocks, or "
                        "sub-modules. Dense decision logic is the #1 source of "
                        "missed corner cases in verification."
                    ),
                ))
        return findings
