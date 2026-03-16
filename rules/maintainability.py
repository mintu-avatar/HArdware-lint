"""
rules/maintainability.py — Maintainability & Code-Health rules
===============================================================
VLG046  Module too long (>300 SLOC)
VLG047  Module has too many ports (>20)
VLG048  Deeply nested control flow (>3 levels of if/case)
VLG049  Too many always blocks in one module (>10)
VLG050  Repeated magic constant (same literal number appears >3 times)

These are code-smell / design-health rules. No synthesis tool or Vivado
linter reports them, but they strongly predict maintenance burden, review
difficulty, and latent bug rate.
"""

from __future__ import annotations
import re
from collections import Counter
from typing import List, Dict
from engine.rule_base import RuleBase, Severity, Finding, ParseContext, register_rule


# ---------------------------------------------------------------------------
@register_rule
class VLG046(RuleBase):
    """
    Modules over ~300 source lines of code (SLOC, excluding blank lines and
    comments) are hard to review, test, simulate, and modify. They should be
    decomposed into smaller sub-modules.
    """
    rule_id     = "VLG046"
    category    = "Maintainability"
    severity    = Severity.INFO
    description = "Module exceeds 300 SLOC — split into smaller sub-modules for readability"

    THRESHOLD = 300

    def check(self, ctx: ParseContext) -> List[Finding]:
        findings: List[Finding] = []
        for mod in ctx.modules:
            sl, el = mod['start_line'], mod['end_line']
            sloc = 0
            for i in range(sl - 1, min(el, len(ctx.clean_lines))):
                ln = ctx.clean_lines[i].strip()
                if ln and ln not in ('begin', 'end'):
                    sloc += 1
            if sloc > self.THRESHOLD:
                findings.append(self._finding(
                    ctx, sl,
                    snippet=f"Module '{mod['name']}' has {sloc} SLOC (threshold: {self.THRESHOLD})",
                    suggestion=(
                        "Decompose this module into smaller functional sub-modules. "
                        "Large modules increase review time and defect density."
                    ),
                ))
        return findings


# ---------------------------------------------------------------------------
@register_rule
class VLG047(RuleBase):
    """
    A module with more than 20 ports is doing too many things — it's a
    "god-module." This hurts readability, makes the interface unwieldy for
    integrators, and makes formal verification harder.
    """
    rule_id     = "VLG047"
    category    = "Maintainability"
    severity    = Severity.INFO
    description = "Module has >20 ports — god-module, consider splitting functionality"

    THRESHOLD = 20

    def check(self, ctx: ParseContext) -> List[Finding]:
        findings: List[Finding] = []
        for mod in ctx.modules:
            sl, el = mod['start_line'], mod['end_line']
            # Count ports belonging to this module
            ports_in_mod = [
                p for p in ctx.port_decls
                if sl <= p['line'] <= el
            ]
            n = len(ports_in_mod)
            if n > self.THRESHOLD:
                findings.append(self._finding(
                    ctx, sl,
                    snippet=f"Module '{mod['name']}' has {n} ports (threshold: {self.THRESHOLD})",
                    suggestion=(
                        "Group related signals into sub-modules or use bus interfaces. "
                        "Large port lists increase integration errors."
                    ),
                ))
        return findings


# ---------------------------------------------------------------------------
@register_rule
class VLG048(RuleBase):
    """
    Deeply nested if/else/case blocks (>3 levels) are extremely hard to
    review, reason about coverage, and verify. They also tend to synthesize
    into deep MUX chains with long combinational delay.

    This is analogous to "cyclomatic complexity" in software.
    """
    rule_id     = "VLG048"
    category    = "Maintainability"
    severity    = Severity.WARNING
    description = "Control flow nested >3 levels deep — hard to review and verify"

    THRESHOLD = 3
    _NEST_UP   = re.compile(r'\b(if|case|casez|casex)\b')
    _NEST_DOWN = re.compile(r'\b(end|endcase)\b')

    def check(self, ctx: ParseContext) -> List[Finding]:
        findings: List[Finding] = []
        flagged_blocks: set = set()

        for blk in ctx.always_blocks:
            depth = 0
            max_depth = 0
            deepest_line = blk['start_line']
            for bln in blk['body_lines']:
                ups   = len(self._NEST_UP.findall(bln))
                downs = len(self._NEST_DOWN.findall(bln))
                depth += ups
                if depth > max_depth:
                    max_depth = depth
                    deepest_line = blk['start_line']  # report at block start
                depth -= downs
                if depth < 0:
                    depth = 0

            if max_depth > self.THRESHOLD:
                key = blk['start_line']
                if key not in flagged_blocks:
                    flagged_blocks.add(key)
                    findings.append(self._finding(
                        ctx, blk['start_line'],
                        snippet=f"Nesting depth {max_depth} (threshold: {self.THRESHOLD})",
                        suggestion=(
                            "Flatten deep nesting by extracting sub-blocks into separate "
                            "always blocks, using case statements, or splitting logic into "
                            "sub-modules."
                        ),
                    ))
        return findings


# ---------------------------------------------------------------------------
@register_rule
class VLG049(RuleBase):
    """
    A module with >10 always blocks usually has too much micro-level logic
    crammed together. It becomes hard to trace signal flow, find related
    assignments, and verify reset logic.
    """
    rule_id     = "VLG049"
    category    = "Maintainability"
    severity    = Severity.INFO
    description = "Module has >10 always blocks — consider decomposing into sub-modules"

    THRESHOLD = 10

    def check(self, ctx: ParseContext) -> List[Finding]:
        findings: List[Finding] = []
        for mod in ctx.modules:
            sl, el = mod['start_line'], mod['end_line']
            count = sum(
                1 for blk in ctx.always_blocks
                if sl <= blk['start_line'] <= el
            )
            if count > self.THRESHOLD:
                findings.append(self._finding(
                    ctx, sl,
                    snippet=f"Module '{mod['name']}' has {count} always blocks (threshold: {self.THRESHOLD})",
                    suggestion=(
                        "Group related always blocks into sub-modules. "
                        "Many blocks in one file make signal tracing difficult."
                    ),
                ))
        return findings


# ---------------------------------------------------------------------------
@register_rule
class VLG050(RuleBase):
    """
    When the same magic constant (e.g., 32'd1024) appears more than 3 times
    in one module, it should be extracted to a parameter or localparam. This
    reduces typo risk and makes width / range changes trivial.
    """
    rule_id     = "VLG050"
    category    = "Maintainability"
    severity    = Severity.INFO
    description = "Same magic constant appears >3 times — extract to parameter / localparam"

    THRESHOLD = 3
    # Match sized Verilog literals like 8'hFF, 32'd1024, 4'b1010 — ignore 1'b0/1'b1
    _LITERAL_RE = re.compile(r"\b(\d+'[hHdDbBoO][\da-fA-F_xXzZ]+)\b")

    # Literals that are too common / harmless to flag
    _IGNORE = {"1'b0", "1'b1", "1'h0", "1'h1", "1'd0", "1'd1"}

    def check(self, ctx: ParseContext) -> List[Finding]:
        findings: List[Finding] = []
        for mod in ctx.modules:
            sl, el = mod['start_line'], mod['end_line']
            counter: Counter = Counter()
            first_line: Dict[str, int] = {}

            for i in range(sl - 1, min(el, len(ctx.clean_lines))):
                for m in self._LITERAL_RE.finditer(ctx.clean_lines[i]):
                    lit = m.group(1)
                    if lit in self._IGNORE:
                        continue
                    counter[lit] += 1
                    if lit not in first_line:
                        first_line[lit] = i + 1

            for lit, cnt in counter.items():
                if cnt > self.THRESHOLD:
                    findings.append(self._finding(
                        ctx, first_line[lit],
                        snippet=f"Literal '{lit}' appears {cnt} times in module '{mod['name']}'",
                        suggestion=(
                            f"Replace '{lit}' with a named localparam. "
                            f"Repeated literals are error-prone when specifications change."
                        ),
                    ))
        return findings
