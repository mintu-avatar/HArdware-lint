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
