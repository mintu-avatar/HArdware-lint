"""
rule_base.py
============
Defines the base class for all lint rules and the global rule registry.

Design principle: every rule is a self-contained class with a single
`check(context) -> list[Finding]` method. This makes adding new rules
trivial — subclass RuleBase, decorate with @register_rule, done.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable, List, Dict, Optional


# ---------------------------------------------------------------------------
# Severity levels
# ---------------------------------------------------------------------------
class Severity:
    ERROR   = "ERROR"
    WARNING = "WARNING"
    INFO    = "INFO"

    # Numerical weight for sorting / threshold filtering
    _WEIGHT = {ERROR: 3, WARNING: 2, INFO: 1}

    @classmethod
    def weight(cls, sev: str) -> int:
        return cls._WEIGHT.get(sev, 0)


# ---------------------------------------------------------------------------
# Finding  — one issue found in one file at one location
# ---------------------------------------------------------------------------
@dataclass
class Finding:
    rule_id:     str
    severity:    str
    category:    str
    description: str
    file:        str
    line:        int
    snippet:     str = ""           # the offending source line (stripped)
    suggestion:  str = ""           # optional fix hint

    def __lt__(self, other: "Finding") -> bool:
        """Sort: severity desc, then file, then line."""
        if self.file != other.file:
            return self.file < other.file
        if Severity.weight(self.severity) != Severity.weight(other.severity):
            return Severity.weight(self.severity) > Severity.weight(other.severity)
        return self.line < other.line


# ---------------------------------------------------------------------------
# Parse context  — what every rule receives
# ---------------------------------------------------------------------------
@dataclass
class ParseContext:
    """
    Holds both the raw lines of a file and pre-computed metadata produced
    by the VerilogParser. Rules may query either layer.
    """
    filepath:    str
    lines:       List[str]          # raw file lines (0-indexed)
    clean_lines: List[str]          # lines with single-line comments stripped
    # Metadata populated by the parser
    modules:     List[Dict]         = field(default_factory=list)
    always_blocks: List[Dict]       = field(default_factory=list)
    assign_stmts:  List[Dict]       = field(default_factory=list)
    port_decls:    List[Dict]       = field(default_factory=list)
    signal_decls:  List[Dict]       = field(default_factory=list)
    instances:     List[Dict]       = field(default_factory=list)
    parameters:    List[Dict]       = field(default_factory=list)
    # Verilog-AMS metadata populated by parser
    analog_blocks: List[Dict]       = field(default_factory=list)
    disciplines:   List[Dict]       = field(default_factory=list)
    natures:       List[Dict]       = field(default_factory=list)
    branches:      List[Dict]       = field(default_factory=list)
    contributions: List[Dict]       = field(default_factory=list)
    ams_keywords:  List[Dict]       = field(default_factory=list)


# ---------------------------------------------------------------------------
# Rule base class
# ---------------------------------------------------------------------------
class RuleBase:
    """
    Every lint rule must subclass RuleBase and implement `check`.

    Attributes (class-level — override in subclass):
        rule_id    : unique identifier, e.g. "VLG013"
        category   : human-readable category string
        severity   : one of Severity.ERROR / WARNING / INFO
        description: one-line human description shown in reports
    """
    rule_id:     str = "VLGXXX"
    category:    str = "Uncategorized"
    severity:    str = Severity.WARNING
    description: str = "No description"

    def check(self, ctx: ParseContext) -> List[Finding]:
        """
        Analyse *ctx* and return a (possibly empty) list of Finding objects.
        Subclasses MUST override this method.
        """
        raise NotImplementedError(f"{self.__class__.__name__} must implement check()")

    # Convenience helper so rule code stays concise
    def _finding(self, ctx: ParseContext, line: int, snippet: str = "",
                 suggestion: str = "") -> Finding:
        raw = ctx.lines[line - 1].rstrip() if 0 < line <= len(ctx.lines) else ""
        return Finding(
            rule_id=self.rule_id,
            severity=self.severity,
            category=self.category,
            description=self.description,
            file=ctx.filepath,
            line=line,
            snippet=snippet or raw.strip(),
            suggestion=suggestion,
        )


# ---------------------------------------------------------------------------
# Rule registry
# ---------------------------------------------------------------------------
_RULE_REGISTRY: Dict[str, RuleBase] = {}


def register_rule(cls: type) -> type:
    """
    Class decorator — instantiates the rule class and adds it to the global
    registry keyed by rule_id.

    Usage:
        @register_rule
        class VLG013(RuleBase):
            ...
    """
    instance = cls()
    if instance.rule_id in _RULE_REGISTRY:
        raise ValueError(f"Duplicate rule_id: {instance.rule_id}")
    _RULE_REGISTRY[instance.rule_id] = instance
    return cls


def get_all_rules() -> List[RuleBase]:
    """Return all registered rules sorted by rule_id."""
    return sorted(_RULE_REGISTRY.values(), key=lambda r: r.rule_id)
