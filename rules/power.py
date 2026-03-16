"""
rules/power.py — Power Awareness rules
========================================
VLG061  No clock gating detected — always-on clock wastes dynamic power
VLG062  Wide bus toggling without enable — unnecessary switching activity
VLG063  No power-down / sleep signal — missing low-power mode
VLG064  Memory array without chip-enable — always-active RAM wastes power
VLG065  Redundant toggling — signal assigned same value in both if/else branches

None of these appear in Vivado / Quartus warnings. They catch power-hungry
RTL patterns that only show up in gate-level power analysis or silicon.
"""

from __future__ import annotations
import re
from typing import List
from engine.rule_base import RuleBase, Severity, Finding, ParseContext, register_rule


# ---------------------------------------------------------------------------
@register_rule
class VLG061(RuleBase):
    """
    Modules with clocked always blocks but no clock-gating signal
    (clk_en, clk_gate, gclk, icg, etc.) leave the clock tree always active,
    burning dynamic power even when the logic is idle.
    """
    rule_id     = "VLG061"
    category    = "Power"
    severity    = Severity.WARNING
    description = "No clock gating detected — always-on clock wastes dynamic power"

    _CG_RE = re.compile(
        r'\b(?:clk_en|clock_en|clk_gate|clock_gate|gclk|icg|cg_en|clk_enable)\b', re.I
    )

    def check(self, ctx: ParseContext) -> List[Finding]:
        findings: List[Finding] = []
        for mod in ctx.modules:
            sl, el = mod['start_line'], mod['end_line']
            has_clocked = any(
                blk['block_type'] in ('clocked_posedge', 'clocked_negedge')
                and sl <= blk['start_line'] <= el
                for blk in ctx.always_blocks
            )
            if not has_clocked:
                continue
            mod_text = '\n'.join(ctx.clean_lines[sl - 1 : el])
            if not self._CG_RE.search(mod_text):
                findings.append(self._finding(
                    ctx, sl,
                    snippet=f"Module '{mod['name']}' has FFs but no clock-gating signal",
                    suggestion=(
                        "Add a clock-enable (clk_en) or use an ICG cell to gate the clock "
                        "when the module is idle. This can reduce dynamic power by 30-60%."
                    ),
                ))
        return findings


# ---------------------------------------------------------------------------
@register_rule
class VLG062(RuleBase):
    """
    A wide bus (>=8 bits) driven inside a clocked block without any enable
    guard toggles every cycle, causing unnecessary switching activity.
    Wrapping updates in `if (enable)` dramatically reduces power.
    """
    rule_id     = "VLG062"
    category    = "Power"
    severity    = Severity.INFO
    description = "Wide bus (>=8b) updated every cycle without enable — high switching power"

    _NB_ASSIGN = re.compile(r'(\w+)\s*<=')

    @staticmethod
    def _sig_width(name: str, ctx: ParseContext) -> int:
        for p in ctx.port_decls:
            if p['name'] == name:
                m = re.match(r'\[\s*(\d+)\s*:\s*(\d+)\s*\]', p['width'])
                return abs(int(m.group(1)) - int(m.group(2))) + 1 if m else 1
        for s in ctx.signal_decls:
            if s['name'] == name:
                m = re.match(r'\[\s*(\d+)\s*:\s*(\d+)\s*\]', s['width'])
                return abs(int(m.group(1)) - int(m.group(2))) + 1 if m else 1
        return -1

    def check(self, ctx: ParseContext) -> List[Finding]:
        findings: List[Finding] = []
        _IF_RE = re.compile(r'\bif\b')
        for blk in ctx.always_blocks:
            if blk['block_type'] not in ('clocked_posedge', 'clocked_negedge'):
                continue
            body = '\n'.join(blk['body_lines'])
            # Check if assignments are NOT guarded by any if/enable
            # Simple heuristic: if body has no 'if' at all, every signal toggles always
            if _IF_RE.search(body):
                continue
            for bln in blk['body_lines']:
                for m in self._NB_ASSIGN.finditer(bln):
                    sig = m.group(1)
                    w = self._sig_width(sig, ctx)
                    if w >= 8:
                        findings.append(self._finding(
                            ctx, blk['start_line'],
                            snippet=f"'{sig}' ({w}b) updated every cycle without enable guard",
                            suggestion=(
                                f"Wrap updates to '{sig}' in 'if (enable)' to avoid toggling "
                                f"when data is not changing. Saves ~{w * 0.1:.0f}% dynamic power."
                            ),
                        ))
        return findings


# ---------------------------------------------------------------------------
@register_rule
class VLG063(RuleBase):
    """
    Modules without any power-down / sleep / idle signal have no way to
    enter a low-power state. This means the logic is always active even
    when upstream data is absent.
    """
    rule_id     = "VLG063"
    category    = "Power"
    severity    = Severity.INFO
    description = "No power-down / sleep signal — no low-power idle mode"

    _LP_RE = re.compile(
        r'\b(?:sleep|power_down|pwr_down|idle_mode|standby|low_power|powerdn|pwrdn)\b', re.I
    )

    def check(self, ctx: ParseContext) -> List[Finding]:
        findings: List[Finding] = []
        for mod in ctx.modules:
            sl, el = mod['start_line'], mod['end_line']
            has_clocked = any(
                blk['block_type'] in ('clocked_posedge', 'clocked_negedge')
                and sl <= blk['start_line'] <= el
                for blk in ctx.always_blocks
            )
            if not has_clocked:
                continue
            mod_text = '\n'.join(ctx.clean_lines[sl - 1 : el])
            if not self._LP_RE.search(mod_text):
                findings.append(self._finding(
                    ctx, sl,
                    snippet=f"Module '{mod['name']}' has no sleep / power-down signal",
                    suggestion=(
                        "Add a sleep or power-down input. When asserted, gate clocks and "
                        "hold outputs to reduce both dynamic and leakage power."
                    ),
                ))
        return findings


# ---------------------------------------------------------------------------
@register_rule
class VLG064(RuleBase):
    """
    A memory array (reg [N:0] mem [0:M]) without a chip-enable / read-enable
    signal is always active, consuming power even when not accessed.
    """
    rule_id     = "VLG064"
    category    = "Power"
    severity    = Severity.WARNING
    description = "Memory array without chip-enable — always-active RAM wastes power"

    _MEM_RE = re.compile(r'\breg\s+\[.*?\]\s+(\w+)\s*\[')
    _CE_RE  = re.compile(r'\b(?:ce|chip_en|mem_en|ram_en|ren|wen|rd_en|wr_en)\b', re.I)

    def check(self, ctx: ParseContext) -> List[Finding]:
        findings: List[Finding] = []
        for mod in ctx.modules:
            sl, el = mod['start_line'], mod['end_line']
            mod_lines = ctx.clean_lines[sl - 1 : el]
            mod_text = '\n'.join(mod_lines)
            for i, ln in enumerate(mod_lines):
                m = self._MEM_RE.search(ln)
                if m:
                    mem_name = m.group(1)
                    if not self._CE_RE.search(mod_text):
                        findings.append(self._finding(
                            ctx, sl + i,
                            snippet=f"Memory '{mem_name}' has no chip-enable / read-write enable",
                            suggestion=(
                                f"Add 'wen'/'ren' enables and gate memory access with them. "
                                f"An always-active memory wastes significant dynamic power."
                            ),
                        ))
                    break  # one finding per module
        return findings


# ---------------------------------------------------------------------------
@register_rule
class VLG065(RuleBase):
    """
    A signal assigned the same value in both the if-branch and else-branch
    of a conditional creates redundant switching activity — the signal
    toggles to the same value regardless, wasting power on the clock edge.
    """
    rule_id     = "VLG065"
    category    = "Power"
    severity    = Severity.INFO
    description = "Redundant toggling — same assignment in both if/else branches"

    _NB_LHS = re.compile(r'(\w+)\s*<=\s*(.+?)\s*;')
    _B_LHS  = re.compile(r'(\w+)\s*=\s*(.+?)\s*;')

    def check(self, ctx: ParseContext) -> List[Finding]:
        findings: List[Finding] = []
        for blk in ctx.always_blocks:
            body = '\n'.join(blk['body_lines'])
            # Simple pattern: find if/else pairs where same signal gets same value
            sections = re.split(r'\belse\b', body)
            if len(sections) < 2:
                continue
            assign_re = self._NB_LHS if '<=' in body else self._B_LHS
            if_assigns = {}
            for m in assign_re.finditer(sections[0]):
                if_assigns[m.group(1)] = m.group(2).strip()
            for section in sections[1:]:
                for m in assign_re.finditer(section):
                    sig, val = m.group(1), m.group(2).strip()
                    if sig in if_assigns and if_assigns[sig] == val:
                        findings.append(self._finding(
                            ctx, blk['start_line'],
                            snippet=f"'{sig} <= {val}' appears in both if and else — redundant toggle",
                            suggestion=(
                                f"Move '{sig} <= {val}' outside the if/else since it's the same "
                                f"in both branches. Avoids unnecessary mux and switching."
                            ),
                        ))
        return findings
