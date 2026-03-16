"""
rules/reset_integrity.py — Reset Integrity rules
==================================================
VLG066  Inconsistent reset polarity — mixed active-high / active-low in module
VLG067  Incomplete reset — not all FFs initialized in reset branch
VLG068  Async reset without synchronizer — metastability on de-assertion
VLG069  Reset signal used as data — reset leaking into datapath
VLG070  Missing reset in sequential block — FF has no reset path at all

These rules target reset-tree integrity issues that are invisible to
synthesis tools but cause silicon failures and non-deterministic behavior.
"""

from __future__ import annotations
import re
from typing import List, Set, Dict
from engine.rule_base import RuleBase, Severity, Finding, ParseContext, register_rule


# Shared helpers
_RST_ACTIVE_HIGH = re.compile(r'\bif\s*\(\s*(?!!)(\w*rst\w*|\w*reset\w*)\s*\)', re.I)
_RST_ACTIVE_LOW  = re.compile(r'\bif\s*\(\s*!(\w*rst\w*|\w*reset\w*)\s*\)', re.I)
_RST_NAME        = re.compile(r'\b\w*(rst|reset)\w*\b', re.I)
_NB_LHS          = re.compile(r'(\w+)\s*<=')


# ---------------------------------------------------------------------------
@register_rule
class VLG066(RuleBase):
    """
    Using both active-high and active-low resets in the same module is a
    design smell — it makes reset tree synthesis unpredictable, complicates
    constraint files, and is a frequent source of reset-domain crossing bugs.
    """
    rule_id     = "VLG066"
    category    = "Reset Integrity"
    severity    = Severity.WARNING
    description = "Inconsistent reset polarity — mixed active-high and active-low in module"

    def check(self, ctx: ParseContext) -> List[Finding]:
        findings: List[Finding] = []
        for mod in ctx.modules:
            sl, el = mod['start_line'], mod['end_line']
            has_high = False
            has_low  = False
            first_line = sl
            for blk in ctx.always_blocks:
                if not (sl <= blk['start_line'] <= el):
                    continue
                body = '\n'.join(blk['body_lines'])
                if _RST_ACTIVE_HIGH.search(body):
                    has_high = True
                    if not has_low:
                        first_line = blk['start_line']
                if _RST_ACTIVE_LOW.search(body):
                    has_low = True
            if has_high and has_low:
                findings.append(self._finding(
                    ctx, first_line,
                    snippet=f"Module '{mod['name']}' uses both active-high and active-low resets",
                    suggestion=(
                        "Standardize on one reset polarity throughout the module. "
                        "Most flows use active-low (rst_n). Convert all resets to match."
                    ),
                ))
        return findings


# ---------------------------------------------------------------------------
@register_rule
class VLG067(RuleBase):
    """
    In a clocked block's reset branch, if some FFs are initialized but
    others are not, the un-reset FFs power up in unknown state ('X'),
    which can propagate and corrupt the design.
    """
    rule_id     = "VLG067"
    category    = "Reset Integrity"
    severity    = Severity.ERROR
    description = "Incomplete reset — not all FFs initialized in reset branch"

    def check(self, ctx: ParseContext) -> List[Finding]:
        findings: List[Finding] = []
        for blk in ctx.always_blocks:
            if blk['block_type'] not in ('clocked_posedge', 'clocked_negedge'):
                continue
            body = '\n'.join(blk['body_lines'])
            # Find reset branch
            rst_match = re.search(r'\bif\s*\(\s*!?\s*\w*(rst|reset)\w*\s*\)', body, re.I)
            if not rst_match:
                continue
            # Split at else to get reset branch vs normal branch
            parts = re.split(r'\belse\b', body, maxsplit=1)
            if len(parts) < 2:
                continue
            rst_branch = parts[0]
            norm_branch = parts[1]
            # Collect LHS in normal branch (all FFs in this block)
            all_ffs: Set[str] = set()
            for m in _NB_LHS.finditer(norm_branch):
                all_ffs.add(m.group(1))
            # Collect LHS in reset branch (initialized FFs)
            reset_ffs: Set[str] = set()
            for m in _NB_LHS.finditer(rst_branch):
                reset_ffs.add(m.group(1))
            missing = all_ffs - reset_ffs
            if missing and reset_ffs:  # only flag if SOME are reset (partial reset)
                for sig in sorted(missing):
                    findings.append(self._finding(
                        ctx, blk['start_line'],
                        snippet=f"FF '{sig}' not initialized in reset branch",
                        suggestion=(
                            f"Add '{sig} <= <reset_value>;' to the reset branch. "
                            f"Uninitialized FFs power up as 'X' and may corrupt downstream logic."
                        ),
                    ))
        return findings


# ---------------------------------------------------------------------------
@register_rule
class VLG068(RuleBase):
    """
    An asynchronous reset in the sensitivity list (posedge rst / negedge rst_n)
    without a corresponding reset synchronizer in the module creates a
    metastability window on de-assertion. The reset release must be
    synchronized to the clock domain.
    """
    rule_id     = "VLG068"
    category    = "Reset Integrity"
    severity    = Severity.WARNING
    description = "Async reset without synchronizer — metastability on reset de-assertion"

    _ASYNC_RST = re.compile(
        r'\b(?:posedge|negedge)\s+(\w*(?:rst|reset)\w*)', re.I
    )
    _SYNC_RE = re.compile(
        r'\b(?:rst_sync|reset_sync|sync_rst|rst_ff|reset_ff|rst_d\d|rst_meta)\b', re.I
    )

    def check(self, ctx: ParseContext) -> List[Finding]:
        findings: List[Finding] = []
        for mod in ctx.modules:
            sl, el = mod['start_line'], mod['end_line']
            mod_text = '\n'.join(ctx.clean_lines[sl - 1 : el])
            has_async_rst = False
            async_line = sl
            for blk in ctx.always_blocks:
                if not (sl <= blk['start_line'] <= el):
                    continue
                if self._ASYNC_RST.search(blk['sensitivity']):
                    has_async_rst = True
                    async_line = blk['start_line']
                    break
            if has_async_rst and not self._SYNC_RE.search(mod_text):
                findings.append(self._finding(
                    ctx, async_line,
                    snippet=f"Module '{mod['name']}' has async reset but no reset synchronizer",
                    suggestion=(
                        "Add a 2-FF reset synchronizer (async assert, sync de-assert). "
                        "Without synchronization, reset release can cause metastability."
                    ),
                ))
        return findings


# ---------------------------------------------------------------------------
@register_rule
class VLG069(RuleBase):
    """
    A reset signal used in datapath logic (outside of the reset-guard
    if-branch) pollutes the data path with reset timing, creating a
    false path that constraining tools often miss.
    """
    rule_id     = "VLG069"
    category    = "Reset Integrity"
    severity    = Severity.WARNING
    description = "Reset signal used as data — reset leaking into datapath logic"

    _RST_AS_DATA = re.compile(
        r'(?:<=|=)\s*[^;]*\b(\w*(?:rst|reset)\w*)\b', re.I
    )
    _RST_GUARD   = re.compile(r'\bif\s*\(\s*!?\s*\w*(?:rst|reset)\w*\s*\)', re.I)

    def check(self, ctx: ParseContext) -> List[Finding]:
        findings: List[Finding] = []
        for blk in ctx.always_blocks:
            if blk['block_type'] not in ('clocked_posedge', 'clocked_negedge'):
                continue
            # Find the normal (non-reset) section of the block
            body = '\n'.join(blk['body_lines'])
            parts = re.split(r'\belse\b', body, maxsplit=1)
            if len(parts) < 2:
                normal = body
            else:
                normal = parts[1]
            # Check if reset signal appears on RHS in normal logic
            for m in self._RST_AS_DATA.finditer(normal):
                rst_sig = m.group(1)
                if _RST_NAME.match(rst_sig):
                    findings.append(self._finding(
                        ctx, blk['start_line'],
                        snippet=f"Reset signal '{rst_sig}' used in datapath logic (RHS of assignment)",
                        suggestion=(
                            f"Do not use '{rst_sig}' as data. If you need a 'reset happened' "
                            f"flag, create a separate registered signal set during reset."
                        ),
                    ))
                    break  # one per block
        return findings


# ---------------------------------------------------------------------------
@register_rule
class VLG070(RuleBase):
    """
    A clocked always block with no reset branch at all means the FFs
    start in an unknown state after power-on. This is acceptable for
    data pipelines but dangerous for control logic.
    """
    rule_id     = "VLG070"
    category    = "Reset Integrity"
    severity    = Severity.WARNING
    description = "Sequential block has no reset — FFs start in unknown state"

    _CTRL_RE = re.compile(
        r'\b(?:state|fsm|ctrl|control|valid|ready|enable|en|cnt|count|flag|busy|done|start|stop)\b', re.I
    )

    def check(self, ctx: ParseContext) -> List[Finding]:
        findings: List[Finding] = []
        for blk in ctx.always_blocks:
            if blk['block_type'] not in ('clocked_posedge', 'clocked_negedge'):
                continue
            body = '\n'.join(blk['body_lines'])
            # Check if there's any reset reference
            if _RST_NAME.search(blk['sensitivity']) or _RST_NAME.search(body):
                continue
            # Only flag if the block contains control-like signals
            lhs_signals = set()
            for m in _NB_LHS.finditer(body):
                lhs_signals.add(m.group(1))
            has_ctrl = any(self._CTRL_RE.search(s) for s in lhs_signals)
            if has_ctrl:
                ctrl_sigs = [s for s in sorted(lhs_signals) if self._CTRL_RE.search(s)]
                findings.append(self._finding(
                    ctx, blk['start_line'],
                    snippet=f"Control signal(s) {ctrl_sigs[:3]} have no reset initialization",
                    suggestion=(
                        "Add a reset branch to initialize control signals. "
                        "Un-reset control FFs power up as 'X' and cause unpredictable behavior."
                    ),
                ))
        return findings
