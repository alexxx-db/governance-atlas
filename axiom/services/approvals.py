"""Approval gate for governance metadata mutations.

Non-admin writers (role=writer) propose metadata changes; the gate
intercepts their writes, stashes the full proposed patch on a pending
change_request (reusing the existing v5 task-backed workflow), and
returns a `queued` envelope instead of applying to Unity Catalog.
Stewards and admins bypass the gate and apply directly.

When an approver flips a queued request to `approved`, the consumer
re-reads the stored patch and applies it with `bypass_approval=True`
so the same service helper runs — no duplicate "apply" code path.

Design notes
------------
- The patch payload lives in `new_uc_tags` (the `new_uc_tags_json`
  column). We wrap it in a `{__kind__, __payload__}` envelope so the
  consumer can dispatch by kind (`asset-metadata`, `column-metadata`,
  etc.) and re-inflate the Pydantic model cleanly.
- We do NOT gate notification mutations — those aren't content
  changes. Callers opt in by invoking `gate_asset_metadata_patch`
  before invoking the write; helpers that don't call the gate simply
  go through, which is the correct behavior for non-content paths.
- Stewards bypass. The previous iteration accidentally queued
  steward edits to themselves; the fix is to include "steward" in
  `APPROVAL_BYPASS_ROLES`. Only `writer` is gated.
"""
from __future__ import annotations

import json
from typing import Any, Dict, Optional, Tuple

from axiom.services.capabilities import APPROVAL_ROLES

# Stewards own approvals AND they write to assets they steward; they
# bypass the gate so they don't queue proposals for themselves. Writers
# are the gated role.
APPROVAL_BYPASS_ROLES = {"steward", "admin"}

CHANGE_REQUEST_KIND_ASSET_METADATA = "asset-metadata"
CHANGE_REQUEST_KIND_COLUMN_METADATA = "column-metadata"


def role_bypasses_gate(actor_role: str) -> bool:
    """Return True when the actor can write directly without queuing."""
    return str(actor_role or "").strip().lower() in APPROVAL_BYPASS_ROLES


def role_can_decide(actor_role: str) -> bool:
    """Return True when the actor may approve/reject pending requests."""
    return str(actor_role or "").strip().lower() in APPROVAL_ROLES


def _serialize_patch(kind: str, payload: Dict[str, Any]) -> Dict[str, str]:
    return {
        "__kind__": str(kind or ""),
        "__payload__": json.dumps(payload or {}, sort_keys=True, ensure_ascii=False),
    }


def _deserialize_patch(stored: Optional[Dict[str, Any]]) -> Tuple[str, Dict[str, Any]]:
    if not isinstance(stored, dict):
        return "", {}
    kind = str(stored.get("__kind__") or "")
    raw = stored.get("__payload__")
    if isinstance(raw, dict):
        return kind, raw
    if not isinstance(raw, str) or not raw.strip():
        return kind, {}
    try:
        decoded = json.loads(raw)
    except (TypeError, ValueError):
        return kind, {}
    return kind, decoded if isinstance(decoded, dict) else {}


def gate_asset_metadata_patch(
    store: Any,
    *,
    actor_email: str,
    actor_role: str,
    asset_fqn: str,
    payload: Dict[str, Any],
    rationale: str = "",
) -> Dict[str, Any]:
    """Gate an asset-metadata patch.

    Returns either:
      - `{"kind": "apply"}` — caller should proceed with the real UC
        write. Admins and stewards hit this branch.
      - `{"kind": "queued", "requestId": "...", "status": "pending"}` —
        the proposal was stashed on a pending change_request; the
        caller must NOT write to UC. Surface the requestId to the user.
    """
    if role_bypasses_gate(actor_role):
        return {"kind": "apply"}

    tags_payload = _serialize_patch(
        CHANGE_REQUEST_KIND_ASSET_METADATA,
        {
            "assetFqn": str(asset_fqn or ""),
            "rationale": str(rationale or ""),
            "patch": payload or {},
        },
    )
    note_prefix = "Proposed metadata change"
    note_rationale = str(rationale or "").strip()
    note = f"{note_prefix}: {note_rationale}" if note_rationale else note_prefix
    request_id = store.create_change_request(
        created_by=actor_email,
        uc_full_name=asset_fqn,
        new_comment=note,
        new_uc_tags=tags_payload,
        actor_role=actor_role or "reader",
    )
    return {
        "kind": "queued",
        "requestId": str(request_id or ""),
        "status": "pending",
    }


def load_pending_patch(store: Any, request_id: str) -> Tuple[str, Dict[str, Any]]:
    """Re-read a pending change_request and return `(kind, payload)`.

    Used by the approve endpoint — once status flips to `approved`,
    the consumer invokes the real apply helper with the admin bypass.
    Returns `("", {})` when the request can't be re-read or is empty,
    signaling the caller to skip the apply (guards against wiping a
    table description with an empty patch when the stash is corrupt).
    """
    request = store.get_change_request(request_id)
    if not request:
        return "", {}
    return _deserialize_patch(getattr(request, "new_uc_tags", None) or {})
