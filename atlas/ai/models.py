"""Typed records for the AI governance extension (DESIGN.md sections 4 to 6).

Every record that reaches a table carries provenance: source system, collector
and version, run ID, and observed-at time. Sample rows are distinguished by
``provenance_class='sample'`` plus ``sample_run_id`` rather than by a source
value, because the frontend fails closed on source values such as ``seed`` or
``mock`` (nonAuthoritativeEvidence.js); see DESIGN.md 10.1.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional

# entity_kind values (DESIGN.md section 1).
AI_MODEL = "ai_model"
AI_MODEL_VERSION = "ai_model_version"
SERVING_ENDPOINT = "serving_endpoint"
EXTERNAL_MODEL = "external_model"
AGENT = "agent"
MCP_SERVER = "mcp_server"
UC_FUNCTION_TOOL = "uc_function_tool"
INTAKE_RECORD = "intake_record"

ENTITY_KINDS = (
    AI_MODEL,
    AI_MODEL_VERSION,
    SERVING_ENDPOINT,
    EXTERNAL_MODEL,
    AGENT,
    MCP_SERVER,
    UC_FUNCTION_TOOL,
    INTAKE_RECORD,
)
OBSERVED_KINDS = tuple(kind for kind in ENTITY_KINDS if kind != INTAKE_RECORD)

PROVENANCE_ORGANIC = "organic"
PROVENANCE_SAMPLE = "sample"

PROBE_AVAILABLE = "available"
PROBE_DEGRADED = "degraded"
PROBE_UNAVAILABLE = "unavailable"

INTAKE_STATES = ("draft", "submitted", "approved", "rejected", "retired")
FINDING_STATES = ("open", "acknowledged", "resolved", "suppressed")
CONTROL_STATUSES = ("pass", "fail", "not_applicable", "unknown")
SEVERITIES = ("critical", "high", "medium", "low")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def canonical_json(value: Any) -> str:
    """Stable JSON (sorted keys, no whitespace) for hashing and storage."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def content_hash(fields: Mapping[str, Any]) -> str:
    """SHA-256 over canonical JSON of normalized, redacted fields. Callers must
    exclude volatile fields (timestamps, ETags, state) so an unchanged asset
    hashes identically across runs."""
    return hashlib.sha256(canonical_json(dict(fields)).encode("utf-8")).hexdigest()


def ai_entity_id(entity_kind: str, source_system: str, source_entity_id: str) -> str:
    """Deterministic entity_registry ID for an AI asset (DESIGN.md 4.1), so the
    same platform object maps to the same registry row on every run."""
    raw = f"ai|{entity_kind}|{source_system}|{source_entity_id}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


@dataclass(frozen=True)
class ProbeResult:
    source: str
    ok: bool
    state: str  # available | degraded | unavailable
    reason: str
    sampled_at: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RunContext:
    run_id: str
    collector: str
    collector_version: str
    source_system: str
    started_at: datetime
    provenance_class: str = PROVENANCE_ORGANIC
    sample_run_id: Optional[str] = None
    job_run_id: Optional[str] = None
    actor: str = "system"


@dataclass
class Observation:
    run_id: str
    source_system: str
    collector: str
    collector_version: str
    entity_kind: str
    source_entity_id: str
    observed_at: datetime
    display_name: Optional[str] = None
    parent_source_entity_id: Optional[str] = None
    platform: Optional[str] = None
    provider: Optional[str] = None
    model_family: Optional[str] = None
    owner: Optional[str] = None
    tags: Dict[str, str] = field(default_factory=dict)
    config: Dict[str, Any] = field(default_factory=dict)
    relationships: List[Dict[str, str]] = field(default_factory=list)
    probe_state: str = PROBE_AVAILABLE
    provenance_class: str = PROVENANCE_ORGANIC
    sample_run_id: Optional[str] = None

    @property
    def entity_id(self) -> str:
        return ai_entity_id(self.entity_kind, self.source_system, self.source_entity_id)

    def hash_fields(self) -> Dict[str, Any]:
        # Everything that describes the asset, nothing that describes the run.
        return {
            "entity_kind": self.entity_kind,
            "source_system": self.source_system,
            "source_entity_id": self.source_entity_id,
            "display_name": self.display_name,
            "parent_source_entity_id": self.parent_source_entity_id,
            "platform": self.platform,
            "provider": self.provider,
            "model_family": self.model_family,
            "owner": self.owner,
            "tags": self.tags,
            "config": self.config,
            "relationships": self.relationships,
        }

    @property
    def content_hash(self) -> str:
        return content_hash(self.hash_fields())


@dataclass
class IntakeRecord:
    intake_id: str
    title: str
    state: str
    owner_email: str
    source_system: str
    ingest_source: str
    ingest_run_id: str
    business_unit: Optional[str] = None
    risk_tier: Optional[str] = None
    platform: Optional[str] = None
    provider: Optional[str] = None
    model_family: Optional[str] = None
    intended_use: Optional[str] = None
    approved_at: Optional[datetime] = None
    review_due_at: Optional[datetime] = None
    source_record_id: Optional[str] = None
    attributes: Dict[str, Any] = field(default_factory=dict)
    provenance_class: str = PROVENANCE_ORGANIC
    sample_run_id: Optional[str] = None

    def hash_fields(self) -> Dict[str, Any]:
        return {
            "intake_id": self.intake_id,
            "title": self.title,
            "state": self.state,
            "owner_email": self.owner_email,
            "business_unit": self.business_unit,
            "risk_tier": self.risk_tier,
            "platform": self.platform,
            "provider": self.provider,
            "model_family": self.model_family,
            "intended_use": self.intended_use,
            "approved_at": self.approved_at.isoformat() if self.approved_at else None,
            "review_due_at": self.review_due_at.isoformat() if self.review_due_at else None,
            "source_record_id": self.source_record_id,
            "attributes": self.attributes,
        }

    @property
    def content_hash(self) -> str:
        return content_hash(self.hash_fields())


@dataclass
class Finding:
    finding_id: str
    finding_type: str
    rule_id: str
    severity: str
    entity_id: Optional[str]
    entity_kind: Optional[str]
    intake_id: Optional[str]
    match_rule: Optional[str]
    match_score: Optional[float]
    evidence: Dict[str, Any] = field(default_factory=dict)
    provenance_class: str = PROVENANCE_ORGANIC
    sample_run_id: Optional[str] = None


def finding_id_for(finding_type: str, entity_id: Optional[str], intake_id: Optional[str], rule_id: str) -> str:
    """Idempotency key (DESIGN.md 5.4): identical conditions on re-run map to
    the same row, so reconciliation MERGEs instead of duplicating."""
    raw = f"{finding_type}|{entity_id or ''}|{intake_id or ''}|{rule_id}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass
class ControlResult:
    entity_id: str
    entity_kind: str
    control_id: str
    control_version: str
    status: str
    signal_source: str
    evidence: Dict[str, Any] = field(default_factory=dict)
