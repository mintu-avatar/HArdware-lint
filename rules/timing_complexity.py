"""
rules/timing_complexity.py — Timing Complexity rules
======================================================
VLG091  Long combinational chain — too many operations in single assign
VLG092  Latch mixed with flip-flops — inconsistent timing model
VLG093  Combinational feedback loop — signal depends on itself combinationally
VLG094  Wide mux without pipeline — large select mux creates timing bottleneck
VLG095  Wide arithmetic without pipeline — carry chain limits clock frequency

These rules flag RTL patterns that make timing closure difficult. Synthesis
tools report timing *after* place-and-route, but these rules catch the root
cause at the RTL level — before hours of P&R iterations.
"""

from __future__ import annotations
import re
from typing import List, Set
from engine.rule_base import RuleBase, Severity, Finding, ParseContext, register_rule


# ---------------------------------------------------------------------------
@register_rule
class VLG091(RuleBase):
    """
    A continuous assign or combinational expression with many chained
    operators (>6 operators) implies a deep combinational path that will
    be the critical timing path. Pipeline or break into stages.
    """
    rule_id     = "VLG091"
    category    = "Timing"
    severity    = Severity.WARNING
    description = "Long combinational chain (>6 ops) — likely critical timing path"

    THRESHOLD = 6
    _OPS = re.compile(r'[+\-*/&|^~<>]|<<|>>|==|!=|>=|<=|&&|\|\|')

    def check(self, ctx: ParseContext) -> List[Finding]:
        findings: List[Finding] = []
        for a in ctx.assign_stmts:
            ops = len(self._OPS.findall(a['rhs']))
            if ops > self.THRESHOLD:
                findings.append(self._finding(
                    ctx, a['line'],
                    snippet=f"assign has {ops} operators — deep combinational chain",
                    suggestion=(
                        "Break this assign into pipeline stages or intermediate wires. "
                        "Each operator adds gate delay; >6 in series is a timing risk."
                    ),
                ))
        # Also check combinational always block expressions
        for blk in ctx.always_blocks:
            if blk['block_type'] != 'combinational':
                continue
            for bln in blk['body_lines']:
                assign_m = re.search(r'=\s*(.+?)\s*;', bln)
                if assign_m:
                    rhs = assign_m.group(1)
                    ops = len(self._OPS.findall(rhs))
                    if ops > self.THRESHOLD:
                        findings.append(self._finding(
                            ctx, blk['start_line'],
                            snippet=f"Expression has {ops} operators in comb block",
                            suggestion=(
                                "Break complex expressions into named intermediate wires. "
                                "This helps synthesis optimize and improves timing."
                            ),
                        ))
                        break  # one per block
        return findings


# ---------------------------------------------------------------------------
@register_rule
class VLG092(RuleBase):
    """
    A module using both transparent latches (always @* with incomplete
    sensitivity or level-sensitive) and edge-triggered flip-flops has an
    inconsistent timing model. Latches and FFs have fundamentally different
    timing constraints, making STA unreliable.
    """
    rule_id     = "VLG092"
    category    = "Timing"
    severity    = Severity.WARNING
    description = "Latch mixed with flip-flops — inconsistent timing model in module"

    def check(self, ctx: ParseContext) -> List[Finding]:
        findings: List[Finding] = []
        for mod in ctx.modules:
            sl, el = mod['start_line'], mod['end_line']
            has_ff = False
            has_latch_hint = False
            for blk in ctx.always_blocks:
                if not (sl <= blk['start_line'] <= el):
                    continue
                if blk['block_type'] in ('clocked_posedge', 'clocked_negedge'):
                    has_ff = True
                elif blk['block_type'] in ('combinational', 'unknown'):
                    # Check if block uses non-blocking assign (latch-like) or incomplete assignment
                    body = '\n'.join(blk['body_lines'])
                    if re.search(r'\bif\b', body) and not re.search(r'\belse\b', body):
                        has_latch_hint = True
                    if re.search(r'<=', body) and blk['block_type'] == 'unknown':
                        has_latch_hint = True
            if has_ff and has_latch_hint:
                findings.append(self._finding(
                    ctx, sl,
                    snippet=f"Module '{mod['name']}' mixes FFs and potential latches",
                    suggestion=(
                        "Use either FFs (edge-triggered) or latches (level-sensitive), "
                        "not both. Mixed timing models confuse STA and cause hold violations."
                    ),
                ))
        return findings


# ---------------------------------------------------------------------------
@register_rule
class VLG093(RuleBase):
    """
    A signal that appears on both LHS and RHS of an assignment in a
    combinational always block creates a feedback loop. This is either
    an intentional latch (should be explicit) or a bug that causes
    simulation oscillation and synthesis unpredictability.
    """
    rule_id     = "VLG093"
    category    = "Timing"
    severity    = Severity.ERROR
    description = "Combinational feedback — signal on both LHS and RHS in comb block"

    _ASSIGN_BLK = re.compile(r'(\w+)\s*=\s*(.+?)\s*;')
    _IDENT      = re.compile(r'\b([a-zA-Z_]\w*)\b')

    def check(self, ctx: ParseContext) -> List[Finding]:
        findings: List[Finding] = []
        for blk in ctx.always_blocks:
            if blk['block_type'] != 'combinational':
                continue
            for bln in blk['body_lines']:
                for m in self._ASSIGN_BLK.finditer(bln):
                    lhs = m.group(1)
                    rhs = m.group(2)
                    rhs_idents = set(self._IDENT.findall(rhs))
                    if lhs in rhs_idents:
                        findings.append(self._finding(
                            ctx, blk['start_line'],
                            snippet=f"'{lhs}' depends on itself in combinational block",
                            suggestion=(
                                f"Signal '{lhs}' appears on both sides of '=' in a comb block. "
                                f"This creates a feedback loop. Use a registered (<=) path "
                                f"or restructure the logic."
                            ),
                        ))
        return findings


# ---------------------------------------------------------------------------
@register_rule
class VLG094(RuleBase):
    """
    A case/casez statement selecting among many wide buses without pipeline
    creates a large multiplexer tree that dominates the timing path.
    Anything over 8 branches of wide (>=16-bit) data should be pipelined.
    """
    rule_id     = "VLG094"
    category    = "Timing"
    severity    = Severity.INFO
    description = "Wide mux (>8 branches, >=16b) — pipeline to ease timing"

    BRANCH_THRESHOLD = 8
    WIDTH_THRESHOLD  = 16

    _CASE_RE     = re.compile(r'\b(case|casez|casex)\s*\(\s*(\w+)\s*\)')
    _END_CASE_RE = re.compile(r'\bendcase\b')
    _BRANCH_RE   = re.compile(r'^\s*\d+[\s\'dhbxzHDBXZ]|^\s*[A-Z_][A-Z0-9_]*\s*:|^\s*default\s*:')

    def check(self, ctx: ParseContext) -> List[Finding]:
        findings: List[Finding] = []
        for blk in ctx.always_blocks:
            if blk['block_type'] != 'combinational':
                continue
            body_lines = blk['body_lines']
            j = 0
            while j < len(body_lines):
                m = self._CASE_RE.search(body_lines[j])
                if m:
                    sel_sig = m.group(2)
                    branches = 0
                    k = j + 1
                    while k < len(body_lines):
                        if self._END_CASE_RE.search(body_lines[k]):
                            break
                        if self._BRANCH_RE.match(body_lines[k]):
                            branches += 1
                        k += 1
                    if branches > self.BRANCH_THRESHOLD:
                        # Check if output is wide
                        for bln in body_lines[j:k]:
                            assign_m = re.search(r'(\w+)\s*=', bln)
                            if assign_m:
                                from rules.reliability import VLG043
                                w = VLG043._width_of(assign_m.group(1), ctx)
                                if w >= self.WIDTH_THRESHOLD:
                                    findings.append(self._finding(
                                        ctx, blk['start_line'],
                                        snippet=f"Case mux: {branches} branches, output '{assign_m.group(1)}' is {w}b wide",
                                        suggestion=(
                                            "Pipeline the mux or use a ROM-based lookup. "
                                            "Large multiplexers create wide timing cones."
                                        ),
                                    ))
                                break
                    j = k + 1
                    continue
                j += 1
        return findings


# ---------------------------------------------------------------------------
@register_rule
class VLG095(RuleBase):
    """
    Wide arithmetic operations (addition, subtraction, multiplication on
    signals >= 16 bits) without pipeline stages create long carry chains
    that limit clock frequency. Pipeline the arithmetic or use DSP blocks.
    """
    rule_id     = "VLG095"
    category    = "Timing"
    severity    = Severity.INFO
    description = "Wide arithmetic (>=16b) without pipeline — carry chain limits Fmax"

    WIDTH_THRESHOLD = 16
    _ARITH_RE = re.compile(r'(\w+)\s*(?:<=|=)\s*(\w+)\s*([+\-*])\s*(\w+)')

    def check(self, ctx: ParseContext) -> List[Finding]:
        findings: List[Finding] = []
        seen: Set[int] = set()
        for i, ln in enumerate(ctx.clean_lines):
            for m in self._ARITH_RE.finditer(ln):
                result, op_a, op, op_b = m.group(1), m.group(2), m.group(3), m.group(4)
                if op_a.isdigit() or op_b.isdigit():
                    continue
                from rules.reliability import VLG043
                wa = VLG043._width_of(op_a, ctx)
                wb = VLG043._width_of(op_b, ctx)
                max_w = max(wa, wb)
                if max_w >= self.WIDTH_THRESHOLD and i not in seen:
                    seen.add(i)
                    # Check if this is inside a clocked block (pipelined) or comb
                    in_comb = any(
                        blk['block_type'] == 'combinational'
                        and blk['start_line'] <= i + 1 <= blk['end_line']
                        for blk in ctx.always_blocks
                    )
                    is_assign = ln.strip().startswith('assign')
                    if in_comb or is_assign:
                        findings.append(self._finding(
                            ctx, i + 1,
                            snippet=f"'{op_a}' ({wa}b) {op} '{op_b}' ({wb}b) in combinational path",
                            suggestion=(
                                f"Pipeline this {max_w}-bit {'+' if op == '+' else op} operation "
                                f"or infer a DSP block. Wide carry chains limit Fmax."
                            ),
                        ))
        return findings
