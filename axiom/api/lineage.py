from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from axiom.api.identity import _request_auth_mode
from axiom.api.response import (
    _cacheable_json_response,
    _error_response,
    _with_meta,
)
from axiom.services import capabilities as capability_service
from axiom.services import lineage as lineage_service

_LINEAGE_FULL_WARMING: set[str] = set()
_LINEAGE_FULL_WARMING_LOCK = threading.Lock()
_LINEAGE_RECOMMENDATIONS_WARMING: set[str] = set()
_LINEAGE_RECOMMENDATIONS_WARMING_LOCK = threading.Lock()

# Surface failures from the background lineage-warming thread. Previously
# the warmer caught and dropped every exception silently, which meant a
# slow/flaky system.access.table_lineage warehouse query would never
# populate the cache, and the next user request would see "0 edges"
# without any signal of why. We now log warm-thread exceptions at
# WARNING so they show up in app logs and can be correlated with
# warehouse incidents.
_LINEAGE_LOGGER = logging.getLogger("axiom.lineage")

# The recommendations warmer computes for the MAX limit and each request
# slices afterwards — the cache key deliberately excludes the requested
# limit so `?limit=8` and `?limit=12` share one warm instead of each
# re-scanning the estate from scratch (audited P1: per-limit keys made the
# panel re-warm for 25+ minutes per distinct limit).
_LINEAGE_RECOMMENDATIONS_WARM_LIMIT = 25
# Fresh windows for the recommendations cache: successful payloads serve
# for 180s; failed warm attempts are terminal-but-short so the endpoint
# stops claiming "loading" forever yet retries within a minute.
_LINEAGE_RECOMMENDATIONS_TTL_S = 180
_LINEAGE_RECOMMENDATIONS_FAILED_TTL_S = 60


# How many of the top recommended assets to warm the full lineage build for
# after the recommendations warm completes, and how many to build at once. A
# small pool keeps concurrent system.access.table_lineage load bounded while
# still collapsing 10 serial ~12s builds into a few waves.
_LINEAGE_WARM_AHEAD_COUNT = 10
_LINEAGE_WARM_AHEAD_WORKERS = 3
_LINEAGE_WARM_AHEAD_INFLIGHT: set[str] = set()
_LINEAGE_WARM_AHEAD_GUARD = threading.Lock()


def _warm_recommended_lineage_ahead(
    request_uc,
    store,
    system_uc,
    cache_scope: str,
    recommendations_payload,
) -> None:
    """Pre-warm full lineage for the top-N recommended assets.

    Best-effort and self-guarded: each FQN warms at most once concurrently, and
    an already-fresh full-lineage cache short-circuits the build inside
    lineage_payload. Failures are logged, never raised — this is background
    warming, not a request path.
    """
    from concurrent.futures import ThreadPoolExecutor

    try:
        items = list((recommendations_payload or {}).get("items") or [])
    except Exception:
        return
    fqns: list[str] = []
    for item in items[:_LINEAGE_WARM_AHEAD_COUNT]:
        fqn = ""
        if isinstance(item, dict):
            fqn = str(item.get("fqn") or item.get("assetFqn") or "").strip()
        if fqn and fqn not in fqns:
            fqns.append(fqn)
    if not fqns:
        return

    def _warm_one(fqn: str) -> None:
        key = lineage_service.lineage_cache_key(
            request_uc,
            fqn,
            cache_scope=cache_scope,
            profile=lineage_service.LINEAGE_PROFILE_FULL,
        )
        with _LINEAGE_WARM_AHEAD_GUARD:
            if key in _LINEAGE_WARM_AHEAD_INFLIGHT:
                return
            _LINEAGE_WARM_AHEAD_INFLIGHT.add(key)
        try:
            lineage_service.lineage_payload(
                request_uc,
                store,
                fqn,
                cache_scope=cache_scope,
                system_uc=system_uc,
                profile=lineage_service.LINEAGE_PROFILE_FULL,
            )
        except Exception:
            _LINEAGE_LOGGER.warning(
                "lineage warm-ahead failed for %s", fqn, exc_info=True
            )
        finally:
            with _LINEAGE_WARM_AHEAD_GUARD:
                _LINEAGE_WARM_AHEAD_INFLIGHT.discard(key)

    def _run() -> None:
        with ThreadPoolExecutor(
            max_workers=min(_LINEAGE_WARM_AHEAD_WORKERS, len(fqns)),
            thread_name_prefix="axiom-lineage-warm-ahead",
        ) as pool:
            list(pool.map(_warm_one, fqns))

    threading.Thread(
        target=_run, name="axiom-lineage-warm-ahead", daemon=True
    ).start()


def _no_store(response: JSONResponse) -> JSONResponse:
    """Loading-state envelopes must NEVER be HTTP-cached: with
    `max-age=30, stale-while-revalidate=120` the browser kept re-reading
    the stale "loading" body from its cache, so the frontend polled a
    frozen loading state forever (audited P1 poll-termination defect)."""
    response.headers["Cache-Control"] = "no-store"
    return response


def api_lineage(asset_fqn: str, request: Request) -> JSONResponse:
    from runtime_app import (
        _asset_visibility_record,
        _ensure_live_runtime,
        _lineage_payload,
        _request_cache_scope,
        _store_for_read,
        _uc,
        _uc_for_request,
    )

    _ensure_live_runtime()
    actor_scoped = _request_auth_mode(request) == capability_service.OBO_AVAILABLE_MODE
    try:
        requested_profile = str(request.query_params.get("profile") or "full")
    except Exception:
        requested_profile = "full"
    try:
        refresh_requested = str(request.query_params.get("refresh") or "").strip().lower() in {
            "1",
            "true",
            "yes",
        }
    except Exception:
        refresh_requested = False
    profile_name = lineage_service._lineage_profile(requested_profile)
    if refresh_requested:
        lineage_service.invalidate_lineage_caches(asset_fqn)
    if profile_name == lineage_service.LINEAGE_PROFILE_INITIAL:
        # Poll termination (audited P1): if the FULL build already finished
        # warming, return it here with a terminal state instead of the
        # hard-coded "loading" shell — otherwise the frontend's 3s
        # initial-profile poll never observes a terminal state and spins
        # forever. The peek is cache-only (no build, no SQL) and is
        # best-effort: any failure falls back to the hydrating shell.
        cached_full = None
        try:
            cached_full = lineage_service.cached_lineage_payload(
                _uc_for_request(request),
                asset_fqn,
                cache_scope=_request_cache_scope(request),
                profile=lineage_service.LINEAGE_PROFILE_FULL,
            )
        except Exception:
            cached_full = None
        if cached_full is not None and (
            ((cached_full.get("graphs") or {}).get("data") or {}).get("nodes")
        ):
            build_degraded = (
                str(cached_full.get("buildState") or "").lower() == "degraded"
            )
            build_warnings = [
                str(item)
                for item in (cached_full.get("buildWarnings") or [])
                if str(item or "").strip()
            ]
            return _cacheable_json_response(
                _with_meta(
                    cached_full,
                    request,
                    source="unity-catalog-lineage",
                    # Never claim "available" for a degraded build — the
                    # graph may be missing edges a query failure dropped.
                    state="degraded" if (build_degraded or not actor_scoped) else "available",
                    authoritative=actor_scoped and not build_degraded,
                    entity_fqn=asset_fqn,
                    entity_id=asset_fqn,
                    capabilities={
                        "visibilityState": "unverified",
                        "visibilityScope": "initial-route-warm-full-topology",
                        "lineageProfile": cached_full.get("profile") or "full",
                        "requestedLineageProfile": "initial",
                        "progressive": (cached_full.get("stats") or {}).get("progressive") or {},
                    },
                    warnings=build_warnings,
                ),
                request,
                max_age=5 if build_degraded else 30,
                stale_while_revalidate=15 if build_degraded else 120,
            )
        payload = _lineage_payload(asset_fqn, request=request)
        # State "hydrating" (not a hard-coded "loading"): the shell carries
        # a real focus node while the full profile warms; clients poll
        # until a terminal available/degraded state arrives above.
        return _no_store(
            _cacheable_json_response(
                _with_meta(
                    payload,
                    request,
                    source="unity-catalog-lineage",
                    state="hydrating",
                    authoritative=False,
                    entity_fqn=asset_fqn,
                    entity_id=asset_fqn,
                    capabilities={
                        "visibilityState": "unverified",
                        "visibilityScope": "initial-route-shell",
                        "lineageProfile": payload.get("profile") or "initial",
                        "hydrating": True,
                        "progressive": (payload.get("stats") or {}).get("progressive") or {},
                    },
                    warnings=[
                        "Initial lineage shell does not verify asset visibility; backed detail and full lineage requests remain permission-gated."
                    ],
                ),
                request,
                max_age=5,
                stale_while_revalidate=30,
            )
        )
    visibility = _asset_visibility_record(asset_fqn, request)
    if not visibility.get("openable") and visibility.get("visibilityState") != "loading":
        if visibility.get("visibilityState") == "hidden":
            return _error_response(
                request,
                status_code=404,
                source="unity-catalog-lineage",
                detail="Asset exists but is not visible in the current workspace scope.",
                entity_fqn=asset_fqn,
                entity_id=asset_fqn,
                capabilities={"visibilityState": "hidden"},
            )
        if visibility.get("visibilityState") == "unknown":
            detail = (
                visibility.get("reason")
                or "Asset visibility could not be verified in the current workspace scope."
            )
            return _error_response(
                request,
                status_code=503,
                source="unity-catalog-lineage",
                detail=detail,
                state="unknown",
                entity_fqn=asset_fqn,
                entity_id=asset_fqn,
                capabilities={"visibilityState": "unknown"},
                warnings=[detail],
            )
        return _error_response(
            request,
            status_code=404,
            source="unity-catalog-lineage",
            detail="Asset not found.",
            entity_fqn=asset_fqn,
            entity_id=asset_fqn,
            capabilities={
                "visibilityState": visibility.get("visibilityState") or "missing"
            },
        )
    request_uc = _uc_for_request(request)
    cache_scope = _request_cache_scope(request)
    system_uc = request_uc if actor_scoped else _uc()

    def loading_lineage_response(reason: str) -> JSONResponse:
        initial_payload = lineage_service.lineage_payload(
            request_uc,
            None,
            asset_fqn,
            cache_scope=cache_scope,
            system_uc=system_uc,
            profile=lineage_service.LINEAGE_PROFILE_INITIAL,
        )
        # no-store: a cached "loading" body would freeze the client's poll
        # loop on a stale loading state (audited P1).
        return _no_store(
            _cacheable_json_response(
                _with_meta(
                    initial_payload,
                    request,
                    source="unity-catalog-lineage",
                    state="loading",
                    authoritative=False,
                    entity_fqn=asset_fqn,
                    entity_id=asset_fqn,
                    capabilities={
                        "visibilityState": visibility.get("visibilityState") or "loading",
                        "visibilityScope": "full-lineage-hydrating",
                        "lineageProfile": initial_payload.get("profile") or "initial",
                        "requestedLineageProfile": "full",
                        "hydrating": True,
                        "progressive": (initial_payload.get("stats") or {}).get("progressive") or {},
                    },
                    warnings=[reason],
                ),
                request,
                max_age=5,
                stale_while_revalidate=30,
            )
        )

    cached_full = lineage_service.cached_lineage_payload(
        request_uc,
        asset_fqn,
        cache_scope=cache_scope,
        profile=lineage_service.LINEAGE_PROFILE_FULL,
    )
    if cached_full is None:
        warm_key = lineage_service.lineage_cache_key(
            request_uc,
            asset_fqn,
            cache_scope=cache_scope,
            profile=lineage_service.LINEAGE_PROFILE_FULL,
        )
        with _LINEAGE_FULL_WARMING_LOCK:
            should_warm = warm_key not in _LINEAGE_FULL_WARMING
            if should_warm:
                _LINEAGE_FULL_WARMING.add(warm_key)

        if should_warm:
            store = _store_for_read()

            def warm_full_lineage() -> None:
                try:
                    try:
                        lineage_service.lineage_payload(
                            request_uc,
                            store,
                            asset_fqn,
                            cache_scope=cache_scope,
                            system_uc=system_uc,
                            profile=lineage_service.LINEAGE_PROFILE_FULL,
                        )
                    except Exception:
                        # Log instead of swallowing — silent failures
                        # here were the root cause of "0 edges" for
                        # assets the user could see populated in UC.
                        _LINEAGE_LOGGER.warning(
                            "lineage warmer failed for %s",
                            asset_fqn,
                            exc_info=True,
                        )
                finally:
                    with _LINEAGE_FULL_WARMING_LOCK:
                        _LINEAGE_FULL_WARMING.discard(warm_key)

            threading.Thread(
                target=warm_full_lineage,
                name=f"axiom-lineage-full-warm-{asset_fqn}",
                daemon=True,
            ).start()

        if visibility.get("visibilityState") == "loading":
            return loading_lineage_response(
                visibility.get("reason")
                or "Lineage is hydrating after actor-visible inventory starts."
            )
        if visibility.get("openable"):
            return loading_lineage_response(
                "Full lineage topology is hydrating from Unity Catalog system lineage tables."
            )

    if not visibility.get("openable"):
        if visibility.get("visibilityState") == "loading":
            if cached_full is not None and (
                len(((cached_full.get("graphs") or {}).get("data") or {}).get("nodes") or [])
                > 1
                or len(((cached_full.get("graphs") or {}).get("operational") or {}).get("nodes") or [])
                > 1
            ):
                payload = cached_full
                return _cacheable_json_response(
                    _with_meta(
                        payload,
                        request,
                        source="unity-catalog-lineage",
                        state="degraded",
                        authoritative=False,
                        entity_fqn=asset_fqn,
                        entity_id=asset_fqn,
                        capabilities={
                            "visibilityState": "loading",
                            "includesOperationalContext": bool(
                                (payload.get("graphs") or {}).get("operational")
                            ),
                            "visibilityScope": "workspace-app-principal-cached-topology",
                            "lineageProfile": payload.get("profile") or "full",
                            "progressive": (payload.get("stats") or {}).get("progressive") or {},
                        },
                        warnings=[
                            visibility.get("reason")
                            or "Actor-visible inventory is still hydrating; showing cached workspace-scoped lineage topology.",
                            "Lineage is shown from workspace-scoped app-principal reads; per-user authorization is not available.",
                        ],
                    ),
                    request,
                    max_age=30,
                    stale_while_revalidate=120,
                )
            return loading_lineage_response(
                visibility.get("reason")
                or "Lineage is hydrating while actor-visible inventory catches up."
            )
        if visibility.get("visibilityState") == "hidden":
            return _error_response(
                request,
                status_code=404,
                source="unity-catalog-lineage",
                detail="Asset exists but is not visible in the current workspace scope.",
                entity_fqn=asset_fqn,
                entity_id=asset_fqn,
                capabilities={"visibilityState": "hidden"},
            )
        if visibility.get("visibilityState") == "unknown":
            detail = (
                visibility.get("reason")
                or "Asset visibility could not be verified in the current workspace scope."
            )
            return _error_response(
                request,
                status_code=503,
                source="unity-catalog-lineage",
                detail=detail,
                state="unknown",
                entity_fqn=asset_fqn,
                entity_id=asset_fqn,
                capabilities={"visibilityState": "unknown"},
                warnings=[detail],
            )
        return _error_response(
            request,
            status_code=404,
            source="unity-catalog-lineage",
            detail="Asset not found.",
            entity_fqn=asset_fqn,
            entity_id=asset_fqn,
            capabilities={
                "visibilityState": visibility.get("visibilityState") or "missing"
            },
        )
    payload = cached_full or _lineage_payload(asset_fqn, request=request)
    # Build honesty (audited P0): a build that hit a lineage query failure
    # is state="degraded", never authoritative, and gets a short HTTP cache
    # so browsers retry quickly. buildState/buildWarnings come from the
    # service layer (see _build_lineage_payload).
    build_degraded = str(payload.get("buildState") or "").lower() == "degraded"
    build_warnings = [
        str(item)
        for item in (payload.get("buildWarnings") or [])
        if str(item or "").strip()
    ]
    scope_warnings = (
        []
        if actor_scoped
        else [
            "Lineage is shown from workspace-scoped app-principal reads; per-user authorization is not available."
        ]
    )
    return _cacheable_json_response(
        _with_meta(
            payload,
            request,
            source="unity-catalog-lineage",
            state="available" if (actor_scoped and not build_degraded) else "degraded",
            authoritative=actor_scoped and not build_degraded,
            entity_fqn=asset_fqn,
            entity_id=asset_fqn,
            capabilities={
                "visibilityState": visibility.get("visibilityState"),
                "includesOperationalContext": bool(
                    (payload.get("graphs") or {}).get("operational")
                ),
                "visibilityScope": (
                    capability_service.ACTOR_SCOPED_VISIBILITY
                    if actor_scoped
                    else capability_service.WORKSPACE_APP_PRINCIPAL_VISIBILITY
                ),
                "lineageProfile": payload.get("profile") or "full",
                "progressive": (payload.get("stats") or {}).get("progressive") or {},
            },
            warnings=[*build_warnings, *scope_warnings],
        ),
        request,
        max_age=5 if build_degraded else 60,
        stale_while_revalidate=15 if build_degraded else 240,
    )


def api_lineage_recommendations(
    request: Request,
    limit: int = 8,
) -> JSONResponse:
    from runtime_app import (
        _ensure_live_runtime,
        _request_cache_scope,
        _store_for_read,
        _uc,
        _uc_for_request,
    )

    _ensure_live_runtime()
    actor_scoped = _request_auth_mode(request) == capability_service.OBO_AVAILABLE_MODE
    request_uc = _uc_for_request(request)
    system_uc = request_uc if actor_scoped else _uc()
    cache_scope = _request_cache_scope(request)
    resolved_limit = max(1, min(int(limit or 8), 25))
    # NOTE: the cache key deliberately excludes resolved_limit (audited
    # P1). Warming is done once at _LINEAGE_RECOMMENDATIONS_WARM_LIMIT and
    # each request slices to its own limit — including the limit made
    # every distinct `?limit=` re-warm the whole estate from scratch.
    cache_key = (
        "lineage_recommendations:"
        f"{lineage_service._warehouse_key(request_uc)}:"
        f"{lineage_service._cache_scope_key(cache_scope)}:"
        f"{lineage_service._warehouse_key(system_uc)}"
    )

    cached = lineage_service._TTL_CACHE.get(cache_key)
    payload = None
    stale_payload = None
    if cached:
        cached_meta = dict((cached[1] or {}).get("meta") or {})
        # Failed warms are terminal (state degraded, poll loop ends) but
        # only fresh for 60s so a transient failure retries quickly.
        fresh_ttl = (
            _LINEAGE_RECOMMENDATIONS_FAILED_TTL_S
            if cached_meta.get("queryFailed")
            else _LINEAGE_RECOMMENDATIONS_TTL_S
        )
        if time.time() - cached[0] < fresh_ttl:
            payload = cached[1]
        else:
            stale_payload = cached[1]
    if payload is None:
        with _LINEAGE_RECOMMENDATIONS_WARMING_LOCK:
            should_warm = cache_key not in _LINEAGE_RECOMMENDATIONS_WARMING
            if should_warm:
                _LINEAGE_RECOMMENDATIONS_WARMING.add(cache_key)

        if should_warm:
            store = _store_for_read()

            def warm_recommendations() -> None:
                try:
                    try:
                        warmed_payload = lineage_service.lineage_recommendations_payload(
                            request_uc,
                            store,
                            system_uc=system_uc,
                            limit=_LINEAGE_RECOMMENDATIONS_WARM_LIMIT,
                        )
                        lineage_service._TTL_CACHE[cache_key] = (time.time(), warmed_payload)
                        # Warm-ahead the FULL lineage build for the top
                        # recommended assets so the picker's example assets
                        # open fast (cold lineage was 10-20s). Runs under the
                        # same actor scope/uc as the eventual click so the
                        # warmed cache keys match. Bounded + guarded inside
                        # _warm_recommended_lineage_ahead.
                        _warm_recommended_lineage_ahead(
                            request_uc,
                            store,
                            system_uc,
                            cache_scope,
                            warmed_payload,
                        )
                    except Exception:
                        _LINEAGE_LOGGER.warning(
                            "lineage recommendations warmer failed",
                            exc_info=True,
                        )
                        # Terminal failure payload (audited P1): without
                        # this the cache never fills and every request
                        # returns "loading" forever. queryFailed=True gives
                        # it the short TTL above so the warm retries soon.
                        lineage_service._TTL_CACHE[cache_key] = (
                            time.time(),
                            {
                                "items": [],
                                "meta": {
                                    "source": "system.access.table_lineage",
                                    "rankingSource": "visible-inventory-batched-lineage",
                                    "queryFailed": True,
                                    "unavailableReason": (
                                        "Lineage recommendation ranking failed against Unity Catalog system lineage tables; it will retry shortly."
                                    ),
                                },
                            },
                        )
                finally:
                    with _LINEAGE_RECOMMENDATIONS_WARMING_LOCK:
                        _LINEAGE_RECOMMENDATIONS_WARMING.discard(cache_key)

            threading.Thread(
                target=warm_recommendations,
                name="axiom-lineage-recommendations-warm",
                daemon=True,
            ).start()

        if stale_payload is not None:
            # Return whatever we have (stale-while-revalidate at the app
            # layer) instead of a loading envelope — the warm above
            # refreshes it in the background.
            payload = stale_payload
        else:
            service_meta = {
                "source": "system.access.table_lineage",
                "rankingSource": "visible-inventory-batched-lineage",
                "visibleAssetCount": None,
                "scannedAssetCount": 0,
                "candidateLimit": lineage_service.LINEAGE_RECOMMENDATION_CANDIDATE_LIMIT,
                "edgeSampleLimit": lineage_service.LINEAGE_RECOMMENDATION_PER_SEED_LIMIT,
                "recommendationLimit": resolved_limit,
                "hydrating": True,
                "unavailableReason": "Lineage recommendations are warming from actor-visible Unity Catalog inventory.",
            }
            response_payload = {"items": [], "recommendationMeta": service_meta}
            # no-store: a browser-cached "loading" body freezes the panel's
            # poll loop on a stale loading state (audited P1).
            return _no_store(
                _cacheable_json_response(
                    _with_meta(
                        response_payload,
                        request,
                        source="unity-catalog-lineage",
                        state="loading",
                        authoritative=False,
                        capabilities={
                            "visibilityScope": (
                                capability_service.ACTOR_SCOPED_VISIBILITY
                                if actor_scoped
                                else capability_service.WORKSPACE_APP_PRINCIPAL_VISIBILITY
                            ),
                            "recommendationLimit": resolved_limit,
                            "evidenceSource": service_meta["source"],
                            "lineageRecommendation": service_meta,
                            "hydrating": True,
                        },
                        warnings=[
                            "Lineage recommendations are warming from Unity Catalog system lineage tables; no recommendations are shown until backed evidence is returned."
                        ],
                    ),
                    request,
                    max_age=5,
                    stale_while_revalidate=30,
                )
            )

    service_meta = dict(payload.get("meta") or {})
    response_payload = dict(payload)
    response_payload.pop("meta", None)
    # The payload was warmed at the max limit; slice to this request's.
    response_payload["items"] = list(response_payload.get("items") or [])[:resolved_limit]
    service_meta["recommendationLimit"] = resolved_limit
    if service_meta:
        response_payload["recommendationMeta"] = service_meta
    ranking_source = str(service_meta.get("rankingSource") or "")
    aggregate_fallback = ranking_source == "system.access.table_lineage.aggregate-fallback"
    # queryFailed marks a warm attempt that hit a warehouse error: the
    # response is TERMINAL (state degraded — the panel stops polling) but
    # never authoritative and never "available".
    query_failed = bool(service_meta.get("queryFailed"))
    stale_served = stale_payload is not None and payload is stale_payload
    recommendations_authoritative = (
        actor_scoped and not aggregate_fallback and not query_failed and not stale_served
    )
    recommendation_warnings = []
    if query_failed:
        recommendation_warnings.append(
            "Lineage recommendation ranking failed for one or more Unity Catalog queries; results may be incomplete and will refresh automatically."
        )
    if stale_served:
        recommendation_warnings.append(
            "Showing previously ranked lineage recommendations while a fresh ranking is computed."
        )
    if aggregate_fallback:
        recommendation_warnings.append(
            "Lineage recommendations used the aggregate fallback: candidate assets were verified openable, but edge counts may include relationships whose opposite endpoint is not actor-openable."
        )
    if not actor_scoped:
        recommendation_warnings.append(
            "Lineage recommendations are ranked from workspace-scoped app-principal reads; per-user authorization is not available."
        )

    return _cacheable_json_response(
        _with_meta(
            response_payload,
            request,
            source="unity-catalog-lineage",
            state="available" if recommendations_authoritative else "degraded",
            authoritative=recommendations_authoritative,
            capabilities={
                "visibilityScope": (
                    capability_service.ACTOR_SCOPED_VISIBILITY
                    if actor_scoped
                    else capability_service.WORKSPACE_APP_PRINCIPAL_VISIBILITY
                ),
                "relationshipVisibilityScope": (
                    "actor-openable-candidate-aggregate"
                    if aggregate_fallback
                    else (
                        capability_service.ACTOR_SCOPED_VISIBILITY
                        if actor_scoped
                        else capability_service.WORKSPACE_APP_PRINCIPAL_VISIBILITY
                    )
                ),
                "recommendationLimit": resolved_limit,
                "evidenceSource": service_meta.get("source") or "system.access.table_lineage",
                "lineageRecommendation": service_meta,
            },
            warnings=recommendation_warnings,
        ),
        request,
        # Failed/stale rankings must not pin in the browser cache — keep
        # them short so the refreshed ranking is picked up quickly.
        max_age=5 if (query_failed or stale_served) else 120,
        stale_while_revalidate=30 if (query_failed or stale_served) else 300,
    )


def api_column_lineage_trace_query(
    request: Request,
    asset_fqn: str = "",
    column_name: str = "",
    direction: str = "upstream",
    depth: int = 2,
) -> JSONResponse:
    """Query-param variant so asset_fqn (which contains dots) doesn't
    have to collide with FastAPI's dot-unfriendly path parameter."""
    if not asset_fqn or not column_name:
        raise HTTPException(
            status_code=400,
            detail="asset_fqn and column_name query parameters are required.",
        )
    return api_column_lineage_trace(asset_fqn, column_name, request, direction, depth)


def api_column_lineage_trace(
    asset_fqn: str,
    column_name: str,
    request: Request,
    direction: str = "upstream",
    depth: int = 2,
) -> JSONResponse:
    """Phase 9 — multi-hop column lineage. Walks system.access.column_lineage
    recursively, bounded by depth/node/fanout caps to fail closed against
    runaway fan-out."""
    from runtime_app import _ensure_live_runtime, _uc_for_request

    _ensure_live_runtime()
    actor_scoped = _request_auth_mode(request) == capability_service.OBO_AVAILABLE_MODE
    if not actor_scoped:
        raise HTTPException(
            status_code=403,
            detail="Column lineage requires per-user authorization (OBO).",
        )
    try:
        system_uc = _uc_for_request(request)
    except Exception:
        system_uc = None
    if system_uc is None:
        raise HTTPException(
            status_code=503,
            detail="System lineage tables are not reachable in the current runtime mode.",
        )
    direction_norm = (direction or "upstream").strip().lower()
    if direction_norm == "upstream":
        fetcher = lineage_service.build_upstream_column_fetcher(system_uc)
    elif direction_norm == "downstream":
        fetcher = lineage_service.build_downstream_column_fetcher(system_uc)
    else:
        raise HTTPException(status_code=400, detail="direction must be 'upstream' or 'downstream'")
    try:
        payload = lineage_service.trace_multi_hop_column_lineage(
            asset_fqn=asset_fqn,
            column_name=column_name,
            direction=direction_norm,
            depth=depth,
            fetch_neighbors=fetcher,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return JSONResponse(
        status_code=200,
        content={
            "data": payload,
            "meta": {
                "authoritative": True,
                "source": "system.access.column_lineage",
                "observedAt": datetime.now(timezone.utc).isoformat(),
            },
            "errors": [],
        },
    )


def build_lineage_router() -> APIRouter:
    router = APIRouter(tags=["lineage"])
    # Register specific lineage subroutes before the generic catch-all below.
    router.add_api_route(
        "/api/lineage/recommendations",
        api_lineage_recommendations,
        methods=["GET"],
        name="api_lineage_recommendations",
    )
    router.add_api_route(
        "/api/lineage/column-trace",
        api_column_lineage_trace_query,
        methods=["GET"],
        name="api_column_lineage_trace_query",
    )
    # Back-compat alias — path style for asset_fqns without dots.
    router.add_api_route(
        "/api/lineage/columns/{asset_fqn}/{column_name}/trace",
        api_column_lineage_trace,
        methods=["GET"],
        name="api_column_lineage_trace",
    )
    router.add_api_route(
        "/api/lineage/{asset_fqn:path}",
        api_lineage,
        methods=["GET"],
        response_class=JSONResponse,
        name="api_lineage",
    )
    return router
