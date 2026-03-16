"""
rules/security.py — Hardware Security rules
=============================================
VLG051  Uninitialized memory array — data-leak risk between privilege contexts
VLG052  Debug / JTAG port exposed in production RTL — attack surface
VLG053  No data zeroization on reset — sensitive register retains stale data
VLG054  Hardcoded key / credential literal — secrets must be parameterized
VLG055  Privilege or security signal driven by combinational logic — bypass risk

These rules address hardware-level security concerns. No commercial
synthesis tool (Vivado, Quartus, DC) checks for them; they map to the
Common Weakness Enumeration for hardware (CWE-1191 through CWE-1300).
"""

from __future__ import annotations
import re
from typing import List, Set
from engine.rule_base import RuleBase, Severity, Finding, ParseContext, register_rule


# ---------------------------------------------------------------------------
@register_rule
class VLG051(RuleBase):
    """
    Memory arrays (reg [N:0] mem [0:M]) that are never cleared/initialized
    on reset can retain stale data from a previous privilege context,
    leaking secrets across trust boundaries (CWE-1239).

    Heuristic: detect array declarations (two-dimensional reg) and check
    whether any reset block or initial block initializes them.
    """
    rule_id     = "VLG051"
    category    = "Security"
    severity    = Severity.WARNING
    description = "Memory array never cleared on reset — stale-data leak across contexts"

    _MEM_ARRAY_RE = re.compile(
        r'\breg\s+\[[^\]]+\]\s+(\w+)\s*\[\s*\d+\s*:\s*\d+\s*\]'
    )

    def check(self, ctx: ParseContext) -> List[Finding]:
        findings: List[Finding] = []
        all_text = '\n'.join(ctx.clean_lines)

        for i, ln in enumerate(ctx.clean_lines):
            m = self._MEM_ARRAY_RE.search(ln)
            if not m:
                continue
            mem_name = m.group(1)
            # Check if it's ever assigned in a reset branch or initial block
            # Look for patterns like:  mem[X] <= 0  or  for(...) mem[X] =
            init_re = re.compile(
                rf'\b{re.escape(mem_name)}\s*\[', re.I
            )
            # Search inside reset branches (look for rst/reset followed by mem init)
            found_init = False
            for blk in ctx.always_blocks:
                body = '\n'.join(blk['body_lines'])
                if re.search(r'\b(rst|reset|rst_n)\b', body, re.I) and init_re.search(body):
                    found_init = True
                    break

            if not found_init:
                # Also check initial blocks
                if re.search(rf'\binitial\b.*{re.escape(mem_name)}\s*\[', all_text, re.DOTALL):
                    found_init = True

            if not found_init:
                findings.append(self._finding(
                    ctx, i + 1,
                    snippet=f"Memory array '{mem_name}' is never cleared on reset or initialization",
                    suggestion=(
                        "Add a reset loop: 'for (i=0; i<DEPTH; i=i+1) mem[i] <= 0;' "
                        "to prevent stale data leakage between secure contexts."
                    ),
                ))
        return findings


# ---------------------------------------------------------------------------
@register_rule
class VLG052(RuleBase):
    """
    Debug, JTAG, or trace ports left in production RTL give attackers
    low-level access to internal state (CWE-1191). They should be removed
    or gated behind a hardware fuse.

    Heuristic: flag ports whose names match common debug patterns.
    """
    rule_id     = "VLG052"
    category    = "Security"
    severity    = Severity.WARNING
    description = "Debug / JTAG port in production RTL — potential attack surface"

    _DEBUG_RE = re.compile(
        r'\b(?:i_|o_)?(?:jtag|debug|trace|dbg|tdi|tdo|tms|tck|trst)\w*\b',
        re.I,
    )

    def check(self, ctx: ParseContext) -> List[Finding]:
        findings: List[Finding] = []
        for p in ctx.port_decls:
            if self._DEBUG_RE.search(p['name']):
                findings.append(self._finding(
                    ctx, p['line'],
                    snippet=f"Port '{p['name']}' looks like a debug/JTAG interface",
                    suggestion=(
                        "Gate debug ports behind a hardware fuse or eFuse-controlled mux. "
                        "In production silicon, debug access should be permanently disabled."
                    ),
                ))
        return findings


# ---------------------------------------------------------------------------
@register_rule
class VLG053(RuleBase):
    """
    Security-sensitive registers (keys, tokens, nonces, passwords) that are
    NOT cleared to zero on reset can retain cryptographic material after a
    context switch — violating CWE-1272.

    Heuristic: if a signal name contains 'key', 'secret', 'token', 'nonce',
    'passwd', or 'cipher', check that it's assigned 0 inside a reset branch.
    """
    rule_id     = "VLG053"
    category    = "Security"
    severity    = Severity.ERROR
    description = "Sensitive register not zeroed on reset — cryptographic data-remanence risk"

    _SENSITIVE_RE = re.compile(
        r'\b\w*(?:key|secret|token|nonce|passwd|cipher|crypt|hmac|aes|sha|priv)\w*\b', re.I
    )
    _RST_RE = re.compile(r'\b(?:rst|reset|rst_n|i_rst|i_rst_n)\b', re.I)

    def check(self, ctx: ParseContext) -> List[Finding]:
        findings: List[Finding] = []

        # Collect all sensitive signal names
        sensitive_sigs: dict = {}  # name -> decl line
        for s in ctx.signal_decls:
            if self._SENSITIVE_RE.search(s['name']):
                sensitive_sigs[s['name']] = s['line']
        for p in ctx.port_decls:
            if p['direction'] == 'input':
                continue  # inputs can't be zeroed by this module
            if self._SENSITIVE_RE.search(p['name']):
                sensitive_sigs[p['name']] = p['line']

        if not sensitive_sigs:
            return findings

        # Check which are written to 0 inside reset branches
        zeroed: Set[str] = set()
        for blk in ctx.always_blocks:
            body_text = '\n'.join(blk['body_lines'])
            if not self._RST_RE.search(body_text):
                continue
            for sig in sensitive_sigs:
                if re.search(rf'\b{re.escape(sig)}\s*<=\s*(\d+\'[bdh])?0+\s*;', body_text):
                    zeroed.add(sig)

        for sig, line in sensitive_sigs.items():
            if sig not in zeroed:
                findings.append(self._finding(
                    ctx, line,
                    snippet=f"Sensitive register '{sig}' is not zeroed on reset",
                    suggestion=(
                        f"Add '{sig} <= 0;' in the reset branch to prevent "
                        f"cryptographic data remanence after context switch."
                    ),
                ))
        return findings


# ---------------------------------------------------------------------------
@register_rule
class VLG054(RuleBase):
    """
    Hardcoded cryptographic keys or credential constants embedded directly in
    RTL source code are a severe security anti-pattern (CWE-321). Keys should
    come from OTP, eFuse, or a key-management bus — never from a literal.

    Heuristic: flag localparam / parameter whose name contains 'key',
    'secret', 'passwd', etc. AND whose value is a large hex/binary literal.
    """
    rule_id     = "VLG054"
    category    = "Security"
    severity    = Severity.ERROR
    description = "Hardcoded key / credential in RTL — use OTP or eFuse instead"

    _KEY_NAME_RE  = re.compile(
        r'(?:key|secret|passwd|password|seed|iv_val|init_vec)', re.I
    )
    _BIG_LIT_RE   = re.compile(r"\d+'[hHbB][\da-fA-F_]{4,}")
    # Match parameter/localparam with optional type/width prefix
    _PARAM_LINE_RE = re.compile(
        r'\b(?:parameter|localparam)\s+(?:\[[^\]]*\]\s+)?(?:\w+\s+)?(\w+)\s*=\s*([^;,]+)',
        re.I,
    )

    def check(self, ctx: ParseContext) -> List[Finding]:
        findings: List[Finding] = []
        # Check ctx.parameters first, then scan lines for sized ones the parser may miss
        checked_names: set = set()
        for p in ctx.parameters:
            checked_names.add(p['name'])
            if self._KEY_NAME_RE.search(p['name']) and self._BIG_LIT_RE.search(p['value']):
                findings.append(self._finding(
                    ctx, p['line'],
                    snippet=f"Parameter '{p['name']}' = {p['value'][:40]}… is a hardcoded secret",
                    suggestion=(
                        "Never hardcode keys in RTL. Load them from OTP/eFuse/key-bus at runtime. "
                        "Hardcoded keys can be extracted from the bitstream by an attacker."
                    ),
                ))
        # Fallback: scan lines for sized localparams the parser regex missed
        for i, ln in enumerate(ctx.clean_lines):
            m = self._PARAM_LINE_RE.search(ln)
            if not m:
                continue
            name, value = m.group(1), m.group(2).strip()
            if name in checked_names:
                continue
            checked_names.add(name)
            if self._KEY_NAME_RE.search(name) and self._BIG_LIT_RE.search(value):
                findings.append(self._finding(
                    ctx, i + 1,
                    snippet=f"Parameter '{name}' = {value[:40]}… is a hardcoded secret",
                    suggestion=(
                        "Never hardcode keys in RTL. Load them from OTP/eFuse/key-bus at runtime. "
                        "Hardcoded keys can be extracted from the bitstream by an attacker."
                    ),
                ))
        return findings


# ---------------------------------------------------------------------------
@register_rule
class VLG055(RuleBase):
    """
    Privilege-escalation, security-fence, or access-control signals that are
    driven purely by combinational logic (no registration) can be glitched
    by an attacker using voltage or EM fault injection.

    Heuristic: if a signal whose name contains 'priv', 'secure', 'trust',
    'auth', 'grant', 'access', 'lock' is in a continuous assign or comb
    always block (never registered), flag it.
    """
    rule_id     = "VLG055"
    category    = "Security"
    severity    = Severity.ERROR
    description = "Security signal driven combinationally — glitch-fault bypass risk"

    _SEC_SIG_RE = re.compile(
        r'\b\w*(?:priv|secure|trust|auth|grant|access|lock|perm|protect|fence|firewall)\w*\b',
        re.I,
    )

    def check(self, ctx: ParseContext) -> List[Finding]:
        findings: List[Finding] = []

        # Collect security-related signal names
        sec_sigs: dict = {}
        for s in ctx.signal_decls:
            if self._SEC_SIG_RE.search(s['name']):
                sec_sigs[s['name']] = s['line']
        for p in ctx.port_decls:
            if self._SEC_SIG_RE.search(p['name']):
                sec_sigs[p['name']] = p['line']

        if not sec_sigs:
            return findings

        # Check: is the signal ever assigned in a clocked block?
        registered: Set[str] = set()
        _LHS_NB = re.compile(r'(\w+)\s*<=')
        for blk in ctx.always_blocks:
            if blk['block_type'] in ('clocked_posedge', 'clocked_negedge'):
                for bln in blk['body_lines']:
                    for m in _LHS_NB.finditer(bln):
                        registered.add(m.group(1))

        # Check: is it driven combinationally?
        comb_driven: Set[str] = set()
        for a in ctx.assign_stmts:
            comb_driven.add(a['lhs'].split('[')[0])
        _ASSIGN = re.compile(r'(\w+)\s*=')
        for blk in ctx.always_blocks:
            if blk['block_type'] == 'combinational':
                for bln in blk['body_lines']:
                    for m in _ASSIGN.finditer(bln):
                        comb_driven.add(m.group(1))

        for sig, line in sec_sigs.items():
            if sig in comb_driven and sig not in registered:
                findings.append(self._finding(
                    ctx, line,
                    snippet=f"Security signal '{sig}' is driven combinationally, never registered",
                    suggestion=(
                        f"Register '{sig}' with a flip-flop. Combinational security signals "
                        f"are vulnerable to voltage/EM glitch-fault injection."
                    ),
                ))
        return findings
