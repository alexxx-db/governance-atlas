"""Phase 8/10/11/13 — consolidated catalog router.

Groups together:
- custom properties (Phase 8)
- profile (Phase 8)
- quality (Phase 10)
- classifications / domains / data-products / logical column groups (Phase 11)
- audit browser (Phase 13)

Each surface is a thin wrapper around the store; business-logic guards
live in the services modules (custom_properties, quality, export).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import pandas as pd
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from atlas.api.identity import _request_auth_mode, _user_email
from atlas.services import atlas_metrics
from atlas.services import capabilities as capability_service
from atlas.services import custom_properties as cp_service
from atlas.services import databricks_evidence
from atlas.services import input_safety
from atlas.services import quality as quality_service
from atlas.services.assets import normalize_str as _normalize_str
from atlas.services.metadata_audit import record_audit_log


def _ts(value: Any) -> Optional[str]:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _as_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _df_records(frame: pd.DataFrame) -> List[Dict[str, Any]]:
    if frame is None or getattr(frame, "empty", True):
        return []
    return [row.to_dict() for _, row in frame.iterrows()]


def _envelope(data: Any, *, source: str = "control_plane", extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    meta: Dict[str, Any] = {
        "authoritative": True,
        "source": source,
        "observedAt": datetime.now(timezone.utc).isoformat(),
    }
    if extra:
        meta.update(extra)
    return {"data": data, "meta": meta, "errors": []}


# -----------------------------------------------------------------------------
# Custom properties (Phase 8)
# -----------------------------------------------------------------------------


class CustomPropertyDefinitionPayload(BaseModel):
    entityKind: str
    propertyKey: str
    displayName: str | None = None
    description: str | None = None
    dataType: str
    enumValues: Optional[List[str]] = None
    isRequired: bool = False
    isMulti: bool = False
    scope: Optional[Dict[str, Any]] = None
    changeSummary: str | None = None

    @field_validator("changeSummary", mode="before")
    @classmethod
    def _sanitize_change_summary(cls, value):
        if value is None:
            return None
        return input_safety.sanitize_markdown(value, field="changeSummary", max_length=2000)


class CustomPropertyAssignmentPayload(BaseModel):
    definitionId: str
    value: Any = None
    entityFqn: str | None = None
    columnName: str | None = None

    @field_validator("definitionId", mode="before")
    @classmethod
    def _sanitize_definition_id(cls, value):
        return input_safety.sanitize_plain_text(value, field="definitionId", max_length=128, allow_empty=False)

    @field_validator("entityFqn", "columnName", mode="before")
    @classmethod
    def _sanitize_optional_identifier(cls, value, info):
        if value is None:
            return None
        return input_safety.sanitize_plain_text(value, field=info.field_name, max_length=512)


def _admin_required(request: Request) -> str:
    from runtime_app import _user_role_slug
    role = _user_role_slug(request)
    if role != "admin":
        raise HTTPException(status_code=403, detail="Admin role required.")
    return role


def _steward_or_admin(request: Request) -> str:
    from runtime_app import _user_role_slug
    role = _user_role_slug(request)
    if role not in ("admin", "steward"):
        raise HTTPException(status_code=403, detail="Steward or admin role required.")
    return role


def _store_read():
    from runtime_app import _ensure_governance_store, _ensure_live_runtime, _store

    _ensure_live_runtime()
    _ensure_governance_store()
    return _store()


def _request_id(request: Request) -> str | None:
    try:
        from runtime_app import _http_request_id

        return _http_request_id(request)
    except Exception:
        return request.headers.get("x-databricks-request-id") or request.headers.get("x-request-id")


def _require_open_asset(entity_fqn: str, request: Request) -> None:
    from runtime_app import _asset_is_openable

    if not _asset_is_openable(entity_fqn, request):
        raise HTTPException(status_code=404, detail="Asset not found or not visible.")


def _custom_property_assignment_snapshot(
    store,
    *,
    definition_id: str,
    entity_fqn: str | None,
    column_name: str | None,
) -> list[dict[str, Any]]:
    try:
        frame = store.list_custom_property_assignments(
            entity_fqn=entity_fqn,
            column_name=column_name,
        )
    except Exception:
        return []
    rows = _df_records(frame)
    return [
        row
        for row in rows
        if str(row.get("definition_id") or "") == str(definition_id)
    ]


def api_list_custom_property_definitions(
    request: Request,
    entityKind: Optional[str] = None,
) -> JSONResponse:
    store = _store_read()
    try:
        frame = store.list_custom_property_definitions(entity_kind=entityKind)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to list definitions: {exc}")
    rows = _df_records(frame)
    for row in rows:
        for ts_key in ("created_at", "updated_at"):
            row[ts_key] = _ts(row.get(ts_key))
    return JSONResponse(status_code=200, content=_envelope(rows))


def api_create_custom_property_definition(
    payload: CustomPropertyDefinitionPayload,
    request: Request,
) -> JSONResponse:
    _admin_required(request)
    actor = _user_email(request) or "unknown"
    try:
        normalized = cp_service.normalize_definition_payload(payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    store = _store_read()
    definition_id = cp_service.new_id()
    try:
        store.insert_custom_property_definition(
            definition_id=definition_id,
            entity_kind=normalized["entityKind"],
            property_key=normalized["propertyKey"],
            display_name=normalized["displayName"],
            description=normalized["description"],
            data_type=normalized["dataType"],
            enum_values=normalized["enumValues"] or None,
            is_required=normalized["isRequired"],
            is_multi=normalized["isMulti"],
            scope=normalized["scope"] or None,
            created_by=actor,
        )
        store.insert_custom_property_definition_version(
            version_id=cp_service.new_id(),
            definition_id=definition_id,
            version_number=1,
            snapshot_json=cp_service.definition_snapshot_json(normalized),
            change_summary=payload.changeSummary,
            recorded_by=actor,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to create definition: {exc}")
    record_audit_log(
        entity_type="custom_property_definition",
        action="created",
        actor_email=actor,
        actor_role="admin",
        entity_id=definition_id,
        request_id=_request_id(request),
        after=normalized,
        detail=payload.changeSummary,
        fail_closed=True,
    )
    return JSONResponse(
        status_code=201,
        content=_envelope({"definitionId": definition_id, **normalized}),
    )


def api_upsert_custom_property_assignment(
    payload: CustomPropertyAssignmentPayload,
    request: Request,
) -> JSONResponse:
    role = _steward_or_admin(request)
    actor = _user_email(request) or "unknown"
    store = _store_read()
    try:
        defs = store.list_custom_property_definitions(state="active")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to resolve definitions: {exc}")
    match = None
    if defs is not None and not defs.empty:
        for _, row in defs.iterrows():
            if str(row.get("definition_id")) == payload.definitionId:
                match = row.to_dict()
                break
    if not match:
        raise HTTPException(status_code=404, detail="Custom property definition not found.")
    enum_values: Optional[List[str]] = None
    raw_enum = match.get("enum_values_json")
    if raw_enum:
        try:
            import json
            enum_values = json.loads(raw_enum)
        except Exception:
            enum_values = None
    entity_fqn = _normalize_str(payload.entityFqn)
    column_name = _normalize_str(payload.columnName)
    entity_kind = str(match.get("entity_kind") or "").lower()
    if entity_kind in {"asset", "column"}:
        if not entity_fqn:
            raise HTTPException(status_code=400, detail="entityFqn is required for asset and column properties.")
        _require_open_asset(entity_fqn, request)
    validation = cp_service.validate_value(
        str(match.get("data_type") or ""),
        payload.value,
        enum_values=enum_values,
        is_required=bool(match.get("is_required")),
        is_multi=bool(match.get("is_multi")),
    )
    if not validation.ok:
        raise HTTPException(status_code=400, detail=validation.reason)
    if entity_kind == "column" and not column_name:
        raise HTTPException(status_code=400, detail="columnName is required for column-scoped properties.")
    assignment_id = cp_service.new_id()
    before = _custom_property_assignment_snapshot(
        store,
        definition_id=payload.definitionId,
        entity_fqn=entity_fqn,
        column_name=column_name,
    )
    expected_assignment = {
        "assignment_id": assignment_id,
        "definition_id": payload.definitionId,
        "definition_version": 1,
        "entity_kind": str(match.get("entity_kind")),
        "entity_fqn": entity_fqn,
        "column_name": column_name,
        "value": validation.value,
        "updated_by": actor,
    }
    record_audit_log(
        entity_type="custom_property_assignment",
        action="upserted",
        actor_email=actor,
        actor_role=role,
        entity_fqn=entity_fqn,
        column_name=column_name,
        request_id=_request_id(request),
        before=before,
        after={
            "definitionId": payload.definitionId,
            "propertyKey": match.get("property_key"),
            "value": validation.value,
            "assignment": expected_assignment,
        },
        fail_closed=True,
    )
    try:
        store.upsert_custom_property_assignment(
            assignment_id=assignment_id,
            definition_id=payload.definitionId,
            definition_version=1,
            entity_kind=str(match.get("entity_kind")),
            entity_fqn=entity_fqn,
            column_name=column_name,
            value=validation.value,
            actor_email=actor,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to persist assignment: {exc}")
    return JSONResponse(
        status_code=200,
        content=_envelope({
            "assignmentId": assignment_id,
            "propertyKey": match.get("property_key"),
            "value": validation.value,
        }),
    )


def api_asset_custom_properties(
    asset_fqn: str,
    request: Request,
) -> JSONResponse:
    asset_fqn = _normalize_str(asset_fqn)
    if not asset_fqn:
        raise HTTPException(status_code=400, detail="asset_fqn is required.")
    _require_open_asset(asset_fqn, request)
    store = _store_read()
    try:
        frame = store.list_custom_property_assignments(entity_fqn=asset_fqn)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to list assignments: {exc}")
    rows = _df_records(frame)
    import json
    for row in rows:
        for key in ("created_at", "updated_at"):
            row[key] = _ts(row.get(key))
        value_raw = row.pop("value_json", None)
        if value_raw:
            try:
                row["value"] = json.loads(value_raw)
            except Exception:
                row["value"] = value_raw
        else:
            row["value"] = None
    return JSONResponse(status_code=200, content=_envelope(rows))


# -----------------------------------------------------------------------------
# Profile (Phase 8)
# -----------------------------------------------------------------------------


def api_run_asset_profile(asset_fqn: str, request: Request) -> JSONResponse:
    """Phase 8 — trigger a profile run for an asset.
    Steward/admin gated. Runs synchronously (no background queue) so
    the caller gets the new profile_run_id back in the response.
    Large/expensive tables should use the background runner via the
    profile work item type."""
    from runtime_app import _ensure_governance_store, _ensure_live_runtime, _asset_detail_payload, _store, _uc_for_request
    from atlas.services import profile_runner

    role = _steward_or_admin(request)
    _ensure_live_runtime()
    try:
        _ensure_governance_store()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Governance store not ready: {exc}")
    actor = _user_email(request) or "unknown"
    asset_fqn = _normalize_str(asset_fqn)
    if not asset_fqn:
        raise HTTPException(status_code=400, detail="asset_fqn is required.")
    _require_open_asset(asset_fqn, request)
    try:
        detail = _asset_detail_payload(asset_fqn, request=request, sections=["schema"])
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"Asset not available: {exc}")
    columns = detail.get("columns") or []
    uc_client = _uc_for_request(request)
    store = _store()
    try:
        before = store.latest_profile_run_for_entity(asset_fqn)
    except Exception:
        before = None
    result = profile_runner.run_profile(
        store=store,
        uc_client=uc_client,
        asset_fqn=asset_fqn,
        columns=columns,
        actor_email=actor,
        trigger="manual",
        include_top_values=False,
    )
    record_audit_log(
        entity_type="profile_run",
        action="profile-run-executed",
        actor_email=actor,
        actor_role=role,
        entity_fqn=asset_fqn,
        entity_id=result.profile_run_id,
        request_id=_request_id(request),
        before={"latestProfileRun": before} if before else None,
        after={
            "profileRunId": result.profile_run_id,
            "status": result.status,
            "rowCount": result.row_count,
            "columnMetricsWritten": result.column_metrics_written,
            "error": result.error or None,
        },
        source="api",
        status="success" if result.status == "succeeded" else "failed",
        detail=result.error or None,
        fail_closed=True,
    )
    return JSONResponse(
        status_code=200,
        content=_envelope({
            "profileRunId": result.profile_run_id,
            "status": result.status,
            "rowCount": result.row_count,
            "columnMetricsWritten": result.column_metrics_written,
            "error": result.error or None,
        }),
    )


def api_asset_profile(asset_fqn: str, request: Request) -> JSONResponse:
    asset_fqn = _normalize_str(asset_fqn)
    if not asset_fqn:
        raise HTTPException(status_code=400, detail="asset_fqn is required.")
    _require_open_asset(asset_fqn, request)
    from runtime_app import _uc_for_request

    store = _store_read()
    import json
    try:
        run = store.latest_profile_run_for_entity(asset_fqn)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read profile: {exc}")
    try:
        databricks_profile = databricks_evidence.profile_metric_tables_payload(
            _uc_for_request(request),
            asset_fqn,
        )
    except Exception as exc:
        databricks_profile = {
            "state": "unavailable",
            "source": databricks_evidence.PROFILE_METRICS_SOURCE,
            "rows": [],
            "warnings": [str(exc).splitlines()[0][:500]],
        }
    if not run:
        return JSONResponse(
            status_code=200,
            content=_envelope(
                {
                    "run": None,
                    "tableMetrics": None,
                    "columnMetrics": [],
                    "databricksProfile": databricks_profile,
                },
                extra={"degraded": True, "warnings": ["No profile runs recorded for this entity."]},
            ),
        )
    run_id = run.get("profile_run_id")
    try:
        table_frame = store.profile_table_metrics_for_run(run_id)
        column_frame = store.profile_column_metrics_for_run(run_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read profile metrics: {exc}")
    table_rows = _df_records(table_frame)
    column_rows = _df_records(column_frame)
    def _expand(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        for row in rows:
            for key in ("observed_at",):
                row[key] = _ts(row.get(key))
            for json_key in ("detail_json", "quantiles_json", "top_values_json"):
                raw = row.pop(json_key, None)
                if raw:
                    try:
                        row[json_key.replace("_json", "")] = json.loads(raw)
                    except Exception:
                        row[json_key.replace("_json", "")] = None
        return rows
    run_payload = {
        "profileRunId": run_id,
        "entityFqn": run.get("entity_fqn"),
        "trigger": run.get("trigger"),
        "status": run.get("status"),
        "sampleStrategy": run.get("sample_strategy"),
        "sampleRows": _as_int(run.get("sample_rows")),
        "startedAt": _ts(run.get("started_at")),
        "finishedAt": _ts(run.get("finished_at")),
        "notes": run.get("notes"),
    }
    return JSONResponse(
        status_code=200,
        content=_envelope(
            {
                "run": run_payload,
                "tableMetrics": _expand(table_rows)[:1] or None,
                "columnMetrics": _expand(column_rows),
                "databricksProfile": databricks_profile,
            }
        ),
    )


# -----------------------------------------------------------------------------
# Quality (Phase 10)
# -----------------------------------------------------------------------------


class QualityRunRequest(BaseModel):
    suiteId: str | None = None
    trigger: str = "manual"
    rowBudget: int | None = None
    byteBudget: int | None = None
    timeBudgetMs: int | None = None
    summary: Optional[Dict[str, Any]] = None


def api_list_quality_runs(
    request: Request,
    entityFqn: str | None = None,
    suiteId: str | None = None,
    limit: int = 50,
) -> JSONResponse:
    entityFqn = _normalize_str(entityFqn) or None
    if entityFqn:
        _require_open_asset(entityFqn, request)
    store = _store_read()
    try:
        frame = store.list_quality_runs(
            entity_fqn=entityFqn,
            suite_id=suiteId,
            limit=max(1, min(int(limit), 200)),
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to list quality runs: {exc}")
    import json
    rows = _df_records(frame)
    for row in rows:
        row["started_at"] = _ts(row.get("started_at"))
        row["finished_at"] = _ts(row.get("finished_at"))
        raw_summary = row.pop("summary_json", None)
        if raw_summary:
            try:
                row["summary"] = json.loads(raw_summary)
            except Exception:
                row["summary"] = None
        else:
            row["summary"] = None
    return JSONResponse(status_code=200, content=_envelope(rows))


def api_quality_findings(
    request: Request,
    asset: Optional[str] = None,
    severity: Optional[str] = None,
    outcome: Optional[str] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
    limit: int = 200,
) -> JSONResponse:
    """Wave A4 — browseable quality findings for the Evidence quality tab.

    Quality-run results joined with run metadata, filterable by asset /
    severity / outcome / date window. Visibility-scoped like audit evidence:
    rows about assets outside the actor's visible estate are withheld (and
    counted), and the endpoint fails closed when the visibility scope cannot
    be verified — never serving unscoped findings.
    """
    from runtime_app import _ensure_live_runtime, _store_for_read, _visible_assets
    from atlas.api.response import _error_response, _with_meta

    _ensure_live_runtime()
    asset_filter = input_safety.sanitize_plain_text(
        asset, field="asset", max_length=512
    )
    severity_filter = input_safety.sanitize_plain_text(
        severity, field="severity", max_length=64
    )
    outcome_filter = input_safety.sanitize_plain_text(
        outcome, field="outcome", max_length=32
    ).lower()
    since_filter = input_safety.sanitize_plain_text(since, field="since", max_length=64)
    until_filter = input_safety.sanitize_plain_text(until, field="until", max_length=64)
    if outcome_filter and outcome_filter not in quality_service.FINDING_OUTCOME_FILTERS:
        raise HTTPException(
            status_code=400,
            detail="outcome must be one of: passed, failed, errored, skipped, failing.",
        )
    limit_value = max(1, min(_as_int(limit) or 200, 500))

    # Fail-closed visibility scope, same contract as audit evidence: if the
    # visible-asset inventory cannot be read we withhold everything rather
    # than serve findings about assets the actor may not see.
    try:
        visible_frame = _visible_assets(request)
        visible_fqns = [
            _normalize_str(value)
            for value in visible_frame["fqn"].dropna().astype(str).tolist()
            if _normalize_str(value)
        ] if visible_frame is not None and not visible_frame.empty and "fqn" in visible_frame.columns else []
    except Exception:
        return _error_response(
            request,
            status_code=503,
            source="quality-runner+governance-store",
            detail=(
                "Asset visibility scope could not be verified; quality findings are "
                "unavailable rather than exposing out-of-scope assets."
            ),
            state="unavailable",
            capabilities={"rowLevelSecurity": "fail-closed-visible-assets"},
        )
    if asset_filter and asset_filter.lower() not in {
        fqn.lower() for fqn in visible_fqns
    }:
        # Honest 200 (not 404): mirrors api_asset_quality's availability-probe
        # contract for out-of-scope assets referenced from lineage/deep links.
        payload = _with_meta(
            {
                "findings": [],
                "summary": None,
                "state": "unavailable",
                "reason": "Asset is not visible in the current workspace scope.",
                "windowTruncated": False,
                "visibilityScopedRowsExcluded": 0,
            },
            request,
            source="quality-runner+governance-store",
            state="unavailable",
            authoritative=False,
            entity_fqn=asset_filter,
            warnings=["Asset is not visible in the current workspace scope."],
            capabilities={"rowLevelSecurity": "visible-assets-only"},
        )
        return JSONResponse(status_code=200, content=payload)

    findings_payload = quality_service.quality_findings(
        _store_for_read(),
        asset_fqn=asset_filter or None,
        severity=severity_filter or None,
        outcome=outcome_filter or None,
        since=since_filter or None,
        until=until_filter or None,
        limit=limit_value,
        visible_asset_fqns=visible_fqns,
    )
    state = findings_payload.get("state") or "unavailable"
    reason = _normalize_str(findings_payload.get("reason"))
    envelope = _with_meta(
        findings_payload,
        request,
        source="quality-runner+governance-store",
        state=state,
        authoritative=state == "available",
        entity_fqn=asset_filter or None,
        warnings=[reason] if reason else None,
        capabilities={
            "rowLevelSecurity": "visible-assets-only",
            "visibleAssetCount": len(visible_fqns),
            "maxLimit": 500,
            "defaultLimit": 200,
        },
    )
    return JSONResponse(status_code=200, content=envelope)


def api_asset_quality(asset_fqn: str, request: Request) -> JSONResponse:
    asset_fqn = _normalize_str(asset_fqn)
    if not asset_fqn:
        raise HTTPException(status_code=400, detail="asset_fqn is required.")
    from runtime_app import _asset_is_openable, _uc_for_request

    # Availability probe, not a resource fetch: lineage nodes legitimately
    # reference assets outside the actor's scope, and a 404 here spams the
    # browser console on every such node. Answer 200 with an honest
    # unavailable envelope instead.
    if not _asset_is_openable(asset_fqn, request):
        return JSONResponse(
            status_code=200,
            content=_envelope(
                {
                    "runs": [],
                    "results": [],
                    "summary": None,
                    "databricksMonitoring": None,
                    "state": "unavailable",
                    "reason": "Asset is not visible in the current workspace scope.",
                },
                extra={"state": "unavailable"},
            ),
        )

    store = _store_read()
    try:
        results_frame = store.list_quality_run_results(entity_fqn=asset_fqn, limit=200)
        runs_frame = store.list_quality_runs(entity_fqn=asset_fqn, limit=25)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read quality: {exc}")
    try:
        databricks_monitoring = databricks_evidence.quality_monitoring_payload(
            _uc_for_request(request),
            asset_fqn,
        )
    except Exception as exc:
        databricks_monitoring = {
            "state": "unavailable",
            "source": databricks_evidence.QUALITY_MONITORING_SOURCE,
            "rows": [],
            "warnings": [str(exc).splitlines()[0][:500]],
            "summary": {
                "healthStatus": "Unavailable",
                "freshnessStatus": "Unavailable",
                "completenessStatus": "Unavailable",
            },
        }
    import json
    results = _df_records(results_frame)
    for row in results:
        row["executed_at"] = _ts(row.get("executed_at"))
        raw_ev = row.pop("evidence_json", None)
        if raw_ev:
            try:
                row["evidence"] = json.loads(raw_ev)
            except Exception:
                row["evidence"] = None
    runs = _df_records(runs_frame)
    for row in runs:
        row["started_at"] = _ts(row.get("started_at"))
        row["finished_at"] = _ts(row.get("finished_at"))
    summary = quality_service.summarize_run_results(results)
    return JSONResponse(
        status_code=200,
        content=_envelope(
            {
                "runs": runs,
                "results": results,
                "summary": summary,
                "databricksMonitoring": databricks_monitoring,
            }
        ),
    )


def api_asset_databricks_evidence(asset_fqn: str, request: Request) -> JSONResponse:
    asset_fqn = _normalize_str(asset_fqn)
    if not asset_fqn:
        raise HTTPException(status_code=400, detail="asset_fqn is required.")
    from runtime_app import _asset_is_openable, _uc_for_request

    # Same contract as api_asset_quality: availability probe → honest 200
    # unavailable envelope, never console-spamming 404s for out-of-scope
    # lineage neighbors.
    if not _asset_is_openable(asset_fqn, request):
        return JSONResponse(
            status_code=200,
            content=_envelope(
                {
                    "assetFqn": asset_fqn,
                    "state": "unavailable",
                    "reason": "Asset is not visible in the current workspace scope.",
                },
                extra={"state": "unavailable"},
            ),
        )

    try:
        payload = databricks_evidence.asset_databricks_evidence_payload(
            _uc_for_request(request),
            asset_fqn,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        payload = {
            "assetFqn": asset_fqn,
            "qualityMonitoring": {
                "state": "unavailable",
                "source": databricks_evidence.QUALITY_MONITORING_SOURCE,
                "rows": [],
                "warnings": [str(exc).splitlines()[0][:500]],
            },
            "profileMetrics": {
                "state": "unavailable",
                "source": databricks_evidence.PROFILE_METRICS_SOURCE,
                "rows": [],
                "warnings": [str(exc).splitlines()[0][:500]],
            },
            "lakeflow": {
                "state": "unavailable",
                "source": databricks_evidence.LAKEFLOW_SOURCE,
                "jobs": [],
                "pipelines": [],
                "warnings": [str(exc).splitlines()[0][:500]],
            },
            "pipelineEvents": {
                "state": "unavailable",
                "source": databricks_evidence.PIPELINE_EVENT_LOG_SOURCE,
                "rows": [],
                "warnings": [str(exc).splitlines()[0][:500]],
            },
            "provenance": [],
        }
    return JSONResponse(
        status_code=200,
        content=_envelope(
            payload,
            source="databricks-system-tables",
            extra={
                "capabilities": {
                    "dataQualityMonitoring": payload.get("qualityMonitoring", {}).get("state"),
                    "profileMetrics": payload.get("profileMetrics", {}).get("state"),
                    "lakeflow": payload.get("lakeflow", {}).get("state"),
                    "pipelineEvents": payload.get("pipelineEvents", {}).get("state"),
                }
            },
        ),
    )


class QualityRunInlineRequest(BaseModel):
    """Ad-hoc quality run — caller supplies the test cases inline.
    Used by admins + stewards to validate a case set against an asset
    before persisting a quality_suites row."""
    assetFqn: str
    cases: List[Dict[str, Any]] = Field(default_factory=list)
    severity: str = "warn"

    @field_validator("assetFqn", mode="before")
    @classmethod
    def _sanitize_asset_fqn(cls, value):
        return input_safety.sanitize_plain_text(value, field="assetFqn", max_length=512, allow_empty=False)

    @field_validator("severity", mode="before")
    @classmethod
    def _sanitize_severity(cls, value):
        return input_safety.sanitize_allowed(
            value or "warn",
            field="severity",
            allowed=("info", "warn", "critical"),
            default="warn",
        )


def api_run_asset_quality(payload: QualityRunInlineRequest, request: Request) -> JSONResponse:
    """Phase 10 — execute a set of quality test cases inline and
    persist the results. Steward/admin gated because custom_sql
    cases touch arbitrary data."""
    from runtime_app import _asset_is_openable, _ensure_governance_store, _ensure_live_runtime, _store, _uc_for_request
    from atlas.services import quality_runner

    role = _steward_or_admin(request)
    _ensure_live_runtime()
    try:
        _ensure_governance_store()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Governance store not ready: {exc}")
    actor = _user_email(request) or "unknown"
    asset_fqn = _normalize_str(payload.assetFqn)
    if not _asset_is_openable(asset_fqn, request):
        raise HTTPException(status_code=404, detail="Asset not found or not visible.")
    cases: List[quality_runner.TestCaseSpec] = []
    for raw in payload.cases or []:
        if not isinstance(raw, dict):
            continue
        parameters = input_safety.sanitize_json_value(
            dict(raw.get("parameters") or {}),
            field="parameters",
            max_depth=4,
            max_string_length=4000,
        )
        cases.append(
            quality_runner.TestCaseSpec(
                case_id=input_safety.sanitize_plain_text(
                    raw.get("caseId") or uuid.uuid4().hex,
                    field="caseId",
                    max_length=128,
                    allow_empty=False,
                ),
                test_key=input_safety.sanitize_plain_text(
                    raw.get("testKey") or "",
                    field="testKey",
                    max_length=128,
                    allow_empty=False,
                ),
                entity_fqn=asset_fqn,
                parameters=parameters,
                severity=input_safety.sanitize_allowed(
                    raw.get("severity") or payload.severity,
                    field="caseSeverity",
                    allowed=("info", "warn", "critical"),
                    default=payload.severity,
                ),
                column_name=_normalize_str(raw.get("columnName")) or None,
            )
        )
    if not cases:
        raise HTTPException(status_code=400, detail="At least one test case is required.")
    uc_client = _uc_for_request(request)
    store = _store()
    result = quality_runner.run_quality_suite(
        store=store,
        uc_client=uc_client,
        cases=cases,
        suite_id=None,
        trigger="manual",
        actor_email=actor,
    )
    record_audit_log(
        entity_type="quality_run",
        action="quality-run-executed",
        actor_email=actor,
        actor_role=role,
        entity_fqn=asset_fqn,
        entity_id=result.run_id,
        request_id=_request_id(request),
        after={
            "runId": result.run_id,
            "status": result.status,
            "caseCount": len(cases),
            "passed": result.passed,
            "failed": result.failed,
            "errored": result.errored,
            "skipped": result.skipped,
        },
        source="api",
        status="success" if result.status == "succeeded" else "failed",
        fail_closed=True,
    )
    return JSONResponse(
        status_code=200,
        content=_envelope({
            "runId": result.run_id,
            "status": result.status,
            "passed": result.passed,
            "failed": result.failed,
            "errored": result.errored,
            "skipped": result.skipped,
        }),
    )


class QualityCustomSqlRequest(BaseModel):
    targetEntityFqn: str
    sql: str
    rowBudget: int | None = None
    byteBudget: int | None = None
    timeBudgetMs: int | None = None

    @field_validator("targetEntityFqn", mode="before")
    @classmethod
    def _sanitize_target_entity(cls, value):
        return input_safety.sanitize_plain_text(value, field="targetEntityFqn", max_length=512, allow_empty=False)

    @field_validator("sql", mode="before")
    @classmethod
    def _sanitize_sql(cls, value):
        return input_safety.normalize_text(value)


def api_quality_validate_custom_sql(
    payload: QualityCustomSqlRequest,
    request: Request,
) -> JSONResponse:
    _steward_or_admin(request)
    _require_open_asset(payload.targetEntityFqn, request)
    validation = quality_service.validate_custom_sql(
        payload.sql,
        target_entity_fqn=payload.targetEntityFqn,
    )
    budget = quality_service.check_budgets(
        row_budget=payload.rowBudget,
        byte_budget=payload.byteBudget,
        time_budget_ms=payload.timeBudgetMs,
    )
    return JSONResponse(
        status_code=200,
        content=_envelope({
            "sql": {
                "ok": validation.ok,
                "reason": validation.reason,
                "normalized": validation.normalized,
            },
            "budget": {
                "ok": budget.ok,
                "reason": budget.reason,
                "rowBudget": budget.row_budget,
                "byteBudget": budget.byte_budget,
                "timeBudgetMs": budget.time_budget_ms,
            },
        }),
    )


# -----------------------------------------------------------------------------
# Classifications / domains / data products / column groups (Phase 11)
# -----------------------------------------------------------------------------


def api_list_classifications(request: Request) -> JSONResponse:
    store = _store_read()
    try:
        frame = store.list_classifications()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to list classifications: {exc}")
    rows = _df_records(frame)
    for row in rows:
        row["created_at"] = _ts(row.get("created_at"))
        row["updated_at"] = _ts(row.get("updated_at"))
        row["term_count"] = _as_int(row.get("term_count")) or 0
    return JSONResponse(status_code=200, content=_envelope(rows))


def api_get_classification(classification_id: str, request: Request) -> JSONResponse:
    store = _store_read()
    try:
        classifications_frame = store.list_classifications()
        terms_frame = store.list_classification_terms(classification_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read classification: {exc}")
    classification = None
    if classifications_frame is not None and not classifications_frame.empty:
        for _, row in classifications_frame.iterrows():
            if str(row.get("classification_id")) == classification_id:
                classification = row.to_dict()
                break
    if not classification:
        raise HTTPException(status_code=404, detail="Classification not found.")
    terms = _df_records(terms_frame)
    for term in terms:
        term["created_at"] = _ts(term.get("created_at"))
        term["updated_at"] = _ts(term.get("updated_at"))
    classification["created_at"] = _ts(classification.get("created_at"))
    classification["updated_at"] = _ts(classification.get("updated_at"))
    classification["term_count"] = _as_int(classification.get("term_count")) or len(terms)
    return JSONResponse(
        status_code=200,
        content=_envelope({"classification": classification, "terms": terms}),
    )


def api_list_domains(request: Request) -> JSONResponse:
    store = _store_read()
    try:
        frame = store.list_domains()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to list domains: {exc}")
    rows = _df_records(frame)
    for row in rows:
        row["created_at"] = _ts(row.get("created_at"))
        row["updated_at"] = _ts(row.get("updated_at"))
    return JSONResponse(status_code=200, content=_envelope(rows))


def api_list_data_products(request: Request) -> JSONResponse:
    store = _store_read()
    try:
        frame = store.list_data_products()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to list data products: {exc}")
    rows = _df_records(frame)
    for row in rows:
        row["created_at"] = _ts(row.get("created_at"))
        row["updated_at"] = _ts(row.get("updated_at"))
        row["member_count"] = _as_int(row.get("member_count")) or 0
    return JSONResponse(status_code=200, content=_envelope(rows))


def api_list_logical_column_groups(request: Request) -> JSONResponse:
    store = _store_read()
    try:
        frame = store.list_logical_column_groups()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to list column groups: {exc}")
    import json
    rows = _df_records(frame)
    for row in rows:
        row["last_reviewed_at"] = _ts(row.get("last_reviewed_at"))
        row["member_count"] = _as_int(row.get("member_count")) or 0
        row["confidence"] = _as_float(row.get("confidence"))
        raw_rule = row.pop("match_rule_json", None)
        if raw_rule:
            try:
                row["matchRule"] = json.loads(raw_rule)
            except Exception:
                row["matchRule"] = None
        else:
            row["matchRule"] = None
    return JSONResponse(status_code=200, content=_envelope(rows))


def api_get_logical_column_group(group_id: str, request: Request) -> JSONResponse:
    store = _store_read()
    try:
        frame = store.get_logical_column_group(group_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read column group: {exc}")
    if frame is None or frame.empty:
        raise HTTPException(status_code=404, detail="Column group not found.")
    import json
    rows = _df_records(frame)
    header = {
        "groupId": rows[0].get("group_id"),
        "displayName": rows[0].get("display_name"),
        "description": rows[0].get("description"),
        "confidence": _as_float(rows[0].get("confidence")),
        "state": rows[0].get("state"),
        "lastReviewedAt": _ts(rows[0].get("last_reviewed_at")),
        "lastReviewedBy": rows[0].get("last_reviewed_by"),
    }
    raw_rule = rows[0].get("match_rule_json")
    if raw_rule:
        try:
            header["matchRule"] = json.loads(raw_rule)
        except Exception:
            header["matchRule"] = None
    members: List[Dict[str, Any]] = []
    conflicts: Dict[str, set] = {"descriptions": set(), "tags": set(), "glossaryTermIds": set()}
    for row in rows:
        if not row.get("membership_id"):
            continue
        member = {
            "membershipId": row.get("membership_id"),
            "entityFqn": row.get("entity_fqn"),
            "columnName": row.get("column_name"),
            "dataType": row.get("column_data_type"),
            "currentDescription": row.get("current_description"),
            "currentGlossaryTermId": row.get("current_glossary_term_id"),
            "matchConfidence": _as_float(row.get("match_confidence")),
            "lastSeenAt": _ts(row.get("last_seen_at")),
        }
        raw_tags = row.get("current_tags_json")
        if raw_tags:
            try:
                member["currentTags"] = json.loads(raw_tags)
            except Exception:
                member["currentTags"] = None
        if member.get("currentDescription"):
            conflicts["descriptions"].add(str(member["currentDescription"]))
        if member.get("currentGlossaryTermId"):
            conflicts["glossaryTermIds"].add(str(member["currentGlossaryTermId"]))
        current_tags = member.get("currentTags")
        if isinstance(current_tags, list):
            for tag in current_tags:
                conflicts["tags"].add(str(tag))
        members.append(member)
    header["conflictCounts"] = {key: len(value) for key, value in conflicts.items()}
    return JSONResponse(
        status_code=200,
        content=_envelope({"group": header, "members": members}),
    )


# -----------------------------------------------------------------------------
# Audit browser (Phase 13)
# -----------------------------------------------------------------------------


# Only these keys leave /api/audit/events. The endpoint previously returned
# raw store rows (uc_full_name, new_uc_tags_json, pandas-NaN "nan" strings)
# with no visibility scoping, while the Audit Evidence browser whitelisted —
# the same event looked different (and leaked more) depending on the URL.
_AUDIT_EVENT_FIELD_WHITELIST = (
    "displayAuditId",
    "audit_id",
    "auditEventId",
    "entity_type",
    "entity_fqn",
    "column_name",
    "action",
    "source",
    "display_source",
    "status",
    "detail",
    "display_detail",
    "actor_email",
    "actor_role",
    "actorKind",
    "created_at",
    "request_id",
    "displayRequestId",
    "before",
    "after",
    "diffState",
    "diffReason",
    "object_label",
)


def _scrub_audit_value(value: Any) -> Any:
    """Drop pandas NaN leakage: real NaN/NaT and their stringified forms
    ("nan"/"None"/"NaT") must never reach a customer payload."""
    if value is None:
        return None
    if isinstance(value, float) and value != value:
        return None
    if isinstance(value, str) and value.strip().lower() in {"nan", "none", "nat", "null"}:
        return ""
    return value


def api_audit_events(
    request: Request,
    actorEmail: str | None = None,
    entityFqn: str | None = None,
    entityKind: str | None = None,
    action: str | None = None,
    since: str | None = None,
    until: str | None = None,
    limit: int = 200,
) -> JSONResponse:
    # Gate to admins + stewards. Readers should not see audit trails.
    _steward_or_admin(request)
    from runtime_app import _visible_assets

    # Same row-level security as the Audit Evidence browser: fail closed when
    # the visibility scope cannot be established rather than serving the
    # whole unscoped audit ledger.
    try:
        assets_frame = _visible_assets(request)
        visible_fqns = [
            _normalize_str(value)
            for value in (
                assets_frame["fqn"].dropna().astype(str).tolist()
                if assets_frame is not None
                and not getattr(assets_frame, "empty", True)
                and "fqn" in assets_frame.columns
                else []
            )
            if _normalize_str(value)
        ]
    except Exception:
        raise HTTPException(
            status_code=503,
            detail="Audit visibility scope could not be verified; audit events are unavailable rather than unscoped.",
        )
    store = _store_read()
    try:
        frame = store.list_audit_events(
            actor_email=actorEmail,
            entity_fqn=entityFqn,
            entity_kind=entityKind,
            action=action,
            since=since,
            until=until,
            limit=max(1, min(int(limit), 500)),
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read audit events: {exc}")
    import json

    rows = _df_records(frame)
    # Asset-linked events are scoped to the actor-visible estate; events with
    # no entity_fqn (glossary, custom-property definitions) are store-level
    # governance records and stay visible to stewards/admins.
    scoped_rows = atlas_metrics._filter_audit_rows_by_visible_assets(rows, visible_fqns)
    hidden_rows_excluded = len(rows) - len(scoped_rows)
    safe_rows: List[Dict[str, Any]] = []
    for row in scoped_rows:
        if not atlas_metrics._is_customer_visible_audit_row(row):
            continue
        # Shared sanitizer: same displayAuditId derivation ("AUD-" + first 8
        # hex of the event UUID) and diff whitelist as the Audit Evidence
        # browser, so events are joinable across both surfaces.
        safe = atlas_metrics._customer_safe_audit_row(row)
        for key in ("before_json", "after_json"):
            raw = safe.get(key)
            parsed = None
            if raw:
                try:
                    parsed = json.loads(raw)
                except Exception:
                    parsed = None
            safe[key.replace("_json", "")] = parsed
        filtered = {
            key: _scrub_audit_value(safe.get(key))
            for key in _AUDIT_EVENT_FIELD_WHITELIST
            if key in safe
        }
        safe_rows.append(filtered)
    return JSONResponse(
        status_code=200,
        content=_envelope(
            safe_rows,
            extra={
                "rowScope": "visible-assets",
                "hiddenRowsExcluded": hidden_rows_excluded,
                "fieldWhitelist": True,
            },
        ),
    )


# -----------------------------------------------------------------------------
# Phase 14 — Databricks differentiation: access explainer
# -----------------------------------------------------------------------------


def api_access_explainer(asset_fqn: str, request: Request) -> JSONResponse:
    """Phase 14 — "Why can't I access this?" explainer.
    Returns the auth mode, the actor's capability bundle, and a concrete
    remediation list. The asset FQN is optional context — this is
    designed to also work for generic auth diagnostics."""
    from runtime_app import _ensure_live_runtime

    _ensure_live_runtime()
    # Shared core (capabilities.access_explain_summary) so this endpoint and
    # the /360 composite's access block always tell the same access story.
    summary = capability_service.access_explain_summary(
        _request_auth_mode(request),
        _user_email(request) or "unknown",
        _normalize_str(asset_fqn),
    )
    return JSONResponse(status_code=200, content=_envelope(summary))


# -----------------------------------------------------------------------------
# Router factory
# -----------------------------------------------------------------------------


def build_catalog_router() -> APIRouter:
    router = APIRouter(tags=["catalog"])

    # Phase 8 — custom properties
    router.add_api_route(
        "/api/custom-properties/definitions",
        api_list_custom_property_definitions,
        methods=["GET"],
        name="api_list_custom_property_definitions",
    )
    router.add_api_route(
        "/api/custom-properties/definitions",
        api_create_custom_property_definition,
        methods=["POST"],
        name="api_create_custom_property_definition",
    )
    router.add_api_route(
        "/api/custom-properties/assignments",
        api_upsert_custom_property_assignment,
        methods=["POST"],
        name="api_upsert_custom_property_assignment",
    )
    router.add_api_route(
        "/api/assets/{asset_fqn:path}/custom-properties",
        api_asset_custom_properties,
        methods=["GET"],
        name="api_asset_custom_properties",
    )

    # Phase 8 — profile
    router.add_api_route(
        "/api/assets/{asset_fqn:path}/profile/run",
        api_run_asset_profile,
        methods=["POST"],
        name="api_run_asset_profile",
    )
    router.add_api_route(
        "/api/assets/{asset_fqn:path}/profile",
        api_asset_profile,
        methods=["GET"],
        name="api_asset_profile",
    )
    router.add_api_route(
        "/api/assets/{asset_fqn:path}/databricks-evidence",
        api_asset_databricks_evidence,
        methods=["GET"],
        name="api_asset_databricks_evidence",
    )

    # Phase 10 — quality
    router.add_api_route(
        "/api/quality/runs",
        api_list_quality_runs,
        methods=["GET"],
        name="api_list_quality_runs",
    )
    # Wave A4 — Evidence quality tab browse endpoint.
    router.add_api_route(
        "/api/quality/findings",
        api_quality_findings,
        methods=["GET"],
        name="api_quality_findings",
    )
    router.add_api_route(
        "/api/assets/{asset_fqn:path}/quality",
        api_asset_quality,
        methods=["GET"],
        name="api_asset_quality",
    )
    router.add_api_route(
        "/api/quality/custom-sql/validate",
        api_quality_validate_custom_sql,
        methods=["POST"],
        name="api_quality_validate_custom_sql",
    )
    router.add_api_route(
        "/api/quality/run",
        api_run_asset_quality,
        methods=["POST"],
        name="api_run_asset_quality",
    )

    # Phase 11 — classifications / domains / products / column groups
    router.add_api_route(
        "/api/classifications",
        api_list_classifications,
        methods=["GET"],
        name="api_list_classifications",
    )
    router.add_api_route(
        "/api/classifications/{classification_id}",
        api_get_classification,
        methods=["GET"],
        name="api_get_classification",
    )
    router.add_api_route(
        "/api/domains",
        api_list_domains,
        methods=["GET"],
        name="api_list_domains",
    )
    router.add_api_route(
        "/api/data-products",
        api_list_data_products,
        methods=["GET"],
        name="api_list_data_products",
    )
    router.add_api_route(
        "/api/governance/columns",
        api_list_logical_column_groups,
        methods=["GET"],
        name="api_list_logical_column_groups",
    )
    router.add_api_route(
        "/api/governance/columns/{group_id}",
        api_get_logical_column_group,
        methods=["GET"],
        name="api_get_logical_column_group",
    )

    # Phase 13 — audit browser
    router.add_api_route(
        "/api/audit/events",
        api_audit_events,
        methods=["GET"],
        name="api_audit_events",
    )

    # Phase 14 — access explainer
    router.add_api_route(
        "/api/assets/{asset_fqn:path}/access-explain",
        api_access_explainer,
        methods=["GET"],
        name="api_access_explainer",
    )
    def _access_explainer_generic(request: Request) -> JSONResponse:
        return api_access_explainer("", request)

    router.add_api_route(
        "/api/access-explain",
        _access_explainer_generic,
        methods=["GET"],
        name="api_access_explainer_generic",
    )

    return router
