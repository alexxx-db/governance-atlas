"""AI control registry (DESIGN.md section 6), Phase 1 subset.

Controls are registered by ID. Each returns ``pass | fail | unknown`` for an
asset it applies to, or ``None`` when it does not apply (nothing is stored).
``unknown`` means the signal was not observable: it is excluded from posture
and rendered as "Unknown: signal not observable from <source>".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional

from atlas.ai import models

CONTROL_VERSION = "1"


@dataclass
class AssetContext:
    """What a control may look at: the observation, its match, and config."""

    entity_id: str
    entity_kind: str
    tags: Dict[str, str]
    config: Dict[str, Any]
    match_state: str  # matched | ambiguous | unmatched
    intake: Optional[Mapping[str, Any]] = None
    parent_tags: Dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Outcome:
    status: str
    signal_source: str
    evidence: Dict[str, Any]


ControlFn = Callable[[AssetContext, Mapping[str, Any]], Optional[Outcome]]
CONTROLS: Dict[str, ControlFn] = {}
CONTROL_TITLES: Dict[str, str] = {}

_ENDPOINT_KINDS = {models.SERVING_ENDPOINT, models.AGENT}
_GOVERNED_UNITS = {models.SERVING_ENDPOINT, models.AGENT, models.MCP_SERVER, models.UC_FUNCTION_TOOL, models.AI_MODEL}


def control(control_id: str, title: str) -> Callable[[ControlFn], ControlFn]:
    def register(fn: ControlFn) -> ControlFn:
        CONTROLS[control_id] = fn
        CONTROL_TITLES[control_id] = title
        return fn

    return register


@control("AIC-01", "Linked to an approved intake")
def aic_01(asset: AssetContext, cfg: Mapping[str, Any]) -> Optional[Outcome]:
    if asset.entity_kind not in _GOVERNED_UNITS:
        return None
    if asset.match_state == "ambiguous":
        return Outcome("unknown", "reconciliation", {"reason": "match is ambiguous; awaiting steward confirmation"})
    if asset.match_state != "matched" or not asset.intake:
        return Outcome("fail", "reconciliation", {"reason": "no matching intake record"})
    state = str(asset.intake.get("state") or "")
    return Outcome(
        "pass" if state == "approved" else "fail",
        "reconciliation",
        {"intakeId": asset.intake.get("intake_id"), "intakeState": state},
    )


@control("AIC-03", "Risk tier tag present and equal to the intake tier")
def aic_03(asset: AssetContext, cfg: Mapping[str, Any]) -> Optional[Outcome]:
    if asset.entity_kind == models.AI_MODEL:
        return Outcome("unknown", "registered_models", {"reason": "registered model tags are not observable in databricks-sdk 0.95"})
    if asset.entity_kind == models.MCP_SERVER:
        return Outcome("unknown", "mcp_connections", {"reason": "connection tags are not observed"})
    if asset.entity_kind == models.UC_FUNCTION_TOOL:
        return Outcome("unknown", "uc_function_tools", {"reason": "function tags are not observable (information_schema.routine_tags is unsupported)"})
    if asset.entity_kind not in {models.SERVING_ENDPOINT, models.AGENT}:
        return None
    key = str(cfg.get("tier_tag_key") or "ai_risk_tier")
    tier = (asset.tags or {}).get(key)
    if not tier:
        return Outcome("fail", "tags", {"reason": f"tag {key!r} is not set"})
    declared = str((asset.intake or {}).get("risk_tier") or "")
    if declared and declared.strip().lower() != tier.strip().lower():
        return Outcome("fail", "tags", {"observedTier": tier, "declaredTier": declared})
    return Outcome("pass", "tags", {"observedTier": tier, "declaredTier": declared or None})


def _gateway_flag(asset: AssetContext, section: str) -> Optional[Outcome]:
    if asset.entity_kind not in _ENDPOINT_KINDS:
        return None
    gateway = (asset.config or {}).get("ai_gateway") or {}
    enabled = bool((gateway.get(section) or {}).get("enabled"))
    return Outcome(
        "pass" if enabled else "fail",
        "serving_endpoints",
        {"section": section, "enabled": enabled, "gatewayConfigured": bool(gateway)},
    )


@control("AIC-04", "AI Gateway usage tracking enabled")
def aic_04(asset: AssetContext, cfg: Mapping[str, Any]) -> Optional[Outcome]:
    return _gateway_flag(asset, "usage_tracking_config")


@control("AIC-06", "Inference table logging enabled (configuration only)")
def aic_06(asset: AssetContext, cfg: Mapping[str, Any]) -> Optional[Outcome]:
    return _gateway_flag(asset, "inference_table_config")


@control("AIC-09", "External provider credentials use a secret reference")
def aic_09(asset: AssetContext, cfg: Mapping[str, Any]) -> Optional[Outcome]:
    if asset.entity_kind != models.EXTERNAL_MODEL:
        return None
    creds = (asset.config or {}).get("credentials") or {}
    if not creds.get("observable"):
        return Outcome(
            "unknown",
            "serving_endpoints",
            {"reason": "credential configuration is not exposed by the serving API"},
        )
    if creds.get("plaintext_fields"):
        return Outcome("fail", "serving_endpoints", {"plaintextFields": creds["plaintext_fields"]})
    return Outcome("pass", "serving_endpoints", {"secretRefs": creds.get("secret_refs") or []})


def evaluate(asset: AssetContext, cfg: Mapping[str, Any]) -> List[models.ControlResult]:
    results = []
    for control_id, fn in CONTROLS.items():
        outcome = fn(asset, cfg)
        if outcome is None:
            continue
        results.append(
            models.ControlResult(
                entity_id=asset.entity_id,
                entity_kind=asset.entity_kind,
                control_id=control_id,
                control_version=CONTROL_VERSION,
                status=outcome.status,
                signal_source=outcome.signal_source,
                evidence=outcome.evidence,
            )
        )
    return results


def posture(results: List[models.ControlResult]) -> str:
    """Band from known results only; unknowns never count as pass or fail."""
    known = [r for r in results if r.status in ("pass", "fail")]
    if not known:
        return "unknown"
    failed = sum(1 for r in known if r.status == "fail")
    if failed == 0:
        return "strong"
    return "weak" if failed * 2 > len(known) else "partial"
