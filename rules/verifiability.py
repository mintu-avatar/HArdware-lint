"""
rules/verifiability.py — Verifiability & Testability rules
============================================================
VLG081  No assertion hooks — module lacks coverage / assertion-friendly signals
VLG082  FSM state not observable — state variable not on output port
VLG083  Large combinational cone — too many inputs to single always block
VLG084  No handshake protocol check — valid/ready without back-pressure logic
VLG085  Potentially dead code — signal assigned but never read in module

These rules predict how hard a module is to verify, whether by simulation,
formal, or FPGA prototyping. No synthesis tool flags them.
"""

from __future__ import annotations
import re
from typing import List, Set
from engine.rule_base import RuleBase, Severity, Finding, ParseContext, register_rule


# ---------------------------------------------------------------------------
@register_rule
class VLG081(RuleBase):
    """
    Modules without any assertion property, cover statement, or named
    observation points lack hooks for formal verification and coverage
    closure. Even in pure-RTL, adding `// synopsys translate_off` blocks
    with assertions dramatically improves bug-finding.
    """
    rule_id     = "VLG081"
    category    = "Verifiability"
    severity    = Severity.INFO
    description = "No assertion or coverage hooks — hard to verify formally"

    _ASSERT_RE = re.compile(
        r'\b(?:assert|assume|cover|restrict|property|sequence)\b'
        r'|//\s*(?:psl|sva)\b'
        r'|\bassert_\w+\b',
        re.I
    )

    def check(self, ctx: ParseContext) -> List[Finding]:
        findings: List[Finding] = []
        for mod in ctx.modules:
            sl, el = mod['start_line'], mod['end_line']
            # Only flag sequential modules (those with FFs are complex enough to need assertions)
            has_ffs = any(
                blk['block_type'] in ('clocked_posedge', 'clocked_negedge')
                and sl <= blk['start_line'] <= el
                for blk in ctx.always_blocks
            )
            if not has_ffs:
                continue
            mod_text = '\n'.join(ctx.lines[sl - 1 : el])
            if not self._ASSERT_RE.search(mod_text):
                findings.append(self._finding(
                    ctx, sl,
                    snippet=f"Module '{mod['name']}' has no assertion or coverage hooks",
                    suggestion=(
                        "Add SVA assertions or cover properties for key invariants. "
                        "Even simple assertions catch 40-60% of bugs that simulation misses."
                    ),
                ))
        return findings


# ---------------------------------------------------------------------------
@register_rule
class VLG082(RuleBase):
    """
    An FSM state variable that exists only internally with no debug output
    port is invisible during silicon bring-up and FPGA prototyping.
    Making the state observable is critical for post-silicon debug.
    """
    rule_id     = "VLG082"
    category    = "Verifiability"
    severity    = Severity.INFO
    description = "FSM state not observable — state variable not routed to output port"

    _STATE_RE = re.compile(r'\b(\w*(?:state|fsm_st)\w*)\b', re.I)

    def check(self, ctx: ParseContext) -> List[Finding]:
        findings: List[Finding] = []
        for mod in ctx.modules:
            sl, el = mod['start_line'], mod['end_line']
            # Scope output names to THIS module only
            output_names = {
                p['name'] for p in ctx.port_decls
                if p['direction'] == 'output' and sl <= p['line'] <= el
            }
            state_vars = set()
            for blk in ctx.always_blocks:
                if not (sl <= blk['start_line'] <= el):
                    continue
                body = '\n'.join(blk['body_lines'])
                # Look for case(state) patterns
                case_m = re.search(r'\bcase\s*\(\s*(\w+)\s*\)', body)
                if case_m:
                    state_vars.add(case_m.group(1))
            for sv in state_vars:
                # Check if state var or any *_state* output exists in this module
                is_observable = any(
                    sv in name or 'state' in name.lower() or 'dbg' in name.lower()
                    for name in output_names
                )
                if not is_observable:
                    findings.append(self._finding(
                        ctx, sl,
                        snippet=f"FSM state '{sv}' in '{mod['name']}' is not on any output port",
                        suggestion=(
                            f"Add 'output [{sv}_WIDTH-1:0] dbg_{sv}' to expose the state "
                            f"for debug. Wrap in `ifdef DEBUG if area is a concern."
                        ),
                    ))
        return findings


# ---------------------------------------------------------------------------
@register_rule
class VLG083(RuleBase):
    """
    A combinational always block that reads many distinct signals has a
    large combinational cone which is hard to constrain in simulation and
    formal tools, and creates wide timing fan-in.
    """
    rule_id     = "VLG083"
    category    = "Verifiability"
    severity    = Severity.INFO
    description = "Large combinational cone — always @(*) block reads >10 signals"

    THRESHOLD = 10
    _IDENT = re.compile(r'\b([a-zA-Z_]\w*)\b')
    _KEYWORDS = {
        'if', 'else', 'begin', 'end', 'case', 'endcase', 'casez', 'casex',
        'default', 'assign', 'wire', 'reg', 'logic', 'always',
    }

    def check(self, ctx: ParseContext) -> List[Finding]:
        findings: List[Finding] = []
        for blk in ctx.always_blocks:
            if blk['block_type'] != 'combinational':
                continue
            body = '\n'.join(blk['body_lines'])
            # Collect all identifiers used on RHS
            rhs_idents: Set[str] = set()
            lhs_idents: Set[str] = set()
            for bln in blk['body_lines']:
                # LHS of assignments
                for m in re.finditer(r'(\w+)\s*(?:<=|=)', bln):
                    lhs_idents.add(m.group(1))
                # All identifiers
                for m in self._IDENT.finditer(bln):
                    rhs_idents.add(m.group(1))
            read_sigs = rhs_idents - lhs_idents - self._KEYWORDS
            read_sigs = {s for s in read_sigs if not s[0].isdigit()}
            if len(read_sigs) > self.THRESHOLD:
                findings.append(self._finding(
                    ctx, blk['start_line'],
                    snippet=f"Comb block reads {len(read_sigs)} signals (threshold: {self.THRESHOLD})",
                    suggestion=(
                        "Break this comb block into smaller blocks or use intermediate "
                        "wires. Large combinational cones are hard to constrain in formal."
                    ),
                ))
        return findings


# ---------------------------------------------------------------------------
@register_rule
class VLG084(RuleBase):
    """
    A module with valid/ready handshake ports but no visible back-pressure
    logic (ready depends on internal state or valid) is likely missing
    flow-control and can silently drop data.
    """
    rule_id     = "VLG084"
    category    = "Verifiability"
    severity    = Severity.WARNING
    description = "Handshake port without back-pressure logic — may drop data"

    _VALID_RE = re.compile(r'\b\w*valid\w*\b', re.I)
    _READY_RE = re.compile(r'\b\w*ready\w*\b', re.I)

    def check(self, ctx: ParseContext) -> List[Finding]:
        findings: List[Finding] = []
        port_names = [p['name'] for p in ctx.port_decls]
        has_valid = any(self._VALID_RE.match(n) for n in port_names)
        has_ready = any(self._READY_RE.match(n) for n in port_names)
        if not (has_valid and has_ready):
            return findings
        # Check if ready is actually driven by some logic
        full_text = '\n'.join(ctx.clean_lines)
        ready_driven = re.search(r'\b\w*ready\w*\s*(?:<=|=)', full_text, re.I)
        valid_checked = re.search(r'\bif\s*\(.*\bvalid\b', full_text, re.I)
        if has_valid and has_ready and not (ready_driven and valid_checked):
            findings.append(self._finding(
                ctx, ctx.modules[0]['start_line'] if ctx.modules else 1,
                snippet="Module has valid/ready ports but no visible back-pressure logic",
                suggestion=(
                    "Ensure ready is deasserted when the module cannot accept data. "
                    "A valid/ready handshake without flow control silently drops transactions."
                ),
            ))
        return findings


# ---------------------------------------------------------------------------
@register_rule
class VLG085(RuleBase):
    """
    A signal that is assigned but never read anywhere in the module is
    dead code — it wastes area and confuses reviewers. This is harder to
    detect than unused ports because internal signals have no external
    consumers to check.
    """
    rule_id     = "VLG085"
    category    = "Verifiability"
    severity    = Severity.INFO
    description = "Potentially dead signal — assigned but never read in module"

    _ASSIGN_LHS = re.compile(r'(\w+)\s*(?:<=|=)')
    _IDENT      = re.compile(r'\b([a-zA-Z_]\w*)\b')

    def check(self, ctx: ParseContext) -> List[Finding]:
        findings: List[Finding] = []
        for mod in ctx.modules:
            sl, el = mod['start_line'], mod['end_line']
            mod_lines = ctx.clean_lines[sl - 1 : el]
            # Collect all LHS (assigned) signals
            assigned: Set[str] = set()
            for ln in mod_lines:
                for m in self._ASSIGN_LHS.finditer(ln):
                    assigned.add(m.group(1))
            # Collect output port names (they ARE externally read)
            output_names = {
                p['name'] for p in ctx.port_decls
                if p['direction'] == 'output' and sl <= p['line'] <= el
            }
            # Collect all identifiers used on RHS or in conditions
            all_read: Set[str] = set()
            for ln in mod_lines:
                # RHS of assignments
                parts = re.split(r'(?:<=|(?<!=)=(?!=))', ln, maxsplit=1)
                if len(parts) > 1:
                    for m in self._IDENT.finditer(parts[1]):
                        all_read.add(m.group(1))
                # Condition identifiers (if, case)
                for m in re.finditer(r'\b(?:if|case|casez|casex)\s*\(([^)]+)\)', ln):
                    for ident_m in self._IDENT.finditer(m.group(1)):
                        all_read.add(ident_m.group(1))
                # Instance connections
                for m in re.finditer(r'\.\w+\s*\(([^)]+)\)', ln):
                    for ident_m in self._IDENT.finditer(m.group(1)):
                        all_read.add(ident_m.group(1))
            dead = assigned - all_read - output_names
            # Filter out common names that might be read implicitly
            dead = {s for s in dead if len(s) > 1 and not s.startswith('_')}
            for sig in sorted(dead)[:5]:  # limit to 5 per module
                findings.append(self._finding(
                    ctx, sl,
                    snippet=f"Signal '{sig}' is assigned but never read in module '{mod['name']}'",
                    suggestion=(
                        f"Remove '{sig}' if unused, or route it to a debug port. "
                        f"Dead signals waste area and confuse code reviewers."
                    ),
                ))
        return findings
