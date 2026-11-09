from __future__ import annotations

import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import pandas as pd

from axiom.bounded_cache import BoundedTTLCache
from axiom import uc as uc_module
from axiom.uc import UCSQLClient

logger = logging.getLogger(__name__)

HIDDEN_CATALOGS = {"hive_metastore", "samples", "system", "__databricks_internal"}
PLACEHOLDER_DESCRIPTION = "No description has been captured for this asset yet."
_EXCLUDED_ASSET_MARKERS = ("__materialization_mat_", "temp_metric_view_")
_STANDARD_TAG_ALIASES = {
    "domain": ("domain", "data_domain"),
    "tier": ("tier", "data_tier"),
    "certification": ("certification", "certified", "data_certification"),
    "sensitivity": ("sensitivity", "classification", "data_classification"),
    "criticality": ("criticality", "priority"),
    # business_criticality is orthogonal to `criticality` (SLA tier).
    # Demo feedback: stewards want a fixed-enum business-impact axis —
    # Mission Critical, Business Critical, Operational, Low Impact,
    # Not Assessed — round-tripped to UC tags.
    "business_criticality": ("business_criticality", "biz_criticality"),
    "glossary_term": ("glossary_term", "glossary"),
    "data_product": ("data_product", "product"),
    # Critical Data Element marker — asset- or column-level boolean tag.
    "cde": ("cde", "is_cde"),
}

# Canonical business criticality values — duplicated in
# axiom/api/assets.py::BUSINESS_CRITICALITY_VALUES for frontend
# facet rendering. Keep in sync.
BUSINESS_CRITICALITY_VALUES = (
    "Mission Critical",
    "Business Critical",
    "Operational",
    "Low Impact",
    "Not Assessed",
)

_TTL_CACHE: Dict[str, Tuple[float, Any]] = BoundedTTLCache()
# Per-key locks so a burst of concurrent requests for the same cached item
# issues ONE loader call, not N. The outer dict is guarded by a guard lock
# while a new per-key lock is being created. Pattern mirrors the equivalent
# guard in services/lineage.py — the comment there has the long-form
# justification.
_TTL_CACHE_LOCKS: Dict[str, threading.Lock] = {}
_TTL_CACHE_LOCKS_GUARD = threading.Lock()


def _ttl_cache_lock(key: str) -> threading.Lock:
    existing = _TTL_CACHE_LOCKS.get(key)
    if existing is not None:
        return existing
    with _TTL_CACHE_LOCKS_GUARD:
        existing = _TTL_CACHE_LOCKS.get(key)
        if existing is None:
            existing = threading.Lock()
            _TTL_CACHE_LOCKS[key] = existing
        return existing


def _ttl_value(key: str, ttl_s: int, loader: Callable[[], Any]) -> Any:
    now = time.time()
    cached = _TTL_CACHE.get(key)
    if cached and now - cached[0] < ttl_s:
        return cached[1]
    lock = _ttl_cache_lock(key)
    with lock:
        cached = _TTL_CACHE.get(key)
        if cached and time.time() - cached[0] < ttl_s:
            return cached[1]
        value = loader()
        _TTL_CACHE[key] = (time.time(), value)
        return value


def _warehouse_key(uc: Any) -> str:
    """Cache partition for this client: warehouse AND acting credentials.

    Keying by warehouse alone leaked per-user Unity Catalog reads (sample rows,
    columns, lineage, table detail) across users: data fetched under one user's
    OBO permissions was served to every other user on the same warehouse.
    """
    warehouse = normalize_str(getattr(uc, "warehouse_id", "")) or "default"
    scope = normalize_str(getattr(uc, "cache_scope", "")) or "app"
    return f"{warehouse}:{scope}"


def invalidate_live_metadata_caches(asset_fqn: str | None = None) -> None:
    _TTL_CACHE.clear()


def normalize_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    return str(value).strip()


def split_uc_name(name: str) -> Tuple[str, str, str]:
    parts = [part.strip() for part in normalize_str(name).split(".") if part.strip()]
    if len(parts) != 3:
        raise ValueError("Expected catalog.schema.table")
    return parts[0], parts[1], parts[2]


def _is_excluded_asset_name(value: Any) -> bool:
    lowered = normalize_str(value).lower()
    return any(marker in lowered for marker in _EXCLUDED_ASSET_MARKERS)


def filter_asset_rows(
    df: pd.DataFrame,
    columns: List[str],
    *,
    exclude_fqn: str = "",
) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=df.columns if df is not None else [])

    view = df.copy()
    keep_mask = pd.Series(True, index=view.index)
    excluded = normalize_str(exclude_fqn).lower()

    for column in columns:
        if column not in view.columns:
            continue
        values = view[column].map(normalize_str).str.lower()
        keep_mask &= ~values.map(_is_excluded_asset_name)
        if excluded:
            keep_mask &= values != excluded

    return view.loc[keep_mask].reset_index(drop=True)


def catalog_filter_options(
    inventory: pd.DataFrame,
    *,
    available_catalogs: Optional[List[str]] = None,
    observed_catalogs: Optional[List[str]] = None,
) -> List[str]:
    values: set[str] = set()
    if inventory is not None and not inventory.empty:
        if "table_catalog" in inventory.columns:
            values.update(
                normalize_str(value)
                for value in inventory["table_catalog"].dropna().astype(str).tolist()
                if normalize_str(value)
            )
        if "fqn" in inventory.columns:
            for raw in inventory["fqn"].dropna().astype(str).tolist():
                try:
                    catalog, _, _ = split_uc_name(normalize_str(raw))
                except ValueError:
                    continue
                if catalog:
                    values.add(catalog)
    if available_catalogs:
        values.update(
            normalize_str(catalog)
            for catalog in available_catalogs
            if normalize_str(catalog)
        )
    if observed_catalogs:
        values.update(
            normalize_str(catalog)
            for catalog in observed_catalogs
            if normalize_str(catalog)
        )
    return sorted(values)


def lineage_asset_stub(inventory: pd.DataFrame, asset_fqn: str) -> pd.Series:
    if inventory is not None and not inventory.empty:
        match = inventory[inventory["fqn"] == asset_fqn]
        if not match.empty:
            return match.iloc[0]
    try:
        catalog, schema, table = split_uc_name(asset_fqn)
    except ValueError:
        catalog, schema, table = "", "", asset_fqn
    base: Dict[str, Any] = {}
    if inventory is not None and not inventory.empty:
        base = {column: "" for column in inventory.columns}
    base.update(
        {
            "fqn": asset_fqn,
            "table_catalog": catalog,
            "table_schema": schema,
            "table_name": table,
            "table_type": "",
            "comment": "",
            "governance_score": 0,
            "pending_requests": 0,
            "owner_count": 0,
            "governance_status": "",
            "tags": {},
            "domain": "",
            "tier": "",
            "certification": "",
            "sensitivity": "",
            "criticality": "",
            "business_criticality": "",
            "cde": "",
            "glossary_term_tag": "",
            "glossary_term": "",
            "glossaryLinks": [],
            "glossaryTerms": [],
            "steward": "",
        }
    )
    return pd.Series(base)


def tag_value(tags: Dict[str, str], key: str) -> str:
    for alias in _STANDARD_TAG_ALIASES.get(key, (key,)):
        value = normalize_str(tags.get(alias))
        if value:
            return value
    if key == "sensitivity":
        pii_value = normalize_str(tags.get("contains_pii") or tags.get("pii"))
        if pii_value.lower() in {"1", "true", "yes", "pii", "sensitive"}:
            return "Sensitive"
    return ""


def glossary_term_lookup(terms_df: pd.DataFrame | None) -> Dict[str, Dict[str, Any]]:
    if terms_df is None or terms_df.empty:
        return {}
    lookup: Dict[str, Dict[str, Any]] = {}
    for _, row in terms_df.iterrows():
        term_id = normalize_str(row.get("term_id"))
        if not term_id:
            continue
        lookup[term_id.lower()] = {
            "termId": term_id,
            "name": normalize_str(row.get("name")),
            "definition": normalize_str(row.get("definition")),
        }
    return lookup


def glossary_link_lookup(
    links_df: pd.DataFrame | None,
    term_lookup: Dict[str, Dict[str, Any]] | None = None,
) -> Dict[str, List[Dict[str, Any]]]:
    if links_df is None or links_df.empty:
        return {}
    lookup: Dict[str, List[Dict[str, Any]]] = {}
    for _, row in links_df.iterrows():
        if normalize_str(row.get("removed_at")):
            continue
        subject_type = normalize_str(row.get("subject_type")).lower()
        subject_fqn = normalize_str(row.get("subject_fqn"))
        if not subject_type or not subject_fqn:
            continue
        column_name = normalize_str(row.get("column_name"))
        key = f"{subject_type}:{subject_fqn}:{column_name}"
        term_id = normalize_str(row.get("term_id"))
        term = (term_lookup or {}).get(term_id.lower()) if term_id else None
        lookup.setdefault(key, []).append(
            {
                "termId": term_id,
                "term": normalize_str(term.get("name")) if term else "",
                "source": normalize_str(row.get("source")).lower() or "manual",
                "resolutionState": normalize_str(row.get("resolution_state")).lower()
                or "linked",
            }
        )
    return lookup


def glossary_terms_for_subject(
    subject_type: str,
    subject_fqn: str,
    link_lookup: Dict[str, List[Dict[str, Any]]],
) -> List[Dict[str, Any]]:
    return list(
        link_lookup.get(
            f"{normalize_str(subject_type).lower()}:{normalize_str(subject_fqn)}:", []
        )
    )


def empty_inventory() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "table_catalog",
            "table_schema",
            "table_name",
            "table_type",
            "comment",
            "fqn",
            "tags",
            "domain",
            "tier",
            "certification",
            "sensitivity",
            "criticality",
            "glossary_term",
            "glossaryLinks",
            "glossaryTerms",
            "data_product",
            "owner_count",
            "owners_summary",
            "business_owner",
            "technical_owner",
            "steward",
            "pending_requests",
            "approved_requests",
            "rejected_requests",
            "total_requests",
            "governance_score",
            "governance_status",
            "search_text",
        ]
    )


@lru_cache(maxsize=1)
def _hidden_catalog_set() -> set[str]:
    return {value.lower() for value in HIDDEN_CATALOGS}


_DEFAULT_SKIPPED_CATALOG_TYPES = "FOREIGN_CATALOG,MANAGED_ONLINE_CATALOG,DELTASHARING_CATALOG"


def _skipped_catalog_types() -> set[str]:
    """Catalog types left out of "all catalogs" discovery.

    Federated catalogs answer information_schema by calling out to the remote
    system (3-6s per query), and Lakebase/shared catalogs carry no governance
    state. Listing a catalog in AXIOM_DISCOVERY_CATALOGS still includes it.
    """
    import os

    raw = os.getenv("AXIOM_DISCOVERY_SKIP_CATALOG_TYPES", _DEFAULT_SKIPPED_CATALOG_TYPES)
    return {item.strip().upper() for item in raw.split(",") if item.strip()}


_LINEAGE_CATALOGS_LOCK = threading.Lock()


def _lineage_catalogs_ttl_s() -> float:
    try:
        return float(os.getenv("AXIOM_LINEAGE_CATALOGS_TTL_S", "3600"))
    except ValueError:
        return 3600.0


def cached_lineage_catalogs(uc: UCSQLClient) -> List[str]:
    """Catalogs seen in system.access.table_lineage, cached for an hour.

    The underlying DISTINCT scan over the lineage window is the slowest
    discovery query and its answer changes rarely. Empty or failed results
    are retried after 15 seconds.
    """
    loader = getattr(uc, "list_lineage_catalogs", None)
    if loader is None:
        return []
    key = f"lineage_catalogs:{_warehouse_key(uc)}"

    def _fresh(entry) -> bool:
        if not entry:
            return False
        age = time.time() - entry[0]
        return age < (_lineage_catalogs_ttl_s() if entry[1] else 15)

    cached = _TTL_CACHE.get(key)
    if _fresh(cached):
        return list(cached[1])
    with _LINEAGE_CATALOGS_LOCK:
        cached = _TTL_CACHE.get(key)
        if _fresh(cached):
            return list(cached[1])
        try:
            df = loader()
        except Exception:
            df = None
        value: List[str] = []
        if df is not None and not df.empty:
            value = sorted(
                {
                    normalize_str(item)
                    for item in df.iloc[:, 0].tolist()
                    if normalize_str(item)
                }
            )
        _TTL_CACHE[key] = (time.time(), value)
        return list(value)


def cached_catalogs(uc: UCSQLClient) -> List[str]:
    def _show_catalogs() -> List[str]:
        try:
            df = uc.list_catalogs()
        except Exception:
            return []
        if df is None or df.empty:
            return []
        return [
            normalize_str(value)
            for value in df.iloc[:, 0].tolist()
            if normalize_str(value)
        ]

    def _load() -> List[str]:
        hidden = _hidden_catalog_set()
        skipped_types = _skipped_catalog_types()
        want_types = bool(skipped_types) and hasattr(uc, "list_catalog_types")
        # SHOW CATALOGS, the lineage scan and the catalog-type REST call are
        # independent; run them together instead of back to back.
        with ThreadPoolExecutor(max_workers=3, thread_name_prefix="axiom-catalogs") as pool:
            shown = pool.submit(_show_catalogs)
            lineage = pool.submit(cached_lineage_catalogs, uc)
            types_future = pool.submit(uc.list_catalog_types) if want_types else None
            values: set[str] = set(shown.result()) | set(lineage.result())
            catalog_types: Dict[str, str] = {}
            if types_future is not None:
                try:
                    catalog_types = types_future.result()
                except Exception:
                    catalog_types = {}
        return sorted(
            value
            for value in values
            if value
            and value.lower() not in hidden
            and catalog_types.get(value.lower(), "") not in skipped_types
        )

    key = f"catalogs:{_warehouse_key(uc)}"
    # Use a short TTL for empty results so a transient warehouse cold-start or
    # permission propagation lag does not poison the cache for 10 minutes.
    cached = _TTL_CACHE.get(key)
    now = time.time()
    if cached and now - cached[0] < 600 and cached[1]:
        return cached[1]
    if cached and now - cached[0] < 15 and not cached[1]:
        return cached[1]
    value = _load()
    _TTL_CACHE[key] = (now, value)
    return value


def cached_catalog_inventory(uc: UCSQLClient, catalog: str) -> pd.DataFrame:
    key = f"catalog_inventory:{_warehouse_key(uc)}:{normalize_str(catalog)}"
    cached = _TTL_CACHE.get(key)
    now = time.time()
    if cached and now - cached[0] < 600:
        payload = cached[1]
        # Empty frames from a transient permission / cold-start failure should
        # not stick for 10 minutes; fall through to a quick retry after 15s.
        if payload is not None and not (hasattr(payload, "empty") and payload.empty):
            return payload
        if now - cached[0] < 15:
            return payload
    value = uc.get_catalog_table_inventory(catalog)
    _TTL_CACHE[key] = (now, value)
    return value


def cached_catalog_table_tags(uc: UCSQLClient, catalog: str) -> pd.DataFrame:
    return _ttl_value(
        f"catalog_table_tags:{_warehouse_key(uc)}:{normalize_str(catalog)}",
        600,
        lambda: uc.get_catalog_table_tags(catalog),
    )


def cached_columns(
    uc: UCSQLClient, catalog: str, schema: str, table: str
) -> pd.DataFrame:
    return _ttl_value(
        f"columns:{_warehouse_key(uc)}:{normalize_str(catalog)}:{normalize_str(schema)}:{normalize_str(table)}",
        600,
        lambda: uc.get_table_columns(catalog, schema, table),
    )


def cached_comment(uc: UCSQLClient, catalog: str, schema: str, table: str) -> str:
    return _ttl_value(
        f"comment:{_warehouse_key(uc)}:{normalize_str(catalog)}:{normalize_str(schema)}:{normalize_str(table)}",
        600,
        lambda: uc.get_table_comment(catalog, schema, table),
    )


def cached_table_detail(
    uc: UCSQLClient, catalog: str, schema: str, table: str
) -> pd.DataFrame:
    return _ttl_value(
        f"table_detail:{_warehouse_key(uc)}:{normalize_str(catalog)}:{normalize_str(schema)}:{normalize_str(table)}",
        600,
        lambda: uc.get_table_detail(catalog, schema, table),
    )


def cached_table_row_count(
    uc: UCSQLClient, catalog: str, schema: str, table: str
) -> Any:
    return _ttl_value(
        f"row_count:{_warehouse_key(uc)}:{normalize_str(catalog)}:{normalize_str(schema)}:{normalize_str(table)}",
        # COUNT(*) is a warehouse round-trip (and a full scan for views), and
        # counts drift slowly, so keep them for an hour.
        3600,
        lambda: uc.get_table_row_count(catalog, schema, table),
    )


def cached_table_properties(
    uc: UCSQLClient, catalog: str, schema: str, table: str
) -> pd.DataFrame:
    return _ttl_value(
        f"table_properties:{_warehouse_key(uc)}:{normalize_str(catalog)}:{normalize_str(schema)}:{normalize_str(table)}",
        600,
        lambda: uc.get_table_properties(catalog, schema, table),
    )


def cached_table_history(
    uc: UCSQLClient, catalog: str, schema: str, table: str
) -> pd.DataFrame:
    """600s-TTL cache around DESCRIBE HISTORY. Used to compute Last
    Updated for Delta tables in the asset header. The query is cheap
    (~50ms) but called for every visible lineage card via the per-node
    header fetch, so caching avoids hammering the warehouse on graph
    re-render."""
    return _ttl_value(
        f"table_history:{_warehouse_key(uc)}:{normalize_str(catalog)}:{normalize_str(schema)}:{normalize_str(table)}",
        600,
        lambda: uc.get_table_history(catalog, schema, table),
    )


def cached_information_schema_table_metadata(
    uc: UCSQLClient, catalog: str, schema: str, table: str
) -> pd.DataFrame:
    """600s-TTL cache around the per-table information_schema.tables
    lookup. Used to source the UC `table_owner` / `created_by` /
    `last_altered` fields when the local governance store has nothing
    assigned for the asset."""
    return _ttl_value(
        f"info_schema_table:{_warehouse_key(uc)}:{normalize_str(catalog)}:{normalize_str(schema)}:{normalize_str(table)}",
        600,
        lambda: uc.get_information_schema_table_metadata(catalog, schema, table),
    )


def cached_table_constraints(
    uc: UCSQLClient, catalog: str, schema: str, table: str
) -> pd.DataFrame:
    return _ttl_value(
        f"table_constraints:{_warehouse_key(uc)}:{normalize_str(catalog)}:{normalize_str(schema)}:{normalize_str(table)}",
        600,
        lambda: uc.get_table_constraints(catalog, schema, table),
    )


def cached_sample_rows(
    uc: UCSQLClient, catalog: str, schema: str, table: str
) -> pd.DataFrame:
    return _ttl_value(
        f"sample_rows:{_warehouse_key(uc)}:{normalize_str(catalog)}:{normalize_str(schema)}:{normalize_str(table)}",
        600,
        lambda: uc.get_table_sample(catalog, schema, table, limit=15),
    )


def cached_lineage_up(
    uc: UCSQLClient, catalog: str, schema: str, table: str
) -> pd.DataFrame:
    return _ttl_value(
        f"lineage_up:{_warehouse_key(uc)}:{normalize_str(catalog)}:{normalize_str(schema)}:{normalize_str(table)}",
        600,
        lambda: uc.get_table_lineage_upstream(catalog, schema, table),
    )


def cached_lineage_down(
    uc: UCSQLClient, catalog: str, schema: str, table: str
) -> pd.DataFrame:
    return _ttl_value(
        f"lineage_down:{_warehouse_key(uc)}:{normalize_str(catalog)}:{normalize_str(schema)}:{normalize_str(table)}",
        600,
        lambda: uc.get_table_lineage_downstream(catalog, schema, table),
    )


def cached_operational_context_up(
    uc: UCSQLClient, catalog: str, schema: str, table: str
) -> pd.DataFrame:
    return _ttl_value(
        f"operational_up:{_warehouse_key(uc)}:{normalize_str(catalog)}:{normalize_str(schema)}:{normalize_str(table)}",
        600,
        lambda: uc.get_operational_context_upstream(catalog, schema, table),
    )


def cached_operational_context_down(
    uc: UCSQLClient, catalog: str, schema: str, table: str
) -> pd.DataFrame:
    return _ttl_value(
        f"operational_down:{_warehouse_key(uc)}:{normalize_str(catalog)}:{normalize_str(schema)}:{normalize_str(table)}",
        600,
        lambda: uc.get_operational_context_downstream(catalog, schema, table),
    )


def cached_operational_entity_name(
    uc: UCSQLClient, entity_type: str, entity_id: str
) -> str:
    return _ttl_value(
        f"operational_entity_name:{_warehouse_key(uc)}:{normalize_str(entity_type)}:{normalize_str(entity_id)}",
        600,
        lambda: uc.resolve_operational_entity_name(entity_type, entity_id),
    )


def enrich_operational_context_names(uc: UCSQLClient, df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty or "entity_type" not in df.columns:
        return df
    view = df.copy()
    lookup: Dict[Tuple[str, str], str] = {}
    for row in view.itertuples(index=False):
        entity_type = normalize_str(getattr(row, "entity_type", ""))
        entity_id = normalize_str(getattr(row, "entity_id", ""))
        if not entity_type or not entity_id:
            continue
        key = (entity_type, entity_id)
        if key not in lookup:
            lookup[key] = cached_operational_entity_name(uc, entity_type, entity_id)
    resolved_names: List[str] = []
    for row in view.itertuples(index=False):
        entity_type = normalize_str(getattr(row, "entity_type", ""))
        entity_id = normalize_str(getattr(row, "entity_id", ""))
        resolved_names.append(lookup.get((entity_type, entity_id), ""))
    view["resolved_entity_name"] = resolved_names
    return view


def parallel_catalog_scan(
    catalogs: Sequence[str],
    fetch: Callable[[str], Any],
    *,
    max_workers: int = 5,
) -> List[Tuple[str, Any, Optional[Exception]]]:
    """Run a per-catalog fetch across a small thread pool, preserving order.

    Cold-start hydration used to scan every catalog SEQUENTIALLY (~1.2s+
    each on information_schema), so an 18-catalog estate left every surface
    on empty "loading" envelopes for 20-40s on each cold start / TTL expiry.
    A bounded pool (5 workers — small enough not to saturate the shared
    serverless warehouse) collapses that wall-clock to roughly the slowest
    few catalogs while keeping per-catalog error isolation: each result
    tuple is (catalog, value, exception) and one bad catalog never kills
    the scan. Results are returned in the caller's catalog order so the
    assembled inventory stays deterministic.
    """
    resolved = [normalize_str(catalog) for catalog in catalogs if normalize_str(catalog)]
    if not resolved:
        return []

    def _run(catalog: str) -> Tuple[str, Any, Optional[Exception]]:
        try:
            return (catalog, fetch(catalog), None)
        except Exception as exc:  # error isolation: caller decides skip/raise
            return (catalog, None, exc)

    if len(resolved) == 1:
        return [_run(resolved[0])]
    with ThreadPoolExecutor(
        max_workers=min(max_workers, len(resolved)),
        thread_name_prefix="axiom-catalog-scan",
    ) as pool:
        return list(pool.map(_run, resolved))


def _peek_fresh_cache(key: str, ttl_s: int = 600) -> Any:
    """Return a still-fresh cached value WITHOUT invoking any loader.

    Used for opportunistic enrichment (e.g. rows/size on discovery cards):
    real numbers are surfaced when a prior DESCRIBE DETAIL / COUNT(*) has
    already been paid for, and honestly absent otherwise — never a new
    per-asset query fan-out from a list endpoint.
    """
    cached = _TTL_CACHE.get(key)
    if cached and time.time() - cached[0] < ttl_s:
        return cached[1]
    return None


def warm_table_stats(
    uc: UCSQLClient, catalog: str, schema: str, table: str
) -> Dict[str, Any]:
    """rows/size/files for a table, sourced ONLY from already-warm caches.

    Peeks the `table_detail:` (DESCRIBE DETAIL) and `row_count:` cache
    entries this scope has already populated. Returns None-valued fields
    when nothing is warm — callers must render those as absent, never
    fabricate.
    """
    scope = _warehouse_key(uc)
    stats: Dict[str, Any] = {"row_count": None, "size_bytes": None, "file_count": None}
    detail_df = _peek_fresh_cache(
        f"table_detail:{scope}:{normalize_str(catalog)}:{normalize_str(schema)}:{normalize_str(table)}"
    )
    if isinstance(detail_df, pd.DataFrame) and not detail_df.empty:
        row = {str(key).lower(): value for key, value in detail_df.iloc[0].to_dict().items()}
        for source_key, target_key in (
            ("numrows", "row_count"),
            ("sizeinbytes", "size_bytes"),
            ("numfiles", "file_count"),
        ):
            value = row.get(source_key)
            try:
                if value is not None and not pd.isna(value) and int(value) > 0:
                    stats[target_key] = int(value)
            except (TypeError, ValueError):
                continue
    if stats["row_count"] is None:
        count = _peek_fresh_cache(
            f"row_count:{scope}:{normalize_str(catalog)}:{normalize_str(schema)}:{normalize_str(table)}"
        )
        try:
            if count is not None and int(count) > 0:
                stats["row_count"] = int(count)
        except (TypeError, ValueError):
            pass
    return stats


def _safe_call(fn: Callable[[], Any]) -> Any:
    try:
        return fn()
    except Exception:
        # Each loader is a self-caching cached_* function; a transient failure
        # here is re-surfaced when the caller re-invokes the same function in
        # context and handles it there. The prefetch is best-effort warming.
        return None


def prefetch_parallel(
    loaders: Sequence[Callable[[], Any]],
    *,
    max_workers: int = 4,
) -> None:
    """Fire independent cache-loader callables concurrently, block until done.

    The per-asset detail header used to serialize its Unity Catalog round
    trips — DESCRIBE DETAIL, then DESCRIBE HISTORY, then
    information_schema.tables, then (when the comment was empty) the table
    comment — at ~1-1.5s each, so a cold header cost 5-7s wall-clock even
    though the four queries are mutually independent. Running them across a
    tiny pool collapses that to roughly the slowest single query. Every
    loader is expected to be a self-caching cached_* function whose return
    value we discard; the point is only to populate the shared TTL cache so
    the caller's subsequent sequential reads hit warm entries. Exceptions are
    swallowed per-loader (see _safe_call) — error handling stays in the
    caller's in-context re-invocation.
    """
    tasks = [fn for fn in loaders if fn is not None]
    if not tasks:
        return
    if len(tasks) == 1:
        _safe_call(tasks[0])
        return
    with ThreadPoolExecutor(
        max_workers=min(max_workers, len(tasks)),
        thread_name_prefix="axiom-meta-prefetch",
    ) as pool:
        # Drain the map so we block until every prefetch completes before the
        # caller proceeds to read the (now-warm) caches.
        list(pool.map(_safe_call, tasks))


def gather_parallel(
    loaders: Sequence[Callable[[], Any]],
    *,
    max_workers: int = 4,
) -> List[Any]:
    """Run loaders concurrently and return their results in order.

    Like prefetch_parallel but hands back each loader's return value (None on
    failure) so callers can use results directly — needed when a loader is NOT
    cache-backed (e.g. a raw uc.get_* call), where a prefetch-then-reread would
    issue the query twice.
    """
    tasks = [fn for fn in loaders if fn is not None]
    if not tasks:
        return []
    if len(tasks) == 1:
        return [_safe_call(tasks[0])]
    with ThreadPoolExecutor(
        max_workers=min(max_workers, len(tasks)),
        thread_name_prefix="axiom-meta-gather",
    ) as pool:
        return list(pool.map(_safe_call, tasks))


def prefetch_asset_header(uc: UCSQLClient, catalog: str, schema: str, table: str) -> None:
    """Warm the four independent header caches for one table in parallel.

    Used both by the detail header build (so its cold path is ~1 round trip
    of latency instead of 4 serialized ones) and by the estate pre-warmer
    (so a first click on a visible asset finds the freshness / DESCRIBE DETAIL
    caches already populated). No-op cost when everything is already fresh:
    each cached_* returns immediately from the TTL cache.
    """
    prefetch_parallel(
        (
            lambda: cached_table_detail(uc, catalog, schema, table),
            lambda: cached_table_history(uc, catalog, schema, table),
            lambda: cached_information_schema_table_metadata(uc, catalog, schema, table),
            lambda: cached_comment(uc, catalog, schema, table),
        ),
        max_workers=4,
    )


def header_cache_is_fresh(uc: UCSQLClient, catalog: str, schema: str, table: str) -> bool:
    """True when the DESCRIBE DETAIL cache for this table is still fresh.

    The estate pre-warmer uses this to skip already-warm assets so a resumed
    sweep is cheap and never re-issues a DESCRIBE DETAIL the current TTL still
    covers.
    """
    scope = _warehouse_key(uc)
    key = (
        f"table_detail:{scope}:{normalize_str(catalog)}:"
        f"{normalize_str(schema)}:{normalize_str(table)}"
    )
    return _peek_fresh_cache(key) is not None


# Bounded pool for the post-hydration estate pre-warmer. A single shared
# executor (not one-per-sweep) caps total concurrency against the serverless
# warehouse regardless of how many scopes trigger a warm, and a guard set
# prevents a second sweep for the same scope from stampeding while the first
# is still running (thundering-herd guard).
_ESTATE_WARMER_POOL = ThreadPoolExecutor(
    max_workers=4, thread_name_prefix="axiom-estate-warm"
)
_ESTATE_WARMING_SCOPES: set[str] = set()
_ESTATE_WARMING_GUARD = threading.Lock()


def warm_estate_headers(
    uc: UCSQLClient,
    fqns: Sequence[str],
    *,
    scope_key: str = "",
    max_assets: int = 50,
) -> Dict[str, int]:
    """Proactively warm header/freshness caches for the visible estate.

    Called after inventory hydration completes. Skips assets whose DESCRIBE
    DETAIL cache is already fresh (resumable + cheap), then warms the rest on
    the bounded shared pool. A per-scope guard means a burst of callers
    triggers ONE sweep, not N (thundering-herd guard). Returns a small
    counters dict for observability. Best-effort: per-asset failures are
    swallowed inside prefetch_asset_header/_safe_call.
    """
    scope = normalize_str(scope_key) or _warehouse_key(uc)
    with _ESTATE_WARMING_GUARD:
        if scope in _ESTATE_WARMING_SCOPES:
            return {"queued": 0, "skippedFresh": 0, "alreadyWarming": 1}
        _ESTATE_WARMING_SCOPES.add(scope)

    counters = {"queued": 0, "skippedFresh": 0, "alreadyWarming": 0}
    try:
        targets: List[Tuple[str, str, str]] = []
        for fqn in list(fqns)[: max(0, int(max_assets))]:
            try:
                catalog, schema, table = split_uc_name(fqn)
            except ValueError:
                continue
            if header_cache_is_fresh(uc, catalog, schema, table):
                counters["skippedFresh"] += 1
                continue
            targets.append((catalog, schema, table))

        counters["queued"] = len(targets)
        if not targets:
            return counters

        def _warm_one(parts: Tuple[str, str, str]) -> None:
            prefetch_asset_header(uc, parts[0], parts[1], parts[2])

        # Drain so the guard is only released once the sweep is complete.
        list(_ESTATE_WARMER_POOL.map(_warm_one, targets))
        return counters
    finally:
        with _ESTATE_WARMING_GUARD:
            _ESTATE_WARMING_SCOPES.discard(scope)


def _inventory_rows_to_frames(uc: UCSQLClient, store: Any) -> pd.DataFrame:
    catalogs = cached_catalogs(uc)
    inventory_frames: List[pd.DataFrame] = []
    tag_maps: Dict[str, Dict[str, str]] = {}
    # Track skipped catalogs separately. If EVERY catalog we tried ended up
    # skipped due to a "skippable" error, that's a transient-failure signal
    # (cold warehouse, OBO propagation lag, expired token), NOT a legitimate
    # "this user has no visible assets" state. Raising at the end prevents
    # an empty inventory from being cached as authoritative for 10 minutes.
    skipped_catalogs: List[str] = []
    last_skippable_exc: Optional[Exception] = None

    # Lineage walks routinely cross into catalogs the current user can't
    # SELECT from (e.g. `bronze.*` feeding a governed `prod.silver.*`).
    # Matching the per-catalog try/except pattern in
    # axiom/services/assets.py:build_inventory — skip catalogs that
    # raise a skippable metadata error (PERMISSION_DENIED, USE CATALOG,
    # CATALOG_NOT_FOUND, etc.) and continue. The lineage graph will
    # surface those nodes as "lineage-only" assets. Without this, one
    # unreadable catalog in the frontier aborts the whole payload and
    # the endpoint 500s. Both fetches for a catalog run inside ONE pool
    # task so a catalog's inventory+tags stay a unit; the pool itself
    # exists because the sequential scan was the cold-start bottleneck
    # (see parallel_catalog_scan).
    def _fetch_catalog(catalog: str) -> Tuple[pd.DataFrame, pd.DataFrame]:
        inv = cached_catalog_inventory(uc, catalog)
        try:
            tags_df = cached_catalog_table_tags(uc, catalog)
        except Exception as exc:
            if uc_module._is_skippable_metadata_error(exc):
                logger.info(
                    "lineage tags skip: catalog=%s reason=%s",
                    catalog,
                    str(exc).splitlines()[0][:200],
                )
                tags_df = pd.DataFrame()
            else:
                raise
        return inv, tags_df

    for catalog, result, exc in parallel_catalog_scan(catalogs, _fetch_catalog):
        if exc is not None:
            if uc_module._is_skippable_metadata_error(exc):
                logger.info(
                    "lineage inventory skip: catalog=%s reason=%s",
                    catalog,
                    str(exc).splitlines()[0][:200],
                )
                skipped_catalogs.append(catalog)
                last_skippable_exc = exc
                continue
            raise exc
        inv, tags_df = result
        if not inv.empty:
            inv = inv.copy()
            inv["comment"] = inv["comment"].map(normalize_str)
            inv["fqn"] = (
                inv["table_catalog"].astype(str)
                + "."
                + inv["table_schema"].astype(str)
                + "."
                + inv["table_name"].astype(str)
            )
            inventory_frames.append(inv)

        if tags_df is None or tags_df.empty:
            continue
        tags_df = tags_df.copy()
        tags_df["fqn"] = (
            tags_df["table_catalog"].astype(str)
            + "."
            + tags_df["table_schema"].astype(str)
            + "."
            + tags_df["table_name"].astype(str)
        )
        for fqn, group in tags_df.groupby("fqn"):
            tag_maps[str(fqn)] = {
                normalize_str(row.tag_name): normalize_str(row.tag_value)
                for row in group.itertuples()
                if normalize_str(row.tag_name)
            }

    # If EVERY catalog we attempted was skipped with a "skippable" error
    # and nothing made it into inventory_frames, that's almost always a
    # transient failure rather than a real empty state. Raise the last
    # seen exception so the caller's short-TTL cache window triggers
    # (empty results cache for 15s, not 10min) and the user sees real
    # data as soon as the transient condition clears.
    if (
        not inventory_frames
        and catalogs
        and skipped_catalogs
        and len(skipped_catalogs) == len(catalogs)
        and last_skippable_exc is not None
    ):
        logger.warning(
            "inventory: all %d catalog(s) skipped with skippable errors; "
            "treating as transient failure (last error: %s)",
            len(catalogs),
            str(last_skippable_exc).splitlines()[0][:200],
        )
        raise last_skippable_exc

    if not inventory_frames:
        return empty_inventory()

    inventory = pd.concat(inventory_frames, ignore_index=True)
    inventory = filter_asset_rows(inventory, ["table_name", "fqn"])
    if inventory.empty:
        return empty_inventory()

    inventory["tags"] = inventory["fqn"].map(
        lambda fqn: tag_maps.get(str(fqn), {}) if pd.notna(fqn) else {}
    )
    inventory["domain"] = inventory["tags"].map(
        lambda tags: tag_value(tags if isinstance(tags, dict) else {}, "domain")
    )
    inventory["tier"] = inventory["tags"].map(
        lambda tags: tag_value(tags if isinstance(tags, dict) else {}, "tier")
    )
    inventory["certification"] = inventory["tags"].map(
        lambda tags: tag_value(tags if isinstance(tags, dict) else {}, "certification")
    )
    inventory["sensitivity"] = inventory["tags"].map(
        lambda tags: tag_value(tags if isinstance(tags, dict) else {}, "sensitivity")
    )
    inventory["criticality"] = inventory["tags"].map(
        lambda tags: tag_value(tags if isinstance(tags, dict) else {}, "criticality")
    )
    inventory["business_criticality"] = inventory["tags"].map(
        lambda tags: tag_value(tags if isinstance(tags, dict) else {}, "business_criticality")
    )
    inventory["cde"] = inventory["tags"].map(
        lambda tags: tag_value(tags if isinstance(tags, dict) else {}, "cde")
    )
    inventory["glossary_term_tag"] = inventory["tags"].map(
        lambda tags: tag_value(tags if isinstance(tags, dict) else {}, "glossary_term")
    )
    inventory["data_product"] = inventory["tags"].map(
        lambda tags: tag_value(tags if isinstance(tags, dict) else {}, "data_product")
    )

    glossary_terms_df = pd.DataFrame()
    glossary_links_df = pd.DataFrame()
    if store is not None and hasattr(store, "list_glossary_terms"):
        try:
            glossary_terms_df = store.list_glossary_terms(limit=500)
        except Exception:
            glossary_terms_df = pd.DataFrame()
    if store is not None and hasattr(store, "list_glossary_term_links"):
        try:
            glossary_links_df = store.list_glossary_term_links()
        except Exception:
            glossary_links_df = pd.DataFrame()
    glossary_term_index = glossary_term_lookup(glossary_terms_df)
    glossary_link_index = glossary_link_lookup(glossary_links_df, glossary_term_index)
    inventory["glossaryLinks"] = inventory["fqn"].map(
        lambda fqn: (
            glossary_terms_for_subject("asset", str(fqn), glossary_link_index)
            if pd.notna(fqn)
            else []
        )
    )
    inventory["glossaryTerms"] = inventory["glossaryLinks"].map(
        lambda links: [
            normalize_str(link.get("term"))
            for link in links
            if normalize_str(link.get("term"))
        ]
    )
    inventory["glossary_term"] = inventory["glossaryTerms"].map(
        lambda terms: terms[0] if terms else ""
    )
    inventory["glossary_term"] = inventory.apply(
        lambda row: (
            normalize_str(row.get("glossary_term"))
            or normalize_str(row.get("glossary_term_tag"))
        ),
        axis=1,
    )

    owners_df = store.list_owner_assignments()
    if not owners_df.empty:
        owner_rows = []
        for fqn, group in owners_df.groupby("uc_full_name"):
            owner_rows.append(
                {
                    "fqn": fqn,
                    "owner_count": int(group["owner_email"].nunique()),
                    "owners_summary": ", ".join(
                        sorted(
                            {
                                normalize_str(email)
                                for email in group["owner_email"].tolist()
                                if normalize_str(email)
                            }
                        )[:3]
                    ),
                    "business_owner": ", ".join(
                        sorted(
                            {
                                normalize_str(email)
                                for email in group.loc[
                                    group["owner_type"] == "business", "owner_email"
                                ].tolist()
                                if normalize_str(email)
                            }
                        )
                    ),
                    "technical_owner": ", ".join(
                        sorted(
                            {
                                normalize_str(email)
                                for email in group.loc[
                                    group["owner_type"] == "technical", "owner_email"
                                ].tolist()
                                if normalize_str(email)
                            }
                        )
                    ),
                    "steward": ", ".join(
                        sorted(
                            {
                                normalize_str(email)
                                for email in group.loc[
                                    group["owner_type"] == "steward", "owner_email"
                                ].tolist()
                                if normalize_str(email)
                            }
                        )
                    ),
                }
            )
        inventory = inventory.merge(pd.DataFrame(owner_rows), on="fqn", how="left")
    else:
        inventory["owner_count"] = 0
        inventory["owners_summary"] = ""
        inventory["business_owner"] = ""
        inventory["technical_owner"] = ""
        inventory["steward"] = ""

    requests_df = store.list_change_requests(limit=500)
    if not requests_df.empty:
        request_rollup = (
            requests_df[requests_df["uc_full_name"].notna()]
            .groupby("uc_full_name")
            .agg(
                pending_requests=("status", lambda s: int((s == "pending").sum())),
                approved_requests=("status", lambda s: int((s == "approved").sum())),
                rejected_requests=("status", lambda s: int((s == "rejected").sum())),
                total_requests=("request_id", "count"),
            )
            .reset_index()
            .rename(columns={"uc_full_name": "fqn"})
        )
        inventory = inventory.merge(request_rollup, on="fqn", how="left")
    else:
        inventory["pending_requests"] = 0
        inventory["approved_requests"] = 0
        inventory["rejected_requests"] = 0
        inventory["total_requests"] = 0

    for col in [
        "owner_count",
        "pending_requests",
        "approved_requests",
        "rejected_requests",
        "total_requests",
    ]:
        if col not in inventory.columns:
            inventory[col] = 0
        inventory[col] = inventory[col].fillna(0).astype(int)

    for col in [
        "owners_summary",
        "business_owner",
        "technical_owner",
        "steward",
    ]:
        if col not in inventory.columns:
            inventory[col] = ""
        inventory[col] = inventory[col].map(normalize_str)

    inventory["governance_score"] = (
        35 * inventory["comment"].ne("").astype(int)
        + 20 * inventory["owner_count"].gt(0).astype(int)
        + 15 * inventory["domain"].ne("").astype(int)
        + 15 * inventory["certification"].ne("").astype(int)
        + 15 * inventory["glossary_term"].ne("").astype(int)
    )
    inventory["governance_status"] = "Needs Work"
    inventory.loc[inventory["governance_score"] >= 55, "governance_status"] = (
        "Operational"
    )
    inventory.loc[inventory["governance_score"] >= 80, "governance_status"] = (
        "Enterprise Ready"
    )

    search_cols = [
        "fqn",
        "table_name",
        "table_schema",
        "comment",
        "domain",
        "tier",
        "certification",
        "sensitivity",
        "criticality",
        "glossary_term_tag",
        "glossary_term",
        "glossaryLinks",
        "glossaryTerms",
        "data_product",
        "owners_summary",
        "business_owner",
        "technical_owner",
        "steward",
    ]
    inventory["search_text"] = (
        inventory[search_cols].fillna("").astype(str).agg(" ".join, axis=1).str.lower()
    )
    return inventory.sort_values(
        ["governance_score", "pending_requests", "fqn"],
        ascending=[False, False, True],
    ).reset_index(drop=True)


def cached_asset_inventory(_uc: UCSQLClient, _store: Any) -> pd.DataFrame:
    """Cache asset inventory per warehouse.

    Short-TTL guard on empty results: a populated inventory is cached for
    10 minutes (cheap to reuse, rarely changes), but an empty result is
    cached for only 15 seconds. Without that, a transient cold-start or
    OBO-token-propagation lag that returns zero assets would poison
    Discovery for 10 minutes — users would see "No assets match the
    current scope" even after permissions settle. Mirrors the same
    pattern already used in `cached_catalogs` and `cached_catalog_inventory`.
    """
    key = f"asset_inventory:{_warehouse_key(_uc)}"
    now = time.time()
    cached = _TTL_CACHE.get(key)
    if cached:
        age = now - cached[0]
        payload = cached[1]
        is_empty = payload is None or (hasattr(payload, "empty") and payload.empty)
        if age < 600 and not is_empty:
            return payload
        if age < 15 and is_empty:
            return payload
    # Use the locked loader so concurrent misses don't stampede.
    lock = _ttl_cache_lock(key)
    with lock:
        cached = _TTL_CACHE.get(key)
        if cached:
            age = time.time() - cached[0]
            payload = cached[1]
            is_empty = payload is None or (hasattr(payload, "empty") and payload.empty)
            if age < 600 and not is_empty:
                return payload
            if age < 15 and is_empty:
                return payload
        try:
            value = _inventory_rows_to_frames(_uc, _store)
        except Exception as exc:
            # `_inventory_rows_to_frames` raises when every catalog was
            # skipped by a transient metadata error (see its own comment
            # for the why). Translate to an empty frame cached under the
            # 15-second short-TTL so the next call will retry quickly
            # once the transient condition clears — NOT the 10-minute
            # full TTL that would trap users on "No assets match".
            if uc_module._is_skippable_metadata_error(exc):
                logger.warning(
                    "inventory: transient empty state cached for 15s "
                    "due to skippable error: %s",
                    str(exc).splitlines()[0][:200],
                )
                value = empty_inventory()
            else:
                raise
        _TTL_CACHE[key] = (time.time(), value)
        return value
