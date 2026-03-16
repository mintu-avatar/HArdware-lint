# Hardware-Lint: Verilog/SystemVerilog HDL Static Analyzer

A SonarQube-style static analysis engine for RTL design code — catches synthesis hazards, CDC issues, latch inference risks, FSM bugs, security vulnerabilities, cognitive complexity, maintainability smells, power-awareness gaps, reset integrity, reusability, structural complexity, verifiability, clock-domain complexity, and timing issues **before** simulation or synthesis.

---

## Quick Start

```bash
# Scan a single file
python hardware_lint.py path/to/design.v

# Scan a full RTL directory recursively
python hardware_lint.py rtl/src/

# Only report errors and warnings (suppress INFO)
python hardware_lint.py rtl/ --severity WARNING

# Also produce a JSON report for CI/dashboard integration
python hardware_lint.py rtl/ --json report.json

# List all 95 registered rules
python hardware_lint.py --rules
```

### Exit Codes
| Code | Meaning |
|------|---------|
| 0 | Clean — no errors or warnings |
| 1 | Warnings found |
| 2 | Errors found (requires attention before tape-out) |

---

## Project Structure

```
Hardware-lint/
├── hardware_lint.py          # CLI entry point
├── engine/
│   ├── rule_base.py          # RuleBase class, Finding dataclass, registry
│   ├── parser.py             # Lightweight regex-based Verilog parser
│   └── scanner.py            # Orchestrator: parse → rules → findings
├── rules/
│   ├── style.py              # VLG001–VLG005  (Coding style)
│   ├── synthesis.py          # VLG006–VLG012  (Synthesis safety)
│   ├── assignments.py        # VLG013–VLG015  (Blocking vs non-blocking)
│   ├── latch.py              # VLG016–VLG018  (Latch inference)
│   ├── cdc.py                # VLG019–VLG022  (Clock domain crossing)
│   ├── reset.py              # VLG023–VLG026  (Reset strategy)
│   ├── fsm.py                # VLG027–VLG030  (FSM design quality)
│   ├── ports.py              # VLG031–VLG034  (Port hygiene)
│   ├── timing.py             # VLG035–VLG037  (Timing / comb loops)
│   ├── testability.py        # VLG038–VLG040  (DFT / observability)
│   ├── reliability.py        # VLG041–VLG045  (Reliability / robustness)
│   ├── maintainability.py    # VLG046–VLG050  (Maintainability / code health)
│   ├── security.py           # VLG051–VLG055  (Hardware security)
│   ├── cognitive.py          # VLG056–VLG060  (Cognitive complexity)
│   ├── power.py              # VLG061–VLG065  (Power awareness)
│   ├── reset_integrity.py    # VLG066–VLG070  (Reset integrity)
│   ├── reusability.py        # VLG071–VLG075  (Reusability)
│   ├── structural_complexity.py # VLG076–VLG080 (Structural complexity)
│   ├── verifiability.py      # VLG081–VLG085  (Verifiability / testability)
│   ├── clock_domain.py       # VLG086–VLG090  (Clock domain complexity)
│   └── timing_complexity.py  # VLG091–VLG095  (Timing complexity)
├── reporter/
│   ├── cli.py                # Colored terminal output
│   └── json_report.py        # Machine-readable JSON output
└── samples/
    ├── bad_fifo.v             # Intentionally buggy FIFO
    ├── uart_tx.v              # UART TX with CDC + FSM + reset issues
    ├── cdc_hazards.v          # CDC anti-pattern showcase
    ├── good_counter.v         # Clean RTL (minimal lint findings)
    ├── security_ctrl.v        # Security controller (triggers VLG041–VLG060)
    ├── power_timing_sample.v  # Multi-module sample (triggers VLG061–VLG095)
    └── report.json            # Example JSON report output
```

---

## Rule Catalog (95 Rules)

### Coding Style & Readability
| Rule | Sev | Description |
|------|-----|-------------|
| VLG001 | INFO | Module has no preceding comment block |
| VLG002 | WARNING | Magic number in port/signal width — use named parameter |
| VLG003 | INFO | Signal name doesn't follow prefix convention (i_/o_/r_/w_) |
| VLG004 | WARNING | Port declared without explicit direction |
| VLG005 | INFO | Line exceeds 120 characters |

### Synthesis Safety
| Rule | Sev | Description |
|------|-----|-------------|
| VLG006 | **ERROR** | `initial` block in RTL — not synthesizable |
| VLG007 | **ERROR** | `#delay` in RTL — simulation-only, causes sim/synth mismatch |
| VLG008 | WARNING | `casex`/`casez` — X/Z wildcard can mask bugs |
| VLG009 | **ERROR** | Explicit sensitivity list in combinational block — may be incomplete |
| VLG010 | WARNING | `force`/`release` statements — simulation-only |
| VLG011 | **ERROR** | `$display`/`$monitor`/`$finish` in RTL — not synthesizable |
| VLG012 | WARNING | `1'bz` assigned without explicit tri-state enable |

### Blocking vs Non-Blocking Assignments
| Rule | Sev | Description |
|------|-----|-------------|
| VLG013 | **ERROR** | Blocking `=` in clocked always block — use `<=` for FFs |
| VLG014 | **ERROR** | Non-blocking `<=` in combinational always block — use `=` |
| VLG015 | WARNING | Mixed blocking and non-blocking in same always block |

### Latch Inference
| Rule | Sev | Description |
|------|-----|-------------|
| VLG016 | **ERROR** | `if` without `else` in combinational block — latch inferred |
| VLG017 | **ERROR** | `case` without `default` in combinational block — latch inferred |
| VLG018 | WARNING | Signal not assigned on all paths — possible latch |

### Clock Domain Crossing (CDC)
| Rule | Sev | Description |
|------|-----|-------------|
| VLG019 | **ERROR** | Multi-bit signal crosses clock domains without synchronizer |
| VLG020 | WARNING | Single-bit CDC without double-flop synchronizer |
| VLG021 | WARNING | Clock signal used as data in logic expression |
| VLG022 | **ERROR** | Combinational logic on clock path — gated clock glitch risk |

### Reset Strategy
| Rule | Sev | Description |
|------|-----|-------------|
| VLG023 | WARNING | Mixed synchronous and asynchronous reset in same module |
| VLG024 | **ERROR** | Async reset pattern inconsistent across module blocks |
| VLG025 | WARNING | Active-high (rst) and active-low (rst_n) both used in same module |
| VLG026 | INFO | Clocked block has no reset — FF powers up in unknown state |

### FSM Design Quality
| Rule | Sev | Description |
|------|-----|-------------|
| VLG027 | WARNING | FSM `case` has no `default` — unreachable state lockup risk |
| VLG028 | WARNING | FSM with >6 states not using one-hot encoding |
| VLG029 | **ERROR** | FSM state assigned with `=` in combinational block |
| VLG030 | WARNING | FSM outputs decoded combinationally — glitch risk |

### Port Hygiene
| Rule | Sev | Description |
|------|-----|-------------|
| VLG031 | WARNING | Output port never driven inside module |
| VLG032 | **ERROR** | Input port left unconnected in submodule instantiation |
| VLG033 | WARNING | `` `default_nettype none `` not set — implicit net risk |
| VLG034 | INFO | Positional port connections used — use named connections |

### Timing & Combinational Loops
| Rule | Sev | Description |
|------|-----|-------------|
| VLG035 | **ERROR** | Combinational feedback loop — signal drives itself |
| VLG036 | WARNING | Deeply nested ternary operators (>4 levels) — timing risk |
| VLG037 | WARNING | `assign` drives a `reg`-declared signal — use `wire` |

### Testability & Observability
| Rule | Sev | Description |
|------|-----|-------------|
| VLG038 | WARNING | Sequential module lacks scan-enable port (DFT gap) |
| VLG039 | INFO | `$random`/`$urandom` in RTL — testbench-only construct |
| VLG040 | WARNING | Signal with fan-out >16 — may need buffer tree |

### Reliability & Robustness *(not flagged by Vivado/Quartus)*
| Rule | Sev | Description |
|------|-----|-------------|
| VLG041 | WARNING | FSM has no timeout / watchdog — stuck-state lockup risk |
| VLG042 | INFO | Unregistered module output — glitch & timing fragility |
| VLG043 | WARNING | Width mismatch (≥4 bits) in comparison — implicit extension risk |
| VLG044 | **ERROR** | Shift amount ≥ signal width — result always zero |
| VLG045 | WARNING | Clock-enable feedback — CE depends on own output, livelock risk |

### Maintainability & Code Health *(not flagged by any HDL tool)*
| Rule | Sev | Description |
|------|-----|-------------|
| VLG046 | INFO | Module exceeds 300 SLOC — decompose into sub-modules |
| VLG047 | INFO | Module has >20 ports — "god-module" smell |
| VLG048 | WARNING | Control flow nested >3 levels — hard to review and verify |
| VLG049 | INFO | Module has >10 always blocks — split for signal traceability |
| VLG050 | INFO | Same magic constant used >3 times — extract to parameter |

### Hardware Security *(CWE-mapped, unique to this tool)*
| Rule | Sev | Description |
|------|-----|-------------|
| VLG051 | WARNING | Memory array never cleared on reset — stale-data leak (CWE-1239) |
| VLG052 | WARNING | Debug/JTAG port in production RTL — attack surface (CWE-1191) |
| VLG053 | **ERROR** | Sensitive register not zeroed on reset — data remanence (CWE-1272) |
| VLG054 | **ERROR** | Hardcoded key/credential in RTL — use OTP/eFuse (CWE-321) |
| VLG055 | **ERROR** | Security signal driven combinationally — glitch-fault bypass risk |

### Cognitive Complexity *(not flagged by any HDL tool)*
| Rule | Sev | Description |
|------|-----|-------------|
| VLG056 | INFO | Case statement has >12 branches — consider ROM/LUT decode |
| VLG057 | WARNING | Complex boolean expression (>4 operators) — split into named wires |
| VLG058 | WARNING | Chained ternary (>2 deep) — use case statement instead |
| VLG059 | WARNING | File contains multiple modules — one module per file |
| VLG060 | INFO | Mixed behavioral + structural styles in one module |

### Power Awareness *(unique to this tool)*
| Rule | Sev | Description |
|------|-----|-------------|
| VLG061 | WARNING | No clock gating — always-on clock wastes dynamic power |
| VLG062 | INFO | Wide bus updated every cycle without enable guard |
| VLG063 | INFO | No power-down / sleep signal in module |
| VLG064 | WARNING | Memory array without chip-enable — always active |
| VLG065 | INFO | Redundant toggling — same value in both if/else branches |

### Reset Integrity
| Rule | Sev | Description |
|------|-----|-------------|
| VLG066 | WARNING | Inconsistent reset polarity — mixed active-high and active-low |
| VLG067 | **ERROR** | Incomplete reset — not all FFs initialized in reset branch |
| VLG068 | WARNING | Async reset without synchronizer — metastability risk |
| VLG069 | WARNING | Reset signal used as data in normal logic path |
| VLG070 | WARNING | Sequential block has no reset — control signals start unknown |

### Reusability
| Rule | Sev | Description |
|------|-----|-------------|
| VLG071 | INFO | Hardcoded bus width (>7 bits) — use parameters for reuse |
| VLG072 | WARNING | Module depends on `` `define `` — tightly coupled to globals |
| VLG073 | INFO | Instance without parameter override — missed customization |
| VLG074 | INFO | Inconsistent port naming — mixed prefix styles |
| VLG075 | WARNING | Generate block without label — hard to reference in hierarchy |

### Structural Complexity *(RTL Cyclomatic Complexity)*
| Rule | Sev | Description |
|------|-----|-------------|
| VLG076 | WARNING | RTL cyclomatic complexity >15 — decompose always block |
| VLG077 | WARNING | Deep if/else-if chain >6 levels — priority encode instead |
| VLG078 | INFO | High fan-in — single assignment depends on >8 signals |
| VLG079 | INFO | High interconnect ratio — internal signals >5× port count |
| VLG080 | WARNING | Always block with >5 decision constructs |

### Verifiability / Testability
| Rule | Sev | Description |
|------|-----|-------------|
| VLG081 | INFO | No assertion / coverage hooks in module |
| VLG082 | INFO | FSM state register not observable at output ports |
| VLG083 | INFO | Large combinational cone — reads >10 signals |
| VLG084 | WARNING | Handshake port without back-pressure logic |
| VLG085 | INFO | Dead signal — assigned but never read in module |

### Clock Domain Complexity
| Rule | Sev | Description |
|------|-----|-------------|
| VLG086 | WARNING | Multiple clock domains in one module |
| VLG087 | **ERROR** | Clock signal used as data in logic assignment |
| VLG088 | WARNING | Generated clock without SDC constraint hint |
| VLG089 | **ERROR** | Clock mux without glitch protection |
| VLG090 | WARNING | Clock derived from counter bit — jitter & skew risk |

### Timing Complexity
| Rule | Sev | Description |
|------|-----|-------------|
| VLG091 | WARNING | Long combinational chain (>6 operators) — timing risk |
| VLG092 | WARNING | Latch mixed with flip-flops — inconsistent timing model |
| VLG093 | **ERROR** | Combinational feedback — signal drives itself |
| VLG094 | INFO | Wide mux (>8 branches, ≥16-bit output) — routing congestion |
| VLG095 | INFO | Wide arithmetic (≥16-bit) without pipeline stage |

---

## JSON Report Schema

```json
{
  "metadata": {
    "scanned_files": ["path/to/file.v"],
    "elapsed_s": 0.012,
    "total_findings": 71
  },
  "summary": { "ERROR": 13, "WARNING": 32, "INFO": 26 },
  "findings": [
    {
      "file": "samples/bad_fifo.v",
      "line": 31,
      "rule_id": "VLG006",
      "severity": "ERROR",
      "category": "Synthesis",
      "description": "'initial' block found — not synthesizable",
      "snippet": "initial begin",
      "suggestion": "Remove 'initial' block from RTL. Use reset logic..."
    }
  ],
  "errors": []
}
```

---

## Adding New Rules

1. Create or open a file in `rules/`
2. Subclass `RuleBase` and decorate with `@register_rule`:

```python
from engine.rule_base import RuleBase, Severity, ParseContext, register_rule, Finding

@register_rule
class VLG096(RuleBase):
    rule_id     = "VLG096"
    category    = "Style"
    severity    = Severity.WARNING
    description = "My new rule description"

    def check(self, ctx: ParseContext):
        findings = []
        for i, ln in enumerate(ctx.clean_lines):
            if "bad_pattern" in ln:
                findings.append(self._finding(ctx, i + 1,
                    suggestion="Do this instead..."))
        return findings
```

3. Import your module in `engine/scanner.py` — the rule is live.

---

## Requirements

- Python 3.10+
- No external dependencies (stdlib only)
#   H A r d w a r e - l i n t  
 