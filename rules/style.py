"""
rules/style.py — Coding Style & Readability rules
===================================================
VLG001  Missing module header comment
VLG002  Magic number in port/signal width
VLG003  Non-standard signal naming (no prefix convention)
VLG004  Port direction not explicitly declared
VLG005  Line exceeds 120 characters
"""

from __future__ import annotations
import re
from typing import List
from engine.rule_base import RuleBase, Severity, Finding, ParseContext, register_rule


# ---------------------------------------------------------------------------
@register_rule
class VLG001(RuleBase):
    """
    Every module should be preceded by a documentation comment block.
    RTL reason: In large designs, undocumented modules become black boxes.
    """
    rule_id     = "VLG001"
    category    = "Style"
    severity    = Severity.INFO
    description = "Module has no preceding comment block (documentation missing)"

    def check(self, ctx: ParseContext) -> List[Finding]:
        findings = []
        for mod in ctx.modules:
            line_idx = mod['start_line'] - 1   # 0-based
            # Look back up to 10 lines for a comment
            has_comment = False
            for j in range(max(0, line_idx - 10), line_idx):
                if '//' in ctx.lines[j] or '/*' in ctx.lines[j]:
                    has_comment = True
                    break
            if not has_comment:
                findings.append(self._finding(
                    ctx, mod['start_line'],
                    suggestion=f"Add a block comment before 'module {mod['name']}' describing its purpose."
                ))
        return findings


# ---------------------------------------------------------------------------
@register_rule
class VLG002(RuleBase):
    """
    Port/signal widths should use parameters, not raw integers.
    e.g.  output [31:0] data  →  should be  output [DATA_WIDTH-1:0] data
    RTL reason: magic numbers make resizing error-prone and grep-unfriendly.
    """
    rule_id     = "VLG002"
    category    = "Style"
    severity    = Severity.WARNING
    description = "Magic number used in signal/port width — use a named parameter instead"

    # Matches [N:M] where N is a large integer (>=8 in MSB position).
    # Small widths like [2:0], [3:0], [7:0] in clean 8/16-bit contexts are common;
    # flag only when MSB >= 8 (i.e., the raw number is >= 8) — truly magic-looking widths.
    _MAGIC_WIDTH_RE = re.compile(r'\[\s*([89]|[1-9]\d+)\s*(?:[-+]\s*\d+\s*)?:\s*\d+\s*\]')

    def check(self, ctx: ParseContext) -> List[Finding]:
        findings = []
        for decl in ctx.port_decls + ctx.signal_decls:
            width = decl.get('width', '')
            if self._MAGIC_WIDTH_RE.search(width):
                findings.append(self._finding(
                    ctx, decl['line'],
                    suggestion="Replace literal width with a named parameter, e.g. `parameter DATA_WIDTH = 32`."
                ))
        return findings


# ---------------------------------------------------------------------------
@register_rule
class VLG003(RuleBase):
    """
    Signal naming convention: RTL signals should carry prefix type hints.
    Common conventions: i_ (input), o_ (output), r_ (register), w_ (wire).
    RTL reason: prefix conventions make signal intent immediately readable.
    """
    rule_id     = "VLG003"
    category    = "Style"
    severity    = Severity.INFO
    description = "Signal name does not follow prefix convention (i_/o_/r_/w_)"

    _VALID_PREFIX_RE = re.compile(r'^(i_|o_|r_|w_|clk|rst|n_|p_|s_|c_)', re.IGNORECASE)
    _IGNORE_RE       = re.compile(r'^(clk|rst|reset|clock)', re.IGNORECASE)

    def check(self, ctx: ParseContext) -> List[Finding]:
        findings = []
        for decl in ctx.signal_decls:
            name = decl['name']
            if self._IGNORE_RE.match(name):
                continue
            if not self._VALID_PREFIX_RE.match(name):
                findings.append(self._finding(
                    ctx, decl['line'],
                    suggestion=f"Rename '{name}' to follow convention, e.g. r_{name} (reg) or w_{name} (wire)."
                ))
        return findings


# ---------------------------------------------------------------------------
@register_rule
class VLG004(RuleBase):
    """
    Every port in the module list must have an explicit direction keyword.
    Implicit directions (defaulting to input) cause silent bugs.
    RTL reason: ambiguous ports lead to sim vs synth discrepancies.
    """
    rule_id     = "VLG004"
    category    = "Style"
    severity    = Severity.WARNING
    description = "Port declared without explicit direction (input/output/inout)"

    # Matches module port list items that are just identifiers with no direction
    _MODULE_PORT_ONLY_RE = re.compile(
        r'\bmodule\s+\w+\s*(?:#[^)]*\))?\s*\(([^)]*)\)', re.DOTALL)
    _DIRECTION_RE = re.compile(r'\b(input|output|inout)\b')

    def check(self, ctx: ParseContext) -> List[Finding]:
        findings = []
        # find module declarations and check if all ports in the list have directions
        for i, ln in enumerate(ctx.clean_lines):
            m = self._MODULE_PORT_ONLY_RE.search(ln)
            if m:
                port_block = m.group(1)
                # If ANY port token exists without a direction keyword, flag
                tokens = [t.strip() for t in port_block.split(',') if t.strip()]
                for tok in tokens:
                    tok_clean = tok.replace('\n', ' ')
                    if tok_clean and not self._DIRECTION_RE.search(tok_clean):
                        # It's a bare identifier — implicit direction
                        # Only flag if it looks like a simple identifier (no type keyword)
                        if re.match(r'^\w+$', tok_clean.split()[-1]):
                            findings.append(self._finding(
                                ctx, i + 1,
                                suggestion="Add explicit 'input'/'output' direction to each port in the module header."
                            ))
                            break   # one finding per module line is enough
        return findings


# ---------------------------------------------------------------------------
@register_rule
class VLG005(RuleBase):
    """
    Lines longer than 120 characters hurt readability and diff tooling.
    RTL reason: wide lines in schematics-driven teams cause review friction.
    """
    rule_id     = "VLG005"
    category    = "Style"
    severity    = Severity.INFO
    description = "Line exceeds 120 characters"
    _LIMIT = 120

    def check(self, ctx: ParseContext) -> List[Finding]:
        findings = []
        for i, ln in enumerate(ctx.lines):
            if len(ln.rstrip('\n')) > self._LIMIT:
                findings.append(self._finding(
                    ctx, i + 1,
                    snippet=f"[{len(ln.rstrip())} chars] " + ln.strip()[:80] + "...",
                    suggestion="Break long lines at logical operators or port lists."
                ))
        return findings
