"""
reporter/cli.py
===============
Colored terminal reporter for hardware-lint findings.

Color scheme:
  ERROR   → bold red
  WARNING → bold yellow
  INFO    → cyan
"""

from __future__ import annotations
import io
import os
import sys
from collections import defaultdict
from typing import List
from engine.rule_base import Finding, Severity
from engine.scanner   import ScanResult

# Ensure stdout uses UTF-8 on Windows so box-drawing / emoji render correctly.
if sys.platform == "win32":
    try:
        sys.stdout = io.TextIOWrapper(
            sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True
        )
    except AttributeError:
        pass  # already wrapped (e.g. pytest capture)


# ---------------------------------------------------------------------------
# ANSI escape codes (disabled on non-TTY or Windows without ANSI support)
# ---------------------------------------------------------------------------

def _ansi_supported() -> bool:
    """True if the terminal supports ANSI escape sequences."""
    if sys.platform == "win32":
        # Enable ANSI on Windows 10+ via virtual terminal processing
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
            return True
        except Exception:
            return False
    return hasattr(sys.stdout, 'isatty') and sys.stdout.isatty()


_USE_COLOR = _ansi_supported()

_RESET  = "\033[0m"   if _USE_COLOR else ""
_BOLD   = "\033[1m"   if _USE_COLOR else ""
_RED    = "\033[31m"  if _USE_COLOR else ""
_YELLOW = "\033[33m"  if _USE_COLOR else ""
_CYAN   = "\033[36m"  if _USE_COLOR else ""
_GREEN  = "\033[32m"  if _USE_COLOR else ""
_GREY   = "\033[90m"  if _USE_COLOR else ""
_WHITE  = "\033[97m"  if _USE_COLOR else ""


def _color_severity(sev: str) -> str:
    if sev == Severity.ERROR:
        return f"{_BOLD}{_RED}{sev}{_RESET}"
    elif sev == Severity.WARNING:
        return f"{_BOLD}{_YELLOW}{sev}{_RESET}"
    else:
        return f"{_CYAN}{sev}{_RESET}"


def _rule_tag(rule_id: str) -> str:
    return f"{_BOLD}{_WHITE}[{rule_id}]{_RESET}"


# ---------------------------------------------------------------------------
# Main print function
# ---------------------------------------------------------------------------

def print_report(result: ScanResult, show_summary: bool = True) -> None:
    """Print a formatted, severity-grouped report to stdout."""

    findings_by_file: dict = defaultdict(list)
    for f in result.findings:
        findings_by_file[f.file].append(f)

    # -----------------------------------------------------------------------
    # Header banner
    # -----------------------------------------------------------------------
    total = len(result.findings)
    n_errors   = result.count(Severity.ERROR)
    n_warnings = result.count(Severity.WARNING)
    n_info     = result.count(Severity.INFO)

    print()
    print(f"{_BOLD}{'═' * 72}{_RESET}")
    print(f"{_BOLD}  Hardware-Lint — Verilog/SystemVerilog Static Analyzer{_RESET}")
    print(f"{_BOLD}{'═' * 72}{_RESET}")
    print(f"  Scanned  : {len(result.files)} file(s)")
    print(f"  Findings : {_BOLD}{total}{_RESET}  "
          f"({_color_severity('ERROR')} {n_errors}  "
          f"{_color_severity('WARNING')} {n_warnings}  "
          f"{_color_severity('INFO')} {n_info})")
    print(f"  Time     : {result.elapsed:.2f}s")
    print()

    # -----------------------------------------------------------------------
    # Per-severity groups, then per-file
    # -----------------------------------------------------------------------
    for sev in (Severity.ERROR, Severity.WARNING, Severity.INFO):
        sev_findings = [f for f in result.findings if f.severity == sev]
        if not sev_findings:
            continue

        print(f"{_BOLD}{'─' * 72}{_RESET}")
        print(f"  {_color_severity(sev)} — {len(sev_findings)} finding(s)")
        print(f"{_BOLD}{'─' * 72}{_RESET}")

        by_file: dict = defaultdict(list)
        for f in sev_findings:
            by_file[f.file].append(f)

        for fpath, findings in sorted(by_file.items()):
            rel = os.path.relpath(fpath)
            print(f"\n  {_BOLD}{_GREEN}▶ {rel}{_RESET}")
            for f in sorted(findings, key=lambda x: x.line):
                loc  = f"{_GREY}{rel}:{f.line}{_RESET}"
                tag  = _rule_tag(f.rule_id)
                cat  = f"{_GREY}[{f.category}]{_RESET}"
                desc = f.description
                print(f"    {loc}  {tag} {cat}")
                print(f"      {_WHITE}{desc}{_RESET}")
                if f.snippet:
                    print(f"      {_GREY}> {f.snippet[:100]}{_RESET}")
                if f.suggestion:
                    print(f"      {_CYAN}✦ {f.suggestion}{_RESET}")
                print()

    # -----------------------------------------------------------------------
    # Parse / rule errors
    # -----------------------------------------------------------------------
    if result.errors:
        print(f"{_BOLD}{'─' * 72}{_RESET}")
        print(f"  {_BOLD}{_RED}Parse/Rule Errors:{_RESET}")
        for err in result.errors:
            print(f"  ✖ {err}")
        print()

    # -----------------------------------------------------------------------
    # Summary footer
    # -----------------------------------------------------------------------
    if show_summary:
        print(f"{_BOLD}{'═' * 72}{_RESET}")
        if n_errors == 0 and n_warnings == 0:
            print(f"  {_GREEN}{_BOLD}✔  No errors or warnings found.{_RESET}")
        elif n_errors > 0:
            print(f"  {_RED}{_BOLD}✖  {n_errors} error(s) require attention before tape-out.{_RESET}")
        else:
            print(f"  {_YELLOW}{_BOLD}⚠  {n_warnings} warning(s) — review before sign-off.{_RESET}")
        print(f"{_BOLD}{'═' * 72}{_RESET}")
        print()
