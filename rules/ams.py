"""
rules/ams.py — Verilog-AMS lint rules
======================================
VLG096–VLG113 (AMS category)
"""

from __future__ import annotations
import re
from typing import Dict, List, Set
from engine.rule_base import RuleBase, Severity, Finding, ParseContext, register_rule


_DISCIPLINE_NETS_RE = re.compile(
    r'\b(electrical|thermal|magnetic|kinematic|rotational)\b\s+([^;]+);',
    re.IGNORECASE,
)
_CONTRIB_TARGET_RE = re.compile(r'\b[VI]\s*\(\s*([^\)]+)\s*\)\s*<\+')
_BRANCH_RE = re.compile(r'\bbranch\s*\([^\)]*\)\s*(\w+)\s*;')


def _extract_target_nets(target_text: str) -> List[str]:
    nets = []
    for raw in target_text.split(','):
        net = raw.strip()
        if net and net != '0':
            nets.append(net)
    return nets


def _count_call_args(line: str, fn_name: str) -> int:
    m = re.search(rf'\b{fn_name}\s*\(([^\)]*)\)', line)
    if not m:
        return 0
    inside = m.group(1).strip()
    if not inside:
        return 0
    return len([x for x in inside.split(',') if x.strip()])


def _collect_discipline_net_map(lines: List[str]) -> Dict[str, Set[str]]:
    net_map: Dict[str, Set[str]] = {}
    for ln in lines:
        m = _DISCIPLINE_NETS_RE.search(ln)
        if m:
            disc = m.group(1).lower()
            for token in m.group(2).split(','):
                name = token.strip()
                if name:
                    net_map.setdefault(name, set()).add(disc)
    return net_map


@register_rule
class VLG096(RuleBase):
    """
    VLG096 — Unsmoothed Analog Contribution
    Category : Analog Signal Integrity
    Severity : WARNING

    Why it matters:
        Abrupt piecewise analog contributions inject discontinuities into the
        solver Jacobian and increase Newton iteration failures.

    Example trigger:
        analog begin
            V(out) <+ (en ? vin : 0.0);
        end

    Suggestion:
        Wrap abrupt value jumps with transition(...) or slew(...) to smooth edges.
    """
    rule_id = "VLG096"
    category = "AMS"
    severity = Severity.WARNING
    description = "Contribution uses abrupt analog jump without transition/slew smoothing"

    def check(self, ctx: ParseContext):
        findings = []
        for i, ln in enumerate(ctx.clean_lines):
            # WHAT: Detects direct V()/I() contributions that do not use smoothing operators.
            # WHY: Abrupt discontinuities make analog solvers struggle near switching edges.
            # CONSEQUENCE: Causes signal discontinuity artifacts and convergence instability.
            if '<+' in ln and re.search(r'\b[VI]\s*\(', ln) and not re.search(r'\b(transition|slew)\s*\(', ln):
                findings.append(self._finding(ctx, i + 1, suggestion="Use transition(...) or slew(...) on abrupt contribution edges."))
        return findings


@register_rule
class VLG097(RuleBase):
    """
    VLG097 — Cross Event Without Tolerance
    Category : Analog Signal Integrity
    Severity : WARNING

    Why it matters:
        cross() without explicit hysteresis/tolerance can fire repeatedly on
        noise, causing event chatter and unstable mixed-signal behavior.

    Example trigger:
        @(cross(V(in)-vth, +1)) d = 1'b1;

    Suggestion:
        Provide additional cross() tolerance arguments suitable for noise levels.
    """
    rule_id = "VLG097"
    category = "AMS"
    severity = Severity.WARNING
    description = "cross() call is missing tolerance/hysteresis arguments"

    def check(self, ctx: ParseContext):
        findings = []
        for i, ln in enumerate(ctx.clean_lines):
            # WHAT: Detects any cross(...) usage, then checks argument count.
            # WHY: Minimal-argument cross calls are often too sensitive to analog noise.
            # CONSEQUENCE: Leads to repeated false edge triggers and unstable state updates.
            if 'cross(' in ln:
                argc = _count_call_args(ln, 'cross')
                # WHAT: Flags cross() with fewer than three arguments.
                # WHY: Missing tolerance/hysteresis weakens event robustness.
                # CONSEQUENCE: Produces event chattering and metastable digital handoff.
                if argc < 3:
                    findings.append(self._finding(ctx, i + 1, suggestion="Use cross(expr, dir, tol[, abstol]) with meaningful tolerance."))
        return findings


@register_rule
class VLG098(RuleBase):
    """
    VLG098 — Integrator Without Initial Condition
    Category : Analog Signal Integrity
    Severity : WARNING

    Why it matters:
        idt() without an explicit initial condition can drift from unknown startup
        state and produce non-repeatable analog behavior across simulations.

    Example trigger:
        I(out) <+ idt(vin);

    Suggestion:
        Use idt(signal, ic) or reset-gated integrator state initialization.
    """
    rule_id = "VLG098"
    category = "AMS"
    severity = Severity.WARNING
    description = "idt() integrator appears without explicit initial condition"

    def check(self, ctx: ParseContext):
        findings = []
        single_arg_idt = re.compile(r'\bidt\s*\(\s*[^,\)]+\s*\)')
        for i, ln in enumerate(ctx.clean_lines):
            # WHAT: Detects contribution expressions that call idt() with one argument only.
            # WHY: Integrators without IC rely on simulator defaults and hidden state behavior.
            # CONSEQUENCE: Causes startup drift, state ambiguity, and correlation failures.
            if '<+' in ln and single_arg_idt.search(ln):
                findings.append(self._finding(ctx, i + 1, suggestion="Use idt(input, ic) and define reset/startup behavior explicitly."))
        return findings


@register_rule
class VLG099(RuleBase):
    """
    VLG099 — Undeclared Analog Net In Access Function
    Category : Discipline & Nature Compliance
    Severity : WARNING

    Why it matters:
        V(net) or I(net) on undeclared nets bypasses discipline checks and hides
        physical-domain intent from both simulator and reviewers.

    Example trigger:
        V(vsense) <+ gain * V(in);

    Suggestion:
        Declare each analog net with an explicit discipline (e.g., electrical).
    """
    rule_id = "VLG099"
    category = "AMS"
    severity = Severity.WARNING
    description = "V()/I() accesses net that lacks explicit discipline declaration"

    def check(self, ctx: ParseContext):
        findings = []
        net_map = _collect_discipline_net_map(ctx.clean_lines)
        declared = set(net_map.keys())
        for i, ln in enumerate(ctx.clean_lines):
            m = _CONTRIB_TARGET_RE.search(ln)
            # WHAT: Finds contribution statements with V()/I() net targets.
            # WHY: Target nets should be physically typed through discipline declarations.
            # CONSEQUENCE: Missing typing leads to domain ambiguity and model misuse.
            if m:
                for net in _extract_target_nets(m.group(1)):
                    # WHAT: Flags each target net that does not appear in discipline declarations.
                    # WHY: Untyped nets skip discipline/nature consistency enforcement.
                    # CONSEQUENCE: Can create invalid analog equations and hidden connection bugs.
                    if net not in declared:
                        findings.append(self._finding(ctx, i + 1, suggestion=f"Declare '{net}' with an explicit discipline (for example: electrical {net};)."))
                        break
        return findings


@register_rule
class VLG100(RuleBase):
    """
    VLG100 — Incomplete Discipline Definition
    Category : Discipline & Nature Compliance
    Severity : WARNING

    Why it matters:
        Custom disciplines require both potential and flow bindings to natures;
        incomplete definitions break consistency of constitutive equations.

    Example trigger:
        discipline thermal_sig
            potential temperature;
        enddiscipline

    Suggestion:
        Provide both potential and flow nature mappings in discipline blocks.
    """
    rule_id = "VLG100"
    category = "AMS"
    severity = Severity.WARNING
    description = "Discipline declaration is missing potential or flow nature binding"

    def check(self, ctx: ParseContext):
        findings = []
        for i, ln in enumerate(ctx.clean_lines):
            for disc in ctx.disciplines:
                # WHAT: Matches the source line where a discipline definition starts.
                # WHY: Validation should report exactly at the declaration site.
                # CONSEQUENCE: Incomplete discipline typing propagates modeling inconsistencies.
                if disc.get('line') == i + 1:
                    # WHAT: Checks whether potential/flow entries are both present.
                    # WHY: Both quantities are required for physically complete discipline semantics.
                    # CONSEQUENCE: Missing fields lead to invalid or partial analog behavior models.
                    if not disc.get('potential') or not disc.get('flow'):
                        findings.append(self._finding(ctx, i + 1, suggestion="Add both 'potential <nature>' and 'flow <nature>' in this discipline."))
        return findings


@register_rule
class VLG101(RuleBase):
    """
    VLG101 — Net Declared With Multiple Disciplines
    Category : Discipline & Nature Compliance
    Severity : WARNING

    Why it matters:
        A single node mapped to multiple physical disciplines introduces
        ambiguous semantics and unpredictable analog solver interpretation.

    Example trigger:
        electrical n1;
        thermal n1;

    Suggestion:
        Keep one discipline per net or use explicit connect modeling.
    """
    rule_id = "VLG101"
    category = "AMS"
    severity = Severity.WARNING
    description = "Same net is declared under multiple disciplines"

    def check(self, ctx: ParseContext):
        findings = []
        net_map = _collect_discipline_net_map(ctx.clean_lines)
        for i, ln in enumerate(ctx.clean_lines):
            m = _DISCIPLINE_NETS_RE.search(ln)
            # WHAT: Looks for discipline-based net declaration lines.
            # WHY: Multi-discipline assignments are introduced at declaration points.
            # CONSEQUENCE: Conflicting domain semantics can break connect resolution.
            if m:
                for token in m.group(2).split(','):
                    net = token.strip()
                    # WHAT: Flags nets associated with more than one discipline.
                    # WHY: A net should represent one physical domain unless bridged explicitly.
                    # CONSEQUENCE: Causes analog/digital interface ambiguity and simulation mismatch.
                    if net and len(net_map.get(net, set())) > 1:
                        findings.append(self._finding(ctx, i + 1, suggestion=f"Use one discipline for '{net}' or introduce explicit connect behavior."))
                        break
        return findings


@register_rule
class VLG102(RuleBase):
    """
    VLG102 — Unterminated Contribution Statement
    Category : Contribution Statement Safety
    Severity : ERROR

    Why it matters:
        Contribution equations must terminate cleanly for the analog parser;
        unterminated statements corrupt subsequent equation interpretation.

    Example trigger:
        I(out) <+ gm * V(in)

    Suggestion:
        End every contribution statement with a semicolon.
    """
    rule_id = "VLG102"
    category = "AMS"
    severity = Severity.ERROR
    description = "Contribution statement appears without terminating semicolon"

    def check(self, ctx: ParseContext):
        findings = []
        for i, ln in enumerate(ctx.clean_lines):
            # WHAT: Detects lines containing contribution operator '<+'.
            # WHY: Contribution equations are syntax-critical and must be terminated.
            # CONSEQUENCE: Missing terminators trigger parser or equation-assembly failures.
            if '<+' in ln and ';' not in ln:
                findings.append(self._finding(ctx, i + 1, suggestion="Terminate this contribution with ';' to keep equations well-formed."))
        return findings


@register_rule
class VLG103(RuleBase):
    """
    VLG103 — Conflicting Voltage/Current Contributions
    Category : Contribution Statement Safety
    Severity : WARNING

    Why it matters:
        Driving both V(target) and I(target) on the same target can over-constrain
        the analog system unless done with careful physical intent.

    Example trigger:
        V(br) <+ 1.2;
        I(br) <+ 5u;

    Suggestion:
        Use a consistent source model and avoid contradictory dual driving.
    """
    rule_id = "VLG103"
    category = "AMS"
    severity = Severity.WARNING
    description = "Same target receives both V() and I() contributions"

    def check(self, ctx: ParseContext):
        findings = []
        target_kinds: Dict[str, Set[str]] = {}
        for c in ctx.contributions:
            target_kinds.setdefault(c['target'], set()).add(c['kind'])
        for i, ln in enumerate(ctx.clean_lines):
            m = re.search(r'\b([VI])\s*\(\s*([^\)]+)\s*\)\s*<\+', ln)
            # WHAT: Locates contribution lines and resolves their target identifier.
            # WHY: Conflicts can only be evaluated after grouping by the same target.
            # CONSEQUENCE: Conflicting drives over-constrain equations and destabilize solves.
            if m:
                target = m.group(2).strip()
                # WHAT: Flags targets that are driven by both V and I contributions.
                # WHY: Simultaneous ideal constraints can be physically contradictory.
                # CONSEQUENCE: Generates singular matrices or non-physical simulation results.
                if len(target_kinds.get(target, set())) > 1:
                    findings.append(self._finding(ctx, i + 1, suggestion=f"Avoid mixing V() and I() ideal contributions on '{target}' unless explicitly modeled."))
        return findings


@register_rule
class VLG104(RuleBase):
    """
    VLG104 — Procedural Control Around Contribution
    Category : Contribution Statement Safety
    Severity : WARNING

    Why it matters:
        Embedding contributions directly in procedural-style control flow often
        creates discontinuous topology changes and fragile analog equations.

    Example trigger:
        if (mode) I(out) <+ 1m;

    Suggestion:
        Prefer smooth analog equations and continuous blending functions.
    """
    rule_id = "VLG104"
    category = "AMS"
    severity = Severity.WARNING
    description = "Contribution appears inside procedural control construct"

    def check(self, ctx: ParseContext):
        findings = []
        ctrl_re = re.compile(r'\b(if|for|while|repeat|case)\b')
        for i, ln in enumerate(ctx.clean_lines):
            # WHAT: Detects contributions that share a line with control-flow keywords.
            # WHY: Hard control branching around equations produces abrupt topology changes.
            # CONSEQUENCE: Leads to convergence failures and inconsistent transient behavior.
            if '<+' in ln and ctrl_re.search(ln):
                findings.append(self._finding(ctx, i + 1, suggestion="Restructure with smooth conditional blending instead of direct procedural gating."))
        return findings


@register_rule
class VLG105(RuleBase):
    """
    VLG105 — Digital Net Used In Analog Access
    Category : Analog-Digital Interface
    Severity : WARNING

    Why it matters:
        Referencing logic/reg signals directly inside V()/I() analog access
        blurs domain boundaries and can create invalid mixed-domain semantics.

    Example trigger:
        V(ctrl_logic) <+ 1.0;

    Suggestion:
        Bridge through proper connect modeling or real-valued interface logic.
    """
    rule_id = "VLG105"
    category = "AMS"
    severity = Severity.WARNING
    description = "V()/I() references a signal declared as logic/reg"

    def check(self, ctx: ParseContext):
        findings = []
        digital_nets: Set[str] = set()
        for p in ctx.port_decls:
            # WHAT: Collects port declarations that are explicitly typed as logic/reg.
            # WHY: These names represent digital-domain signals at module boundaries.
            # CONSEQUENCE: Reusing them in analog access can break A/D interface semantics.
            if p.get('dtype') in ('logic', 'reg'):
                digital_nets.add(p.get('name', ''))
        for s in ctx.signal_decls:
            # WHAT: Collects internal signal declarations typed as logic/reg.
            # WHY: Internal digital storage nets should not be directly treated as analog nodes.
            # CONSEQUENCE: Direct analog probing of digital nets can create solver/domain conflicts.
            if s.get('dtype') in ('logic', 'reg'):
                digital_nets.add(s.get('name', ''))

        for i, ln in enumerate(ctx.clean_lines):
            m = _CONTRIB_TARGET_RE.search(ln)
            # WHAT: Parses V()/I() targets used in analog contribution statements.
            # WHY: Target nets should belong to analog disciplines, not digital storage types.
            # CONSEQUENCE: Domain confusion causes boundary modeling errors and sim mismatch.
            if m:
                for net in _extract_target_nets(m.group(1)):
                    # WHAT: Flags targets that were declared as logic/reg in RTL declarations.
                    # WHY: Direct analog access to digital nets bypasses proper A/D bridging.
                    # CONSEQUENCE: Causes threshold ambiguity and invalid analog interface behavior.
                    if net in digital_nets:
                        findings.append(self._finding(ctx, i + 1, suggestion=f"Use a connect model or bridge signal instead of direct V()/I() on digital net '{net}'."))
                        break
        return findings


@register_rule
class VLG106(RuleBase):
    """
    VLG106 — cross() Used Without Event Control
    Category : Analog-Digital Interface
    Severity : WARNING

    Why it matters:
        cross() is intended for event detection; using it outside event controls
        can hide intended sampling points and produce inconsistent updates.

    Example trigger:
        d = cross(V(in)-vth, +1);

    Suggestion:
        Use cross() within @(... ) event controls for discrete-time transitions.
    """
    rule_id = "VLG106"
    category = "AMS"
    severity = Severity.WARNING
    description = "cross() appears outside event control expression"

    def check(self, ctx: ParseContext):
        findings = []
        for i, ln in enumerate(ctx.clean_lines):
            # WHAT: Detects lines with cross(...) but no event-control token '@('.
            # WHY: cross() semantics are most robust when used as an event trigger.
            # CONSEQUENCE: Misuse can produce missed transitions and mixed-signal race behavior.
            if 'cross(' in ln and '@(' not in ln:
                findings.append(self._finding(ctx, i + 1, suggestion="Place cross(...) inside an event control, for example: @(cross(...))."))
        return findings


@register_rule
class VLG107(RuleBase):
    """
    VLG107 — Hardcoded Analog Threshold In Interface Logic
    Category : Analog-Digital Interface
    Severity : INFO

    Why it matters:
        Hardcoded threshold literals at analog/digital boundaries are brittle
        across process, voltage, and temperature corners.

    Example trigger:
        if (V(in) > 0.5) logic_out = 1'b1;

    Suggestion:
        Replace literal threshold values with parameters/constants.
    """
    rule_id = "VLG107"
    category = "AMS"
    severity = Severity.INFO
    description = "Analog boundary comparison uses hardcoded numeric threshold"

    def check(self, ctx: ParseContext):
        findings = []
        thresh_re = re.compile(r'\b(if|while)\s*\([^\)]*[VI]\s*\([^\)]*\)\s*[<>]=?\s*\d+(?:\.\d+)?')
        for i, ln in enumerate(ctx.clean_lines):
            # WHAT: Identifies control decisions comparing V()/I() against literal constants.
            # WHY: Fixed thresholds are not portable across PVT and design reuse contexts.
            # CONSEQUENCE: Causes threshold mismatch, false switching, and verification churn.
            if thresh_re.search(ln):
                findings.append(self._finding(ctx, i + 1, suggestion="Promote interface threshold to a named parameter (e.g., VTH_ADC)."))
        return findings


@register_rule
class VLG108(RuleBase):
    """
    VLG108 — Potential Singular Denominator In Contribution
    Category : Analog Power & Convergence
    Severity : ERROR

    Why it matters:
        Dividing by a voltage difference that may approach zero introduces
        singularities and severely destabilizes Newton-Raphson iteration.

    Example trigger:
        I(out) <+ gain / (V(p)-V(n));

    Suggestion:
        Add limiting term/epsilon or reformulate the equation to avoid singularity.
    """
    rule_id = "VLG108"
    category = "AMS"
    severity = Severity.ERROR
    description = "Contribution contains divide-by-(V()-V()) style singularity risk"

    def check(self, ctx: ParseContext):
        findings = []
        singular_re = re.compile(r'/\s*\(\s*V\([^\)]*\)\s*\-\s*V\([^\)]*\)\s*\)')
        for i, ln in enumerate(ctx.clean_lines):
            # WHAT: Detects denominator terms built from voltage differences.
            # WHY: These denominators can become near-zero during transients.
            # CONSEQUENCE: Produces singular matrix conditions and solver divergence.
            if '<+' in ln and singular_re.search(ln):
                findings.append(self._finding(ctx, i + 1, suggestion="Guard denominator with epsilon/limiting or use a numerically safe formulation."))
        return findings


@register_rule
class VLG109(RuleBase):
    """
    VLG109 — Continuous Analog Block Without Event Gating
    Category : Analog Power & Convergence
    Severity : WARNING

    Why it matters:
        Unconditionally active analog equations force frequent reevaluation,
        increasing simulation power/cost and raising convergence burden.

    Example trigger:
        analog begin
            V(out) <+ transition(code, 0, tr);
        end

    Suggestion:
        Introduce event gating or conditional activity windows where possible.
    """
    rule_id = "VLG109"
    category = "AMS"
    severity = Severity.WARNING
    description = "Analog block has contributions but no apparent event/activity gating"

    def check(self, ctx: ParseContext):
        findings = []
        for i, ln in enumerate(ctx.clean_lines):
            for blk in ctx.analog_blocks:
                # WHAT: Anchors this check at each analog block start line.
                # WHY: Activity-gating properties are block-level behavioral attributes.
                # CONSEQUENCE: Ungated blocks increase simulation cost and convergence stress.
                if blk.get('start_line') == i + 1:
                    body_text = '\n'.join(blk.get('body_lines', []))
                    has_contrib = '<+' in body_text
                    has_event = '@(' in body_text or 'cross(' in body_text or 'timer(' in body_text
                    # WHAT: Flags analog blocks that contribute continuously without event control.
                    # WHY: Constantly active equations run every analog timestep.
                    # CONSEQUENCE: Causes unnecessary power/runtime overhead and convergence pressure.
                    if has_contrib and not has_event:
                        findings.append(self._finding(ctx, i + 1, suggestion="Add event/condition gating (for example @cross or timer windows) for expensive analog activity."))
        return findings


@register_rule
class VLG110(RuleBase):
    """
    VLG110 — Zero-Rise/Fall Transition Edge
    Category : Analog Power & Convergence
    Severity : WARNING

    Why it matters:
        transition() with zero rise/fall times reintroduces hard discontinuities,
        defeating smoothing and often hurting convergence.

    Example trigger:
        V(out) <+ transition(code, 0, 0, 0);

    Suggestion:
        Use physically meaningful non-zero rise/fall transition parameters.
    """
    rule_id = "VLG110"
    category = "AMS"
    severity = Severity.WARNING
    description = "transition() uses zero rise/fall time which can degrade convergence"

    def check(self, ctx: ParseContext):
        findings = []
        zero_edge_re = re.compile(r'\btransition\s*\([^\)]*,\s*0+(?:\.0+)?\s*,\s*0+(?:\.0+)?')
        for i, ln in enumerate(ctx.clean_lines):
            # WHAT: Detects transition(...) calls with explicit zero rise/fall arguments.
            # WHY: Zero transition edge times collapse into discontinuous signal steps.
            # CONSEQUENCE: Increases timestep shock and solver non-convergence risk.
            if zero_edge_re.search(ln):
                findings.append(self._finding(ctx, i + 1, suggestion="Set non-zero rise/fall times in transition(...) to preserve numerical smoothness."))
        return findings


@register_rule
class VLG111(RuleBase):
    """
    VLG111 — Late Discipline/Nature Declaration
    Category : AMS Readability & Style
    Severity : INFO

    Why it matters:
        Declaring discipline/nature definitions late in the file hides essential
        physical context and makes model intent harder to review.

    Example trigger:
        module m(...);
        ...
        nature volts;

    Suggestion:
        Place discipline and nature declarations near the top of the file.
    """
    rule_id = "VLG111"
    category = "AMS"
    severity = Severity.INFO
    description = "Discipline/nature declaration appears after module declaration"

    def check(self, ctx: ParseContext):
        findings = []
        first_module_line = ctx.modules[0]['start_line'] if ctx.modules else None
        decl_re = re.compile(r'\b(discipline|nature)\b')
        for i, ln in enumerate(ctx.clean_lines):
            # WHAT: Detects discipline/nature declarations in source order.
            # WHY: Physical-domain declarations are foundational context for AMS readers.
            # CONSEQUENCE: Late declarations reduce readability and onboarding speed.
            if decl_re.search(ln) and first_module_line is not None and (i + 1) > first_module_line:
                findings.append(self._finding(ctx, i + 1, suggestion="Move discipline/nature declarations before module bodies for clarity."))
        return findings


@register_rule
class VLG112(RuleBase):
    """
    VLG112 — Non-Descriptive Branch Name
    Category : AMS Readability & Style
    Severity : INFO

    Why it matters:
        Generic branch names hide physical meaning and complicate debug of
        branch equations, probes, and post-processing scripts.

    Example trigger:
        branch (vin, vout) b1;

    Suggestion:
        Rename branches to intent-rich names (e.g., br_input_path, br_load).
    """
    rule_id = "VLG112"
    category = "AMS"
    severity = Severity.INFO
    description = "Branch name is generic and not descriptive"

    def check(self, ctx: ParseContext):
        findings = []
        weak_name_re = re.compile(r'^(b\d+|br\d+|tmp\d+)$', re.IGNORECASE)
        for i, ln in enumerate(ctx.clean_lines):
            m = _BRANCH_RE.search(ln)
            # WHAT: Detects branch declaration lines and extracts branch identifiers.
            # WHY: Branch names should communicate physical path intent.
            # CONSEQUENCE: Generic names slow debug and increase maintenance errors.
            if m:
                name = m.group(1)
                # WHAT: Flags weak auto-generated branch naming patterns.
                # WHY: Non-descriptive names provide no domain context.
                # CONSEQUENCE: Leads to review mistakes and slower root-cause analysis.
                if weak_name_re.match(name):
                    findings.append(self._finding(ctx, i + 1, suggestion=f"Rename branch '{name}' to reflect physical function or path meaning."))
        return findings


@register_rule
class VLG113(RuleBase):
    """
    VLG113 — Analog Block Missing Context Comment
    Category : AMS Readability & Style
    Severity : INFO

    Why it matters:
        Analog equations often encode physical assumptions; without nearby
        comments, reviewers may misinterpret model behavior.

    Example trigger:
        analog begin
            I(out) <+ gm * V(in);
        end

    Suggestion:
        Add a short comment above analog blocks describing intent and assumptions.
    """
    rule_id = "VLG113"
    category = "AMS"
    severity = Severity.INFO
    description = "Analog block has no nearby explanatory comment"

    def check(self, ctx: ParseContext):
        findings = []
        for i, ln in enumerate(ctx.clean_lines):
            # WHAT: Anchors check at lines that begin an analog block.
            # WHY: Comments are most useful directly before behavioral analog sections.
            # CONSEQUENCE: Missing context increases misunderstanding of model assumptions.
            if re.search(r'\banalog\b', ln):
                prev_start = max(0, i - 2)
                prev_lines = ctx.lines[prev_start:i]
                has_comment = False
                for prev in prev_lines:
                    # WHAT: Detects comment markers in lines preceding analog block.
                    # WHY: Nearby comments provide immediate physical modeling context.
                    # CONSEQUENCE: Without context, maintainers may introduce incorrect edits.
                    if '//' in prev or '/*' in prev:
                        has_comment = True
                # WHAT: Reports analog blocks that start without nearby explanatory comments.
                # WHY: Unexplained equations are difficult to validate and maintain.
                # CONSEQUENCE: Raises long-term style debt and review ambiguity in AMS code.
                if not has_comment:
                    findings.append(self._finding(ctx, i + 1, suggestion="Add a brief comment above this analog block describing its physical intent."))
        return findings
