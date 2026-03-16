"""
rules/synthesis.py — Synthesis Safety rules
============================================
VLG006  initial block in synthesizable RTL
VLG007  #delay in synthesizable code
VLG008  casex / casez usage
VLG009  Incomplete sensitivity list (non always @(*))
VLG010  force / release statements
VLG011  $display / $monitor / $finish in RTL
VLG012  Tri-state output without explicit enable
"""

from __future__ import annotations
import re
from typing import List
from engine.rule_base import RuleBase, Severity, Finding, ParseContext, register_rule


# ---------------------------------------------------------------------------
@register_rule
class VLG006(RuleBase):
    """
    'initial' blocks are not synthesizable — they exist only for simulation.
    RTL reason: synthesis tools either ignore or error on 'initial' blocks,
    causing state mismatch between RTL sim and gate-level sim.
    """
    rule_id     = "VLG006"
    category    = "Synthesis"
    severity    = Severity.ERROR
    description = "'initial' block found — not synthesizable (simulation-only construct)"

    _INITIAL_RE = re.compile(r'\binitial\b')

    def check(self, ctx: ParseContext) -> List[Finding]:
        findings = []
        for i, ln in enumerate(ctx.clean_lines):
            if self._INITIAL_RE.search(ln):
                findings.append(self._finding(
                    ctx, i + 1,
                    suggestion="Remove 'initial' block from RTL. Use reset logic in a clocked always block instead."
                ))
        return findings


# ---------------------------------------------------------------------------
@register_rule
class VLG007(RuleBase):
    """
    '#N' delay statements are simulation-only timing annotations.
    RTL reason: synthesizers strip all delays — the synthesized netlist
    behaves differently from RTL simulation, masking real timing issues.
    """
    rule_id     = "VLG007"
    category    = "Synthesis"
    severity    = Severity.ERROR
    description = "Delay (#N) found in RTL — simulation-only, causes sim/synth mismatch"

    # Match #<number> timing delays — but NOT #( which is parameter syntax in module headers.
    # Also exclude module #( parameter override syntax: word #(
    _DELAY_RE = re.compile(r'(?<!\w)#\s*\d+')

    def check(self, ctx: ParseContext) -> List[Finding]:
        findings = []
        for i, ln in enumerate(ctx.clean_lines):
            if self._DELAY_RE.search(ln):
                findings.append(self._finding(
                    ctx, i + 1,
                    suggestion="Remove all '#delay' constructs from RTL code. Rely on clock edges for timing."
                ))
        return findings


# ---------------------------------------------------------------------------
@register_rule
class VLG008(RuleBase):
    """
    'casex' and 'casez' treat X (unknown) and Z (high-Z) as wildcards.
    RTL reason: this can mask real X-propagation bugs in simulation, and
    synthesis tools may interpret the wildcards differently than expected.
    Prefer 'case' with explicit 'default'.
    """
    rule_id     = "VLG008"
    category    = "Synthesis"
    severity    = Severity.WARNING
    description = "'casex'/'casez' used — X/Z wildcard matching can mask bugs"

    _CASEXZ_RE = re.compile(r'\bcasex\b|\bcasez\b')

    def check(self, ctx: ParseContext) -> List[Finding]:
        findings = []
        for i, ln in enumerate(ctx.clean_lines):
            if self._CASEXZ_RE.search(ln):
                findings.append(self._finding(
                    ctx, i + 1,
                    suggestion="Replace 'casex'/'casez' with 'case' and add explicit 'default' branch."
                ))
        return findings


# ---------------------------------------------------------------------------
@register_rule
class VLG009(RuleBase):
    """
    Explicit sensitivity lists that are incomplete cause the always block to
    not re-evaluate when unlisted signals change — simulation models a latch
    but synthesis infers combinational logic, creating a mismatch.
    RTL reason: always use always @(*) or always_comb for combinational logic.
    """
    rule_id     = "VLG009"
    category    = "Synthesis"
    severity    = Severity.ERROR
    description = "Explicit sensitivity list in combinational block — may be incomplete (use always @(*))"

    def check(self, ctx: ParseContext) -> List[Finding]:
        findings = []
        for blk in ctx.always_blocks:
            sen = blk['sensitivity'].strip()
            # If it's not @(*) or always_comb, and has no posedge/negedge → explicit list
            if (sen != '*'
                    and 'posedge' not in sen
                    and 'negedge' not in sen
                    and sen != ''):
                findings.append(self._finding(
                    ctx, blk['start_line'],
                    suggestion="Replace explicit sensitivity list with 'always @(*)' or SystemVerilog 'always_comb'."
                ))
        return findings


# ---------------------------------------------------------------------------
@register_rule
class VLG010(RuleBase):
    """
    'force' and 'release' are procedural force statements — simulation-only.
    RTL reason: synthesis tools do not support these; they override normal
    signal assignment hierarchically, but only in simulation.
    """
    rule_id     = "VLG010"
    category    = "Synthesis"
    severity    = Severity.WARNING
    description = "'force'/'release' statement found — simulation-only, not synthesizable"

    _FORCE_RE = re.compile(r'\b(force|release)\b\s+\w+')

    def check(self, ctx: ParseContext) -> List[Finding]:
        findings = []
        for i, ln in enumerate(ctx.clean_lines):
            if self._FORCE_RE.search(ln):
                findings.append(self._finding(
                    ctx, i + 1,
                    suggestion="Remove 'force'/'release' from RTL. Use proper enable/mux logic instead."
                ))
        return findings


# ---------------------------------------------------------------------------
@register_rule
class VLG011(RuleBase):
    """
    System tasks like $display, $monitor, $finish are simulation utilities.
    RTL reason: synthesis tools ignore them silently, so they provide no
    real observability in silicon — they only pollute RTL with dead code.
    """
    rule_id     = "VLG011"
    category    = "Synthesis"
    severity    = Severity.ERROR
    description = "System task ($display/$monitor/$finish) found in RTL — not synthesizable"

    _SYSTASK_RE = re.compile(
        r'\$(display|monitor|finish|write|strobe|dumpvars|dumpfile|time|realtime)\b'
    )

    def check(self, ctx: ParseContext) -> List[Finding]:
        findings = []
        for i, ln in enumerate(ctx.clean_lines):
            if self._SYSTASK_RE.search(ln):
                findings.append(self._finding(
                    ctx, i + 1,
                    suggestion="Move system tasks to a testbench file. Guard RTL with `ifdef SIMULATION if needed."
                ))
        return findings


# ---------------------------------------------------------------------------
@register_rule
class VLG012(RuleBase):
    """
    Driving a signal to 1'bz (high-impedance) requires an explicit tri-state
    buffer with enable. Unguarded 'z' assignment implies the driver is always
    floating, causing bus contention when multiple drivers exist.
    RTL reason: unintended Z states cause X-propagation in simulation and
    undefined behavior post-synthesis on non-bus architectures.
    """
    rule_id     = "VLG012"
    category    = "Synthesis"
    severity    = Severity.WARNING
    description = "High-impedance (1'bz) assigned without explicit tri-state enable"

    # Looks for assign ... = ...'bz without a ternary enable condition
    _Z_ASSIGN_RE   = re.compile(r"\bassign\b[^=]+=\s*\d*'b[zZ]")
    _TRISTATE_RE    = re.compile(r"\?\s*\d*'b[Zz]\s*:")   # ... ? val : 'bz or ? 'bz :

    def check(self, ctx: ParseContext) -> List[Finding]:
        findings = []
        for stmt in ctx.assign_stmts:
            rhs = stmt['rhs']
            # Flag if RHS has 'bz but NO ternary operator (no enable mux)
            if re.search(r"\d*'b[Zz]", rhs) and '?' not in stmt.get('full', ''):
                findings.append(self._finding(
                    ctx, stmt['line'],
                    suggestion="Use tri-state pattern: assign out = (oe) ? data : 'bz;"
                ))
        return findings
