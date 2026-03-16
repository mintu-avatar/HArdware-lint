"""
engine/scanner.py
=================
Orchestrates parsing + rule execution for one or many Verilog files.
"""

from __future__ import annotations
import os
import time
from typing import List
from engine.parser    import VerilogParser
from engine.rule_base import get_all_rules, Finding

# Import all rule modules so their @register_rule decorators fire
import rules.style
import rules.synthesis
import rules.assignments
import rules.latch
import rules.cdc
import rules.reset
import rules.fsm
import rules.ports
import rules.timing
import rules.testability
import rules.reliability
import rules.maintainability
import rules.security
import rules.cognitive
import rules.power
import rules.reset_integrity
import rules.reusability
import rules.structural_complexity
import rules.verifiability
import rules.clock_domain
import rules.timing_complexity


_VERILOG_EXTS = {'.v', '.sv'}


def _collect_files(path: str) -> List[str]:
    """Collect all Verilog/SV files under a path (file or directory)."""
    if os.path.isfile(path):
        return [path]
    collected = []
    for root, _, files in os.walk(path):
        for f in files:
            if os.path.splitext(f)[1].lower() in _VERILOG_EXTS:
                collected.append(os.path.join(root, f))
    return sorted(collected)


def scan(path: str, severity_filter: str = "INFO") -> "ScanResult":
    """
    Scan all Verilog files under *path*.

    Parameters
    ----------
    path            : file or directory path
    severity_filter : minimum severity to include ("INFO" | "WARNING" | "ERROR")

    Returns
    -------
    ScanResult containing all findings and timing metadata.
    """
    from engine.rule_base import Severity
    min_weight = Severity.weight(severity_filter)

    files   = _collect_files(path)
    parser  = VerilogParser()
    rules   = get_all_rules()
    results: List[Finding] = []
    errors:  List[str]     = []
    t0 = time.perf_counter()

    for fpath in files:
        try:
            ctx = parser.parse(fpath)
        except Exception as exc:
            errors.append(f"{fpath}: parse error — {exc}")
            continue

        for rule in rules:
            try:
                findings = rule.check(ctx)
                for f in findings:
                    if Severity.weight(f.severity) >= min_weight:
                        results.append(f)
            except Exception as exc:
                errors.append(f"{fpath} [{rule.rule_id}]: rule error — {exc}")

    elapsed = time.perf_counter() - t0
    return ScanResult(
        files=files,
        findings=sorted(results),
        errors=errors,
        elapsed=elapsed,
    )


class ScanResult:
    def __init__(self, files, findings, errors, elapsed):
        self.files    = files
        self.findings = findings
        self.errors   = errors
        self.elapsed  = elapsed

    # Count helpers
    def count(self, sev: str) -> int:
        return sum(1 for f in self.findings if f.severity == sev)
