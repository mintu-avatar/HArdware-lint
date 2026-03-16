"""
rules/reusability.py — Reusability rules
==========================================
VLG071  Hardcoded bus widths — no parameters, not portable
VLG072  Module depends on `define — global coupling reduces reusability
VLG073  Non-parameterized instance — hardcoded config limits flexibility
VLG074  Inconsistent port naming convention — mixed styles hurt integration
VLG075  Generate block without label — unnamed hierarchy, hard to navigate

These rules enforce design-for-reuse practices that are never checked by
synthesis or simulation tools but directly impact IP portability.
"""

from __future__ import annotations
import re
from typing import List
from engine.rule_base import RuleBase, Severity, Finding, ParseContext, register_rule


# ---------------------------------------------------------------------------
@register_rule
class VLG071(RuleBase):
    """
    Hardcoded numeric widths in port declarations (e.g. [31:0]) without
    corresponding parameters make the module non-portable. Any width
    reused more than once should be a parameter.
    """
    rule_id     = "VLG071"
    category    = "Reusability"
    severity    = Severity.INFO
    description = "Hardcoded bus width without parameter — not reusable / configurable"

    _WIDTH_LITERAL = re.compile(r'\[\s*(\d+)\s*:\s*0\s*\]')
    THRESHOLD = 7  # flag widths > 7 bits (i.e. [7:0] is okay, [15:0] is not)

    def check(self, ctx: ParseContext) -> List[Finding]:
        findings: List[Finding] = []
        param_names = {p['name'] for p in ctx.parameters}
        for p in ctx.port_decls:
            m = self._WIDTH_LITERAL.search(p['width'])
            if m:
                msb = int(m.group(1))
                if msb > self.THRESHOLD:
                    # Check if module has ANY width parameter
                    if not param_names:
                        findings.append(self._finding(
                            ctx, p['line'],
                            snippet=f"Port '{p['name']}' [{msb}:0] — hardcoded width with no parameters",
                            suggestion=(
                                f"Replace [{msb}:0] with [WIDTH-1:0] and add "
                                f"'parameter WIDTH = {msb + 1}' for reusability."
                            ),
                        ))
        return findings


# ---------------------------------------------------------------------------
@register_rule
class VLG072(RuleBase):
    """
    Using `define (compiler directives) inside a module couples it to a
    global namespace. Any consumer must include the same header, making
    the module fragile and hard to reuse across projects.
    """
    rule_id     = "VLG072"
    category    = "Reusability"
    severity    = Severity.WARNING
    description = "Module depends on `define — global coupling reduces reusability"

    _TICK_USE = re.compile(r'`(?!(?:ifdef|ifndef|else|endif|timescale|include|define|undef)\b)(\w+)')

    def check(self, ctx: ParseContext) -> List[Finding]:
        findings: List[Finding] = []
        seen = set()
        for mod in ctx.modules:
            sl, el = mod['start_line'], mod['end_line']
            for i in range(sl - 1, min(el, len(ctx.lines))):
                for m in self._TICK_USE.finditer(ctx.lines[i]):
                    macro = m.group(1)
                    if macro not in seen:
                        seen.add(macro)
                        findings.append(self._finding(
                            ctx, i + 1,
                            snippet=f"Uses `{macro} — module depends on global `define",
                            suggestion=(
                                f"Replace `{macro} with a localparam or module parameter. "
                                f"Global defines create hidden dependencies across files."
                            ),
                        ))
        return findings


# ---------------------------------------------------------------------------
@register_rule
class VLG073(RuleBase):
    """
    Instantiating a module without using its parameter override (#(...))
    makes the design rigid. If the sub-module has parameters, the parent
    should explicitly set them for clarity and configurability.
    """
    rule_id     = "VLG073"
    category    = "Reusability"
    severity    = Severity.INFO
    description = "Module instance without parameter override — hardcoded config"

    _INST_WITH_PARAM = re.compile(r'\w+\s+#\s*\(')

    def check(self, ctx: ParseContext) -> List[Finding]:
        findings: List[Finding] = []
        for inst in ctx.instances:
            line_text = ctx.clean_lines[inst['line'] - 1] if inst['line'] <= len(ctx.clean_lines) else ''
            if not self._INST_WITH_PARAM.search(line_text):
                findings.append(self._finding(
                    ctx, inst['line'],
                    snippet=f"Instance '{inst['inst_name']}' of '{inst['module_type']}' has no #(...) parameter override",
                    suggestion=(
                        f"Use '{inst['module_type']} #(.PARAM(VALUE)) {inst['inst_name']} (...)' "
                        f"to explicitly configure the instance, even if defaults are acceptable."
                    ),
                ))
        return findings


# ---------------------------------------------------------------------------
@register_rule
class VLG074(RuleBase):
    """
    Mixing port naming conventions (e.g. some ports use i_/o_ prefix while
    others use _in/_out suffix, or no convention at all) makes integration
    confusing and error-prone. Pick one style consistently.
    """
    rule_id     = "VLG074"
    category    = "Reusability"
    severity    = Severity.INFO
    description = "Inconsistent port naming — mixed prefix/suffix conventions"

    _PREFIX_RE = re.compile(r'^(i_|o_|io_)')
    _SUFFIX_RE = re.compile(r'(_in|_out|_io)$')

    def check(self, ctx: ParseContext) -> List[Finding]:
        findings: List[Finding] = []
        for mod in ctx.modules:
            sl, el = mod['start_line'], mod['end_line']
            mod_ports = [p for p in ctx.port_decls if sl <= p['line'] <= el]
            if len(mod_ports) < 4:
                continue
            has_prefix = sum(1 for p in mod_ports if self._PREFIX_RE.match(p['name']))
            has_suffix = sum(1 for p in mod_ports if self._SUFFIX_RE.search(p['name']))
            has_none   = len(mod_ports) - has_prefix - has_suffix
            styles = sum(1 for c in [has_prefix, has_suffix, has_none] if c > 0)
            if styles >= 2 and has_prefix > 0 and has_none > 0:
                findings.append(self._finding(
                    ctx, sl,
                    snippet=f"Module '{mod['name']}' mixes {has_prefix} prefixed, {has_suffix} suffixed, {has_none} plain port names",
                    suggestion=(
                        "Adopt a consistent naming convention for all ports. "
                        "Common choices: i_/o_ prefix, or _in/_out suffix."
                    ),
                ))
        return findings


# ---------------------------------------------------------------------------
@register_rule
class VLG075(RuleBase):
    """
    Generate blocks without explicit labels produce anonymous hierarchy
    levels (genblk1, genblk2...) that make waveform debugging, constraint
    application, and synthesis reports hard to interpret.
    """
    rule_id     = "VLG075"
    category    = "Reusability"
    severity    = Severity.WARNING
    description = "Generate block without label — anonymous hierarchy, hard to debug"

    _GEN_FOR = re.compile(r'\bfor\b.*\bbegin\b')
    _GEN_IF  = re.compile(r'\bif\b.*\bbegin\b')
    _LABEL   = re.compile(r'\bbegin\s*:\s*\w+')
    _GENERATE = re.compile(r'\bgenerate\b')

    def check(self, ctx: ParseContext) -> List[Finding]:
        findings: List[Finding] = []
        in_generate = False
        for i, ln in enumerate(ctx.clean_lines):
            if self._GENERATE.search(ln):
                in_generate = True
            if re.search(r'\bendgenerate\b', ln):
                in_generate = False
            if in_generate and 'begin' in ln:
                if (self._GEN_FOR.search(ln) or self._GEN_IF.search(ln)):
                    if not self._LABEL.search(ln):
                        findings.append(self._finding(
                            ctx, i + 1,
                            snippet="Generate block 'begin' without label",
                            suggestion=(
                                "Add a label: 'begin : gen_my_block'. "
                                "Unnamed generate blocks get auto-names (genblk1) "
                                "that are tool-dependent and hard to constrain."
                            ),
                        ))
        return findings
