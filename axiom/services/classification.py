"""A9.4 Classification Recommendation Workflow.

Evidence-gathering and steward review for suggested column classifications.
This service never auto-applies policies; on approve, the approved
classification writes as a Databricks column tag via the existing UC tag
APIs. Remediation suggestions are informational only.
"""

from __future__ import annotations

import json
import math
import re
import uuid
from typing import Any, Dict, List, Optional, Sequence


# ----------------------------------------------------------------------
# Pattern matchers. Small and targeted per scope discipline: under 20
# regexes, no ML. Each entry is (name, pattern, suggested_sensitivity).
# ``suggested_sensitivity`` becomes the default recommendation payload
# when a pattern matches.
# ----------------------------------------------------------------------
EVIDENCE_PATTERNS: List[Dict[str, Any]] = [
    {
        "key": "ssn",
        "label": "Social Security Number",
        "regex": re.compile(r"(?:^|_)(ssn|social_?security(?:_?number)?)(?:$|_)", re.IGNORECASE),
        "sensitivity": "restricted",
        "tier": "pii",
        "certification": "classified",
        "confidence": 0.95,
    },
    {
        "key": "email",
        "label": "Email address",
        "regex": re.compile(r"(?:^|_)(email|e_mail|email_address|contact_email)(?:$|_)", re.IGNORECASE),
        "sensitivity": "confidential",
        "tier": "pii",
        "certification": "classified",
        "confidence": 0.85,
    },
    {
        "key": "phone",
        "label": "Phone number",
        "regex": re.compile(
            r"(?:^|_)(phone(?:_?number)?|mobile(?:_?number)?|cell|tel|telephone)(?:$|_)",
            re.IGNORECASE,
        ),
        "sensitivity": "confidential",
        "tier": "pii",
        "certification": "classified",
        "confidence": 0.8,
    },
    {
        "key": "credit_card",
        "label": "Credit card number",
        "regex": re.compile(
            r"(?:^|_)(credit_?card(?:_?number)?|cc_?num(?:ber)?|card_?num(?:ber)?|pan)(?:$|_)",
            re.IGNORECASE,
        ),
        "sensitivity": "restricted",
        "tier": "pci",
        "certification": "classified",
        "confidence": 0.95,
    },
    {
        "key": "dob",
        "label": "Date of birth",
        "regex": re.compile(
            r"(?:^|_)(dob|date_?of_?birth|birth_?date|birthday)(?:$|_)",
            re.IGNORECASE,
        ),
        "sensitivity": "confidential",
        "tier": "pii",
        "certification": "classified",
        "confidence": 0.9,
    },
    {
        "key": "account_number",
        "label": "Account number",
        "regex": re.compile(
            r"(?:^|_)(account_?num(?:ber)?|acct_?num(?:ber)?|bank_?account|iban|routing_?number)(?:$|_)",
            re.IGNORECASE,
        ),
        "sensitivity": "restricted",
        "tier": "financial",
        "certification": "classified",
        "confidence": 0.9,
    },
]


_TAG_SENSITIVITY_KEYS = {"sensitivity", "pii", "classification"}
_COMMENT_SENSITIVITY_KEYWORDS = ("pii", "sensitive", "confidential", "gdpr")


# ----------------------------------------------------------------------
# Helpers.
# ----------------------------------------------------------------------
def redact_sample_values(values: Sequence[Any], sensitivity_hint: str | None) -> List[str]:
    """Redact sample values when the sensitivity hint signals PII/high sensitivity.

    Returns ``["***"] * len(values)`` when redaction applies, otherwise the
    values coerced to strings.
    """
    normalized_hint = str(sensitivity_hint or "").strip().lower()
    if normalized_hint in {"pii", "restricted", "confidential", "high", "sensitive"}:
        return ["***"] * len(list(values))
    return [str(value) for value in values]


def _split_fqn(asset_fqn: str) -> tuple[str, str, str]:
    parts = [part.strip() for part in str(asset_fqn or "").split(".") if part.strip()]
    if len(parts) != 3:
        raise ValueError(f"asset_fqn must be a 3-part UC name; got '{asset_fqn}'")
    return parts[0], parts[1], parts[2]


def _name_matches(column_name: str, pattern: re.Pattern[str]) -> bool:
    name = str(column_name or "").strip()
    if not name:
        return False
    # Accept both full-name matches and word-boundary matches for patterns.
    return bool(pattern.search(f"_{name}_"))


def _tag_evidence(tags: Any) -> List[Dict[str, Any]]:
    if not tags:
        return []
    collected: List[Dict[str, Any]] = []
    if isinstance(tags, dict):
        items = tags.items()
    else:
        try:
            items = [(t.get("name") if isinstance(t, dict) else str(t), t.get("value") if isinstance(t, dict) else "") for t in tags]
        except Exception:
            return []
    for raw_key, raw_value in items:
        key = str(raw_key or "").strip().lower()
        if not key:
            continue
        if key in _TAG_SENSITIVITY_KEYS:
            collected.append(
                {
                    "source": "uc_tag",
                    "tag": str(raw_key),
                    "value": str(raw_value or ""),
                    "confidence": 0.75,
                }
            )
    return collected


def _comment_evidence(comment: str | None) -> List[Dict[str, Any]]:
    text = str(comment or "").strip()
    if not text:
        return []
    lowered = text.lower()
    hits: List[Dict[str, Any]] = []
    for keyword in _COMMENT_SENSITIVITY_KEYWORDS:
        if keyword in lowered:
            hits.append(
                {
                    "source": "column_comment",
                    "keyword": keyword,
                    "text": text,
                    "confidence": 0.6,
                }
            )
    return hits


def _glossary_evidence(
    column_name: str,
    glossary_terms: Sequence[Dict[str, Any]] | None,
) -> List[Dict[str, Any]]:
    if not glossary_terms:
        return []
    normalized = str(column_name or "").strip().lower()
    if not normalized:
        return []
    matches: List[Dict[str, Any]] = []
    for term in glossary_terms:
        if not isinstance(term, dict):
            continue
        name = str(term.get("name") or "").strip().lower()
        if not name:
            continue
        if name == normalized or name in normalized or normalized in name:
            matches.append(
                {
                    "source": "glossary_match",
                    "termId": str(term.get("term_id") or term.get("termId") or ""),
                    "termName": str(term.get("name") or ""),
                    "confidence": 0.7,
                }
            )
    return matches


def _name_pattern_evidence(column_name: str) -> List[Dict[str, Any]]:
    hits: List[Dict[str, Any]] = []
    for pattern in EVIDENCE_PATTERNS:
        if _name_matches(column_name, pattern["regex"]):
            hits.append(
                {
                    "source": "name_pattern",
                    "pattern": pattern["key"],
                    "label": pattern["label"],
                    "confidence": pattern["confidence"],
                    "suggestedSensitivity": pattern["sensitivity"],
                    "suggestedTier": pattern["tier"],
                    "suggestedCertification": pattern["certification"],
                }
            )
    return hits


def _default_remediation(evidence: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Build informational remediation suggestions from the evidence set.

    Intentionally non-actionable — the steward surface renders these in a
    bullet list with a clear "not auto-applied" caption. No UC policy writes.
    """
    suggestions: List[Dict[str, Any]] = []
    if any(ev.get("source") == "name_pattern" and ev.get("pattern") in {"ssn", "credit_card", "account_number"} for ev in evidence):
        suggestions.append(
            {
                "kind": "mask_column",
                "summary": "Consider applying column masking to restrict visibility of this identifier.",
            }
        )
    if any(ev.get("source") == "name_pattern" and ev.get("pattern") in {"email", "phone", "dob"} for ev in evidence):
        suggestions.append(
            {
                "kind": "access_review",
                "summary": "Schedule an access review to confirm consumers have a legitimate need.",
            }
        )
    if any(ev.get("source") == "uc_tag" for ev in evidence):
        suggestions.append(
            {
                "kind": "tag_alignment",
                "summary": "Existing UC tags suggest a sensitivity posture — confirm the classification matches.",
            }
        )
    return suggestions


# ----------------------------------------------------------------------
# Evidence + recommendation generation.
# ----------------------------------------------------------------------
def generate_recommendations(
    uc: Any,
    asset_fqn: str,
    columns: Sequence[Dict[str, Any]],
    *,
    glossary_terms: Sequence[Dict[str, Any]] | None = None,
) -> List[Dict[str, Any]]:
    """Gather evidence and return a list of recommendation dicts for ``asset_fqn``.

    ``columns`` is a sequence of column records with at least ``column_name``
    and optional ``comment``/``tags`` fields. The UC client is used opportunistically
    to fetch column tags when the passed-in record does not carry them; any UC
    exception is tolerated so the scan never fails-hard on a single column.
    """
    normalized_fqn = str(asset_fqn or "").strip()
    if not normalized_fqn:
        return []
    recommendations: List[Dict[str, Any]] = []
    try:
        catalog, schema, table = _split_fqn(normalized_fqn)
    except ValueError:
        return []
    for column in columns:
        column_name = str(column.get("column_name") or column.get("name") or "").strip()
        if not column_name:
            continue
        # Resolve tags WITHOUT collapsing an empty list to None. The prior
        # `column.get("tags") or column.get("tagEntries")` pattern treated
        # `tags = []` (a column with zero tags — the common case) as "no
        # data" and re-fetched from UC per column. On a 50-column table
        # that meant 50 serial UC round-trips and pushed the scan past the
        # 60s edge-proxy timeout. Now: only fall back to a per-column UC
        # query when BOTH the upstream fields are literally absent (None).
        tags = column.get("tags")
        if tags is None:
            tags = column.get("tagEntries")
        if tags is None and uc is not None and hasattr(uc, "get_column_tags"):
            try:
                tag_df = uc.get_column_tags(catalog, schema, table, column_name)
                if tag_df is not None and hasattr(tag_df, "to_dict"):
                    tags = tag_df.to_dict(orient="records")
            except Exception:
                tags = None
        evidence: List[Dict[str, Any]] = []
        evidence.extend(_name_pattern_evidence(column_name))
        evidence.extend(_tag_evidence(tags))
        evidence.extend(_comment_evidence(column.get("comment")))
        evidence.extend(_glossary_evidence(column_name, glossary_terms))
        if not evidence:
            continue
        # Choose the highest-confidence pattern-driven suggestion.
        pattern_hits = [ev for ev in evidence if ev.get("source") == "name_pattern"]
        top = max(pattern_hits, key=lambda ev: ev.get("confidence") or 0) if pattern_hits else None
        suggested_sensitivity = (top or {}).get("suggestedSensitivity")
        suggested_tier = (top or {}).get("suggestedTier")
        suggested_certification = (top or {}).get("suggestedCertification")
        # Fallback defaults when only tag/comment/glossary evidence exists.
        if not suggested_sensitivity:
            if any(ev.get("source") == "uc_tag" for ev in evidence):
                suggested_sensitivity = "confidential"
            elif any(ev.get("source") == "column_comment" for ev in evidence):
                suggested_sensitivity = "confidential"
            else:
                suggested_sensitivity = "internal"
        remediation = _default_remediation(evidence)
        recommendation_id = uuid.uuid4().hex
        recommendations.append(
            {
                "recommendation_id": recommendation_id,
                "asset_fqn": normalized_fqn,
                "column_name": column_name,
                "suggested_sensitivity": suggested_sensitivity,
                "suggested_tier": suggested_tier,
                "suggested_certification": suggested_certification,
                "evidence_json": json.dumps(evidence),
                "sample_redacted": True,
                "sample_values_json": "",
                "status": "pending",
                "remediation_suggestions_json": json.dumps(remediation),
            }
        )
    return recommendations


# ----------------------------------------------------------------------
# Persistence + review.
# ----------------------------------------------------------------------
def persist_recommendations(
    store: Any,
    recommendations: Sequence[Dict[str, Any]],
    *,
    actor_email: str = "system",
    actor_role: str = "system",
    request_id: str | None = None,
) -> List[str]:
    """Upsert a batch of recommendations. Emits one audit-log row per record.

    Returns the list of recommendation_ids that were persisted.
    """
    rec_ids: List[str] = []
    for record in recommendations or []:
        rec_id = store.upsert_classification_recommendation(
            record, actor_email=actor_email
        )
        rec_ids.append(rec_id)
        try:
            store.append_metadata_audit(
                entity_type="column",
                action="classification_recommended",
                actor_email=actor_email,
                actor_role=actor_role,
                entity_fqn=str(record.get("asset_fqn") or ""),
                column_name=str(record.get("column_name") or ""),
                request_id=request_id,
                after={
                    "recommendationId": rec_id,
                    "suggestedSensitivity": record.get("suggested_sensitivity"),
                    "suggestedTier": record.get("suggested_tier"),
                    "suggestedCertification": record.get("suggested_certification"),
                },
                source="classification",
                status="success",
                detail="classification recommendation generated",
            )
        except Exception:
            # Audit failures must not break the scan loop; the record landed.
            pass
    return rec_ids


def list_recommendations(
    store: Any,
    *,
    status: str | None = None,
    asset_fqn: str | None = None,
) -> List[Dict[str, Any]]:
    df = store.list_classification_recommendations(status=status, asset_fqn=asset_fqn)
    if df is None or getattr(df, "empty", True):
        return []
    records: List[Dict[str, Any]] = []
    for _, row in df.iterrows():
        records.append(_row_to_payload(row))
    return records


def get_recommendation(store: Any, recommendation_id: str) -> Optional[Dict[str, Any]]:
    raw = store.get_classification_recommendation(recommendation_id)
    if not raw:
        return None
    return _row_to_payload(raw)


def _json_or_default(value: Any, default: Any) -> Any:
    text = str(value or "").strip()
    if not text:
        return default
    try:
        return json.loads(text)
    except Exception:
        return default


def _row_to_payload(row: Any) -> Dict[str, Any]:
    def _get(name: str) -> Any:
        if hasattr(row, "get"):
            return row.get(name)
        try:
            return row[name]
        except Exception:
            return None

    def _is_nullish(value: Any) -> bool:
        if value is None:
            return True
        if isinstance(value, float) and not math.isfinite(value):
            return True
        try:
            return bool(value != value)
        except Exception:
            return False

    def _text(value: Any) -> str:
        if _is_nullish(value):
            return ""
        return str(value)

    def _bool(value: Any, *, default: bool = False) -> bool:
        if _is_nullish(value):
            return default
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"1", "true", "yes", "y"}:
                return True
            if normalized in {"0", "false", "no", "n"}:
                return False
        return bool(value)

    evidence = _json_or_default(_get("evidence_json"), [])
    remediation = _json_or_default(_get("remediation_suggestions_json"), [])
    sample_values = _json_or_default(_get("sample_values_json"), [])
    sample_redacted = _bool(_get("sample_redacted"), default=True)
    if sample_redacted:
        # Belt-and-suspenders: never surface persisted sample values when
        # the record is marked redacted.
        sample_values = []
    return {
        "recommendationId": _text(_get("recommendation_id")),
        "assetFqn": _text(_get("asset_fqn")),
        "columnName": _text(_get("column_name")),
        "suggestedSensitivity": _text(_get("suggested_sensitivity")),
        "suggestedTier": _text(_get("suggested_tier")),
        "suggestedCertification": _text(_get("suggested_certification")),
        "evidence": evidence if isinstance(evidence, list) else [],
        "sampleRedacted": sample_redacted,
        "sampleValues": sample_values if isinstance(sample_values, list) else [],
        "status": _text(_get("status")) or "pending",
        "remediationSuggestions": remediation if isinstance(remediation, list) else [],
        "reviewNote": _text(_get("review_note")),
        "reviewedBy": _text(_get("reviewed_by")),
        "reviewedAt": _text(_get("reviewed_at")),
        "createdAt": _text(_get("created_at")),
        "createdBy": _text(_get("created_by")),
        "updatedAt": _text(_get("updated_at")),
        "updatedBy": _text(_get("updated_by")),
    }


_VALID_DECISIONS = {"approved", "rejected", "deferred"}


def review_recommendation(
    store: Any,
    recommendation_id: str,
    *,
    decision: str,
    reviewer: str,
    reviewer_role: str = "steward",
    note: str | None = None,
    uc: Any = None,
    request_id: str | None = None,
) -> Dict[str, Any]:
    """Transition a recommendation pending -> approved|rejected|deferred.

    On approve, attempts to write the suggested classification as a column
    tag via the existing UC tag APIs. If the UC write fails (or no UC client
    was supplied), the approval is still recorded in the store and an
    apply-side TODO is appended to the remediation_suggestions_json entry.
    """
    normalized = str(decision or "").strip().lower()
    if normalized not in _VALID_DECISIONS:
        raise ValueError(f"decision must be one of {sorted(_VALID_DECISIONS)}; got '{decision}'")
    existing = store.get_classification_recommendation(recommendation_id)
    if not existing:
        raise LookupError(f"recommendation {recommendation_id!r} not found")
    before_status = str(existing.get("status") or "pending")
    tag_apply_result: Dict[str, Any] | None = None
    if normalized == "approved":
        tag_apply_result = _apply_classification_tag(uc, existing)
    store.set_classification_recommendation_status(
        recommendation_id,
        status=normalized,
        reviewer=reviewer,
        review_note=note,
    )
    audit_action_map = {
        "approved": "classification_approved",
        "rejected": "classification_rejected",
        "deferred": "classification_deferred",
    }
    try:
        store.append_metadata_audit(
            entity_type="column",
            action=audit_action_map[normalized],
            actor_email=reviewer,
            actor_role=reviewer_role or "steward",
            entity_fqn=str(existing.get("asset_fqn") or ""),
            column_name=str(existing.get("column_name") or ""),
            request_id=request_id,
            before={"status": before_status},
            after={
                "status": normalized,
                "reviewNote": note,
                "tagApplied": bool(tag_apply_result and tag_apply_result.get("applied")),
                "tagError": (tag_apply_result or {}).get("error"),
            },
            source="classification",
            status="success",
            detail=(
                f"classification {normalized} by {reviewer}"
                + (f"; {note}" if note else "")
            ),
        )
    except Exception:
        pass
    updated = store.get_classification_recommendation(recommendation_id)
    payload = _row_to_payload(updated) if updated else {}
    if tag_apply_result:
        payload["tagApply"] = tag_apply_result
    return payload


def _apply_classification_tag(
    uc: Any,
    record: Dict[str, Any],
) -> Dict[str, Any]:
    """Best-effort column-tag write for the approved classification."""
    result: Dict[str, Any] = {"applied": False, "error": None, "tags": {}}
    if uc is None or not hasattr(uc, "set_column_tags"):
        result["error"] = "uc client does not expose set_column_tags; recommend applying tag manually"
        return result
    asset_fqn = str(record.get("asset_fqn") or "")
    column_name = str(record.get("column_name") or "")
    try:
        catalog, schema, table = _split_fqn(asset_fqn)
    except ValueError as exc:
        result["error"] = str(exc)
        return result
    tags: Dict[str, str] = {}
    sensitivity = str(record.get("suggested_sensitivity") or "").strip()
    tier = str(record.get("suggested_tier") or "").strip()
    certification = str(record.get("suggested_certification") or "").strip()
    if sensitivity:
        tags["sensitivity"] = sensitivity
    if tier:
        tags["classification"] = tier
    if certification:
        tags["classification_state"] = certification
    if not tags:
        result["error"] = "no suggested classification values to apply"
        return result
    try:
        uc.set_column_tags(catalog, schema, table, column_name, tags)
        result["applied"] = True
        result["tags"] = tags
    except Exception as exc:
        result["error"] = f"{exc.__class__.__name__}: {exc}"
    return result


# Re-export for the API surface to reference by name.
__all__ = [
    "EVIDENCE_PATTERNS",
    "generate_recommendations",
    "persist_recommendations",
    "list_recommendations",
    "get_recommendation",
    "review_recommendation",
    "redact_sample_values",
]
