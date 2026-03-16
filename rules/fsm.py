"""
rules/fsm.py — FSM Design Quality rules
========================================
VLG027  FSM case with no default state transition
VLG028  Large FSM not using one-hot encoding
VLG029  FSM state register modified in combinational block
VLG030  FSM outputs not registered (combinational output decode)
"""

from __future__ import annotations
import re
from typing import List, Set
from engine.rule_base import RuleBase, Severity, Finding, ParseContext, register_rule


def _body_text(blk: dict) -> str:
    return '\n'.join(blk['body_lines'])


def _count_case_items(body: str) -> int:
    """Heuristically count unique case items (not counting default/endcase/begin/end)."""
    items = re.findall(r'^\s*\d+\'[bhodBHOD]\w+\s*:', body, re.MULTILINE)
    items += re.findall(r'^\s*\w+\s*:', body, re.MULTILINE)
    # Remove keywords that look like labels but aren't case items
    _KEYWORDS = {'begin', 'end', 'default', 'endcase', 'else', 'always', 'assign'}
    filtered = [i for i in items if i.strip().rstrip(':').strip().lower() not in _KEYWORDS]
    return len(filtered)


# ---------------------------------------------------------------------------
@register_rule
class VLG027(RuleBase):
    """
    An FSM case statement without a 'default' branch will lock up if the
    state register reaches an unencoded or power-on-reset value.
    RTL reason: unreachable states (e.g., from SEU/radiation or reset glitch)
    have no defined next-state, causing the FSM to freeze indefinitely.
    """
    rule_id     = "VLG027"
    category    = "FSM"
    severity    = Severity.WARNING
    description = "FSM case statement has no 'default' branch — unreachable state lockup risk"

    _STATE_RE   = re.compile(r'\bcase\s*\(\s*\w*state\w*\s*\)', re.IGNORECASE)
    _DEFAULT_RE = re.compile(r'\bdefault\b')

    def check(self, ctx: ParseContext) -> List[Finding]:
        findings = []
        for blk in ctx.always_blocks:
            body = _body_text(blk)
            if self._STATE_RE.search(body):
                if not self._DEFAULT_RE.search(body):
                    findings.append(self._finding(
                        ctx, blk['start_line'],
                        suggestion=(
                            "Add: 'default: state <= IDLE;' (or safe reset state) "
                            "to handle illegal state transitions gracefully."
                        )
                    ))
        return findings


# ---------------------------------------------------------------------------
@register_rule
class VLG028(RuleBase):
    """
    FSMs with more than 6 states benefit from one-hot encoding in FPGAs
    (each state maps to a flip-flop, enabling single-LUT output decode).
    Binary encoding requires a decoder and creates longer combinational paths.
    RTL reason: one-hot FSMs are faster, have fewer glitches on outputs,
    and are easier to debug in simulation (each state bit is observable).
    """
    rule_id     = "VLG028"
    category    = "FSM"
    severity    = Severity.WARNING
    description = "FSM with >6 states may benefit from one-hot encoding"

    _STATE_RE = re.compile(r'\bcase\s*\(\s*\w*state\w*\s*\)', re.IGNORECASE)

    ONE_HOT_THRESHOLD = 6

    def check(self, ctx: ParseContext) -> List[Finding]:
        findings = []
        for blk in ctx.always_blocks:
            body = _body_text(blk)
            if self._STATE_RE.search(body):
                n_states = _count_case_items(body)
                if n_states > self.ONE_HOT_THRESHOLD:
                    # Check if state parameter uses one-hot values (powers of 2)
                    state_vals = re.findall(r"localparam\s+\w+\s*=\s*\d+'b(\d+)", '\n'.join(ctx.clean_lines))
                    is_one_hot = all(v.count('1') == 1 for v in state_vals if v)
                    if not is_one_hot:
                        findings.append(self._finding(
                            ctx, blk['start_line'],
                            snippet=f"FSM with ~{n_states} states using non-one-hot encoding",
                            suggestion=(
                                "Consider one-hot encoding. e.g.: localparam IDLE=4'b0001, "
                                "FETCH=4'b0010, EXEC=4'b0100, DONE=4'b1000;"
                            )
                        ))
        return findings


# ---------------------------------------------------------------------------
@register_rule
class VLG029(RuleBase):
    """
    The FSM state register (next_state/current_state) must only be updated
    in a clocked always block using non-blocking assignment.
    If the state is modified in a combinational block with '=', it creates
    a combinational loop and unpredictable state transitions.
    RTL reason: the two-always FSM pattern separates state register (seq)
    from next-state logic (comb), and they must not be conflated.
    """
    rule_id     = "VLG029"
    category    = "FSM"
    severity    = Severity.ERROR
    description = "FSM state signal modified with blocking '=' in combinational block — race condition"

    _STATE_ASSIGN_RE = re.compile(
        r'^\s*(?<!next_)state\w*\s*=(?!=)', re.IGNORECASE | re.MULTILINE)

    # Also catches bare `state =` but NOT `next_state =` (which is correct 2-always FSM)
    _CURR_STATE_RE = re.compile(
        r'^\s*(state(?!_next)\w*)\s*=(?!=)', re.IGNORECASE | re.MULTILINE)

    def check(self, ctx: ParseContext) -> List[Finding]:
        findings = []
        for blk in ctx.always_blocks:
            if blk['block_type'] != 'combinational':
                continue
            body = _body_text(blk)
            # Only flag if state (not next_state) is assigned with blocking = in comb
            for m in self._CURR_STATE_RE.finditer(body):
                sig = m.group(1)
                # skip: next_state, next_st, nxt_state, state_next — all are OK in comb
                if re.match(r'^(next|nxt|n_)', sig, re.IGNORECASE):
                    continue
                if sig.endswith('_next') or sig.endswith('_nxt'):
                    continue
                findings.append(self._finding(
                    ctx, blk['start_line'],
                    snippet=f"'{sig} =' found in combinational block",
                    suggestion=(
                        "Use a two-always FSM: state <= next_state in the clocked block; "
                        "compute next_state with '=' in the combinational block."
                    )
                ))
                break  # one finding per block is enough
        return findings


# ---------------------------------------------------------------------------
@register_rule
class VLG030(RuleBase):
    """
    When FSM outputs are decoded combinationally (directly from the state
    register in a comb always block), they glitch during state transitions
    because the combinational path sees intermittent combinational values.
    RTL reason: registering outputs adds one cycle latency but eliminates
    glitches and meets setup time more easily (shorter timing paths).
    """
    rule_id     = "VLG030"
    category    = "FSM"
    severity    = Severity.WARNING
    description = "FSM outputs decoded combinationally — consider registering outputs to prevent glitches"

    _STATE_CASE_RE = re.compile(r'\bcase\s*\(\s*\w*state\w*\s*\)', re.IGNORECASE)
    _OUTPUT_ASSIGN_RE = re.compile(r'^\s*(\w+)\s*=(?!=)\s*[^;]+;', re.MULTILINE)
    _NEXT_STATE_RE = re.compile(r'(?:next|nxt|n_)\w*state|state\w*(?:_next|_nxt)', re.IGNORECASE)

    def check(self, ctx: ParseContext) -> List[Finding]:
        findings = []
        for blk in ctx.always_blocks:
            if blk['block_type'] != 'combinational':
                continue
            body = _body_text(blk)
            if not self._STATE_CASE_RE.search(body):
                continue
            # Collect all LHS signals assigned in this block
            assigned_sigs = set()
            for m in self._OUTPUT_ASSIGN_RE.finditer(body):
                assigned_sigs.add(m.group(1))
            if not assigned_sigs:
                continue
            # If the ONLY assigned signals are next-state, this is a clean
            # 2-always FSM pattern — no need to flag
            non_state = [s for s in assigned_sigs if not self._NEXT_STATE_RE.match(s)]
            if non_state:
                findings.append(self._finding(
                    ctx, blk['start_line'],
                    suggestion=(
                        "Move output assignments to a separate registered always block "
                        "(Moore output model) to prevent glitches."
                    )
                ))
        return findings
