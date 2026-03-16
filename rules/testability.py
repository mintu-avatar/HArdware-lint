"""
rules/testability.py — Testability & Observability rules
=========================================================
VLG038  No scan enable port in sequential module
VLG039  $random / $urandom in RTL
VLG040  Large fan-out signal (>16 apparent loads)
"""

from __future__ import annotations
import re
from typing import List
from engine.rule_base import RuleBase, Severity, Finding, ParseContext, register_rule


# ---------------------------------------------------------------------------
@register_rule
class VLG038(RuleBase):
    """
    Sequential modules (those containing flip-flops) should have scan-enable
    (test_en / scan_en) ports for DFT (Design For Testability).
    RTL reason: ATPG (Automatic Test Pattern Generation) requires scan chains
    to achieve >95% stuck-at fault coverage. Modules without DFT hooks are
    untestable black boxes post-silicon.
    """
    rule_id     = "VLG038"
    category    = "Testability"
    severity    = Severity.WARNING
    description = "Sequential module lacks scan-enable port (DFT gap — ATPG coverage risk)"

    # Match scan enable ports with any common prefix (i_, o_, w_, etc.)
    _SCAN_EN_RE = re.compile(r'(?:^|\W)(i_|o_|w_|r_)?(scan_en|test_en|scan_enable|test_mode)\b', re.IGNORECASE)

    def check(self, ctx: ParseContext) -> List[Finding]:
        findings = []
        # Only flag modules that have clocked always blocks (actual FFs)
        has_ffs = any(
            blk['block_type'] in ('clocked_posedge', 'clocked_negedge')
            for blk in ctx.always_blocks
        )
        if not has_ffs:
            return findings

        # Check if any port is a scan enable
        port_text = ' '.join(p['name'] for p in ctx.port_decls)
        if not self._SCAN_EN_RE.search(port_text):
            for mod in ctx.modules:
                findings.append(self._finding(
                    ctx, mod['start_line'],
                    snippet=f"Module '{mod['name']}' has FFs but no scan_en/test_en port",
                    suggestion=(
                        "Add 'input scan_en' port and use it to mux FF data input with scan chain data. "
                        "Consult your DFT methodology guide for scan insertion flow."
                    )
                ))
        return findings


# ---------------------------------------------------------------------------
@register_rule
class VLG039(RuleBase):
    """
    $random and $urandom are simulation-only random number generators.
    RTL reason: synthesis tools cannot synthesize randomness — the synthesized
    design will have no equivalent hardware, making the RTL non-representative.
    These functions belong only in testbenches.
    """
    rule_id     = "VLG039"
    category    = "Testability"
    severity    = Severity.INFO
    description = "$random/$urandom used in RTL — non-synthesizable, testbench-only construct"

    _RANDOM_RE = re.compile(r'\$(u?random|random_range)\b')

    def check(self, ctx: ParseContext) -> List[Finding]:
        findings = []
        for i, ln in enumerate(ctx.clean_lines):
            if self._RANDOM_RE.search(ln):
                findings.append(self._finding(
                    ctx, i + 1,
                    suggestion="Move $random/$urandom to testbench only. Use LFSR or PRNG hardware if randomness needed in RTL."
                ))
        return findings


# ---------------------------------------------------------------------------
@register_rule
class VLG040(RuleBase):
    """
    A signal driving more than 16 module output ports or appearing on the RHS
    of many assignments has high fan-out. High fan-out signals require buffer
    trees in physical implementation, and unplanned fan-out causes timing closure
    issues.
    RTL reason: flag such signals so the designer can add explicit buffering
    commentary or split the load manually before synthesis.
    """
    rule_id     = "VLG040"
    category    = "Testability"
    severity    = Severity.WARNING
    description = "High fan-out signal (appears >16 times on RHS) — may need buffer tree in synthesis"

    FANOUT_THRESHOLD = 16

    def check(self, ctx: ParseContext) -> List[Finding]:
        findings = []
        from collections import Counter
        rhs_usage: Counter = Counter()

        # Count signal usages on RHS of assign
        for stmt in ctx.assign_stmts:
            tokens = re.findall(r'\b([a-zA-Z_]\w*)\b', stmt['rhs'])
            for tok in tokens:
                rhs_usage[tok] += 1

        # Count usages in always block RHS
        for blk in ctx.always_blocks:
            for ln in blk['body_lines']:
                # Extract RHS of assignments
                m = re.search(r'(?:<=|(?<![<>!=])=(?![=]))\s*(.+);', ln)
                if m:
                    tokens = re.findall(r'\b([a-zA-Z_]\w*)\b', m.group(1))
                    for tok in tokens:
                        rhs_usage[tok] += 1

        # Find all declared signal/port names to filter out constants/keywords
        _KEYWORDS = {'begin','end','if','else','case','endcase','default',
                     'posedge','negedge','assign','wire','reg','logic','input',
                     'output','inout','module','endmodule','always','initial'}
        decl_names = {d['name'] for d in ctx.signal_decls + ctx.port_decls}

        for sig, count in rhs_usage.items():
            if count > self.FANOUT_THRESHOLD and (sig in decl_names) and sig not in _KEYWORDS:
                # Find declaration line
                decl_line = next(
                    (d['line'] for d in ctx.signal_decls + ctx.port_decls if d['name'] == sig),
                    1
                )
                findings.append(Finding(
                    rule_id=self.rule_id,
                    severity=self.severity,
                    category=self.category,
                    description=self.description,
                    file=ctx.filepath,
                    line=decl_line,
                    snippet=f"Signal '{sig}' used {count} times on RHS (fan-out={count})",
                    suggestion=(
                        f"Consider adding 'synthesis keep' attribute or manually buffering '{sig}' "
                        "to help the synthesis tool build an optimal buffer tree."
                    )
                ))
        return findings
