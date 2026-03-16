"""
rules/ports.py — Signal Naming & Port Hygiene rules
=====================================================
VLG031  Undriven output port
VLG032  Unconnected input port in submodule instantiation
VLG033  Implicit net declaration
VLG034  Positional port connections in instantiation
"""

from __future__ import annotations
import re
from typing import List, Set
from engine.rule_base import RuleBase, Severity, Finding, ParseContext, register_rule


# ---------------------------------------------------------------------------
@register_rule
class VLG031(RuleBase):
    """
    An output port that is never assigned inside the module will float to X
    in simulation and 0/undefined in synthesis — silently wrong.
    RTL reason: downstream modules receiving this output will see garbage,
    causing functional failures that are difficult to trace.
    """
    rule_id     = "VLG031"
    category    = "Ports"
    severity    = Severity.WARNING
    description = "Output port is never driven (assigned) inside the module"

    def check(self, ctx: ParseContext) -> List[Finding]:
        findings = []
        # Collect output port names
        output_ports: List[dict] = [p for p in ctx.port_decls if p['direction'] == 'output']
        if not output_ports:
            return findings

        # Collect all LHS signals from assigns and always blocks
        driven: Set[str] = set()
        for stmt in ctx.assign_stmts:
            driven.add(re.sub(r'\[.*\]', '', stmt['lhs']).strip())

        for blk in ctx.always_blocks:
            for ln in blk['body_lines']:
                m = re.match(r'\s*(\w+)\s*(?:\[[^\]]*\])?\s*(?:<=|=)(?!=)', ln)
                if m:
                    driven.add(m.group(1))

        for port in output_ports:
            if port['name'] not in driven:
                findings.append(self._finding(
                    ctx, port['line'],
                    snippet=f"output port '{port['name']}' is never assigned",
                    suggestion=f"Add 'assign {port['name']} = <value>;' or drive it from an always block."
                ))
        return findings


# ---------------------------------------------------------------------------
@register_rule
class VLG032(RuleBase):
    """
    Leaving an input port of a submodule unconnected (.port()) silently
    drives it to 0 (or X in some simulators), which may cause:
    - False enable/reset assertions
    - Unintended logic zero propagation
    RTL reason: explicitly list all connections; if a port is intentionally unused,
    tie it to a constant and comment why.
    """
    rule_id     = "VLG032"
    category    = "Ports"
    severity    = Severity.ERROR
    description = "Input port in submodule instantiation left unconnected — driven to 0/X"

    # Matches .portname() — empty connection
    _EMPTY_CONN_RE = re.compile(r'\.\s*(\w+)\s*\(\s*\)')

    def check(self, ctx: ParseContext) -> List[Finding]:
        findings = []
        for inst in ctx.instances:
            for m in self._EMPTY_CONN_RE.finditer(inst['conn_str']):
                port_name = m.group(1)
                findings.append(Finding(
                    rule_id=self.rule_id,
                    severity=self.severity,
                    category=self.category,
                    description=self.description,
                    file=ctx.filepath,
                    line=inst['line'],
                    snippet=f"Instance '{inst['inst_name']}' port '.{port_name}()' unconnected",
                    suggestion=(
                        f"Connect '.{port_name}(<signal>)' or tie to constant "
                        f"e.g. '.{port_name}(1'b0)' with a comment explaining why."
                    )
                ))
        return findings


# ---------------------------------------------------------------------------
@register_rule
class VLG033(RuleBase):
    """
    Using an undeclared signal (relying on implicit net declarations) is
    tool-version-dependent. Older Verilog-1995 allowed implicit wire nets,
    but this causes hard-to-find bugs when signals are mistyped.
    RTL reason: `default_nettype none` should be set at the top of
    every RTL file to catch implicit net usage at elaboration time.
    """
    rule_id     = "VLG033"
    category    = "Ports"
    severity    = Severity.WARNING
    description = "`default_nettype none` not set — implicit net declarations risk"

    _NETTYPE_RE = re.compile(r'`default_nettype\s+none')

    def check(self, ctx: ParseContext) -> List[Finding]:
        findings = []
        full_text = '\n'.join(ctx.clean_lines)
        if not self._NETTYPE_RE.search(full_text):
            if ctx.modules:  # only flag files that actually contain modules
                findings.append(self._finding(
                    ctx, 1,
                    snippet="No `default_nettype none found in file",
                    suggestion="Add '`default_nettype none' at the top of every RTL file before any module."
                ))
        return findings


# ---------------------------------------------------------------------------
@register_rule
class VLG034(RuleBase):
    """
    Using positional port connections in module instantiations causes silent
    bugs when ports are added, reordered, or renamed in the instantiated module.
    RTL reason: named connections (.port_name(signal)) are immune to port
    order changes and make the connection intent self-documenting.
    """
    rule_id     = "VLG034"
    category    = "Ports"
    severity    = Severity.INFO
    description = "Positional port connections used in module instantiation — use named connections"

    # Detect instantiations where content is NOT .name(val) pattern
    _NAMED_CONN_RE = re.compile(r'\.\s*\w+\s*\(')

    def check(self, ctx: ParseContext) -> List[Finding]:
        findings = []
        for inst in ctx.instances:
            conn = inst['conn_str'].strip()
            if not conn:
                continue
            # If there are no .name( patterns but there IS content, it's positional
            if conn and not self._NAMED_CONN_RE.search(conn):
                # Make sure it's not just an empty list ()
                inner = re.sub(r'[)(;\s]', '', conn)
                if inner:
                    findings.append(Finding(
                        rule_id=self.rule_id,
                        severity=self.severity,
                        category=self.category,
                        description=self.description,
                        file=ctx.filepath,
                        line=inst['line'],
                        snippet=f"Instance '{inst['inst_name']}' of '{inst['module_type']}' uses positional ports",
                        suggestion="Use named port connections: .port_name(signal_name)"
                    ))
        return findings
