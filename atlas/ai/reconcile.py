"""Reconciliation: match observed AI assets to intake records, derive
findings and control results (DESIGN.md section 5). Pure functions only; the
job in atlas/ai/jobs/reconcile.py does the I/O.

Units and children. Governed units are endpoints, agents, MCP servers, UC
function tools, and registered models. External models and model versions
are *children*: they inherit their parent's match, and findings are raised
on the parent (a shadow endpoint serving an external model is one high
severity finding, not two). ``found_different`` compares the child's
provider and model family, because those live on the child.

Truthfulness. ``registered_not_found`` is raised or resolved only when every
core source was fully available this run, and auto-resolution skips any kind
whose source was unavailable or degraded. A source outage never reads as
"asset gone" or "intake not found".
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from atlas.ai import controls as control_registry
from atlas.ai import models
from atlas.ai.models import Finding, finding_id_for

RULE_SET_VERSION = "phase1-1"
MATCHED = 0.90
AMBIGUOUS_FLOOR = 0.50
M3_MIN_SIMILARITY = 0.85

UNIT_KINDS = (models.SERVING_ENDPOINT, models.AGENT, models.MCP_SERVER, models.UC_FUNCTION_TOOL, models.AI_MODEL)
CHILD_KINDS = (models.EXTERNAL_MODEL, models.AI_MODEL_VERSION)
SOURCE_KINDS = {
    "serving_endpoints": (models.SERVING_ENDPOINT, models.AGENT, models.EXTERNAL_MODEL),
    "registered_models": (models.AI_MODEL, models.AI_MODEL_VERSION),
    "mcp_connections": (models.MCP_SERVER,),
    "uc_function_tools": (models.UC_FUNCTION_TOOL,),
}
CORE_SOURCES = ("serving_endpoints", "registered_models")


# ----------------------------------------------------------------- inputs
@dataclass
class Asset:
    entity_id: str
    entity_kind: str
    source_system: str
    source_entity_id: str
    display_name: str
    owner: str
    platform: str
    provider: str
    model_family: str
    tags: Dict[str, str]
    config: Dict[str, Any]
    relationships: List[Dict[str, str]]
    parent_source_entity_id: Optional[str]
    provenance_class: str
    sample_run_id: Optional[str]
    observed_at: Any
    run_id: str
    collector: str
    collector_version: str
    children: List["Asset"] = field(default_factory=list)

    @property
    def provenance(self) -> Dict[str, Any]:
        return {
            "sourceSystem": self.source_system,
            "collector": self.collector,
            "collectorVersion": self.collector_version,
            "runId": self.run_id,
            "observedAt": str(self.observed_at),
            "provenanceClass": self.provenance_class,
            "sampleRunId": self.sample_run_id,
        }


def asset_from_row(row: Mapping[str, Any]) -> Asset:
    kind = str(row["entity_kind"])
    system = str(row["source_system"])
    source_id = str(row["source_entity_id"])
    return Asset(
        entity_id=models.ai_entity_id(kind, system, source_id),
        entity_kind=kind,
        source_system=system,
        source_entity_id=source_id,
        display_name=str(row.get("display_name") or source_id),
        owner=str(row.get("owner") or ""),
        platform=str(row.get("platform") or ""),
        provider=str(row.get("provider") or ""),
        model_family=str(row.get("model_family") or ""),
        tags=dict(row.get("tags_json") or {}),
        config=dict(row.get("config_json") or {}),
        relationships=list(row.get("relationships_json") or []),
        parent_source_entity_id=row.get("parent_source_entity_id"),
        provenance_class=str(row.get("provenance_class") or models.PROVENANCE_ORGANIC),
        sample_run_id=row.get("sample_run_id"),
        observed_at=row.get("observed_at"),
        run_id=str(row.get("run_id") or ""),
        collector=str(row.get("collector") or ""),
        collector_version=str(row.get("collector_version") or ""),
    )


# --------------------------------------------------------------- matching
@dataclass(frozen=True)
class Match:
    intake_id: Optional[str]
    rule: Optional[str]
    score: float
    candidates: Tuple[Tuple[str, float], ...] = ()

    @property
    def state(self) -> str:
        if self.intake_id and self.score >= MATCHED:
            return "matched"
        if self.score >= AMBIGUOUS_FLOOR:
            return "ambiguous"
        return "unmatched"


def normalize_name(value: str) -> str:
    return re.sub(r"[\s_.\-/]+", " ", str(value or "").strip().lower()).strip()


def name_similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, normalize_name(a), normalize_name(b)).ratio()


def m3_score(similarity: float) -> float:
    """0.70 at the 0.85 similarity floor, rising linearly to 0.90 at 1.0.
    M3 alone can reach "matched" only on an exact normalized name."""
    return round(min(0.90, max(0.70, 0.70 + 0.20 * (similarity - M3_MIN_SIMILARITY) / (1 - M3_MIN_SIMILARITY))), 4)


def _asset_names(asset: Asset) -> List[str]:
    names = [asset.display_name, asset.source_entity_id.split(".")[-1]]
    return [n for n in names if n]


def _same_platform_or_provider(asset: Asset, intake: Mapping[str, Any]) -> bool:
    providers = {asset.provider.lower()} | {c.provider.lower() for c in asset.children}
    providers.discard("")
    intake_provider = str(intake.get("provider") or "").lower()
    if intake_provider and intake_provider in providers:
        return True
    intake_platform = str(intake.get("platform") or "").lower()
    return bool(intake_platform) and intake_platform == asset.platform.lower()


def match_asset(
    asset: Asset,
    intakes: Mapping[str, Mapping[str, Any]],
    aliases: Mapping[str, str],
    intake_tag_key: str,
) -> Match:
    # M2: steward confirmation is authoritative and survives tag changes.
    alias = aliases.get(asset.entity_id)
    if alias and alias in intakes:
        return Match(alias, "M2", 1.0)
    # M1: the intake tag on the asset names an intake record.
    tagged = (asset.tags or {}).get(intake_tag_key)
    if tagged and tagged in intakes:
        return Match(tagged, "M1", 1.0)
    # M3: same owner + similar name + same platform or provider.
    candidates: List[Tuple[str, float]] = []
    owner = asset.owner.strip().lower()
    for intake_id, intake in intakes.items():
        if not owner or owner != str(intake.get("owner_email") or "").strip().lower():
            continue
        if not _same_platform_or_provider(asset, intake):
            continue
        similarity = max((name_similarity(n, str(intake.get("title") or "")) for n in _asset_names(asset)), default=0.0)
        if similarity >= M3_MIN_SIMILARITY:
            candidates.append((intake_id, m3_score(similarity)))
    if not candidates:
        return Match(None, None, 0.0)
    candidates.sort(key=lambda c: (-c[1], c[0]))
    best_id, best = candidates[0]
    # Two candidates at the same best score can never be a confident match.
    if len(candidates) > 1 and candidates[1][1] == best:
        best = min(best, MATCHED - 0.01)
    return Match(best_id, "M3", best, tuple(candidates[:5]))


# ------------------------------------------------------------ finding rules
@dataclass(frozen=True)
class RuleContext:
    unit: Optional[Asset]
    match: Optional[Match]
    intake: Optional[Mapping[str, Any]]
    tier_tag_key: str


@dataclass(frozen=True)
class Rule:
    rule_id: str
    finding_type: str
    evaluate: Callable[[RuleContext], Optional[Tuple[str, Dict[str, Any]]]]


RULES: Dict[str, Rule] = {}


def rule(rule_id: str, finding_type: str) -> Callable:
    def register(fn: Callable[[RuleContext], Optional[Tuple[str, Dict[str, Any]]]]):
        RULES[rule_id] = Rule(rule_id, finding_type, fn)
        return fn

    return register


def _has_external_child(unit: Asset) -> bool:
    return any(c.entity_kind == models.EXTERNAL_MODEL for c in unit.children)


@rule("R-FNR-01", "found_not_registered")
def _found_not_registered(ctx: RuleContext):
    if ctx.unit is None or ctx.match is None or ctx.match.state != "unmatched":
        return None
    high = ctx.unit.entity_kind in (models.AGENT, models.MCP_SERVER) or _has_external_child(ctx.unit)
    return ("high" if high else "medium"), {"reason": "No intake record matches this asset."}


@rule("R-RBR-01", "rejected_but_running")
def _rejected_but_running(ctx: RuleContext):
    if ctx.match is None or ctx.match.state != "matched" or not ctx.intake:
        return None
    if str(ctx.intake.get("state")) != "rejected":
        return None
    return "critical", {"reason": "The matching intake was rejected, but the asset is running.", "intakeState": "rejected"}


@rule("R-FDF-01", "found_different")
def _found_different(ctx: RuleContext):
    if ctx.unit is None or ctx.match is None or ctx.match.state != "matched" or not ctx.intake:
        return None
    diffs: List[Dict[str, Any]] = []
    intake = ctx.intake

    def differs(declared: Any, observed: Iterable[str]) -> Optional[List[str]]:
        want = str(declared or "").strip().lower()
        got = sorted({str(o).strip() for o in observed if str(o or "").strip()})
        if want and got and want not in {g.lower() for g in got}:
            return got
        return None

    providers = [ctx.unit.provider] + [c.provider for c in ctx.unit.children]
    families = [ctx.unit.model_family] + [c.model_family for c in ctx.unit.children]
    got = differs(intake.get("provider"), providers)
    if got:
        diffs.append({"field": "provider", "declared": intake.get("provider"), "observed": got})
    got = differs(intake.get("model_family"), families)
    if got:
        diffs.append({"field": "model_family", "declared": intake.get("model_family"), "observed": got})
    got = differs(intake.get("risk_tier"), [(ctx.unit.tags or {}).get(ctx.tier_tag_key, "")])
    if got:
        diffs.append({"field": "risk_tier", "declared": intake.get("risk_tier"), "observed": got})
    got = differs(intake.get("owner_email"), [ctx.unit.owner])
    if got:
        diffs.append({"field": "owner", "declared": intake.get("owner_email"), "observed": got})
    if not diffs:
        return None
    fields = {d["field"] for d in diffs}
    severity = "high" if fields & {"provider", "model_family"} else ("medium" if "risk_tier" in fields else "low")
    return severity, {"reason": "Observed configuration differs from the intake record.", "differences": diffs}


@rule("R-AMB-01", "ambiguous_match")
def _ambiguous(ctx: RuleContext):
    if ctx.match is None or ctx.match.state != "ambiguous":
        return None
    return "low", {
        "reason": "More than one intake could describe this asset, or the best match is below the confidence threshold.",
        "candidates": [{"intakeId": i, "score": s} for i, s in ctx.match.candidates],
    }


# ------------------------------------------------------------------ result
@dataclass
class UnitState:
    asset: Asset
    match: Match
    intake: Optional[Mapping[str, Any]]
    reconciliation_state: str


@dataclass
class ReconcileResult:
    units: List[UnitState]
    registry: List[Tuple[Asset, str, Optional[float]]]
    findings: List[Finding]
    resolve_ids: List[str]
    controls: List[models.ControlResult]
    postures: Dict[str, str]
    declares: List[Tuple[str, Asset, str]]  # (intake_id, unit, match rule)
    serves: List[Tuple[Asset, str, str]]  # (source asset, target kind, target entity id)
    counts: Dict[str, Any]


def _registry_state(match: Match, intake: Optional[Mapping[str, Any]]) -> str:
    if match.state == "matched":
        return "pending_intake" if intake and intake.get("state") in ("draft", "submitted") else "matched"
    return "ambiguous" if match.state == "ambiguous" else "orphaned"


def _as_utc(value: Any) -> Optional[datetime]:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def reconcile(
    observations: Sequence[Mapping[str, Any]],
    intake_rows: Sequence[Mapping[str, Any]],
    *,
    aliases: Mapping[str, str],
    active_findings: Sequence[Mapping[str, Any]],
    sources: Mapping[str, Mapping[str, Any]],
    intake_tag_key: str,
    tier_tag_key: str,
    grace_days: int,
    now: Optional[datetime] = None,
) -> ReconcileResult:
    now = now or datetime.now(timezone.utc)
    intakes = {str(r["intake_id"]): r for r in intake_rows}
    assets = [asset_from_row(o) for o in observations]
    by_source_id = {(a.entity_kind, a.source_entity_id): a for a in assets}
    units = [a for a in assets if a.entity_kind in UNIT_KINDS]
    children = [a for a in assets if a.entity_kind in CHILD_KINDS]
    for child in children:
        parent_kinds = (models.AI_MODEL,) if child.entity_kind == models.AI_MODEL_VERSION else (models.SERVING_ENDPOINT, models.AGENT)
        for kind in parent_kinds:
            parent = by_source_id.get((kind, child.parent_source_entity_id or ""))
            if parent:
                parent.children.append(child)
                break

    unit_states: List[UnitState] = []
    findings: Dict[str, Finding] = {}
    matched_intakes: set = set()
    ambiguous_intakes: set = set()

    def add_finding(rule_obj: Rule, severity: str, evidence: Dict[str, Any], unit: Optional[Asset], match: Optional[Match], intake_id: Optional[str]) -> None:
        entity_id = unit.entity_id if unit else None
        fid = finding_id_for(rule_obj.finding_type, entity_id, intake_id, rule_obj.rule_id)
        sample = unit.sample_run_id if unit else (intakes.get(intake_id or "", {}) or {}).get("sample_run_id")
        provenance = unit.provenance if unit else {"sourceSystem": "intake", "intakeId": intake_id}
        findings[fid] = Finding(
            finding_id=fid,
            finding_type=rule_obj.finding_type,
            rule_id=rule_obj.rule_id,
            severity=severity,
            entity_id=entity_id,
            entity_kind=unit.entity_kind if unit else None,
            intake_id=intake_id,
            match_rule=match.rule if match else None,
            match_score=match.score if match and match.rule else None,
            evidence={**evidence, "provenance": provenance, "assetName": unit.display_name if unit else None},
            provenance_class=models.PROVENANCE_SAMPLE if sample else models.PROVENANCE_ORGANIC,
            sample_run_id=sample,
        )

    for unit in units:
        match = match_asset(unit, intakes, aliases, intake_tag_key)
        intake = intakes.get(match.intake_id) if match.state == "matched" and match.intake_id else None
        if intake:
            matched_intakes.add(match.intake_id)
        elif match.state == "ambiguous" and match.intake_id:
            ambiguous_intakes.add(match.intake_id)
        unit_states.append(UnitState(unit, match, intake, _registry_state(match, intake)))
        ctx = RuleContext(unit=unit, match=match, intake=intake, tier_tag_key=tier_tag_key)
        for rule_obj in RULES.values():
            outcome = rule_obj.evaluate(ctx)
            if outcome:
                severity, evidence = outcome
                intake_ref = match.intake_id if match.state in ("matched", "ambiguous") else None
                add_finding(rule_obj, severity, evidence, unit, match, intake_ref)

    core_available = all(
        str((sources.get(name) or {}).get("state")) == models.PROBE_AVAILABLE for name in CORE_SOURCES
    )
    rnf = Rule("R-RNF-01", "registered_not_found", lambda ctx: None)
    if core_available:
        grace = timedelta(days=max(0, int(grace_days)))
        for intake_id, intake in intakes.items():
            # An intake that is the best candidate of an ambiguous asset is
            # awaiting steward confirmation, not missing.
            if intake.get("state") != "approved" or intake_id in matched_intakes or intake_id in ambiguous_intakes:
                continue
            since = _as_utc(intake.get("approved_at")) or _as_utc(intake.get("created_at"))
            if since is None or now - since < grace:
                continue
            add_finding(
                rnf,
                "medium",
                {"reason": f"Approved intake has no observed asset after {grace.days} days.", "approvedAt": str(since), "title": intake.get("title")},
                None,
                None,
                intake_id,
            )

    # Auto-resolve only what this run could actually see.
    blind_kinds = set()
    for source, kinds in SOURCE_KINDS.items():
        if str((sources.get(source) or {}).get("state")) != models.PROBE_AVAILABLE:
            blind_kinds.update(kinds)
    resolve_ids = []
    for prior in active_findings:
        fid = str(prior.get("finding_id"))
        if fid in findings:
            continue
        if prior.get("finding_type") == "registered_not_found":
            if core_available:
                resolve_ids.append(fid)
            continue
        if str(prior.get("entity_kind") or "") in blind_kinds:
            continue
        resolve_ids.append(fid)

    # Registry: units carry their own state; children inherit the parent's.
    registry: List[Tuple[Asset, str, Optional[float]]] = []
    for state in unit_states:
        confidence = state.match.score if state.match.rule else None
        registry.append((state.asset, state.reconciliation_state, confidence))
        for child in state.asset.children:
            registry.append((child, state.reconciliation_state, confidence))
    orphans = [c for c in children if not any(c in s.asset.children for s in unit_states)]
    registry.extend((c, "orphaned", None) for c in orphans)

    # Controls for every observed asset, with the unit's match context.
    control_results: List[models.ControlResult] = []
    postures: Dict[str, str] = {}
    cfg = {"tier_tag_key": tier_tag_key, "intake_tag_key": intake_tag_key}
    for state in unit_states:
        for asset in [state.asset, *state.asset.children]:
            ctx = control_registry.AssetContext(
                entity_id=asset.entity_id,
                entity_kind=asset.entity_kind,
                tags=asset.tags,
                config=asset.config,
                match_state=state.match.state,
                intake=state.intake,
            )
            results = control_registry.evaluate(ctx, cfg)
            control_results.extend(results)
            if results:
                postures[asset.entity_id] = control_registry.posture(results)

    declares = [(s.match.intake_id, s.asset, s.match.rule or "") for s in unit_states if s.match.state == "matched" and s.match.intake_id]
    serves = []
    for asset in assets:
        for edge in asset.relationships:
            if edge.get("kind") == "serves" and edge.get("target_source_entity_id"):
                target_id = models.ai_entity_id(str(edge.get("target_kind")), asset.source_system, str(edge["target_source_entity_id"]))
                serves.append((asset, str(edge.get("target_kind")), target_id))

    counts = {
        "units": len(units),
        "children": len(children),
        "matchStates": _count(s.match.state for s in unit_states),
        "findingsByType": _count(f.finding_type for f in findings.values()),
        "toResolve": len(resolve_ids),
        "coreSourcesAvailable": core_available,
        "ruleSetVersion": RULE_SET_VERSION,
    }
    return ReconcileResult(unit_states, registry, list(findings.values()), resolve_ids, control_results, postures, declares, serves, counts)


def _count(values: Iterable[str]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for value in values:
        out[value] = out.get(value, 0) + 1
    return out
