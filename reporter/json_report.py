"""
reporter/json_report.py
=======================
Machine-readable JSON reporter.
Output schema:
{
  "metadata": { "scanned_files": [...], "elapsed_s": float, "total_findings": int },
  "summary":  { "ERROR": int, "WARNING": int, "INFO": int },
  "findings": [ { "file", "line", "rule_id", "severity", "category",
                  "description", "snippet", "suggestion" }, ... ],
  "errors":   [ "..." ]
}
"""

from __future__ import annotations
import json
import sys
from dataclasses import asdict
from engine.rule_base import Finding, Severity
from engine.scanner   import ScanResult


def build_json(result: ScanResult, pretty: bool = True) -> str:
    """Return the full report as a JSON string."""

    findings_list = []
    for f in result.findings:
        findings_list.append({
            "file":        f.file,
            "line":        f.line,
            "rule_id":     f.rule_id,
            "severity":    f.severity,
            "category":    f.category,
            "description": f.description,
            "snippet":     f.snippet,
            "suggestion":  f.suggestion,
        })

    report = {
        "metadata": {
            "scanned_files":   result.files,
            "elapsed_s":       round(result.elapsed, 4),
            "total_findings":  len(result.findings),
        },
        "summary": {
            Severity.ERROR:   result.count(Severity.ERROR),
            Severity.WARNING: result.count(Severity.WARNING),
            Severity.INFO:    result.count(Severity.INFO),
        },
        "findings": findings_list,
        "errors":   result.errors,
    }

    indent = 2 if pretty else None
    return json.dumps(report, indent=indent, ensure_ascii=False)


def write_json(result: ScanResult, outpath: str, pretty: bool = True) -> None:
    """Write JSON report to *outpath*."""
    data = build_json(result, pretty)
    with open(outpath, 'w', encoding='utf-8') as fh:
        fh.write(data)
    print(f"JSON report written → {outpath}")
