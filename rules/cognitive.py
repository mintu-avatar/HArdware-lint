"""
rules/cognitive.py — Cognitive Complexity rules
=================================================
VLG056  Excessive case branches (>12) — consider ROM / LUT decode
VLG057  Complex boolean expression (>4 operators in single expression)
VLG058  Chained ternary operators (>2 nested) — use case instead
VLG059  File contains multiple modules — split for readability
VLG060  Mixed coding styles (behavioral + structural) in same module

These rules have no Vivado / Quartus equivalent. They measure the
cognitive load a human reviewer must carry when reading the RTL,
directly predicting review time and defect escape rate.
"""

from __future__ import annotations
import re
from typing import List
from engine.rule_base import RuleBase, Severity, Finding, ParseContext, register_rule


# ---------------------------------------------------------------------------
@register_rule
class VLG056(RuleBase):
    """
    A case statement with more than 12 branches suggests the logic should
    be implemented as a ROM or LUT array. Enumerating dozens of branches
    is unreadable and easy to get wrong; a ROM indexed by the select signal
    is both smaller in area and far easier to review.
    """
    rule_id     = "VLG056"
    category    = "Cognitive"
    severity    = Severity.INFO
    description = "Case statement has >12 branches — consider ROM or LUT decode"

    THRESHOLD = 12
    _CASE_RE  = re.compile(r'\b(case|casez|casex)\b')
    _BRANCH_RE = re.compile(r'^\s*\d+[\s\'dhbxzHDBXZ]|^\s*[A-Z_][A-Z0-9_]*\s*:')
    _DEFAULT_RE = re.compile(r'^\s*default\s*:')
    _END_CASE_RE = re.compile(r'\bendcase\b')

    def check(self, ctx: ParseContext) -> List[Finding]:
        findings: List[Finding] = []
        lines = ctx.clean_lines
        i = 0
        while i < len(lines):
            ln = lines[i]
            if self._CASE_RE.search(ln):
                case_line = i + 1
                branches = 0
                j = i + 1
                while j < len(lines):
                    if self._END_CASE_RE.search(lines[j]):
                        break
                    if self._BRANCH_RE.match(lines[j]) or self._DEFAULT_RE.match(lines[j]):
                        branches += 1
                    j += 1
                if branches > self.THRESHOLD:
                    findings.append(self._finding(
                        ctx, case_line,
                        snippet=f"case statement has {branches} branches (threshold: {self.THRESHOLD})",
                        suggestion=(
                            "Replace large case with a ROM array or lookup table. "
                            "Example: wire [W-1:0] rom [0:N]; assign out = rom[sel];"
                        ),
                    ))
                i = j + 1
                continue
            i += 1
        return findings


# ---------------------------------------------------------------------------
@register_rule
class VLG057(RuleBase):
    """
    A single expression with more than 4 boolean / bitwise operators
    (&, |, ^, ~, &&, ||) is extremely hard to verify visually. The
    probability of a parenthesization error or inverted polarity rises
    steeply with operator count.
    """
    rule_id     = "VLG057"
    category    = "Cognitive"
    severity    = Severity.WARNING
    description = "Complex boolean expression (>4 operators) — hard to review, split into named wires"

    THRESHOLD = 4
    # Count boolean/bitwise operators — exclude inside comments (already stripped)
    _BOOL_OPS = re.compile(r'&&|\|\||[&|^~]')
    # Exclude pure declarations (not wire assignments like 'wire x = expr')
    _DECL_RE = re.compile(r'^\s*(input|output|inout|reg|logic|parameter|localparam)\b')
    _WIRE_ASSIGN_RE = re.compile(r'^\s*wire\b.*=')  # wire x = expr → don't exclude

    def check(self, ctx: ParseContext) -> List[Finding]:
        findings: List[Finding] = []
        for i, ln in enumerate(ctx.clean_lines):
            # Skip pure declarations but allow wire assignments
            if self._DECL_RE.match(ln):
                continue
            if re.match(r'^\s*wire\b', ln) and not self._WIRE_ASSIGN_RE.match(ln):
                continue
            count = len(self._BOOL_OPS.findall(ln))
            if count > self.THRESHOLD:
                findings.append(self._finding(
                    ctx, i + 1,
                    snippet=f"{count} boolean/bitwise operators in single expression (threshold: {self.THRESHOLD})",
                    suggestion=(
                        "Break this expression into named intermediate wires with meaningful names. "
                        "Example: wire addr_hit = (addr >= BASE) & (addr < BASE + SIZE);"
                    ),
                ))
        return findings


# ---------------------------------------------------------------------------
@register_rule
class VLG058(RuleBase):
    """
    Chained ternary operators ( a ? b : c ? d : e ? f : g ) are the
    hardware equivalent of deeply nested if/else in one expression.
    After 2 levels they become nearly impossible to read. Use a case
    statement or named wires instead.
    """
    rule_id     = "VLG058"
    category    = "Cognitive"
    severity    = Severity.WARNING
    description = "Chained ternary (>2 deep) — replace with case or named wires for clarity"

    THRESHOLD = 2

    def check(self, ctx: ParseContext) -> List[Finding]:
        findings: List[Finding] = []
        for i, ln in enumerate(ctx.clean_lines):
            # Count number of '?' on the line (proxy for ternary depth)
            ternary_count = ln.count('?')
            if ternary_count > self.THRESHOLD:
                findings.append(self._finding(
                    ctx, i + 1,
                    snippet=f"{ternary_count} ternary operators on one line (threshold: {self.THRESHOLD})",
                    suggestion=(
                        "Replace chained ternaries with a case statement or "
                        "break into named intermediate wires for clarity."
                    ),
                ))
        return findings


# ---------------------------------------------------------------------------
@register_rule
class VLG059(RuleBase):
    """
    Putting multiple module definitions in one file makes it hard to find
    code, confuses version control blame, and violates the "one module per
    file" convention used in nearly all RTL team style guides.
    """
    rule_id     = "VLG059"
    category    = "Cognitive"
    severity    = Severity.WARNING
    description = "File contains multiple modules — one module per file for traceability"

    def check(self, ctx: ParseContext) -> List[Finding]:
        findings: List[Finding] = []
        if len(ctx.modules) > 1:
            for mod in ctx.modules[1:]:
                findings.append(self._finding(
                    ctx, mod['start_line'],
                    snippet=f"Second module '{mod['name']}' in same file (first was '{ctx.modules[0]['name']}')",
                    suggestion=(
                        f"Move module '{mod['name']}' to its own file '{mod['name']}.v'. "
                        f"One module per file improves discoverability and version-control clarity."
                    ),
                ))
        return findings


# ---------------------------------------------------------------------------
@register_rule
class VLG060(RuleBase):
    """
    Mixing behavioral (always blocks) and structural (module instantiation)
    coding styles inside one module increases cognitive load. Readers must
    mentally switch between two abstraction levels. Prefer one style
    per module: either pure-structural wrapper or pure-behavioral logic.
    """
    rule_id     = "VLG060"
    category    = "Cognitive"
    severity    = Severity.INFO
    description = "Mixed behavioral + structural styles in one module — pick one for clarity"

    def check(self, ctx: ParseContext) -> List[Finding]:
        findings: List[Finding] = []
        for mod in ctx.modules:
            sl, el = mod['start_line'], mod['end_line']
            has_behavioral = any(
                sl <= blk['start_line'] <= el for blk in ctx.always_blocks
            )
            has_structural = any(
                sl <= inst['line'] <= el for inst in ctx.instances
            )
            if has_behavioral and has_structural:
                findings.append(self._finding(
                    ctx, sl,
                    snippet=f"Module '{mod['name']}' mixes always blocks and module instantiations",
                    suggestion=(
                        "Separate structural (instantiation) wrappers from behavioral (always) "
                        "logic. This reduces cognitive load during code review."
                    ),
                ))
        return findings
