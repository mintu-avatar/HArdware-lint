"""
parser.py
=========
Lightweight Verilog/SystemVerilog parser using only Python's `re` module.

Goal: extract enough structural information for 40 lint rules without
implementing a full grammar — fast, dependency-free, pragmatic.

Extracted metadata (stored in ParseContext):
  - modules      : list of {name, start_line, end_line, ports_str}
  - always_blocks: list of {start_line, sensitivity, body_lines, block_type}
                   block_type ∈ {"clocked_posedge","clocked_negedge","combinational","unknown"}
  - assign_stmts : list of {line, lhs, rhs, full}
  - port_decls   : list of {line, direction, dtype, name, width}
  - signal_decls : list of {line, dtype, name, width}
  - instances    : list of {line, module_type, inst_name, connections}
  - parameters   : list of {line, name, value}
"""

from __future__ import annotations
import re
from typing import List, Tuple, Optional
from engine.rule_base import ParseContext


# ---------------------------------------------------------------------------
# Comment stripping helpers
# ---------------------------------------------------------------------------

_BLOCK_COMMENT_RE = re.compile(r'/\*.*?\*/', re.DOTALL)
_LINE_COMMENT_RE  = re.compile(r'//.*$', re.MULTILINE)
_STRING_LIT_RE    = re.compile(r'"[^"]*"')


def _strip_comments(source: str) -> str:
    """Remove // and /* */ comments; replace strings to avoid false matches."""
    source = _STRING_LIT_RE.sub('""', source)
    source = _BLOCK_COMMENT_RE.sub('', source)
    source = _LINE_COMMENT_RE.sub('', source)
    return source


def _clean_lines(raw_lines: List[str]) -> List[str]:
    """
    Strip single-line // comments from each line, preserving line count
    (so line numbers stay 1-based and aligned).
    """
    cleaned = []
    for ln in raw_lines:
        # remove string literals first, then strip comment
        ln2 = _STRING_LIT_RE.sub('""', ln)
        ln2 = _LINE_COMMENT_RE.sub('', ln2)
        cleaned.append(ln2)
    return cleaned


# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

# Module header — very permissive, captures name only
_MODULE_RE = re.compile(
    r'\bmodule\s+(\w+)\s*(?:#\s*\(.*?\))?\s*\(', re.DOTALL)

_ENDMODULE_RE = re.compile(r'\bendmodule\b')

# Port direction declarations (ANSI and non-ANSI style)
_PORT_DECL_RE = re.compile(
    r'\b(input|output|inout)\s+'
    r'(?:(wire|reg|logic)\s+)?'
    r'(?:(\[[\w\s\-\+\*/:\']+\])\s+)?'   # optional width
    r'(\w+)'
)

# Wire / reg / logic declarations (non-port)
_SIGNAL_DECL_RE = re.compile(
    r'\b(wire|reg|logic)\s+'
    r'(?:(\[[\w\s\-\+\*/:\']+\])\s+)?'
    r'(\w+)'
)

# Continuous assignment
_ASSIGN_RE = re.compile(
    r'\bassign\s+(\w+(?:\[[\w\s:\-]+\])?)\s*=\s*([^;]+);'
)

# always block sensitivity list  
_ALWAYS_RE = re.compile(
    r'\balways\s*@\s*\(([^)]*)\)'
)

# Parameter / localparam
_PARAM_RE = re.compile(
    r'\b(?:parameter|localparam)\s+(?:\w+\s+)?(\w+)\s*=\s*([^;,]+)'
)

# Module instantiation: ModName #(...) inst_name (...)  or  ModName inst_name (...)
_INST_RE = re.compile(
    r'\b([A-Z]\w*|[a-z]\w*)\s+(?:#\s*\([^)]*\)\s*)?(\w+)\s*\('
)

# Blocking assignment inside procedural block
_BLOCKING_RE    = re.compile(r'(?<![<!\=])=(?!=)')   # = but not <=, ==, !=
_NONBLOCKING_RE = re.compile(r'<=(?!=)')              # <= but not <==

# Sensitivity list helpers
_SEN_POSEDGE = re.compile(r'\bposedge\b')
_SEN_NEGEDGE = re.compile(r'\bnegedge\b')
_SEN_STAR    = re.compile(r'\*')

# Verilog-AMS analog block start; needed to scope analog behavioral statements.
_ANALOG_START_RE = re.compile(r'\banalog\b')

# Verilog-AMS discipline declaration; needed to validate domain typing of nets.
_DISCIPLINE_DECL_RE = re.compile(r'\bdiscipline\s+(\w+)\b')

# Verilog-AMS nature declaration; needed to track potential/flow unit definitions.
_NATURE_DECL_RE = re.compile(r'\bnature\s+(\w+)\b')

# Verilog-AMS discipline body bindings (domain/potential/flow/enddiscipline).
_DISCIPLINE_DOMAIN_RE = re.compile(r'\bdomain\s+(discrete|continuous)\b')
_DISCIPLINE_POTENTIAL_RE = re.compile(r'\bpotential\s+(\w+)\b')
_DISCIPLINE_FLOW_RE = re.compile(r'\bflow\s+(\w+)\b')
_ENDDISCIPLINE_RE = re.compile(r'\benddiscipline\b')

# Verilog-AMS branch declaration; needed to reason about branch-oriented contributions.
_BRANCH_DECL_RE = re.compile(r'\bbranch\s*\(\s*([^,\)]+)\s*(?:,\s*([^\)]+)\s*)?\)\s*(\w+)\s*;')

# Verilog-AMS contribution statement; captures V()/I() target and RHS expression.
_CONTRIB_RE = re.compile(r'\b([VI])\s*\(\s*([^\)]+)\s*\)\s*<\+\s*([^;]+);')

# Verilog-AMS analog operators/functions commonly associated with stability/convergence.
_AMS_KEYWORD_CALL_RE = re.compile(r'\b(ddt|idt|absdelay|transition|slew|cross)\s*\(')


# ---------------------------------------------------------------------------
# Block extractor — finds balanced begin/end or single-statement body
# ---------------------------------------------------------------------------

def _extract_block_lines(lines: List[str], start: int) -> Tuple[List[str], int]:
    """
    Given 0-based start index just after `always @(...)`, collect lines of
    the block body. Returns (body_lines_list, end_line_0based).
    Handles both `begin...end` and single-statement blocks.
    """
    body: List[str] = []
    i = start
    depth = 0
    found_begin = False
    n = len(lines)

    # If 'begin' was on the always @(...) line itself (previous line), account for it
    if start > 0:
        prev_line = lines[start - 1]
        prev_begin = len(re.findall(r'\bbegin\b', prev_line))
        if prev_begin > 0:
            found_begin = True
            depth = prev_begin

    while i < n:
        ln = lines[i]
        ln_stripped = ln.strip()

        # Count begin/end for depth tracking
        begin_count = len(re.findall(r'\bbegin\b', ln))
        end_count   = len(re.findall(r'\bend\b',   ln))

        if begin_count > 0 and not found_begin:
            found_begin = True

        depth += begin_count - end_count
        body.append(lines[i])

        if found_begin and depth <= 0:
            return body, i
        if not found_begin and ln_stripped.endswith(';'):
            # single-statement block
            return body, i
        i += 1

    return body, i - 1


# ---------------------------------------------------------------------------
# Main parser
# ---------------------------------------------------------------------------

class VerilogParser:
    """
    Parses a single Verilog file and populates a ParseContext.
    """

    def parse(self, filepath: str) -> ParseContext:
        with open(filepath, 'r', encoding='utf-8', errors='replace') as fh:
            source = fh.read()

        raw_lines   = source.splitlines()
        clean       = _clean_lines(raw_lines)
        clean_src   = '\n'.join(clean)

        ctx = ParseContext(
            filepath=filepath,
            lines=raw_lines,
            clean_lines=clean,
        )

        self._parse_parameters(clean, ctx)
        self._parse_modules(clean_src, clean, ctx)
        self._parse_ports(clean, ctx)
        self._parse_signals(clean, ctx)
        self._parse_assigns(clean, ctx)
        self._parse_always(clean, ctx)
        self._parse_instances(clean, ctx)
        self._parse_ams(clean, ctx)

        return ctx

    # ------------------------------------------------------------------
    def _parse_parameters(self, lines: List[str], ctx: ParseContext):
        for i, ln in enumerate(lines):
            for m in _PARAM_RE.finditer(ln):
                ctx.parameters.append({
                    'line':  i + 1,
                    'name':  m.group(1),
                    'value': m.group(2).strip(),
                })

    def _parse_modules(self, clean_src: str, lines: List[str], ctx: ParseContext):
        for m in _MODULE_RE.finditer(clean_src):
            start_char = m.start()
            start_line = clean_src[:start_char].count('\n') + 1
            # find endmodule after this position
            em = _ENDMODULE_RE.search(clean_src, m.end())
            end_line = clean_src[:em.start()].count('\n') + 1 if em else len(lines)
            ctx.modules.append({
                'name':       m.group(1),
                'start_line': start_line,
                'end_line':   end_line,
            })

    def _parse_ports(self, lines: List[str], ctx: ParseContext):
        for i, ln in enumerate(lines):
            for m in _PORT_DECL_RE.finditer(ln):
                ctx.port_decls.append({
                    'line':      i + 1,
                    'direction': m.group(1),
                    'dtype':     m.group(2) or 'wire',
                    'width':     m.group(3) or '[0:0]',
                    'name':      m.group(4),
                })

    def _parse_signals(self, lines: List[str], ctx: ParseContext):
        """Collect wire/reg/logic declarations that are NOT ports."""
        port_names = {p['name'] for p in ([] )}   # will be filled below
        for i, ln in enumerate(lines):
            # skip if line already has input/output/inout (port decl)
            if re.search(r'\b(input|output|inout)\b', ln):
                continue
            for m in _SIGNAL_DECL_RE.finditer(ln):
                ctx.signal_decls.append({
                    'line':  i + 1,
                    'dtype': m.group(1),
                    'width': m.group(2) or '[0:0]',
                    'name':  m.group(3),
                })

    def _parse_assigns(self, lines: List[str], ctx: ParseContext):
        for i, ln in enumerate(lines):
            for m in _ASSIGN_RE.finditer(ln):
                ctx.assign_stmts.append({
                    'line': i + 1,
                    'lhs':  m.group(1).strip(),
                    'rhs':  m.group(2).strip(),
                    'full': ln.strip(),
                })

    def _parse_always(self, lines: List[str], ctx: ParseContext):
        i = 0
        n = len(lines)
        while i < n:
            ln = lines[i]
            m = _ALWAYS_RE.search(ln)
            if m:
                sensitivity = m.group(1).strip()
                # Classify block type
                has_posedge = bool(_SEN_POSEDGE.search(sensitivity))
                has_negedge = bool(_SEN_NEGEDGE.search(sensitivity))
                has_star    = bool(_SEN_STAR.search(sensitivity))
                is_comb     = sensitivity.strip() == '*' or has_star

                if has_posedge:
                    btype = 'clocked_posedge'
                elif has_negedge:
                    btype = 'clocked_negedge'
                elif is_comb:
                    btype = 'combinational'
                else:
                    btype = 'unknown'   # explicit sensitivity list — potentially incomplete

                # Check if the entire always statement is on one line
                # e.g. always @(posedge clk) sig <= val;
                after_sens = ln[m.end():]
                if after_sens.strip().endswith(';') and 'begin' not in after_sens:
                    body_lines = [after_sens]
                    end_i = i
                else:
                    body_lines, end_i = _extract_block_lines(lines, i + 1)

                ctx.always_blocks.append({
                    'start_line':  i + 1,
                    'end_line':    end_i + 1,
                    'sensitivity': sensitivity,
                    'body_lines':  body_lines,
                    'block_type':  btype,
                    'raw_line':    ln,
                })
                i = end_i + 1
                continue
            i += 1

    def _parse_instances(self, lines: List[str], ctx: ParseContext):
        """
        Heuristic: ModName inst_name ( ... );
        Exclude keywords that match the pattern.
        """
        _KEYWORDS = {
            'module','endmodule','input','output','inout','wire',
            'reg','logic','always','assign','begin','end','if','else',
            'case','endcase','for','while','posedge','negedge','initial',
            'parameter','localparam','function','task','generate',
        }
        for i, ln in enumerate(lines):
            # only look at lines that contain an opening paren
            if '(' not in ln:
                continue
            for m in _INST_RE.finditer(ln):
                mod_type  = m.group(1)
                inst_name = m.group(2)
                if mod_type.lower() in _KEYWORDS or inst_name.lower() in _KEYWORDS:
                    continue
                # Collect connection string (rough — single line or multi?)
                conn_str = ln[m.end():]
                ctx.instances.append({
                    'line':        i + 1,
                    'module_type': mod_type,
                    'inst_name':   inst_name,
                    'conn_str':    conn_str,
                })

    def _parse_ams(self, lines: List[str], ctx: ParseContext):
        """Collect lightweight Verilog-AMS constructs for AMS-specific lint rules."""
        self._parse_analog_blocks(lines, ctx)
        self._parse_disciplines_and_natures(lines, ctx)
        self._parse_branches(lines, ctx)
        self._parse_contributions(lines, ctx)

    def _parse_analog_blocks(self, lines: List[str], ctx: ParseContext):
        """
        Extract analog block spans using begin/end depth when available,
        with a fallback for single-statement analog forms.
        """
        i = 0
        n = len(lines)
        while i < n:
            ln = lines[i]
            m = _ANALOG_START_RE.search(ln)
            if not m:
                i += 1
                continue

            after_kw = ln[m.end():]
            body_lines: List[str] = []
            start_line = i + 1
            end_i = i

            if re.search(r'\bbegin\b', after_kw):
                depth = len(re.findall(r'\bbegin\b', after_kw)) - len(re.findall(r'\bend\b', after_kw))
                j = i + 1
                while j < n:
                    cur = lines[j]
                    body_lines.append(cur)
                    depth += len(re.findall(r'\bbegin\b', cur))
                    depth -= len(re.findall(r'\bend\b', cur))
                    end_i = j
                    if depth <= 0:
                        break
                    j += 1
            else:
                if ';' in after_kw:
                    body_lines = [after_kw]
                    end_i = i
                else:
                    j = i + 1
                    while j < n:
                        cur = lines[j]
                        body_lines.append(cur)
                        end_i = j
                        if ';' in cur:
                            break
                        j += 1

            ctx.analog_blocks.append({
                'start_line': start_line,
                'end_line': end_i + 1,
                'body_lines': body_lines,
                'raw_line': ln,
            })
            i = end_i + 1

    def _parse_disciplines_and_natures(self, lines: List[str], ctx: ParseContext):
        """Parse discipline and nature declarations, including discipline bindings."""
        i = 0
        n = len(lines)
        while i < n:
            ln = lines[i]

            for m in _NATURE_DECL_RE.finditer(ln):
                ctx.natures.append({
                    'line': i + 1,
                    'name': m.group(1),
                })

            dm = _DISCIPLINE_DECL_RE.search(ln)
            if dm:
                disc_name = dm.group(1)
                domain = None
                potential = None
                flow = None
                end_i = i
                j = i
                while j < n:
                    cur = lines[j]
                    ddom = _DISCIPLINE_DOMAIN_RE.search(cur)
                    if ddom:
                        domain = ddom.group(1)
                    dpot = _DISCIPLINE_POTENTIAL_RE.search(cur)
                    if dpot:
                        potential = dpot.group(1)
                    dflow = _DISCIPLINE_FLOW_RE.search(cur)
                    if dflow:
                        flow = dflow.group(1)
                    end_i = j
                    if _ENDDISCIPLINE_RE.search(cur):
                        break
                    j += 1

                ctx.disciplines.append({
                    'line': i + 1,
                    'end_line': end_i + 1,
                    'name': disc_name,
                    'domain': domain,
                    'potential': potential,
                    'flow': flow,
                })
                i = end_i + 1
                continue

            i += 1

    def _parse_branches(self, lines: List[str], ctx: ParseContext):
        """Collect branch declarations of the form: branch(node_p, node_n) br;"""
        for i, ln in enumerate(lines):
            for m in _BRANCH_DECL_RE.finditer(ln):
                ctx.branches.append({
                    'line': i + 1,
                    'pos': m.group(1).strip(),
                    'neg': (m.group(2) or '').strip(),
                    'name': m.group(3).strip(),
                })

    def _parse_contributions(self, lines: List[str], ctx: ParseContext):
        """Collect contribution statements and AMS keyword invocations."""
        for i, ln in enumerate(lines):
            for m in _CONTRIB_RE.finditer(ln):
                ctx.contributions.append({
                    'line': i + 1,
                    'kind': m.group(1),
                    'target': m.group(2).strip(),
                    'expr': m.group(3).strip(),
                })
            for m in _AMS_KEYWORD_CALL_RE.finditer(ln):
                ctx.ams_keywords.append({
                    'line': i + 1,
                    'keyword': m.group(1),
                })
