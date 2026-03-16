"""
rules/reset.py — Reset Strategy rules
======================================
VLG023  Mixed sync/async reset in same module
VLG024  Reset not in sensitivity list for async reset usage
VLG025  Active-high and active-low resets mixed
VLG026  No reset in clocked always block
"""

from __future__ import annotations
import re
from typing import List
from engine.rule_base import RuleBase, Severity, Finding, ParseContext, register_rule


def _body_text(blk: dict) -> str:
    return '\n'.join(blk['body_lines'])


# ---------------------------------------------------------------------------
@register_rule
class VLG023(RuleBase):
    """
    Mixing synchronous and asynchronous resets within the same module creates
    reset convergence hazards. Different FFs will deassert reset at different
    times relative to the clock edge, causing glitches during reset release.
    RTL reason: pick one reset strategy per module (preferably async assert,
    sync deassert — the industry best practice).
    """
    rule_id     = "VLG023"
    category    = "Reset"
    severity    = Severity.WARNING
    description = "Mixed synchronous and asynchronous reset strategy detected in module"

    def check(self, ctx: ParseContext) -> List[Finding]:
        findings = []
        has_async_rst = False
        has_sync_rst  = False
        async_line    = 1
        sync_line     = 1

        for blk in ctx.always_blocks:
            sen = blk['sensitivity']
            body = _body_text(blk)
            # Async reset: 'posedge rst' or 'negedge rst_n' in sensitivity list
            if re.search(r'(?:posedge|negedge)\s+rst', sen, re.IGNORECASE):
                has_async_rst = True
                async_line = blk['start_line']
            # Sync reset: 'if (rst)' or 'if (!rst_n)' inside a clocked block with
            # NO reset in the sensitivity list
            elif blk['block_type'] in ('clocked_posedge', 'clocked_negedge'):
                if re.search(r'\bif\s*\(\s*!?rst', body, re.IGNORECASE):
                    has_sync_rst = True
                    sync_line = blk['start_line']

        if has_async_rst and has_sync_rst:
            findings.append(self._finding(
                ctx, min(async_line, sync_line),
                snippet=f"Async reset at line {async_line}, sync reset at line {sync_line}",
                suggestion=(
                    "Standardize on one reset strategy. Recommended: async assert, "
                    "synchronous deassert using a 2-FF reset synchronizer."
                )
            ))
        return findings


# ---------------------------------------------------------------------------
@register_rule
class VLG024(RuleBase):
    """
    If 'rst' is used inside a clocked block as an asynchronous check
    (i.e., you expect immediate response), but 'rst' is NOT in the sensitivity
    list, the simulator will not re-evaluate the block on reset assertion.
    RTL reason: for async reset, the sensitivity list MUST include
    'posedge rst' (active-high) or 'negedge rst_n' (active-low).
    """
    rule_id     = "VLG024"
    category    = "Reset"
    severity    = Severity.ERROR
    description = "Reset used as async but not present in always block sensitivity list"

    def check(self, ctx: ParseContext) -> List[Finding]:
        findings = []
        # First pass: discover if the module uses async reset in ANY block
        # (detecting intent — if async pattern used at all, flag missing ones)
        async_rst_blocks = []
        sync_rst_blocks  = []
        for blk in ctx.always_blocks:
            sen  = blk['sensitivity']
            body = _body_text(blk)
            is_clocked = blk['block_type'] in ('clocked_posedge', 'clocked_negedge')
            if not is_clocked:
                continue
            body_has_rst = bool(re.search(r'\bif\s*\(\s*!?\s*\w*(?:rst|reset)\w*', body, re.IGNORECASE))
            sen_has_rst  = bool(re.search(r'\w*(?:rst|reset)\w*', sen, re.IGNORECASE))
            if body_has_rst:
                if sen_has_rst:
                    async_rst_blocks.append(blk)
                else:
                    sync_rst_blocks.append(blk)

        # VLG024 fires only if async reset is used in some blocks but MISSING in others
        # (mixed intent — the sync blocks are suspicious)
        if async_rst_blocks and sync_rst_blocks:
            for blk in sync_rst_blocks:
                findings.append(self._finding(
                    ctx, blk['start_line'],
                    suggestion=(
                        "Other blocks in this module use async reset. "
                        "Add reset to this block's sensitivity list or convert to sync-reset style consistently."
                    )
                ))
        return findings


# ---------------------------------------------------------------------------
@register_rule
class VLG025(RuleBase):
    """
    Using both active-high (rst) and active-low (rst_n) resets in the same
    module creates polarity confusion and potential double-reset scenarios.
    RTL reason: mixed polarity resets require careful phase-alignment and
    create verification complexity. Standardize on one polarity per project.
    """
    rule_id     = "VLG025"
    category    = "Reset"
    severity    = Severity.WARNING
    description = "Active-high (rst) and active-low (rst_n) resets both used in same module"

    _RST_HIGH_RE = re.compile(r'\brst\b(?!_n)', re.IGNORECASE)
    _RST_LOW_RE  = re.compile(r'\brst_n\b', re.IGNORECASE)

    def check(self, ctx: ParseContext) -> List[Finding]:
        findings = []
        for mod in ctx.modules:
            start = mod['start_line'] - 1
            end   = mod['end_line']
            # Only scan lines within this module
            mod_lines = ctx.clean_lines[start:end]
            mod_text  = '\n'.join(mod_lines)
            has_high = bool(self._RST_HIGH_RE.search(mod_text))
            has_low  = bool(self._RST_LOW_RE.search(mod_text))
            if has_high and has_low:
                findings.append(self._finding(
                    ctx, mod['start_line'],
                    snippet=f"Module '{mod['name']}' uses both 'rst' and 'rst_n'",
                    suggestion="Choose one reset polarity for the entire module. Use rst_n (active-low) as the convention."
                ))
        return findings


# ---------------------------------------------------------------------------
@register_rule
class VLG026(RuleBase):
    """
    Flip-flops without any reset condition power up in an unknown state (X).
    In FPGA flows, most FFs initialize to 0 by default, but in ASIC flows
    the initial state is truly unknown without a reset.
    RTL reason: unreset registers can cause unpredictable startup behavior,
    particularly for control logic, FSM states, and valid bits.
    """
    rule_id     = "VLG026"
    category    = "Reset"
    severity    = Severity.INFO
    description = "Clocked always block has no reset condition — FF powers up in unknown state"

    def check(self, ctx: ParseContext) -> List[Finding]:
        findings = []
        for blk in ctx.always_blocks:
            if blk['block_type'] not in ('clocked_posedge', 'clocked_negedge'):
                continue
            body = _body_text(blk)
            # Match any if(...rst...) or if(!...rst...) pattern with flexible naming
            has_reset = bool(re.search(
                r'\bif\s*\(\s*!?\s*\w*(?:rst|reset)\w*', body, re.IGNORECASE))
            if not has_reset:
                findings.append(self._finding(
                    ctx, blk['start_line'],
                    suggestion=(
                        "Add a reset condition: 'if (rst) <output> <= 0; else ...'. "
                        "For FPGAs you may use 'initial' as alternative, but ASIC requires explicit reset."
                    )
                ))
        return findings
