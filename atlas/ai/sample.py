"""AI governance sample scenario (Phase 1 Step 10).

One definition drives both the dev seed (scripts/seed_ai_sample_data.py,
which creates these as *real* labeled objects, decision D1) and the unit test
that proves each case produces its intended finding through the pure
reconciliation code before anything is created.

Cases (intake -> platform object -> expected outcome):
- AI-SAMPLE-001 approved, provider openai; endpoint tagged 001 serves an
  Anthropic model: matched by tag (M1), found_different (provider), high.
- AI-SAMPLE-003 rejected; endpoint tagged 003 is running: rejected_but_running.
- AI-SAMPLE-004 approved; UC function tool tagged 004: matched, no finding.
- AI-SAMPLE-005 approved, title close to the MCP connection name, same owner:
  M3 ambiguous_match (steward confirms in the walk-through).
- AI-SAMPLE-006 approved 90 days ago, nothing on the platform:
  registered_not_found.
- Registered model with no intake: found_not_registered (medium).

Every created object carries the sample marker the collector recognizes
(endpoint tag ``atlas_sample_run_id`` or ``[atlas-sample:<run>]`` in the
comment); every intake row is written with provenance_class='sample'. The
Databricks-hosted endpoint case is observed organically in dev: provisioning
one would start paid serving compute, so the seed does not create it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

SCHEMA = "atlas_ai_samples"
SECRET_SCOPE = "atlas-ai-sample"
# Placeholder, never a credential: the endpoints are created but never queried.
PLACEHOLDER_SECRET_VALUE = "not-a-real-key-atlas-sample"
INTAKE_TAG_KEY = "edw_intake_id"
TIER_TAG_KEY = "ai_risk_tier"


@dataclass(frozen=True)
class SampleEndpoint:
    name: str
    provider: str  # anthropic | openai
    model: str
    intake_id: str
    tier: str
    usage_tracking: bool


@dataclass(frozen=True)
class SampleIntake:
    intake_id: str
    title: str
    state: str
    provider: Optional[str] = None
    model_family: Optional[str] = None
    risk_tier: Optional[str] = None
    platform: str = "databricks"
    approved_days_ago: int = 60


@dataclass(frozen=True)
class Scenario:
    endpoints: List[SampleEndpoint] = field(default_factory=list)
    mcp_connection: str = "atlas_sample_docs_mcp"
    function_tool: str = "lookup_claim_policy"
    function_intake_id: str = "AI-SAMPLE-004"
    registered_model: str = "claims_triage_model"
    intakes: List[SampleIntake] = field(default_factory=list)


SCENARIO = Scenario(
    endpoints=[
        SampleEndpoint("atlas-sample-claims-assistant", "anthropic", "claude-3-5-haiku-latest", "AI-SAMPLE-001", "high", True),
        SampleEndpoint("atlas-sample-rejected-bot", "openai", "gpt-4o-mini", "AI-SAMPLE-003", "medium", False),
    ],
    intakes=[
        SampleIntake("AI-SAMPLE-001", "Claims assistant", "approved", provider="openai", model_family="gpt-4o", risk_tier="high"),
        SampleIntake("AI-SAMPLE-003", "Unvetted support bot", "rejected", provider="openai"),
        SampleIntake("AI-SAMPLE-004", "Claim policy lookup tool", "approved", risk_tier="low"),
        SampleIntake("AI-SAMPLE-005", "Atlas sample docs MCP server", "approved"),
        SampleIntake("AI-SAMPLE-006", "Fraud scoring model", "approved", approved_days_ago=90),
    ],
)

EXPECTED_FINDINGS = {
    ("found_different", "AI-SAMPLE-001"),
    ("rejected_but_running", "AI-SAMPLE-003"),
    ("ambiguous_match", "AI-SAMPLE-005"),
    ("registered_not_found", "AI-SAMPLE-006"),
    ("found_not_registered", None),
}


def sample_comment(run_id: str, text: str) -> str:
    return f"{text} [atlas-sample:{run_id}]"


def intake_rows(owner_email: str, *, now: Optional[datetime] = None) -> List[Dict[str, object]]:
    """Intake records as the store would hold them (for the seed and tests)."""
    now = now or datetime.now(timezone.utc)
    return [
        {
            "intake_id": i.intake_id,
            "title": i.title,
            "state": i.state,
            "owner_email": owner_email,
            "provider": i.provider,
            "model_family": i.model_family,
            "risk_tier": i.risk_tier,
            "platform": i.platform,
            "approved_at": (now - timedelta(days=i.approved_days_ago)) if i.state == "approved" else None,
        }
        for i in SCENARIO.intakes
    ]
