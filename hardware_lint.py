#!/usr/bin/env python3
"""
hardware_lint.py
================
Main CLI entry point for the Hardware-Lint Verilog/SV static analyzer.

Usage
-----
  python hardware_lint.py <path> [options]

Arguments
  path                File (.v/.sv) or directory to scan recursively

Options
  --severity LEVEL    Minimum severity to report: ERROR | WARNING | INFO  (default: INFO)
  --json PATH         Also write a JSON report to PATH
  --no-color          Disable ANSI color output
  --rules             List all registered rules and exit
  --help / -h         Show this help and exit

Examples
  python hardware_lint.py rtl/
  python hardware_lint.py top.v --severity WARNING --json report.json
  python hardware_lint.py rtl/ --rules
"""

from __future__ import annotations
import argparse
import sys
import os


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="hardware_lint",
        description="Verilog/SystemVerilog HDL static analysis engine",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("path", nargs="?", help="File or directory to scan")
    p.add_argument(
        "--severity",
        choices=["ERROR", "WARNING", "INFO"],
        default="INFO",
        help="Minimum severity level to report (default: INFO)",
    )
    p.add_argument(
        "--json",
        metavar="PATH",
        help="Write JSON report to this path",
    )
    p.add_argument(
        "--no-color",
        action="store_true",
        help="Disable ANSI color in CLI output",
    )
    p.add_argument(
        "--rules",
        action="store_true",
        help="List all registered rules and exit",
    )
    return p


def _list_rules() -> None:
    """Print a formatted table of all registered rules."""
    # Import all rule modules so decorators run
    import rules.style, rules.synthesis, rules.assignments
    import rules.latch, rules.cdc, rules.reset, rules.fsm
    import rules.ports, rules.timing, rules.testability
    import rules.reliability, rules.maintainability
    import rules.security, rules.cognitive
    import rules.power, rules.reset_integrity, rules.reusability
    import rules.structural_complexity, rules.verifiability
    import rules.clock_domain, rules.timing_complexity
    from engine.rule_base import get_all_rules, Severity

    all_rules = get_all_rules()
    _SEV_COLOR = {
        Severity.ERROR:   "\033[1;31m",
        Severity.WARNING: "\033[1;33m",
        Severity.INFO:    "\033[36m",
    }
    _RESET = "\033[0m"

    print(f"\n{'─'*80}")
    print(f"  {'ID':<10} {'SEV':<9} {'CATEGORY':<16} DESCRIPTION")
    print(f"{'─'*80}")
    for r in all_rules:
        sc = _SEV_COLOR.get(r.severity, "")
        print(f"  {r.rule_id:<10} {sc}{r.severity:<9}{_RESET} {r.category:<16} {r.description}")
    print(f"{'─'*80}")
    print(f"  Total: {len(all_rules)} rules\n")


def main(argv=None):
    parser = _build_parser()
    args   = parser.parse_args(argv)

    # --rules flag: just list rules and exit
    if args.rules:
        _list_rules()
        sys.exit(0)

    if not args.path:
        parser.print_help()
        sys.exit(1)

    if not os.path.exists(args.path):
        print(f"ERROR: path not found: {args.path}", file=sys.stderr)
        sys.exit(2)

    # Disable color if requested
    if args.no_color:
        import reporter.cli as _cli_mod
        for attr in ['_RESET','_BOLD','_RED','_YELLOW','_CYAN',
                     '_GREEN','_GREY','_WHITE']:
            setattr(_cli_mod, attr, "")

    # Run scan
    from engine.scanner      import scan
    from reporter.cli        import print_report
    from reporter.json_report import write_json

    result = scan(args.path, severity_filter=args.severity)
    print_report(result)

    if args.json:
        write_json(result, args.json)

    # Exit code: 0=clean, 1=warnings, 2=errors
    from engine.rule_base import Severity
    if result.count(Severity.ERROR) > 0:
        sys.exit(2)
    elif result.count(Severity.WARNING) > 0:
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
