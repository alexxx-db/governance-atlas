from __future__ import annotations

import difflib
import json
import math
import os
import re
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import pandas as pd

from axiom.bounded_cache import BoundedTTLCache
from axiom.uc import _is_skippable_metadata_error
from axiom.util import quote_ident, sql_literal
from axiom.services import live_metadata as metadata_service
# Canonical business-concept predicates (CDE / certified / critical). Every
# "is this a CDE?" or "is this certified?" decision in this module MUST route
# through axiom.services.semantics so counts can never drift across surfaces.
from axiom.services import semantics


HIDDEN_CATALOGS = {"hive_metastore", "samples", "system", "__databricks_internal"}
HIDDEN_SCHEMA_PREFIXES = ("axiom_ax_stress_",)
HIDDEN_SCHEMA_NAMES = {"axiom_ai", "axiom_demo", "governance_hub"}
INTERNAL_TAG_PREFIXES = (
    "axiom.",
    "axiom_",
    "governance.axiom.",
)
ORGANIC_EXCLUDE_TAGS = {
    "axiom.exclude_from_organic_evidence",
    "axiom_exclude_from_organic_evidence",
}
PLACEHOLDER_DESCRIPTION = "No description has been captured for this asset yet."
ASSET_DETAIL_SECTIONS = (
    "header",
    "activity",
    "schema",
    "preview",
    "properties",
    "operational",
    "profiler",
)
DISCOVERY_QUERY_SYNTAX_HINT = (
    "Use AND, OR, parentheses, quoted phrases, and field:value selectors such as "
    'name:orders or domain:"Finance".'
)
DISCOVERY_QUERY_SUPPORTED_FIELDS = (
    "name",
    "fqn",
    "description",
    "catalog",
    "schema",
    "domain",
    "tier",
    "certification",
    "sensitivity",
    "criticality",
    "business_criticality",
    "cde",
    "glossary",
    "tag",
    "owner",
    "type",
    "data_product",
)
DISCOVERY_QUERY_FIELD_ALIASES = {
    "name": "name",
    "fqn": "fqn",
    "description": "description",
    "catalog": "catalog",
    "schema": "schema",
    "schema_name": "schema",
    "domain": "domain",
    "tier": "tier",
    "certification": "certification",
    "sensitivity": "sensitivity",
    "criticality": "criticality",
    "business_criticality": "business_criticality",
    "businesscriticality": "business_criticality",
    "biz_criticality": "business_criticality",
    "bizcriticality": "business_criticality",
    "cde": "cde",
    "is_cde": "cde",
    "critical_data_element": "cde",
    "glossary": "glossary",
    "glossary_term": "glossary",
    "glossaryterm": "glossary",
    "tag": "tag",
    "tags": "tag",
    "owner": "owner",
    "owners": "owner",
    "type": "type",
    "asset_type": "type",
    "assettype": "type",
    "data_product": "data_product",
    "dataproduct": "data_product",
}
DISCOVERY_QUERY_FIELD_WEIGHTS = {
    "name": 7,
    "fqn": 4,
    "description": 2,
    "catalog": 2,
    "schema": 2,
    "domain": 2,
    "tier": 2,
    "certification": 2,
    "sensitivity": 2,
    "criticality": 2,
    "business_criticality": 3,
    "cde": 3,
    "glossary": 2,
    "tag": 2,
    "owner": 2,
    "type": 2,
    "data_product": 2,
}

_TTL_CACHE: Dict[str, Tuple[float, Any]] = BoundedTTLCache()

cached_asset_inventory = metadata_service.cached_asset_inventory
cached_catalog_inventory = metadata_service.cached_catalog_inventory
cached_catalog_table_tags = metadata_service.cached_catalog_table_tags
cached_catalogs = metadata_service.cached_catalogs
cached_comment = metadata_service.cached_comment
cached_columns = metadata_service.cached_columns
cached_table_detail = metadata_service.cached_table_detail
cached_table_row_count = metadata_service.cached_table_row_count
cached_table_history = metadata_service.cached_table_history
cached_information_schema_table_metadata = (
    metadata_service.cached_information_schema_table_metadata
)
cached_sample_rows = metadata_service.cached_sample_rows
cached_lineage_up = metadata_service.cached_lineage_up
cached_lineage_down = metadata_service.cached_lineage_down
cached_table_constraints = metadata_service.cached_table_constraints
warm_estate_headers = metadata_service.warm_estate_headers
prefetch_asset_header = metadata_service.prefetch_asset_header

normalize_str = metadata_service.normalize_str
filter_asset_rows = metadata_service.filter_asset_rows
split_uc_name = metadata_service.split_uc_name
catalog_filter_options = metadata_service.catalog_filter_options
tag_value = metadata_service.tag_value
lineage_asset_stub = metadata_service.lineage_asset_stub
empty_inventory = metadata_service.empty_inventory


def customer_safe_label(value: Any) -> str:
    text = normalize_str(value)
    if not text:
        return ""
    return re.sub(
        r"\bga-taxonomy-term-([a-z0-9-]+)\b",
        lambda match: match.group(1).replace("-", " ").title(),
        text,
        flags=re.IGNORECASE,
    )


def customer_safe_payload(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: customer_safe_payload(item) for key, item in value.items()}
    if isinstance(value, list):
        return [customer_safe_payload(item) for item in value]
    if isinstance(value, tuple):
        return tuple(customer_safe_payload(item) for item in value)
    if isinstance(value, str):
        return customer_safe_label(value)
    return value


class DiscoveryQuerySyntaxError(ValueError):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def _ttl_value(key: str, ttl_s: int, loader: Callable[[], Any]) -> Any:
    now = time.time()
    cached = _TTL_CACHE.get(key)
    if cached and now - cached[0] < ttl_s:
        return cached[1]
    value = loader()
    _TTL_CACHE[key] = (now, value)
    return value


def _warehouse_key(uc: Any) -> str:
    """Cache partition for this client: warehouse AND acting credentials.

    Keying by warehouse alone leaked actor-scoped reads (visible inventory,
    discovery index, asset headers) across users sharing the warehouse.
    """
    warehouse = normalize_str(getattr(uc, "warehouse_id", "")) or "default"
    scope = normalize_str(getattr(uc, "cache_scope", "")) or "app"
    return f"{warehouse}:{scope}"


def invalidate_asset_caches(asset_fqn: str | None = None) -> None:
    metadata_service.invalidate_live_metadata_caches(asset_fqn)
    for key in list(_TTL_CACHE):
        if (
            key.startswith("inventory:")
            or key.startswith("visible_assets:")
            or key.startswith("discovery_index:")
        ):
            _TTL_CACHE.pop(key, None)
            continue
        if (
            asset_fqn
            and key.startswith("asset_detail:")
            and normalize_str(asset_fqn) in key
        ):
            _TTL_CACHE.pop(key, None)
            continue
        if (
            key.startswith("asset_header_exact:")
            and (not asset_fqn or normalize_str(asset_fqn) in key)
        ):
            _TTL_CACHE.pop(key, None)
            continue
        # The exact-identity memo (P0 visibility-gate cache) must drop when an
        # asset's metadata/tags mutate, or stale tags would serve for 120s.
        if (
            key.startswith("exact_identity:")
            and (not asset_fqn or normalize_str(asset_fqn) in key)
        ):
            _TTL_CACHE.pop(key, None)
    try:
        from axiom.services import lineage as lineage_service

        lineage_service.invalidate_lineage_caches(asset_fqn)
    except Exception:
        pass


def inventory_catalogs(uc, hidden_catalogs: Sequence[str]) -> List[str]:
    values: set[str] = set()
    try:
        values.update(cached_catalogs(uc))
    except Exception:
        pass
    hidden = {str(value).lower() for value in hidden_catalogs}
    return sorted(value for value in values if value and value.lower() not in hidden)


def lineage_observed_catalogs(
    uc,
    *,
    hidden_catalogs: Sequence[str] = HIDDEN_CATALOGS,
) -> List[str]:
    hidden_lower = {str(value).lower() for value in hidden_catalogs}
    return [
        value
        for value in metadata_service.cached_lineage_catalogs(uc)
        if value.lower() not in hidden_lower
    ]


def inventory(
    uc,
    store,
    *,
    hidden_catalogs: Sequence[str] = HIDDEN_CATALOGS,
) -> pd.DataFrame:
    key = f"inventory:{_warehouse_key(uc)}"
    cached = _TTL_CACHE.get(key)
    now = time.time()
    if cached and now - cached[0] < 600:
        payload = cached[1]
        # Empty inventory should not stick for 10 minutes if it came from a
        # transient failure; fall through to a quick retry after 15 seconds.
        if payload is not None and not (hasattr(payload, "empty") and payload.empty):
            return payload
        if now - cached[0] < 15:
            return payload
    value = build_inventory(
        uc,
        store,
        hidden_catalogs,
        _is_skippable_metadata_error,
    )
    _TTL_CACHE[key] = (now, value)
    return value


def _iso_timestamp(value: Any) -> str:
    """Normalize a timestamp-ish value to an ISO-8601 string ('' when absent).

    Used for information_schema.last_altered so the frontend can compute
    relative freshness with `new Date(...)`. Never fabricates: unparseable
    or missing values return an empty string.
    """
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    try:
        ts = pd.Timestamp(value)
    except (TypeError, ValueError):
        return ""
    if ts is pd.NaT:
        return ""
    try:
        return ts.isoformat()
    except Exception:
        return ""


def _catalog_info_schema_map(uc, catalog: str) -> Dict[str, Dict[str, str]]:
    """fqn -> {"last_altered": ISO-8601, "table_owner": principal} per catalog.

    Sourced from the SAME information_schema.tables relation the inventory
    query reads, as a single per-catalog query cached for 600s — this keeps
    the discovery index enrichment cheap (no per-asset fan-out). The UC
    `table_owner` rides along here because the catalog inventory query does
    not select it, yet discovery owner search must match the authoritative
    UC owner (not just the local stewardship assignments). Any failure
    degrades to an empty map so both fields are simply absent, never
    fabricated.
    """

    def _load() -> Dict[str, Dict[str, str]]:
        # table_owner is a standard information_schema.tables column, but keep
        # owner-less fallbacks so freshness enrichment survives a workspace
        # that denies/omits that column for the acting principal.
        queries = [
            f"""SELECT table_catalog, table_schema, table_name, last_altered, table_owner
FROM {quote_ident(catalog)}.information_schema.tables
WHERE table_schema <> 'information_schema'""",
            f"""SELECT table_catalog, table_schema, table_name, last_altered, table_owner
FROM system.information_schema.tables
WHERE table_catalog = {sql_literal(catalog)}
  AND table_schema <> 'information_schema'""",
            f"""SELECT table_catalog, table_schema, table_name, last_altered
FROM {quote_ident(catalog)}.information_schema.tables
WHERE table_schema <> 'information_schema'""",
            f"""SELECT table_catalog, table_schema, table_name, last_altered
FROM system.information_schema.tables
WHERE table_catalog = {sql_literal(catalog)}
  AND table_schema <> 'information_schema'""",
        ]
        for query in queries:
            try:
                df = uc.query_df(query)
            except Exception:
                continue
            if df is None or df.empty:
                return {}
            mapping: Dict[str, Dict[str, str]] = {}
            for _, row in df.iterrows():
                fqn = ".".join(
                    normalize_str(row.get(col))
                    for col in ("table_catalog", "table_schema", "table_name")
                )
                if not fqn:
                    continue
                iso = _iso_timestamp(row.get("last_altered"))
                owner = normalize_str(row.get("table_owner"))
                if iso or owner:
                    mapping[fqn] = {"last_altered": iso, "table_owner": owner}
            return mapping
        return {}

    return _ttl_value(
        f"catalog_info_schema:{_warehouse_key(uc)}:{normalize_str(catalog)}",
        600,
        _load,
    )


_BULK_INVENTORY_COLUMNS = [
    "table_catalog",
    "table_schema",
    "table_name",
    "table_type",
    "data_source_format",
    "comment",
]
_BULK_TAG_COLUMNS = ["table_catalog", "table_schema", "table_name", "tag_name", "tag_value"]


def _bulk_catalog_metadata(uc, catalogs: Sequence[str]) -> Any:
    """catalog -> (inventory, tags, info_map) from one system.information_schema
    pass over every catalog, or None so the caller falls back to the
    per-catalog scan (query failed, or returned nothing for this principal)."""
    if len(catalogs) < 2 or not hasattr(uc, "get_information_schema_bulk"):
        return None
    key = f"bulk_information_schema:{_warehouse_key(uc)}:{','.join(sorted(catalogs))}"
    try:
        tables, tags = _ttl_value(key, 600, lambda: uc.get_information_schema_bulk(list(catalogs)))
    except Exception:
        return None
    if tables is None or tables.empty or not set(_BULK_INVENTORY_COLUMNS) <= set(tables.columns):
        return None
    tables = tables.copy()
    tables["_catalog_key"] = tables["table_catalog"].astype(str).str.lower()
    if tags is None or tags.empty or not set(_BULK_TAG_COLUMNS) <= set(tags.columns):
        tags = pd.DataFrame(columns=_BULK_TAG_COLUMNS + ["_catalog_key"])
    else:
        tags = tags.copy()
        tags["_catalog_key"] = tags["table_catalog"].astype(str).str.lower()
    tables_by_catalog = dict(tuple(tables.groupby("_catalog_key")))
    tags_by_catalog = dict(tuple(tags.groupby("_catalog_key"))) if not tags.empty else {}

    result: Dict[str, Any] = {}
    for catalog in catalogs:
        lower = normalize_str(catalog).lower()
        inv = tables_by_catalog.get(lower, tables.iloc[0:0])
        info_map: Dict[str, Dict[str, str]] = {}
        for row in inv.itertuples(index=False):
            fqn = ".".join(
                normalize_str(getattr(row, col, ""))
                for col in ("table_catalog", "table_schema", "table_name")
            )
            iso = _iso_timestamp(getattr(row, "last_altered", None))
            owner = normalize_str(getattr(row, "table_owner", ""))
            if iso or owner:
                info_map[fqn] = {"last_altered": iso, "table_owner": owner}
        tag_df = tags_by_catalog.get(lower, tags.iloc[0:0])
        result[catalog] = (
            inv[_BULK_INVENTORY_COLUMNS].reset_index(drop=True),
            tag_df[_BULK_TAG_COLUMNS].reset_index(drop=True),
            info_map,
        )
    return result


def build_inventory(
    uc, store, hidden_catalogs: Sequence[str], is_skippable_metadata_error
) -> pd.DataFrame:
    allowed_catalogs = _configured_catalog_allowlist()
    catalogs = sorted(allowed_catalogs) if allowed_catalogs else inventory_catalogs(uc, hidden_catalogs)
    if not catalogs:
        fallback = cached_asset_inventory(uc, store)
        return (
            fallback
            if fallback is not None and not fallback.empty
            else empty_inventory()
        )

    inventory_frames: List[pd.DataFrame] = []
    tag_maps: Dict[str, Dict[str, str]] = {}

    # Perf (P1 cold-start): scan catalogs through a small thread pool instead
    # of sequentially — each information_schema pass costs ~1.2s+ on the
    # warehouse, so a sequential walk over many catalogs kept every surface
    # in "loading" for tens of seconds after each cold start / TTL expiry.
    # Inventory + tags + last_altered for one catalog run inside one task so
    # per-catalog error isolation is preserved (a bad catalog only skips
    # itself; non-skippable errors still abort the whole build as before).
    def _fetch_catalog(
        catalog: str,
    ) -> Tuple[pd.DataFrame, pd.DataFrame, Dict[str, str]]:
        inv = cached_catalog_inventory(uc, catalog)
        try:
            tags_df = cached_catalog_table_tags(uc, catalog)
        except Exception as exc:
            if is_skippable_metadata_error(exc):
                tags_df = pd.DataFrame()
            else:
                raise
        try:
            info_map = _catalog_info_schema_map(uc, catalog)
        except Exception:
            # Freshness/owner enrichment is best-effort; absence degrades to
            # empty updatedAt / uc_owner, never an aborted inventory.
            info_map = {}
        return inv, tags_df, info_map

    info_schema_map: Dict[str, Dict[str, str]] = {}
    bulk = _bulk_catalog_metadata(uc, catalogs)
    scan_results = (
        [(catalog, bulk[catalog], None) for catalog in catalogs]
        if bulk is not None
        else metadata_service.parallel_catalog_scan(catalogs, _fetch_catalog)
    )
    for catalog, result, exc in scan_results:
        if exc is not None:
            if is_skippable_metadata_error(exc):
                continue
            raise exc
        inv, tags_df, info_map = result
        info_schema_map.update(info_map)
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

    if not inventory_frames:
        fallback = cached_asset_inventory(uc, store)
        return (
            fallback
            if fallback is not None and not fallback.empty
            else empty_inventory()
        )

    inventory = pd.concat(inventory_frames, ignore_index=True)
    inventory = filter_asset_rows(inventory, ["table_name", "fqn"])
    if inventory.empty:
        return empty_inventory()

    inventory["tags"] = inventory["fqn"].map(
        lambda fqn: tag_maps.get(str(fqn), {}) if pd.notna(fqn) else {}
    )
    # Freshness enrichment: last_altered comes from the same
    # information_schema.tables relation the inventory reads — one cached
    # query per catalog (never per-asset fan-out), gathered inside the
    # parallel catalog scan above. This lights up the discovery card
    # freshness, "Recently updated" sort, and preview freshness.
    inventory["last_altered"] = inventory["fqn"].map(
        lambda fqn: (
            info_schema_map.get(str(fqn), {}).get("last_altered", "")
            if pd.notna(fqn)
            else ""
        )
    )
    # UC table_owner enrichment: the authoritative Unity Catalog owner must be
    # discoverable via owner:"..." search even when the local governance store
    # has no steward/business assignment for the asset (which is the common
    # case). Sourced from the same cached per-catalog information_schema pass
    # as last_altered — no extra queries.
    inventory["uc_owner"] = inventory["fqn"].map(
        lambda fqn: (
            info_schema_map.get(str(fqn), {}).get("table_owner", "")
            if pd.notna(fqn)
            else ""
        )
    )
    # D8: rows/size/files enrichment from ALREADY-WARM per-table caches only
    # (DESCRIBE DETAIL / COUNT(*) results a prior detail view paid for).
    # warm_table_stats never issues a query, so list endpoints stay one
    # inventory pass; values are honestly absent (None) until something has
    # loaded the table's detail within its cache TTL.
    def _warm_stats_for(fqn: Any) -> Dict[str, Any]:
        try:
            catalog, schema, table = split_uc_name(str(fqn))
        except Exception:
            return {"row_count": None, "size_bytes": None, "file_count": None}
        try:
            return metadata_service.warm_table_stats(uc, catalog, schema, table)
        except Exception:
            return {"row_count": None, "size_bytes": None, "file_count": None}

    warm_stats = inventory["fqn"].map(_warm_stats_for)
    inventory["row_count"] = warm_stats.map(lambda stats: stats.get("row_count"))
    inventory["size_bytes"] = warm_stats.map(lambda stats: stats.get("size_bytes"))
    inventory["file_count"] = warm_stats.map(lambda stats: stats.get("file_count"))
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
            _glossary_terms_for_subject("asset", str(fqn), glossary_link_index)
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
    inventory["glossary_term"] = inventory.apply(
        lambda row: (
            normalize_str(row["glossaryTerms"][0])
            if row.get("glossaryTerms")
            else normalize_str(row.get("glossary_term_tag"))
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
        "glossary_term",
        "data_product",
        "owners_summary",
        "business_owner",
        "technical_owner",
        "steward",
        # UC owner participates in plain-text search too, matching the
        # structured owner: field semantics (defect: owner:"<uc owner email>"
        # returned 0 results while UC owned many assets).
        "uc_owner",
    ]
    inventory["search_text"] = (
        inventory[search_cols].fillna("").astype(str).agg(" ".join, axis=1).str.lower()
    )
    return inventory.sort_values(
        ["governance_score", "pending_requests", "fqn"],
        ascending=[False, False, True],
    ).reset_index(drop=True)


def _configured_catalog_allowlist() -> set[str]:
    raw = os.getenv("AXIOM_DISCOVERY_CATALOGS", "")
    return {
        normalize_str(item).lower()
        for item in raw.split(",")
        if normalize_str(item)
    }


def _configured_control_plane_schemas() -> set[tuple[str, str]]:
    catalog = normalize_str(os.getenv("AXIOM_CATALOG")).lower()
    schema = normalize_str(os.getenv("AXIOM_SCHEMA")).lower()
    if not catalog or not schema:
        return set()
    return {(catalog, schema)}


def _is_control_plane_schema(catalog: Any, schema: Any) -> bool:
    normalized_catalog = normalize_str(catalog).lower()
    normalized_schema = normalize_str(schema).lower()
    if not normalized_schema:
        return False
    if normalized_schema in HIDDEN_SCHEMA_NAMES:
        return True
    return (normalized_catalog, normalized_schema) in _configured_control_plane_schemas()


def asset_fqn_is_hidden(
    asset_fqn: str,
    *,
    hidden_catalogs: Sequence[str] = HIDDEN_CATALOGS,
) -> bool:
    try:
        catalog, schema, _ = split_uc_name(asset_fqn)
    except Exception:
        return False
    if normalize_str(catalog).lower() in {str(value).lower() for value in hidden_catalogs}:
        return True
    normalized_schema = normalize_str(schema).lower()
    if any(normalized_schema.startswith(prefix) for prefix in HIDDEN_SCHEMA_PREFIXES):
        return True
    return _is_control_plane_schema(catalog, schema)


def _tags_exclude_from_organic_evidence(tags: Any) -> bool:
    if not isinstance(tags, dict):
        return False
    normalized = {
        normalize_str(key).lower(): normalize_str(value).lower()
        for key, value in tags.items()
        if normalize_str(key)
    }
    return any(
        normalized.get(tag_name) in {"true", "1", "yes", "enabled"}
        for tag_name in ORGANIC_EXCLUDE_TAGS
    )


def visible_assets(
    inventory_or_uc,
    store=None,
    *,
    hidden_catalogs: Sequence[str] = HIDDEN_CATALOGS,
) -> pd.DataFrame:
    inventory_df = (
        inventory_or_uc
        if isinstance(inventory_or_uc, pd.DataFrame)
        else inventory(inventory_or_uc, store, hidden_catalogs=hidden_catalogs)
    )
    if inventory_df is None or inventory_df.empty:
        return inventory_df
    hidden = {str(value).lower() for value in hidden_catalogs}
    visible_mask = ~inventory_df["table_catalog"].fillna("").astype(str).str.lower().isin(hidden)
    if "table_schema" in inventory_df.columns:
        schema_series = inventory_df["table_schema"].fillna("").astype(str).str.lower()
        for prefix in HIDDEN_SCHEMA_PREFIXES:
            visible_mask &= ~schema_series.str.startswith(prefix)
        if "table_catalog" in inventory_df.columns:
            visible_mask &= ~inventory_df.apply(
                lambda row: _is_control_plane_schema(row.get("table_catalog"), row.get("table_schema")),
                axis=1,
            )
        else:
            visible_mask &= ~schema_series.isin(HIDDEN_SCHEMA_NAMES)
    if "tags" in inventory_df.columns:
        visible_mask &= ~inventory_df["tags"].map(_tags_exclude_from_organic_evidence)
    return inventory_df[visible_mask].reset_index(drop=True)


def inventory_row(
    inventory_or_uc,
    store_or_asset_fqn,
    asset_fqn: str | None = None,
    *,
    hidden_catalogs: Sequence[str] = HIDDEN_CATALOGS,
) -> pd.Series:
    uc_client = None
    if isinstance(inventory_or_uc, pd.DataFrame):
        inventory_df = inventory_or_uc
        resolved_asset_fqn = str(store_or_asset_fqn)
    else:
        uc_client = inventory_or_uc
        inventory_df = visible_assets(
            inventory_or_uc,
            store_or_asset_fqn,
            hidden_catalogs=hidden_catalogs,
        )
        resolved_asset_fqn = str(asset_fqn or "")
    if inventory_df is not None and not inventory_df.empty:
        match = inventory_df[inventory_df["fqn"] == resolved_asset_fqn]
        if not match.empty:
            return match.iloc[0]
    # Fall back to an exact per-asset identity probe only when the visible
    # inventory does not already contain the row. Calling this eagerly for
    # every node fires two extra SQL queries per asset (get_table_identity
    # and get_table_tags), which dominated lineage build time for graphs
    # with many nodes.
    if uc_client is not None:
        exact_row = None if asset_fqn_is_hidden(resolved_asset_fqn, hidden_catalogs=hidden_catalogs) else exact_identity_row(uc_client, resolved_asset_fqn)
        if exact_row is not None:
            # The raw identity probe knows nothing about the governance store,
            # so out-of-inventory assets rendered "Open requests: 0" while the
            # store held real open requests for them (run_history showed 0
            # against 19 pre-cleanup — an affirmatively false negative on the
            # lineage Impact Brief). Join owners + request counts before
            # returning so per-asset counts are true regardless of inventory
            # membership; store handle is only present in this branch.
            return _enrich_identity_row_with_store(
                exact_row, store_or_asset_fqn, resolved_asset_fqn
            )
    if inventory_df is None or inventory_df.empty:
        return lineage_asset_stub(pd.DataFrame(), resolved_asset_fqn)
    return lineage_asset_stub(inventory_df, resolved_asset_fqn)


def asset_exists(
    inventory_or_uc,
    store_or_asset_fqn,
    asset_fqn: str | None = None,
    *,
    hidden_catalogs: Sequence[str] = HIDDEN_CATALOGS,
) -> bool:
    if isinstance(inventory_or_uc, pd.DataFrame):
        inventory_df = inventory_or_uc
        resolved_asset_fqn = str(store_or_asset_fqn)
        exact_row = None
    else:
        inventory_df = visible_assets(
            inventory_or_uc,
            store_or_asset_fqn,
            hidden_catalogs=hidden_catalogs,
        )
        resolved_asset_fqn = str(asset_fqn or "")
        exact_row = None if asset_fqn_is_hidden(resolved_asset_fqn, hidden_catalogs=hidden_catalogs) else exact_identity_row(inventory_or_uc, resolved_asset_fqn)
    if inventory_df is None or inventory_df.empty:
        return exact_row is not None
    if bool((inventory_df["fqn"] == resolved_asset_fqn).any()):
        return True
    return exact_row is not None


def asset_is_visible(
    inventory_or_uc,
    store_or_asset_fqn,
    asset_fqn: str | None = None,
    *,
    hidden_catalogs: Sequence[str] = HIDDEN_CATALOGS,
) -> bool:
    if isinstance(inventory_or_uc, pd.DataFrame):
        inventory_df = inventory_or_uc
        resolved_asset_fqn = str(store_or_asset_fqn)
    else:
        inventory_df = visible_assets(
            inventory_or_uc,
            store_or_asset_fqn,
            hidden_catalogs=hidden_catalogs,
        )
        resolved_asset_fqn = str(asset_fqn or "")
    if inventory_df is None or inventory_df.empty:
        return False
    return bool((inventory_df["fqn"] == resolved_asset_fqn).any())


def asset_columns_df(uc, asset_fqn: str) -> pd.DataFrame:
    catalog, schema, table = split_uc_name(asset_fqn)
    try:
        return cached_columns(uc, catalog, schema, table)
    except Exception:
        return pd.DataFrame()


def _resolve_inventory_df(
    inventory_or_uc,
    store=None,
    *,
    hidden_catalogs: Sequence[str] = HIDDEN_CATALOGS,
) -> pd.DataFrame:
    if isinstance(inventory_or_uc, pd.DataFrame):
        return inventory_or_uc
    return visible_assets(
        inventory_or_uc,
        store,
        hidden_catalogs=hidden_catalogs,
    )


def friendly_table_type(raw: Any, data_source_format: Any = None) -> str:
    normalized = normalize_str(raw).upper().replace("_", " ")
    normalized_format = normalize_str(data_source_format).upper()
    mapping = {
        "BASE TABLE": "Table",
        "TABLE": "Table",
        "MANAGED": "Table",
        "MANAGED TABLE": "Table",
        "EXTERNAL": "Table",
        "EXTERNAL TABLE": "Table",
        "VIEW": "View",
        "MATERIALIZED VIEW": "Materialized View",
        "STREAMING TABLE": "Streaming Table",
    }
    if normalized_format == "DELTA" and normalized in {
        "",
        "BASE TABLE",
        "TABLE",
        "MANAGED",
        "MANAGED TABLE",
        "EXTERNAL",
        "EXTERNAL TABLE",
    }:
        return "Delta Table"
    if normalized in mapping:
        return mapping[normalized]
    if not normalized or normalized.startswith("UNKNOWN"):
        return ""
    return normalize_str(raw).replace("_", " ").title()


def _prefer_specific_table_type(detail_type: Any, inventory_type: Any) -> str:
    detail_normalized = normalize_str(detail_type).upper().replace("_", " ")
    inventory_normalized = normalize_str(inventory_type).upper().replace("_", " ")
    generic_table_types = {
        "",
        "TABLE",
        "BASE TABLE",
        "MANAGED",
        "MANAGED TABLE",
        "EXTERNAL",
        "EXTERNAL TABLE",
    }
    specific_types = {
        "MATERIALIZED VIEW",
        "STREAMING TABLE",
        "VIEW",
    }
    if (
        detail_normalized in generic_table_types
        and inventory_normalized in specific_types
    ):
        return normalize_str(inventory_type)
    return normalize_str(detail_type) or normalize_str(inventory_type)


def supports_direct_metadata_write(raw_table_type: Any) -> bool:
    normalized = normalize_str(raw_table_type).upper().replace("_", " ")
    return normalized in {
        "TABLE",
        "BASE TABLE",
        "MANAGED",
        "MANAGED TABLE",
        "EXTERNAL",
        "EXTERNAL TABLE",
        "VIEW",
        "METRIC VIEW",
        "MATERIALIZED VIEW",
        "STREAMING TABLE",
    }


def friendly_storage_format(raw: Any) -> str:
    normalized = normalize_str(raw).upper()
    if not normalized or normalized.startswith("UNKNOWN"):
        return "—"
    mapping = {
        "DELTA": "Delta",
        "PARQUET": "Parquet",
        "CSV": "CSV",
        "JSON": "JSON",
        "AVRO": "Avro",
        "ORC": "ORC",
        "ICEBERG": "Iceberg",
        "TEXT": "Text",
    }
    return mapping.get(normalized, normalize_str(raw).replace("_", " ").title() or "—")


def management_type(raw: Any) -> str:
    normalized = normalize_str(raw).upper()
    if normalized in {"MANAGED", "MANAGED TABLE"}:
        return "Managed"
    if normalized in {"EXTERNAL", "EXTERNAL TABLE"}:
        return "External"
    return "—"


def coalesce(*values: Any) -> str:
    for value in values:
        normalized = normalize_str(value)
        if normalized:
            return normalized
    return ""


def safe_int(value: Any) -> int:
    try:
        if value is None or (isinstance(value, float) and math.isnan(value)):
            return 0
        return int(float(str(value).replace(",", "")))
    except Exception:
        return 0


def human_bytes(value: Any) -> str:
    try:
        size = float(value)
    except Exception:
        return "—"
    if size <= 0:
        return "—"
    units = ["B", "KB", "MB", "GB", "TB"]
    idx = 0
    while size >= 1024 and idx < len(units) - 1:
        size /= 1024
        idx += 1
    if idx == 0:
        return f"{int(size)} {units[idx]}"
    return f"{size:.1f} {units[idx]}"


def detail_map(detail_df: pd.DataFrame) -> Dict[str, Any]:
    if detail_df is None or detail_df.empty:
        return {}
    row = detail_df.iloc[0].to_dict()
    return {str(key).lower(): value for key, value in row.items()}


def normalize_asset_detail_sections(
    sections: Optional[Sequence[str]] = None,
) -> Tuple[str, ...]:
    if sections is None:
        normalized = set(ASSET_DETAIL_SECTIONS)
    else:
        normalized = {
            normalize_str(section).lower()
            for section in sections
            if normalize_str(section)
        }
        if not normalized:
            normalized = {"header"}
    normalized.add("header")
    if "profiler" in normalized:
        normalized.update({"activity", "schema"})
    return tuple(section for section in ASSET_DETAIL_SECTIONS if section in normalized)


def annotate_account_member(
    uc: Any, entries: Sequence[Dict[str, Any]], *, keys: Sequence[str] = ("email", "name", "ownerEmail")
) -> None:
    """Stamp each owner/steward entry with ``accountMember`` (True/False/None).

    Honesty-at-read: rendering surfaces can badge principals that are not real
    workspace members instead of silently trusting or hiding them. ``None`` when
    the roster is unavailable (degraded) — we never assert a false negative.
    The roster is cached server-side so this is a set lookup, not a SCIM call.
    """
    if not entries:
        return
    try:
        from axiom.services import identity_roster

        roster = identity_roster.get_roster(uc)
    except Exception:
        return
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        principal = ""
        for key in keys:
            candidate = normalize_str(entry.get(key))
            if candidate:
                principal = candidate
                break
        entry["accountMember"] = roster.account_member_flag(principal)


def owner_entries(row: pd.Series) -> List[Dict[str, str]]:
    owners: List[Dict[str, str]] = []
    owner_fields = [
        ("business_owner", "Business Owner"),
        ("technical_owner", "Technical Owner"),
        ("steward", "Steward"),
    ]
    seen: set[Tuple[str, str]] = set()
    for field_name, title in owner_fields:
        raw = normalize_str(row.get(field_name))
        if not raw:
            continue
        for item in [part.strip() for part in raw.split(",") if part.strip()]:
            key = (item.lower(), title)
            if key in seen:
                continue
            seen.add(key)
            owners.append({"name": item, "title": title})
    return owners


def asset_badges(row: pd.Series) -> List[str]:
    structured_keys = {
        "domain",
        "tier",
        "certification",
        "sensitivity",
        "criticality",
        "glossary_term",
        "data_product",
    }
    badges = [
        normalize_str(row.get("domain")),
        normalize_str(row.get("tier")),
        normalize_str(row.get("certification")),
        normalize_str(row.get("sensitivity")),
        normalize_str(row.get("criticality")),
    ]
    if isinstance(row.get("tags"), dict):
        for key, value in row.get("tags", {}).items():
            if key.startswith("__"):
                continue
            normalized_key = normalize_str(key)
            if not _is_customer_visible_tag(normalized_key):
                continue
            normalized_value = customer_safe_label(value)
            if normalized_key.lower() in structured_keys:
                continue
            label = (
                f"{normalized_key}={normalized_value}"
                if normalized_key and normalized_value
                else normalized_key or normalized_value
            )
            if label and label not in badges:
                badges.append(label)
    return [badge for badge in badges if badge]


def _coerce_bool(value: Any) -> bool:
    if value is True:
        return True
    if value is False or value is None:
        return False
    text = normalize_str(value).lower()
    return text in ("true", "1", "yes", "y", "t")


def _asset_is_cde(asset: Dict[str, Any]) -> bool:
    """Canonical CDE check (D5): delegate to semantics.is_cde_asset.

    The explicit-flag fast path stays first so a literal isCde/cde field
    short-circuits without building the semantics haystack; the canonical
    predicate then adds the criticality-derived cases (Critical / Tier 1)
    that the old tag-only check missed — which is why per-asset `isCde`
    reported false for all 50 assets while CDE surfaces counted 49.
    """
    if _coerce_bool(asset.get("isCde")) or _coerce_bool(asset.get("cde")):
        return True
    return semantics.is_cde_asset(asset)


def raw_tag_map(row: pd.Series) -> Dict[str, str]:
    tags = row.get("tags")
    if not isinstance(tags, dict):
        return {}
    return {
        normalize_str(key): customer_safe_label(value)
        for key, value in tags.items()
        if normalize_str(key) and _is_customer_visible_tag(key)
    }


def _is_customer_visible_tag(tag_name: Any) -> bool:
    normalized = normalize_str(tag_name).lower()
    if not normalized:
        return False
    return not any(normalized.startswith(prefix) for prefix in INTERNAL_TAG_PREFIXES)


def _display_or_empty(value: Any) -> str:
    """Collapse the legacy '—' placeholder to an empty string.

    The API must never bake presentation placeholders into payloads: the
    frontend renders its own labeled fallbacks ("Unavailable", "No
    description...") and treats empty as absent. Emitting literal em-dashes
    defeated those fallbacks and read as fake data.
    """
    text = normalize_str(value)
    return "" if text in {"—", "-"} else text


def base_asset_payload(row: pd.Series) -> Dict[str, Any]:
    raw_table_type = normalize_str(row.get("table_type"))
    raw_storage_format = normalize_str(row.get("data_source_format"))
    raw_tags = raw_tag_map(row)
    tag_labels = asset_badges(row)
    glossary_links = row.get("glossaryLinks")
    glossary_terms = row.get("glossaryTerms")
    normalized_glossary_terms = [
        customer_safe_label(term.get("term") if isinstance(term, dict) else term)
        for term in (glossary_terms if isinstance(glossary_terms, list) else [])
        if customer_safe_label(term.get("term") if isinstance(term, dict) else term)
    ]
    payload = {
        "fqn": normalize_str(row.get("fqn")),
        "name": normalize_str(row.get("table_name"))
        or normalize_str(row.get("fqn")).split(".")[-1],
        "catalog": normalize_str(row.get("table_catalog")),
        "schema": normalize_str(row.get("table_schema")),
        "objectType": friendly_table_type(raw_table_type, raw_storage_format),
        # Emit the REAL description (empty when empty). The client renders
        # the "No description has been captured..." placeholder itself;
        # baking the sentence server-side defeated the frontend's
        # missing-description detection and inflated coverage claims.
        "description": normalize_str(row.get("comment")),
        "coverageScore": safe_int(row.get("governance_score")),
        # Rows / size / files come ONLY from real signals: warm DESCRIBE
        # DETAIL / COUNT(*) caches enrich the inventory frame with
        # row_count / size_bytes / file_count when a prior detail load paid
        # for them (see build_inventory). When absent we emit empty strings
        # (never a fabricated number or a literal "—") so the client renders
        # its honest "Unavailable" fallback.
        "rows": (
            f"{safe_int(row.get('row_count')):,}"
            if safe_int(row.get("row_count"))
            else ""
        ),
        "format": _display_or_empty(friendly_storage_format(raw_storage_format)),
        "storageFormat": _display_or_empty(friendly_storage_format(raw_storage_format)),
        "tableTypeRaw": raw_table_type,
        "managementType": _display_or_empty(management_type(raw_table_type)),
        "size": (
            _display_or_empty(human_bytes(row.get("size_bytes")))
            if safe_int(row.get("size_bytes"))
            else ""
        ),
        "files": (
            str(safe_int(row.get("file_count")))
            if safe_int(row.get("file_count"))
            else ""
        ),
        # ISO-8601 last_altered from information_schema (see build_inventory
        # enrichment). Empty when the source didn't report it.
        "updatedAt": _iso_timestamp(row.get("last_altered")),
        # Freshness split (cohesion law 4 — "Data updated" vs "Metadata
        # changed", never conflated): at inventory scope the only known
        # signal is information_schema.last_altered, which is a METADATA
        # change time. It is emitted under its honest name; dataUpdatedAt (a
        # real Delta data write) is unknown here and stays empty — the detail
        # header path fills it from Delta history / DESCRIBE DETAIL caches.
        # `updatedAt` above keeps its legacy value for existing consumers.
        "lastAltered": _iso_timestamp(row.get("last_altered")),
        "dataUpdatedAt": "",
        "domain": normalize_str(row.get("domain")) or "Unassigned",
        "tier": normalize_str(row.get("tier")) or "Unassigned",
        "certification": normalize_str(row.get("certification")) or "Unassigned",
        "sensitivity": normalize_str(row.get("sensitivity")) or "Unassigned",
        "criticality": normalize_str(row.get("criticality")) or "Unassigned",
        "businessCriticality": normalize_str(
            row.get("business_criticality") or row.get("businessCriticality")
        ) or "Unassigned",
        "business_criticality": normalize_str(
            row.get("business_criticality") or row.get("businessCriticality")
        ) or "Unassigned",
        # D5: per-asset isCde must agree with every CDE surface (hero count,
        # /api/cde, cdeOnly filter). The canonical predicate includes the
        # criticality-derived cases, not just the explicit `cde` tag.
        "isCde": _coerce_bool(row.get("cde")) or semantics.is_cde_asset(row),
        "cdeRationale": normalize_str(
            row.get("cde_rationale") or row.get("cdeRationale")
        ),
        "glossaryTerm": (
            normalized_glossary_terms[0]
            if normalized_glossary_terms
            else normalize_str(row.get("glossary_term"))
            or normalize_str(row.get("glossaryTerm"))
        ),
        "glossaryTerms": normalized_glossary_terms,
        "glossaryLinks": list(glossary_links or [])
        if isinstance(glossary_links, list)
        else [],
        "dataProduct": normalize_str(row.get("data_product"))
        or normalize_str(row.get("dataProduct"))
        or "Unassigned",
        "data_product": normalize_str(row.get("data_product"))
        or normalize_str(row.get("dataProduct"))
        or "Unassigned",
        "openRequests": safe_int(row.get("pending_requests")),
        "owners": owner_entries(row),
        # Authoritative Unity Catalog owner (information_schema.tables
        # table_owner) + the local assignment roll-up. Both feed the
        # discovery owner: search field so searching a UC owner email/name
        # matches even when no steward/business owner is assigned locally.
        "ucOwner": normalize_str(row.get("uc_owner")),
        # Distinct owner roles (teardown P2-10): emitted separately so the
        # frontend renders "Owner" / "Steward" from named fields instead of
        # regex-matching the owners list (where the UC-owner entry's title
        # also contains "owner" and shadowed business owners). Values may be
        # comma-separated when multiple principals hold the role; empty means
        # the role is honestly unassigned. `owners` stays authoritative for
        # the full entry list.
        "businessOwner": normalize_str(row.get("business_owner")),
        "technicalOwner": normalize_str(row.get("technical_owner")),
        "steward": normalize_str(row.get("steward")),
        "ownersSummary": normalize_str(row.get("owners_summary")),
        "tags": raw_tags,
        "tagLabels": tag_labels,
        "relatedAssets": [],
        "preview": [],
        "columns": [],
        "governanceStatus": normalize_str(row.get("governance_status")) or "Needs Work",
    }
    return customer_safe_payload(payload)


def asset_header_payload_from_inventory(
    visible_inventory: pd.DataFrame,
    asset_fqn: str,
) -> Optional[Dict[str, Any]]:
    """Return a fast, backed header payload from the visible inventory row.

    This is used only for explicit `sections=header` requests. It avoids cold
    per-table SQL probes while preserving the same fail-closed boundary: if the
    asset is not in the caller-visible inventory, callers must fall back to the
    normal detail loader or return the visibility error they already computed.
    """

    # Read-only lookup: no defensive .copy() of the whole frame. The batch
    # /api/assets/headers endpoint calls this once per requested FQN (up to
    # 64), and copying a full inventory DataFrame per FQN dominated the
    # request cost. base_asset_payload only reads the matched row.
    inventory = (
        visible_inventory
        if isinstance(visible_inventory, pd.DataFrame)
        else pd.DataFrame()
    )
    if inventory.empty:
        return None
    normalized_fqn = normalize_str(asset_fqn)
    if "fqn" not in inventory.columns:
        return None
    match = inventory[inventory["fqn"].fillna("").astype(str).eq(normalized_fqn)]
    if match.empty:
        return None
    row = match.iloc[0]
    base = base_asset_payload(row)
    base.update(
        {
            "columnCount": 0,
            "ownerAssignments": [],
            "activity": [],
            "metadataAudit": [],
            "tableProperties": [],
            "constraints": [],
            "customProperties": [],
            "operationalContext": {"producers": [], "consumers": []},
            "queries": [],
            "usage": {"queryCount": 0, "producerCount": 0, "consumerCount": 0},
            "profiler": {"cards": [], "summary": {}},
            "loadedSections": ["header"],
            "deferredSections": [
                section for section in ASSET_DETAIL_SECTIONS if section != "header"
            ],
            "headerSource": "visible-unity-catalog-inventory",
        }
    )
    return base


def asset_loading_payload(asset_fqn: str) -> Dict[str, Any]:
    normalized_fqn = normalize_str(asset_fqn)
    try:
        catalog, schema, table = split_uc_name(normalized_fqn)
    except ValueError:
        catalog, schema, table = "", "", normalized_fqn.rsplit(".", 1)[-1] or normalized_fqn
    row = pd.Series(
        {
            "fqn": normalized_fqn,
            "table_catalog": catalog,
            "table_schema": schema,
            "table_name": table,
            "table_type": "",
            "data_source_format": "",
            "comment": "",
            "tags": {},
            "domain": "",
            "tier": "",
            "certification": "",
            "sensitivity": "",
            "criticality": "",
            "glossary_term": "",
            "data_product": "",
            "governance_score": 0,
            "pending_requests": 0,
            "owner_count": 0,
            "governance_status": "",
        }
    )
    base = base_asset_payload(row)
    base.update(
        {
            "columnCount": 0,
            "ownerAssignments": [],
            "activity": [],
            "metadataAudit": [],
            "tableProperties": [],
            "constraints": [],
            "customProperties": [],
            "operationalContext": {"producers": [], "consumers": []},
            "queries": [],
            "usage": {"queryCount": 0, "producerCount": 0, "consumerCount": 0},
            "profiler": {"cards": [], "summary": {}},
            "loadedSections": [],
            "deferredSections": list(ASSET_DETAIL_SECTIONS),
            "headerSource": "live-metadata-hydrating",
            "hydrating": True,
        }
    )
    return base


def _enrich_identity_row_with_store(
    row: pd.Series,
    store: Any,
    asset_fqn: str,
) -> pd.Series:
    enriched = row.copy()
    normalized_fqn = normalize_str(asset_fqn)
    if store is not None and hasattr(store, "list_owner_assignments"):
        try:
            owners_df = store.list_owner_assignments()
        except Exception:
            owners_df = pd.DataFrame()
        if owners_df is not None and not owners_df.empty and "uc_full_name" in owners_df.columns:
            owner_matches = owners_df[
                owners_df["uc_full_name"].fillna("").astype(str).eq(normalized_fqn)
            ]
            enriched["owner_count"] = int(owner_matches["owner_email"].nunique()) if not owner_matches.empty else 0
            enriched["owners_summary"] = ", ".join(
                sorted(
                    {
                        normalize_str(email)
                        for email in owner_matches.get("owner_email", pd.Series(dtype=str)).tolist()
                        if normalize_str(email)
                    }
                )[:3]
            )
            for owner_type, field_name in [
                ("business", "business_owner"),
                ("technical", "technical_owner"),
                ("steward", "steward"),
            ]:
                if owner_matches.empty or "owner_type" not in owner_matches.columns:
                    enriched[field_name] = ""
                    continue
                enriched[field_name] = ", ".join(
                    sorted(
                        {
                            normalize_str(email)
                            for email in owner_matches.loc[
                                owner_matches["owner_type"] == owner_type,
                                "owner_email",
                            ].tolist()
                            if normalize_str(email)
                        }
                    )
                )
    for field_name in ["owner_count", "owners_summary", "business_owner", "technical_owner", "steward"]:
        if field_name not in enriched:
            enriched[field_name] = 0 if field_name == "owner_count" else ""

    if store is not None and hasattr(store, "list_change_requests"):
        try:
            requests_df = store.list_change_requests(limit=500)
        except Exception:
            requests_df = pd.DataFrame()
        if requests_df is not None and not requests_df.empty and "uc_full_name" in requests_df.columns:
            request_matches = requests_df[
                requests_df["uc_full_name"].fillna("").astype(str).eq(normalized_fqn)
            ]
            statuses = request_matches.get("status", pd.Series(dtype=str)).fillna("").astype(str)
            enriched["pending_requests"] = int((statuses == "pending").sum())
            enriched["approved_requests"] = int((statuses == "approved").sum())
            enriched["rejected_requests"] = int((statuses == "rejected").sum())
            enriched["total_requests"] = int(len(request_matches.index))
    for field_name in ["pending_requests", "approved_requests", "rejected_requests", "total_requests"]:
        if field_name not in enriched:
            enriched[field_name] = 0

    owner_count = safe_int(enriched.get("owner_count"))
    score = (
        35 * bool(normalize_str(enriched.get("comment")))
        + 20 * (owner_count > 0)
        + 15 * bool(normalize_str(enriched.get("domain")))
        + 15 * bool(normalize_str(enriched.get("certification")))
        + 15 * bool(normalize_str(enriched.get("glossary_term") or enriched.get("glossaryTerm")))
    )
    enriched["governance_score"] = score
    enriched["governance_status"] = (
        "Complete" if score >= 90 else "In Progress" if score >= 55 else "Needs Work"
    )
    return enriched


def asset_header_payload_from_exact_identity(
    uc,
    store: Any,
    asset_fqn: str,
    *,
    hidden_catalogs: Sequence[str] = HIDDEN_CATALOGS,
) -> Optional[Dict[str, Any]]:
    if asset_fqn_is_hidden(asset_fqn, hidden_catalogs=hidden_catalogs):
        return None
    cache_key = f"asset_header_exact:{_warehouse_key(uc)}:{normalize_str(asset_fqn)}"

    def load() -> Optional[Dict[str, Any]]:
        exact_row = exact_identity_row(uc, asset_fqn)
        if exact_row is None:
            return None
        row = _enrich_identity_row_with_store(exact_row, store, asset_fqn)
        base = base_asset_payload(row)
        base.update(
            {
                "columnCount": 0,
                "ownerAssignments": [],
                "activity": [],
                "metadataAudit": [],
                "tableProperties": [],
                "constraints": [],
                "customProperties": [],
                "operationalContext": {"producers": [], "consumers": []},
                "queries": [],
                "usage": {"queryCount": 0, "producerCount": 0, "consumerCount": 0},
                "profiler": {"cards": [], "summary": {}},
                "loadedSections": ["header"],
                "deferredSections": [
                    section for section in ASSET_DETAIL_SECTIONS if section != "header"
                ],
                "headerSource": "direct-unity-catalog-identity",
            }
        )
        return base

    return _ttl_value(cache_key, 120, load)


def _exact_identity_lookup(
    uc, catalog: str, schema: str, table: str
) -> Tuple[Optional[pd.DataFrame], pd.DataFrame]:
    """One concurrent round trip for (identity, tags).

    P0 perf fix: every OBO asset-detail / lineage request used to pay
    get_table_identity THEN get_table_tags serially (~1.6s warm, 7.5s cold)
    before any payload cache was consulted. The two information_schema
    queries are independent, so issuing them together halves the fixed tax
    whenever the lookup is truly needed. Results are memoized per
    (warehouse|scope, fqn) by exact_identity_row below.
    """
    from concurrent.futures import ThreadPoolExecutor

    def _identity() -> Optional[pd.DataFrame]:
        try:
            return uc.get_table_identity(catalog, schema, table)
        except Exception:
            return None

    def _tags() -> pd.DataFrame:
        try:
            return uc.get_table_tags(catalog, schema, table)
        except Exception:
            return pd.DataFrame()

    with ThreadPoolExecutor(
        max_workers=2, thread_name_prefix="axiom-exact-identity"
    ) as pool:
        identity_future = pool.submit(_identity)
        tags_future = pool.submit(_tags)
        return identity_future.result(), tags_future.result()


# TTLs for the exact-identity memo: hits stay warm for 120s (identity/tags
# churn slowly; mutation paths invalidate explicitly), misses only 15s so a
# transient permission/cold-start failure can't hide a real table for long.
_EXACT_IDENTITY_HIT_TTL_S = 120
_EXACT_IDENTITY_MISS_TTL_S = 15


def exact_identity_row(
    uc,
    asset_fqn: str,
    inventory_columns: Optional[Sequence[str]] = None,
) -> Optional[pd.Series]:
    catalog, schema, table = split_uc_name(asset_fqn)

    # P0 perf fix: memoize the RAW (identity, tags) frames per
    # (warehouse|scope, fqn). This lookup sits on the visibility gate of
    # EVERY asset-detail and lineage request, so an uncached call taxed each
    # request ~1.6s warm / 7.5s cold even when the payload itself was cached.
    # The cache key includes the acting credentials via _warehouse_key, so
    # per-user visibility never leaks across actors. We cache the frames
    # (not the assembled Series) because callers pass differing
    # inventory_columns shapes.
    cache_key = f"exact_identity:{_warehouse_key(uc)}:{normalize_str(asset_fqn)}"
    cached = _TTL_CACHE.get(cache_key)
    identity_df: Optional[pd.DataFrame] = None
    tags_df: Optional[pd.DataFrame] = None
    resolved_from_cache = False
    if cached is not None:
        age = time.time() - cached[0]
        hit = cached[1]
        is_miss = hit is None
        if not is_miss and age < _EXACT_IDENTITY_HIT_TTL_S:
            identity_df, tags_df = hit
            resolved_from_cache = True
        elif is_miss and age < _EXACT_IDENTITY_MISS_TTL_S:
            return None

    if not resolved_from_cache:
        identity_df, tags_df = _exact_identity_lookup(uc, catalog, schema, table)
        if identity_df is None or identity_df.empty:
            _TTL_CACHE[cache_key] = (time.time(), None)
            return None
        _TTL_CACHE[cache_key] = (time.time(), (identity_df, tags_df))
    if identity_df is None or identity_df.empty:
        return None

    columns = list(inventory_columns) if inventory_columns is not None else []
    base: Dict[str, Any] = {column: "" for column in columns}
    identity = identity_df.iloc[0].to_dict()
    base.update(
        {
            "fqn": asset_fqn,
            "table_catalog": normalize_str(identity.get("table_catalog")) or catalog,
            "table_schema": normalize_str(identity.get("table_schema")) or schema,
            "table_name": normalize_str(identity.get("table_name")) or table,
            "table_type": normalize_str(identity.get("table_type")),
            "data_source_format": normalize_str(identity.get("data_source_format")),
            "comment": normalize_str(identity.get("comment")),
        }
    )

    if not isinstance(tags_df, pd.DataFrame):
        tags_df = pd.DataFrame()
    tags = {
        normalize_str(row.get("tag_name")): normalize_str(row.get("tag_value"))
        for _, row in tags_df.iterrows()
        if normalize_str(row.get("tag_name"))
    }
    base["tags"] = tags
    base["domain"] = tag_value(tags, "domain")
    base["tier"] = tag_value(tags, "tier")
    base["certification"] = tag_value(tags, "certification")
    base["sensitivity"] = tag_value(tags, "sensitivity")
    base["criticality"] = tag_value(tags, "criticality")
    base["glossary_term"] = tag_value(tags, "glossary_term")
    base["glossaryTerm"] = tag_value(tags, "glossary_term")
    base["data_product"] = tag_value(tags, "data_product")
    base.setdefault("governance_status", "Needs Work")
    return pd.Series(base)


def merge_identity_row(
    base_row: pd.Series, exact_row: Optional[pd.Series]
) -> pd.Series:
    if exact_row is None:
        return base_row

    merged = base_row.copy()
    for key in [
        "fqn",
        "table_catalog",
        "table_schema",
        "table_name",
        "table_type",
        "data_source_format",
        "comment",
    ]:
        value = normalize_str(exact_row.get(key))
        if value:
            merged[key] = value

    base_tags = merged.get("tags") if isinstance(merged.get("tags"), dict) else {}
    exact_tags = (
        exact_row.get("tags") if isinstance(exact_row.get("tags"), dict) else {}
    )
    if exact_tags:
        merged["tags"] = {**base_tags, **exact_tags}

    for key in [
        "domain",
        "tier",
        "certification",
        "sensitivity",
        "criticality",
        "glossary_term",
        "glossaryTerm",
        "data_product",
    ]:
        if not normalize_str(merged.get(key)) and normalize_str(exact_row.get(key)):
            merged[key] = exact_row.get(key)

    return merged


def _discovery_query_supported_fields() -> List[str]:
    return list(DISCOVERY_QUERY_SUPPORTED_FIELDS)


def discovery_invalid_query_payload(message: str) -> Dict[str, Any]:
    return {
        "state": "invalid",
        "message": normalize_str(message) or "Invalid discovery query.",
        "syntaxHint": DISCOVERY_QUERY_SYNTAX_HINT,
        "supportedFields": _discovery_query_supported_fields(),
    }


def _discovery_tag_terms(asset: Dict[str, Any]) -> List[str]:
    raw_tags = asset.get("tags")
    if isinstance(raw_tags, dict):
        tag_terms = []
        for key, value in raw_tags.items():
            normalized_key = normalize_str(key)
            normalized_value = normalize_str(value)
            if normalized_key:
                tag_terms.append(normalized_key)
            if normalized_value:
                tag_terms.extend(
                    [normalized_value, f"{normalized_key} {normalized_value}".strip()]
                )
        return tag_terms
    return [normalize_str(tag) for tag in asset.get("tags", []) if normalize_str(tag)]


def normalized_search_text(*values: Any) -> str:
    raw = " ".join(normalize_str(value) for value in values if normalize_str(value))
    if not raw:
        return ""
    normalized = re.sub(r"[^0-9a-z]+", " ", raw.lower())
    return re.sub(r"\s+", " ", normalized).strip()


def _normalized_query_field(raw_value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", normalize_str(raw_value).lower()).strip("_")
    return DISCOVERY_QUERY_FIELD_ALIASES.get(normalized, "")


def discovery_search_fields(asset: Dict[str, Any]) -> Dict[str, str]:
    tag_terms = _discovery_tag_terms(asset)
    glossary_terms = [
        normalize_str(term.get("term") if isinstance(term, dict) else term)
        for term in asset.get("glossaryTerms", [])
        if normalize_str(term.get("term") if isinstance(term, dict) else term)
    ]
    # Owner search must match every owner representation the asset carries:
    # local assignment names AND emails, the assignment roll-up summary, and
    # the authoritative UC table_owner (defect: owner:"<uc owner email>"
    # returned 0 results because only steward/business names were indexed).
    owner_terms = [
        term
        for owner in asset.get("owners", [])
        if isinstance(owner, dict)
        for term in (
            normalize_str(owner.get("name")),
            normalize_str(owner.get("email")),
        )
        if term
    ]
    for extra_owner in (asset.get("ucOwner"), asset.get("ownersSummary")):
        if normalize_str(extra_owner):
            owner_terms.append(normalize_str(extra_owner))
    fields = {
        "name": normalized_search_text(asset.get("name")),
        "fqn": normalized_search_text(asset.get("fqn")),
        "description": normalized_search_text(asset.get("description")),
        "catalog": normalized_search_text(asset.get("catalog")),
        "schema": normalized_search_text(asset.get("schema")),
        "domain": normalized_search_text(asset.get("domain")),
        "tier": normalized_search_text(asset.get("tier")),
        "certification": normalized_search_text(asset.get("certification")),
        "sensitivity": normalized_search_text(asset.get("sensitivity")),
        "criticality": normalized_search_text(asset.get("criticality")),
        "business_criticality": normalized_search_text(
            asset.get("businessCriticality"), asset.get("business_criticality")
        ),
        "cde": "true" if _asset_is_cde(asset) else "",
        "glossary": normalized_search_text(
            asset.get("glossaryTerm"), " ".join(glossary_terms)
        ),
        "tag": normalized_search_text(" ".join(tag_terms)),
        "owner": normalized_search_text(" ".join(owner_terms)),
        "type": normalized_search_text(asset.get("objectType")),
        "data_product": normalized_search_text(
            asset.get("dataProduct"), asset.get("data_product")
        ),
    }
    fields["all"] = normalized_search_text(
        asset.get("fqn"),
        asset.get("name"),
        asset.get("description"),
        asset.get("catalog"),
        asset.get("schema"),
        asset.get("domain"),
        asset.get("tier"),
        asset.get("certification"),
        asset.get("sensitivity"),
        asset.get("criticality"),
        # D3: plain-text search must reach every governance field a facet
        # can display — business criticality and the CDE marker were only
        # reachable through structured field:value queries before.
        asset.get("businessCriticality"),
        asset.get("business_criticality"),
        "cde critical data element" if fields.get("cde") else "",
        asset.get("cdeRationale"),
        asset.get("glossaryTerm"),
        " ".join(glossary_terms),
        asset.get("objectType"),
        " ".join(tag_terms),
        " ".join(owner_terms),
        asset.get("dataProduct"),
        asset.get("data_product"),
    )
    return fields


def discovery_result_haystack(asset: Dict[str, Any]) -> str:
    return discovery_search_fields(asset).get("all", "")


def _tokenize_discovery_query(query: str) -> List[Tuple[str, str, int]]:
    tokens: List[Tuple[str, str, int]] = []
    index = 0
    while index < len(query):
        char = query[index]
        if char.isspace():
            index += 1
            continue
        if char == "(":
            tokens.append(("LPAREN", char, index))
            index += 1
            continue
        if char == ")":
            tokens.append(("RPAREN", char, index))
            index += 1
            continue
        if char == ":":
            tokens.append(("COLON", char, index))
            index += 1
            continue
        if char == '"':
            value: List[str] = []
            index += 1
            while index < len(query):
                if query[index] == "\\" and index + 1 < len(query):
                    value.append(query[index + 1])
                    index += 2
                    continue
                if query[index] == '"':
                    break
                value.append(query[index])
                index += 1
            if index >= len(query) or query[index] != '"':
                raise DiscoveryQuerySyntaxError(
                    "Unterminated quoted phrase in discovery query."
                )
            tokens.append(("PHRASE", "".join(value), index))
            index += 1
            continue
        start = index
        while (
            index < len(query)
            and not query[index].isspace()
            and query[index] not in '():"'
        ):
            index += 1
        raw = query[start:index]
        upper = raw.upper()
        if upper == "AND":
            tokens.append(("AND", raw, start))
        elif upper == "OR":
            tokens.append(("OR", raw, start))
        else:
            tokens.append(("WORD", raw, start))
    return tokens


def parse_discovery_query(query: str) -> Dict[str, Any]:
    tokens = _tokenize_discovery_query(query)
    position = 0

    def _peek() -> Optional[Tuple[str, str, int]]:
        return tokens[position] if position < len(tokens) else None

    def _starts_factor(token: Optional[Tuple[str, str, int]]) -> bool:
        return bool(token and token[0] in {"WORD", "PHRASE", "LPAREN"})

    def _take(expected: Optional[str] = None) -> Tuple[str, str, int]:
        nonlocal position
        token = _peek()
        if token is None:
            if expected == "RPAREN":
                raise DiscoveryQuerySyntaxError(
                    "Missing closing parenthesis in discovery query."
                )
            raise DiscoveryQuerySyntaxError(
                "Discovery query ended before the expression was complete."
            )
        if expected and token[0] != expected:
            if token[0] == "RPAREN":
                raise DiscoveryQuerySyntaxError(
                    "Unexpected closing parenthesis in discovery query."
                )
            raise DiscoveryQuerySyntaxError(
                f"Unexpected discovery query token `{token[1]}`."
            )
        position += 1
        return token

    def _parse_or(forced_field: str = "") -> Dict[str, Any]:
        left = _parse_and(forced_field)
        children = [left]
        while True:
            token = _peek()
            if not token or token[0] != "OR":
                break
            _take("OR")
            if not _starts_factor(_peek()):
                raise DiscoveryQuerySyntaxError("Expected a search term after OR.")
            children.append(_parse_and(forced_field))
        return {"kind": "or", "children": children} if len(children) > 1 else left

    def _parse_and(forced_field: str = "") -> Dict[str, Any]:
        left = _parse_factor(forced_field)
        children = [left]
        while True:
            token = _peek()
            if token and token[0] == "AND":
                _take("AND")
                if not _starts_factor(_peek()):
                    raise DiscoveryQuerySyntaxError("Expected a search term after AND.")
                children.append(_parse_factor(forced_field))
                continue
            if _starts_factor(token):
                children.append(_parse_factor(forced_field))
                continue
            break
        return {"kind": "and", "children": children} if len(children) > 1 else left

    def _parse_factor(forced_field: str = "") -> Dict[str, Any]:
        token = _peek()
        if token and token[0] == "LPAREN":
            _take("LPAREN")
            if _peek() and _peek()[0] == "RPAREN":
                raise DiscoveryQuerySyntaxError(
                    "Empty grouped expression in discovery query."
                )
            node = _parse_or(forced_field)
            _take("RPAREN")
            return node
        return _parse_term(forced_field)

    def _parse_term(forced_field: str = "") -> Dict[str, Any]:
        token = _peek()
        if not token or token[0] not in {"WORD", "PHRASE"}:
            raise DiscoveryQuerySyntaxError(
                "Expected a search term in discovery query."
            )
        _, raw_value, _ = _take()
        normalized_value = normalized_search_text(raw_value)
        if not normalized_value:
            raise DiscoveryQuerySyntaxError(
                "Expected a search term in discovery query."
            )
        if forced_field:
            if _peek() and _peek()[0] == "COLON":
                raise DiscoveryQuerySyntaxError(
                    "Nested field selectors are not supported inside grouped discovery field clauses."
                )
            return {
                "kind": "term",
                "field": forced_field,
                "value": normalized_value,
                "rawValue": normalize_str(raw_value) or normalized_value,
            }
        if _peek() and _peek()[0] == "COLON":
            _take("COLON")
            normalized_field = _normalized_query_field(raw_value)
            if not normalized_field:
                raise DiscoveryQuerySyntaxError(
                    f"Unknown discovery field `{normalize_str(raw_value) or raw_value}`."
                )
            if not _starts_factor(_peek()):
                raise DiscoveryQuerySyntaxError(
                    f"Expected a value after {normalize_str(raw_value) or raw_value}:"
                )
            if _peek() and _peek()[0] == "LPAREN":
                return _parse_factor(normalized_field)
            return _parse_term(normalized_field)
        return {
            "kind": "term",
            "field": "",
            "value": normalized_value,
            "rawValue": normalize_str(raw_value) or normalized_value,
        }

    parsed = _parse_or()
    trailing = _peek()
    if trailing:
        if trailing[0] == "RPAREN":
            raise DiscoveryQuerySyntaxError(
                "Unexpected closing parenthesis in discovery query."
            )
        if trailing[0] in {"AND", "OR"}:
            raise DiscoveryQuerySyntaxError(
                f"Expected a search term after {trailing[1]}."
            )
        raise DiscoveryQuerySyntaxError(
            f"Unexpected discovery query token `{trailing[1]}`."
        )
    return parsed


def _serialize_discovery_query_value(value: str) -> str:
    normalized = normalize_str(value)
    if not normalized:
        return ""
    escaped = normalized.replace("\\", "\\\\").replace('"', '\\"')
    return (
        normalized if re.fullmatch(r"[A-Za-z0-9_.-]+", normalized) else f'"{escaped}"'
    )


def _discovery_query_group_field(node: Dict[str, Any]) -> str:
    kind = normalize_str(node.get("kind")).lower()
    if kind == "term":
        return normalize_str(node.get("field"))
    if kind not in {"and", "or"}:
        return ""
    fields = {
        _discovery_query_group_field(child)
        for child in node.get("children", [])
        if isinstance(child, dict)
    }
    return fields.pop() if len(fields) == 1 and fields and "" not in fields else ""


def _serialize_discovery_field_group(
    node: Dict[str, Any], parent_kind: str = ""
) -> str:
    kind = normalize_str(node.get("kind")).lower()
    if kind == "term":
        return _serialize_discovery_query_value(
            normalize_str(node.get("rawValue")) or normalize_str(node.get("value"))
        )
    if kind not in {"and", "or"}:
        return ""
    joiner = f" {kind.upper()} "
    rendered = joiner.join(
        _serialize_discovery_field_group(child, kind)
        for child in node.get("children", [])
        if isinstance(child, dict)
    )
    if parent_kind and parent_kind != kind:
        return f"({rendered})"
    return rendered


def serialize_discovery_query_ast(
    node: Optional[Dict[str, Any]], parent_kind: str = ""
) -> str:
    if not isinstance(node, dict):
        return ""
    kind = normalize_str(node.get("kind")).lower()
    if kind == "term":
        field = normalize_str(node.get("field"))
        value = _serialize_discovery_query_value(
            normalize_str(node.get("rawValue")) or normalize_str(node.get("value"))
        )
        if not value:
            return ""
        return f"{field}:{value}" if field else value
    if kind not in {"and", "or"}:
        return ""

    common_field = _discovery_query_group_field(node)
    if common_field:
        grouped = _serialize_discovery_field_group(node)
        return f"{common_field}:({grouped})" if grouped else ""

    joiner = f" {kind.upper()} "
    rendered_children = [
        serialize_discovery_query_ast(child, kind)
        for child in node.get("children", [])
        if isinstance(child, dict)
    ]
    rendered_children = [child for child in rendered_children if child]
    if not rendered_children:
        return ""
    rendered = joiner.join(rendered_children)
    if parent_kind and parent_kind != kind:
        return f"({rendered})"
    return rendered


def discovery_query_clause_chips(
    compiled_query: Dict[str, Any],
) -> List[Dict[str, Any]]:
    if normalize_str(compiled_query.get("state")).lower() != "valid":
        return []
    ast = compiled_query.get("ast")
    if not isinstance(ast, dict):
        return []

    kind = normalize_str(ast.get("kind")).lower()
    if kind == "and":
        children = [
            child for child in ast.get("children", []) if isinstance(child, dict)
        ]
        if not children:
            return []
        chips: List[Dict[str, Any]] = []
        for index, child in enumerate(children):
            remaining_children = children[:index] + children[index + 1 :]
            if not remaining_children:
                next_query = ""
            elif len(remaining_children) == 1:
                next_query = serialize_discovery_query_ast(remaining_children[0])
            else:
                next_query = serialize_discovery_query_ast(
                    {"kind": "and", "children": remaining_children}
                )
            expression = serialize_discovery_query_ast(child, kind)
            chips.append(
                {
                    "label": expression,
                    "expression": expression,
                    "nextQuery": next_query,
                    "removable": True,
                }
            )
        return [chip for chip in chips if chip.get("label")]

    expression = serialize_discovery_query_ast(ast)
    if not expression:
        return []
    return [
        {
            "label": expression,
            "expression": expression,
            "nextQuery": "",
            "removable": True,
        }
    ]


def compile_discovery_query(query: str) -> Dict[str, Any]:
    normalized_query = normalize_str(query)
    if not normalized_query:
        return {
            "state": "empty",
            "message": "",
            "syntaxHint": DISCOVERY_QUERY_SYNTAX_HINT,
            "supportedFields": _discovery_query_supported_fields(),
            "ast": None,
            "clauseChips": [],
        }
    compiled = {
        "state": "valid",
        "message": "",
        "syntaxHint": DISCOVERY_QUERY_SYNTAX_HINT,
        "supportedFields": _discovery_query_supported_fields(),
        "ast": parse_discovery_query(normalized_query),
    }
    compiled["clauseChips"] = discovery_query_clause_chips(compiled)
    return compiled


def _structured_query_is_plain_text(node: Dict[str, Any]) -> bool:
    """True when a compiled structured query has NO field selectors.

    The Discover UI submits every search as queryMode=structured; a bare
    typo like "custmer" therefore arrives as a structured AST of unfielded
    terms. Such a query is semantically plain text and is eligible for the
    didYouMean typo rewrite; anything with a field-scoped term (owner:...)
    keeps exact structured semantics.
    """
    if not isinstance(node, dict):
        return False
    kind = normalize_str(node.get("kind")).lower()
    if kind == "term":
        return not normalize_str(node.get("field"))
    if kind in {"and", "or"}:
        children = [child for child in node.get("children", []) if isinstance(child, dict)]
        return bool(children) and all(
            _structured_query_is_plain_text(child) for child in children
        )
    return False


def _structured_discovery_query_matches(
    node: Dict[str, Any],
    *,
    haystack: str,
    search_fields: Dict[str, str],
) -> bool:
    kind = normalize_str(node.get("kind")).lower()
    if kind == "term":
        field = normalize_str(node.get("field")).replace(" ", "_")
        target = search_fields.get(field) if field else haystack
        value = normalize_str(node.get("value"))
        return bool(value and target and value in target)
    if kind == "and":
        return all(
            _structured_discovery_query_matches(
                child, haystack=haystack, search_fields=search_fields
            )
            for child in node.get("children", [])
        )
    if kind == "or":
        return any(
            _structured_discovery_query_matches(
                child, haystack=haystack, search_fields=search_fields
            )
            for child in node.get("children", [])
        )
    return False


def _general_discovery_term_score(
    value: str, *, haystack: str, search_fields: Dict[str, str]
) -> int:
    if not value or value not in haystack:
        return 0
    terms = [term for term in value.split(" ") if term]
    if not terms:
        return 0

    name = search_fields.get("name", "")
    schema = search_fields.get("schema", "")
    catalog = search_fields.get("catalog", "")
    description = search_fields.get("description", "")
    fqn = search_fields.get("fqn", "")
    glossary = search_fields.get("glossary", "")
    owner = search_fields.get("owner", "")
    tag = search_fields.get("tag", "")
    object_type = search_fields.get("type", "")
    data_product = search_fields.get("data_product", "")
    criticality = search_fields.get("criticality", "")

    score = 0
    if value in name:
        score += 7
    elif all(term in name for term in terms):
        score += 5
    if value in fqn:
        score += 4
    elif all(term in fqn for term in terms):
        score += 3
    if value in schema or all(term in schema for term in terms):
        score += 2
    if value in catalog or all(term in catalog for term in terms):
        score += 2
    if value in description or all(term in description for term in terms):
        score += 2
    if value in glossary or all(term in glossary for term in terms):
        score += 2
    if value in owner or all(term in owner for term in terms):
        score += 2
    if value in tag or all(term in tag for term in terms):
        score += 2
    if value in object_type or all(term in object_type for term in terms):
        score += 2
    if value in data_product or all(term in data_product for term in terms):
        score += 2
    if value in criticality or all(term in criticality for term in terms):
        score += 2
    score += len(terms)
    return score


def _structured_discovery_query_score(
    node: Dict[str, Any],
    *,
    haystack: str,
    search_fields: Dict[str, str],
) -> int:
    kind = normalize_str(node.get("kind")).lower()
    if kind == "term":
        field = normalize_str(node.get("field")).replace(" ", "_")
        value = normalize_str(node.get("value"))
        target = search_fields.get(field) if field else haystack
        if not value or not target or value not in target:
            return 0
        if field:
            return DISCOVERY_QUERY_FIELD_WEIGHTS.get(field, 2) + len(value.split(" "))
        return _general_discovery_term_score(
            value, haystack=haystack, search_fields=search_fields
        )
    if kind == "and":
        child_scores = [
            _structured_discovery_query_score(
                child, haystack=haystack, search_fields=search_fields
            )
            for child in node.get("children", [])
        ]
        return (
            sum(child_scores)
            if child_scores and all(score > 0 for score in child_scores)
            else 0
        )
    if kind == "or":
        child_scores = [
            _structured_discovery_query_score(
                child, haystack=haystack, search_fields=search_fields
            )
            for child in node.get("children", [])
        ]
        positive_scores = [score for score in child_scores if score > 0]
        return max(positive_scores) if positive_scores else 0
    return 0


def discovery_match_score(
    asset: Dict[str, Any], query: str, *, haystack: str = ""
) -> int:
    q = normalized_search_text(query)
    if not q:
        return 0
    terms = [term for term in q.split(" ") if term]
    haystack = haystack or discovery_result_haystack(asset)
    if not all(term in haystack for term in terms):
        return 0

    name = normalized_search_text(asset.get("name"))
    schema = normalized_search_text(asset.get("schema"))
    catalog = normalized_search_text(asset.get("catalog"))
    description = normalized_search_text(asset.get("description"))
    fqn = normalized_search_text(asset.get("fqn"))

    score = 0
    if q in name:
        score += 7
    elif all(term in name for term in terms):
        score += 5
    if q in fqn:
        score += 4
    elif all(term in fqn for term in terms):
        score += 3
    if q in schema or all(term in schema for term in terms):
        score += 2
    if q in catalog or all(term in catalog for term in terms):
        score += 2
    if q in description or all(term in description for term in terms):
        score += 2
    score += len(terms)
    return score


def structured_discovery_match_score(
    asset: Dict[str, Any],
    compiled_query: Dict[str, Any],
    *,
    haystack: str = "",
    search_fields: Optional[Dict[str, str]] = None,
) -> int:
    if compiled_query.get("state") != "valid" or not compiled_query.get("ast"):
        return 0
    resolved_fields = search_fields or discovery_search_fields(asset)
    resolved_haystack = haystack or resolved_fields.get("all", "")
    return _structured_discovery_query_score(
        compiled_query["ast"],
        haystack=resolved_haystack,
        search_fields=resolved_fields,
    )


def view_matches(asset: Dict[str, Any], view: str) -> bool:
    normalized = normalize_str(view)
    if not normalized or normalized == "All assets":
        return True
    if normalized == "Needs attention":
        return (
            normalize_str(asset.get("governanceStatus")) == "Needs Work"
            or safe_int(asset.get("openRequests")) > 0
        )
    if normalized == "Needs owner":
        return len(asset.get("owners", [])) == 0
    if normalized == "Needs certification":
        return normalize_str(asset.get("certification")) == "Unassigned"
    if normalized == "Certified":
        # D6: strict canonical predicate — only certification == "Certified".
        # The old `!= "Unassigned"` check silently counted Draft/Trusted
        # assets as certified (47 instead of 44 on the live estate). Those
        # states keep their own rows in the certification facet instead.
        return semantics.is_certified(asset)
    if normalized == "High coverage":
        return safe_int(asset.get("coverageScore")) >= 75
    return True


def views_match(asset: Dict[str, Any], views: Sequence[str]) -> bool:
    normalized = [
        normalize_str(view)
        for view in views
        if normalize_str(view) and normalize_str(view) != "All assets"
    ]
    if not normalized:
        return True
    return all(view_matches(asset, view) for view in normalized)


def _effective_business_criticality(asset: Dict[str, Any]) -> str:
    """Business-criticality value for facet/filter purposes.

    Prefers the explicit businessCriticality enum, then falls back to the
    `criticality` tag actually used on real estates (D4). Tier is matched by
    the filter (parity with semantics.is_critical) but NOT surfaced as a
    facet value — tier already has its own facet.
    """
    explicit = normalize_str(asset.get("businessCriticality")) or normalize_str(
        asset.get("business_criticality")
    )
    if explicit and explicit != "Unassigned":
        return explicit
    criticality = normalize_str(asset.get("criticality"))
    return criticality if criticality and criticality != "Unassigned" else ""


def _business_criticality_matches(
    asset: Dict[str, Any], selected: Sequence[str]
) -> bool:
    selected_lower = {normalize_str(value).lower() for value in selected}
    candidates = {
        normalize_str(asset.get(field)).lower()
        for field in (
            "businessCriticality",
            "business_criticality",
            "criticality",
            "tier",
        )
    }
    candidates.discard("")
    candidates.discard("unassigned")
    if not candidates:
        # D7 pairing: the facet now exposes an "Unassigned" chip, so an
        # asset with no criticality signal must be selectable through it.
        return "unassigned" in selected_lower
    return bool(candidates & selected_lower)


def normalize_filter_values(values: Optional[List[str]], all_label: str) -> List[str]:
    if not values:
        return []
    return [
        normalize_str(value)
        for value in values
        if normalize_str(value) and normalize_str(value) != all_label
    ]


def facet_payload(
    assets: List[Dict[str, Any]],
    field: str | Callable[[Dict[str, Any]], str],
    *,
    all_label: str,
) -> List[Dict[str, Any]]:
    """Facet rows: [All, ...real values (sorted), Unassigned].

    D7: empty/"Unassigned" values used to be silently dropped, so chip sums
    never reconciled with the "All" total and users couldn't filter to the
    ungoverned slice. Every asset now lands in exactly one bucket, so the
    per-value counts always sum to the All count. `field` may be a callable
    for derived facets (e.g. business criticality falling back to the
    criticality tag).
    """
    extractor = field if callable(field) else (lambda asset: asset.get(field))
    counts: Dict[str, int] = {}
    unassigned = 0
    for asset in assets:
        value = normalize_str(extractor(asset))
        if not value or value == "Unassigned":
            unassigned += 1
            continue
        counts[value] = counts.get(value, 0) + 1
    items = [{"value": all_label, "count": len(assets)}]
    items.extend({"value": value, "count": counts[value]} for value in sorted(counts))
    # Emit the Unassigned bucket even at zero so the frontend renders a
    # stable chip set and the sum-to-total invariant is visible.
    items.append({"value": "Unassigned", "count": unassigned})
    return items


def owners_facet_payload(
    assets: List[Dict[str, Any]], *, all_label: str, top_n: int = 8
) -> List[Dict[str, Any]]:
    """Owner facet: tally distinct owners across the full matched set
    plus an explicit "Unassigned" bucket for rows with no owners.

    The per-asset "owners" field is a list of {name, title, email?}
    dicts (see owner_entries()). Each named owner contributes one
    vote per asset that lists them; an asset with zero owners feeds
    "Unassigned". Returned as [All, ...top_n real owners, Unassigned]
    matching the shape of facet_payload() so the frontend can render
    identical checkbox rows.
    """
    counts: Dict[str, int] = {}
    unassigned = 0
    for asset in assets:
        owner_list = asset.get("owners") or []
        if not isinstance(owner_list, list) or not owner_list:
            unassigned += 1
            continue
        seen_for_asset: set[str] = set()
        for owner in owner_list:
            if isinstance(owner, dict):
                label = (
                    normalize_str(owner.get("email"))
                    or normalize_str(owner.get("name"))
                    or normalize_str(owner.get("label"))
                )
            else:
                label = normalize_str(owner)
            if not label or label in seen_for_asset:
                continue
            seen_for_asset.add(label)
            counts[label] = counts.get(label, 0) + 1
        if not seen_for_asset:
            unassigned += 1
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:top_n]
    items: List[Dict[str, Any]] = [{"value": all_label, "count": len(assets)}]
    items.extend({"value": label, "count": count} for label, count in ordered)
    items.append({"value": "Unassigned", "count": unassigned})
    return items


def view_facet_payload(
    assets: List[Dict[str, Any]],
    *,
    all_label: str,
    views: Sequence[str],
) -> List[Dict[str, Any]]:
    items = [{"value": all_label, "count": len(assets)}]
    for view in views:
        normalized = normalize_str(view)
        if not normalized or normalized == all_label:
            continue
        items.append(
            {
                "value": view,
                "count": sum(1 for asset in assets if view_matches(asset, view)),
            }
        )
    return items


def sort_discovery_assets(
    assets: List[Dict[str, Any]],
    *,
    sort_by: str,
    query: str,
    query_mode: str = "plain",
    compiled_query: Optional[Dict[str, Any]] = None,
    search_fields_by_fqn: Optional[Dict[str, Dict[str, str]]] = None,
) -> List[Dict[str, Any]]:
    normalized_sort = normalize_str(sort_by)
    normalized_query_mode = normalize_str(query_mode).lower()

    # D9: open requests are a QUALITY-NEGATIVE signal. All descending-quality
    # sorts (best match, governance score) must break ties with FEWER open
    # requests first — the old `reverse=True` tuple put the most-contested
    # asset on top whenever governance scores saturated at 100. Keys below
    # use explicit sign flips with reverse=False so fqn stays A-Z.
    def _best_match_key(asset: Dict[str, Any]) -> Tuple[int, int, int, str]:
        search_fields = (
            search_fields_by_fqn.get(asset.get("fqn"), {})
            if isinstance(search_fields_by_fqn, dict)
            else {}
        )
        haystack = search_fields.get("all", "")
        if normalized_query_mode == "structured" and compiled_query:
            match_score = structured_discovery_match_score(
                asset,
                compiled_query,
                haystack=haystack,
                search_fields=search_fields or None,
            )
        else:
            match_score = discovery_match_score(asset, query, haystack=haystack)
        return (
            -match_score,
            -safe_int(asset.get("coverageScore")),
            safe_int(asset.get("openRequests")),
            normalize_str(asset.get("fqn")),
        )

    # "Governance score" is the honest label for the 35/20/15/15/15 metadata
    # formula; the legacy "Trust score" / "Coverage score" labels stay
    # accepted so old clients don't silently fall back to best-match.
    if normalized_sort in {"Coverage score", "Trust score", "Governance score"}:
        return sorted(
            assets,
            key=lambda asset: (
                -safe_int(asset.get("coverageScore")),
                safe_int(asset.get("openRequests")),
                normalize_str(asset.get("fqn")),
            ),
        )
    if normalized_sort == "Open requests":
        # Explicit "Open requests" sort keeps most-contested-first — that IS
        # the requested ordering — with governance score as the tiebreaker.
        return sorted(
            assets,
            key=lambda asset: (
                -safe_int(asset.get("openRequests")),
                -safe_int(asset.get("coverageScore")),
                normalize_str(asset.get("fqn")),
            ),
        )
    if normalized_sort == "Recently updated":
        # updatedAt is ISO-8601 (lexicographically ordered) from
        # information_schema.last_altered. Assets with no known freshness
        # sort last rather than fabricating a date.
        return sorted(
            assets,
            key=lambda asset: (
                0 if normalize_str(asset.get("updatedAt")) else 1,
                # Negative-lexicographic isn't possible on strings, so sort
                # the dated group descending via a reversed pre-sort key:
                _descending_text_key(normalize_str(asset.get("updatedAt"))),
                normalize_str(asset.get("fqn")),
            ),
        )
    if normalized_sort == "Name (A-Z)":
        return sorted(
            assets, key=lambda asset: normalize_str(asset.get("name")).lower()
        )
    return sorted(assets, key=_best_match_key)


def _descending_text_key(value: str) -> Tuple[int, ...]:
    """Tuple key that orders ISO timestamp strings newest-first inside an
    ascending sort (invert each code point). Empty handled by caller."""
    return tuple(-ord(char) for char in value)


def _discovery_vocabulary(index_entries: List[Dict[str, Any]]) -> List[str]:
    """Distinct searchable tokens across the visible index haystacks."""
    tokens: set[str] = set()
    for entry in index_entries:
        haystack = entry.get("haystack") if isinstance(entry, dict) else ""
        for token in normalize_str(haystack).split(" "):
            if len(token) >= 3:
                tokens.add(token)
    return sorted(tokens)


def suggest_discovery_query(
    query: str, index_entries: List[Dict[str, Any]]
) -> str:
    """Nearest-vocabulary rewrite of a zero-result query (D1 typo tolerance).

    For each query term with no exact vocabulary hit, substitute the closest
    token by difflib ratio (cutoff ≈ edit distance ≤ 2 on short tokens) or a
    prefix completion. Returns the corrected query string, or "" when no
    term could be improved — the caller only surfaces `didYouMean` (and the
    near-match result pass) when this returns a real rewrite, so we never
    invent matches for genuinely unknown terms.
    """
    normalized_query = normalized_search_text(query)
    if not normalized_query:
        return ""
    vocabulary = _discovery_vocabulary(index_entries)
    if not vocabulary:
        return ""
    vocab_set = set(vocabulary)
    corrected: List[str] = []
    changed = False
    for term in normalized_query.split(" "):
        if not term:
            continue
        if term in vocab_set or any(term in token for token in vocab_set):
            # Term already matches something (whole or substring) — the zero
            # results came from AND-ing with other terms; leave it alone.
            corrected.append(term)
            continue
        close = difflib.get_close_matches(term, vocabulary, n=1, cutoff=0.72)
        if not close and len(term) >= 4:
            prefixed = [token for token in vocabulary if token.startswith(term[:4])]
            close = difflib.get_close_matches(term, prefixed, n=1, cutoff=0.6)
        if close:
            corrected.append(close[0])
            changed = True
        else:
            corrected.append(term)
    if not changed:
        return ""
    suggestion = " ".join(corrected)
    return suggestion if suggestion != normalized_query else ""


def _discovery_index_key(uc: Any) -> str:
    return f"discovery_index:{_warehouse_key(uc)}"


def _discovery_index(
    inventory_or_uc,
    store=None,
    *,
    hidden_catalogs: Sequence[str] = HIDDEN_CATALOGS,
) -> List[Dict[str, Any]]:
    inventory = _resolve_inventory_df(
        inventory_or_uc,
        store,
        hidden_catalogs=hidden_catalogs,
    )
    entries: List[Dict[str, Any]] = []
    for _, row in inventory.iterrows():
        asset = base_asset_payload(row)
        search_fields = discovery_search_fields(asset)
        entries.append(
            {
                "asset": asset,
                "haystack": search_fields.get("all", ""),
                "fields": search_fields,
            }
        )
    return entries


def cached_discovery_index(
    inventory_or_uc,
    store=None,
    *,
    hidden_catalogs: Sequence[str] = HIDDEN_CATALOGS,
) -> List[Dict[str, Any]]:
    if isinstance(inventory_or_uc, pd.DataFrame):
        return _discovery_index(inventory_or_uc, store, hidden_catalogs=hidden_catalogs)
    return _ttl_value(
        _discovery_index_key(inventory_or_uc),
        300,
        lambda: _discovery_index(
            inventory_or_uc,
            store,
            hidden_catalogs=hidden_catalogs,
        ),
    )


def discovery_search_payload(
    inventory_or_uc,
    store=None,
    *,
    query: str = "",
    query_mode: str = "plain",
    views: Optional[List[str]] = None,
    asset_types: Optional[List[str]] = None,
    catalogs: Optional[List[str]] = None,
    domains: Optional[List[str]] = None,
    tiers: Optional[List[str]] = None,
    certifications: Optional[List[str]] = None,
    sensitivities: Optional[List[str]] = None,
    business_criticalities: Optional[List[str]] = None,
    cde_only: bool = False,
    sort_by: str = "Best match",
    limit: int = 60,
    offset: int = 0,
    hidden_catalogs: Sequence[str] = HIDDEN_CATALOGS,
) -> Dict[str, Any]:
    index_entries = cached_discovery_index(
        inventory_or_uc,
        store,
        hidden_catalogs=hidden_catalogs,
    )
    query_text = normalize_str(query)
    normalized_query_mode = normalize_str(query_mode).lower()
    compiled_query = (
        compile_discovery_query(query_text)
        if normalized_query_mode == "structured"
        else {
            "state": "empty" if not query_text else "valid",
            "message": "",
            "syntaxHint": DISCOVERY_QUERY_SYNTAX_HINT,
            "supportedFields": _discovery_query_supported_fields(),
            "ast": None,
        }
    )
    selected_views = normalize_filter_values(views, "All assets")
    selected_catalogs = normalize_filter_values(catalogs, "All catalogs")
    selected_domains = normalize_filter_values(domains, "All domains")
    selected_tiers = normalize_filter_values(tiers, "All tiers")
    selected_certifications = normalize_filter_values(
        certifications, "All certifications"
    )
    selected_sensitivities = normalize_filter_values(sensitivities, "All sensitivities")
    selected_business_criticalities = normalize_filter_values(
        business_criticalities, "All criticalities"
    )
    require_cde = bool(cde_only)
    selected_types = normalize_filter_values(asset_types, "All types")

    matched_assets: List[Dict[str, Any]] = []
    search_fields_by_fqn: Dict[str, Dict[str, str]] = {}
    for entry in index_entries:
        asset = entry["asset"]
        search_fields = (
            entry.get("fields", {}) if isinstance(entry.get("fields"), dict) else {}
        )
        asset_fqn = normalize_str(asset.get("fqn"))
        if asset_fqn:
            search_fields_by_fqn[asset_fqn] = search_fields
        if query_text:
            if normalized_query_mode == "structured":
                match_score = structured_discovery_match_score(
                    asset,
                    compiled_query,
                    haystack=entry.get("haystack", ""),
                    search_fields=search_fields or None,
                )
            else:
                match_score = discovery_match_score(
                    asset, query_text, haystack=entry.get("haystack", "")
                )
            if match_score <= 0:
                continue
        matched_assets.append(asset)

    # D1: typo tolerance. When the strict AND-substring pass finds nothing
    # for a plain-text query with no narrowing filters, try a cheap
    # nearest-vocabulary rewrite (difflib over index tokens) and rerun the
    # match with the corrected terms. The rewrite is surfaced as
    # `didYouMean` so the UI can say "Showing results for 'customer'" —
    # results come from real matches on the corrected terms, never invented.
    did_you_mean = ""
    near_match_applied = False
    filters_selected = bool(
        selected_views
        or selected_types
        or selected_catalogs
        or selected_domains
        or selected_tiers
        or selected_certifications
        or selected_sensitivities
        or selected_business_criticalities
        or require_cde
    )
    # The Discover UI always sends queryMode=structured, even for a bare
    # typo like "custmer" — so gating the rewrite on plain mode alone left
    # didYouMean permanently empty in the product. A structured query whose
    # AST carries no field selectors is semantically plain text; give it the
    # same typo tolerance. Genuinely field-scoped queries (owner:..., tag:...)
    # keep exact semantics with no fuzzy rewrite.
    plain_like_query = normalized_query_mode != "structured" or (
        isinstance(compiled_query, dict)
        and _structured_query_is_plain_text(compiled_query.get("ast") or {})
    )
    if (
        query_text
        and plain_like_query
        and not matched_assets
        and not filters_selected
    ):
        did_you_mean = suggest_discovery_query(query_text, index_entries)
        if did_you_mean:
            for entry in index_entries:
                asset = entry["asset"]
                match_score = discovery_match_score(
                    asset, did_you_mean, haystack=entry.get("haystack", "")
                )
                if match_score > 0:
                    matched_assets.append(asset)
            near_match_applied = bool(matched_assets)
            if not near_match_applied:
                # The rewrite found no real matches either — suppress the
                # suggestion instead of promising results that don't exist.
                did_you_mean = ""

    def in_scope(asset: Dict[str, Any], *, exclude: Optional[set[str]] = None) -> bool:
        excluded = exclude or set()
        if (
            selected_views
            and "views" not in excluded
            and not views_match(asset, selected_views)
        ):
            return False
        if selected_types and asset.get("objectType") not in selected_types:
            if "types" not in excluded:
                return False
        if selected_catalogs and asset.get("catalog") not in selected_catalogs:
            if "catalogs" not in excluded:
                return False
        if selected_domains and asset.get("domain") not in selected_domains:
            if "domains" not in excluded:
                return False
        if selected_tiers and asset.get("tier") not in selected_tiers:
            if "tiers" not in excluded:
                return False
        if (
            selected_certifications
            and asset.get("certification") not in selected_certifications
        ):
            if "certifications" not in excluded:
                return False
        if (
            selected_sensitivities
            and asset.get("sensitivity") not in selected_sensitivities
        ):
            if "sensitivities" not in excluded:
                return False
        if (
            selected_business_criticalities
            and "businessCriticalities" not in excluded
        ):
            # D4: match over the SAME field set semantics.is_critical reads
            # (criticality / business_criticality / tier). Real estates tag
            # `criticality=Critical`; the enum businessCriticality axis is
            # sparsely adopted, so filtering only that field returned zero
            # for every chip the facet itself displayed.
            if not _business_criticality_matches(
                asset, selected_business_criticalities
            ):
                return False
        if require_cde and "cde" not in excluded:
            if not _asset_is_cde(asset):
                return False
        return True

    scoped_assets: List[Dict[str, Any]] = []
    for asset in matched_assets:
        if not in_scope(asset):
            continue
        scoped_assets.append(asset)

    sorted_assets = sort_discovery_assets(
        scoped_assets,
        sort_by=sort_by,
        # Near-match results must rank by the corrected terms — scoring them
        # against the original misspelling would zero every match score and
        # collapse ordering to tiebreakers.
        query=did_you_mean if near_match_applied else query_text,
        query_mode=normalized_query_mode,
        # After a near-match rewrite the misspelled AST would zero every
        # structured score; rank by the corrected plain terms instead.
        compiled_query=compiled_query
        if normalized_query_mode == "structured" and not near_match_applied
        else None,
        search_fields_by_fqn=search_fields_by_fqn,
    )
    safe_limit = max(1, min(limit, 200))
    safe_offset = max(0, offset)
    window = sorted_assets[safe_offset : safe_offset + safe_limit]

    facets = {
        "views": view_facet_payload(
            [asset for asset in matched_assets if in_scope(asset, exclude={"views"})],
            all_label="All assets",
            views=[
                "All assets",
                "Needs attention",
                "Needs owner",
                "Needs certification",
                "Certified",
                "High coverage",
            ],
        ),
        "assetTypes": facet_payload(
            [asset for asset in matched_assets if in_scope(asset, exclude={"types"})],
            "objectType",
            all_label="All types",
        ),
        "catalogs": facet_payload(
            [
                asset
                for asset in matched_assets
                if in_scope(asset, exclude={"catalogs"})
            ],
            "catalog",
            all_label="All catalogs",
        ),
        "domains": facet_payload(
            [asset for asset in matched_assets if in_scope(asset, exclude={"domains"})],
            "domain",
            all_label="All domains",
        ),
        "tiers": facet_payload(
            [asset for asset in matched_assets if in_scope(asset, exclude={"tiers"})],
            "tier",
            all_label="All tiers",
        ),
        "certifications": facet_payload(
            [
                asset
                for asset in matched_assets
                if in_scope(asset, exclude={"certifications"})
            ],
            "certification",
            all_label="All certifications",
        ),
        "sensitivities": facet_payload(
            [
                asset
                for asset in matched_assets
                if in_scope(asset, exclude={"sensitivities"})
            ],
            "sensitivity",
            all_label="All sensitivities",
        ),
        # D4: derived extractor so facet chips reflect the same field set the
        # filter matches (businessCriticality falling back to criticality).
        "businessCriticalities": facet_payload(
            [
                asset
                for asset in matched_assets
                if in_scope(asset, exclude={"businessCriticalities"})
            ],
            _effective_business_criticality,
            all_label="All criticalities",
        ),
        "owners": owners_facet_payload(
            [asset for asset in matched_assets if in_scope(asset, exclude={"owners"})],
            all_label="All owners",
        ),
    }

    return {
        "assets": window,
        "count": len(sorted_assets),
        "facets": facets,
        # D1 contract additions (always present, additive):
        # - didYouMean: corrected query string when a near-match rewrite
        #   produced real results (else "").
        # - queryState.nearMatch mirrors whether the returned assets came
        #   from the corrected terms rather than the literal query.
        "didYouMean": did_you_mean,
        "queryState": {
            "state": compiled_query.get("state", "empty"),
            "message": "",
            "syntaxHint": compiled_query.get("syntaxHint", DISCOVERY_QUERY_SYNTAX_HINT),
            "supportedFields": list(
                compiled_query.get(
                    "supportedFields", _discovery_query_supported_fields()
                )
            ),
            "clauseChips": list(compiled_query.get("clauseChips", [])),
            "nearMatch": near_match_applied,
        },
        "selection": {
            "primaryAssetFqn": window[0]["fqn"] if window else "",
            "reason": "top_result" if window else "none",
        },
    }


def cde_registry_payload(
    inventory_or_uc,
    store=None,
    *,
    domains: Optional[List[str]] = None,
    hidden_catalogs: Sequence[str] = HIDDEN_CATALOGS,
) -> Dict[str, Any]:
    """Return Critical Data Element assets grouped by owning domain.

    Reads the discovery index (same source discovery search uses) and
    keeps only entries whose `cde` tag resolves truthy. The payload
    powers the CDE registry workspace.
    """
    index_entries = cached_discovery_index(
        inventory_or_uc,
        store,
        hidden_catalogs=hidden_catalogs,
    )
    requested_domains = normalize_filter_values(domains, "All domains")

    cde_assets: List[Dict[str, Any]] = []
    for entry in index_entries:
        asset = entry.get("asset") if isinstance(entry, dict) else None
        if not isinstance(asset, dict):
            continue
        if not _asset_is_cde(asset):
            continue
        if requested_domains:
            asset_domain = normalize_str(asset.get("domain"))
            if asset_domain not in requested_domains:
                continue
        cde_assets.append(asset)

    by_domain: Dict[str, List[Dict[str, Any]]] = {}
    for asset in cde_assets:
        domain = normalize_str(asset.get("domain")) or "Unassigned"
        by_domain.setdefault(domain, []).append(asset)

    domain_groups: List[Dict[str, Any]] = []
    for domain in sorted(by_domain.keys()):
        group_assets = sorted(
            by_domain[domain],
            key=lambda item: (
                normalize_str(item.get("name")).lower(),
                normalize_str(item.get("fqn")).lower(),
            ),
        )
        domain_groups.append(
            {
                "domain": domain,
                "count": len(group_assets),
                "assets": [
                    {
                        "fqn": normalize_str(asset.get("fqn")),
                        "name": normalize_str(asset.get("name")),
                        "catalog": normalize_str(asset.get("catalog")),
                        "schema": normalize_str(asset.get("schema")),
                        "domain": normalize_str(asset.get("domain")) or "Unassigned",
                        "tier": normalize_str(asset.get("tier")) or "Unassigned",
                        "businessCriticality": normalize_str(
                            asset.get("businessCriticality")
                            or asset.get("business_criticality")
                        )
                        or "Unassigned",
                        "cdeRationale": normalize_str(
                            asset.get("cdeRationale") or asset.get("cde_rationale")
                        ),
                        "coverageScore": asset.get("coverageScore"),
                        "governanceStatus": normalize_str(
                            asset.get("governanceStatus")
                        )
                        or "Needs Work",
                        "owners": asset.get("owners") or [],
                        "glossaryTerm": normalize_str(asset.get("glossaryTerm")),
                        "description": normalize_str(asset.get("description")),
                    }
                    for asset in group_assets
                ],
            }
        )

    return {
        "total": len(cde_assets),
        "domainGroups": domain_groups,
        "domainFilter": {
            "options": sorted({group["domain"] for group in domain_groups}),
            "selected": requested_domains,
        },
    }


def related_assets(
    uc,
    catalog: str,
    schema: str,
    table: str,
    focus_fqn: str,
    inventory_df: Optional[pd.DataFrame] = None,
) -> List[str]:
    try:
        upstream = filter_asset_rows(
            cached_lineage_up(uc, catalog, schema, table),
            ["source_table_name", "source_table_full_name"],
            exclude_fqn=focus_fqn,
        )
    except Exception:
        upstream = pd.DataFrame()
    try:
        downstream = filter_asset_rows(
            cached_lineage_down(uc, catalog, schema, table),
            ["target_table_name", "target_table_full_name"],
            exclude_fqn=focus_fqn,
        )
    except Exception:
        downstream = pd.DataFrame()
    values: List[str] = []
    if (
        upstream is not None
        and not upstream.empty
        and "source_table_full_name" in upstream.columns
    ):
        values.extend(upstream["source_table_full_name"].dropna().astype(str).tolist())
    if (
        downstream is not None
        and not downstream.empty
        and "target_table_full_name" in downstream.columns
    ):
        values.extend(
            downstream["target_table_full_name"].dropna().astype(str).tolist()
        )
    normalized = [normalize_str(item) for item in values if normalize_str(item)]
    deduped = list(dict.fromkeys(item for item in normalized if item != focus_fqn))
    openable: List[str] = []
    for item in deduped:
        if inventory_df is not None and asset_is_visible(inventory_df, item):
            openable.append(item)
    return openable[:8]


def preview_records(sample_df: pd.DataFrame) -> List[Dict[str, str]]:
    if sample_df is None or sample_df.empty:
        return []
    view = sample_df.head(8).copy()
    limited_cols = list(view.columns[:8])
    view = view[limited_cols]
    rows: List[Dict[str, str]] = []
    for _, row in view.iterrows():
        rows.append({str(col): normalize_str(row.get(col)) for col in limited_cols})
    return rows


def table_property_records(properties_df: pd.DataFrame) -> List[Dict[str, str]]:
    if properties_df is None or properties_df.empty:
        return []
    rows: List[Dict[str, str]] = []
    for _, row in properties_df.iterrows():
        key = normalize_str(row.get("key"))
        value = normalize_str(row.get("value"))
        if not key:
            continue
        rows.append({"key": key, "value": value or "—"})
    return rows


def infer_storage_format_from_properties(properties_df: pd.DataFrame) -> str:
    if properties_df is None or properties_df.empty:
        return ""
    keys = {
        normalize_str(row.get("key")).lower()
        for _, row in properties_df.iterrows()
        if normalize_str(row.get("key"))
    }
    if any(key.startswith("delta.") for key in keys):
        return "Delta"
    if any(key.startswith("iceberg.") for key in keys):
        return "Iceberg"
    return ""


def constraint_records(constraints_df: pd.DataFrame) -> List[Dict[str, Any]]:
    if constraints_df is None or constraints_df.empty:
        return []
    grouped: Dict[str, Dict[str, Any]] = {}
    for _, row in constraints_df.iterrows():
        name = normalize_str(row.get("constraint_name")) or "constraint"
        current = grouped.setdefault(
            name,
            {
                "name": name,
                "type": normalize_str(row.get("constraint_type")) or "Constraint",
                "columns": [],
                "matchOption": normalize_str(row.get("match_option")),
                "updateRule": normalize_str(row.get("update_rule")),
                "deleteRule": normalize_str(row.get("delete_rule")),
            },
        )
        column_name = normalize_str(row.get("column_name"))
        if column_name and column_name not in current["columns"]:
            current["columns"].append(column_name)
    return list(grouped.values())


def column_tag_lookup(column_tags_df: pd.DataFrame) -> Dict[str, List[Dict[str, str]]]:
    if column_tags_df is None or column_tags_df.empty:
        return {}
    lookup: Dict[str, List[Dict[str, str]]] = {}
    for _, row in column_tags_df.iterrows():
        column_name = normalize_str(row.get("column_name"))
        tag_name = normalize_str(row.get("tag_name"))
        tag_value = normalize_str(row.get("tag_value"))
        if not column_name or not tag_name:
            continue
        lookup.setdefault(column_name, []).append(
            {"name": tag_name, "value": tag_value}
        )
    return lookup


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
            "domain": normalize_str(row.get("domain")) or "Unassigned",
            "ownerEmail": normalize_str(row.get("owner_email")) or "Unassigned",
            "status": normalize_str(row.get("status")).title() or "Draft",
            "createdAt": normalize_str(row.get("created_at")),
            "createdBy": normalize_str(row.get("created_by")),
            "updatedAt": normalize_str(row.get("updated_at")),
            "updatedBy": normalize_str(row.get("updated_by")),
        }
    return lookup


def glossary_link_record(
    row: pd.Series,
    term_lookup: Dict[str, Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    term_id = normalize_str(row.get("term_id"))
    term = (term_lookup or {}).get(term_id.lower()) if term_id else None
    resolution_state = normalize_str(row.get("resolution_state")).lower() or "linked"
    return {
        "linkId": normalize_str(row.get("link_id")),
        "termId": term_id,
        "term": normalize_str(term.get("name")) if term else "",
        "definition": normalize_str(term.get("definition")) if term else "",
        "domain": normalize_str(term.get("domain")) if term else "",
        "ownerEmail": normalize_str(term.get("ownerEmail")) if term else "",
        "status": normalize_str(term.get("status")) if term else "",
        "subjectType": normalize_str(row.get("subject_type")).lower(),
        "subjectFqn": normalize_str(row.get("subject_fqn")),
        "columnName": normalize_str(row.get("column_name")),
        "isPrimary": bool(row.get("is_primary")),
        "source": normalize_str(row.get("source")).lower() or "manual",
        "sourceValue": normalize_str(row.get("source_value")),
        "resolutionState": resolution_state,
        "createdAt": normalize_str(row.get("created_at")),
        "createdBy": normalize_str(row.get("created_by")),
        "updatedAt": normalize_str(row.get("updated_at")),
        "updatedBy": normalize_str(row.get("updated_by")),
        "removedAt": normalize_str(row.get("removed_at")),
        "removedBy": normalize_str(row.get("removed_by")),
    }


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
        resolution_state = normalize_str(row.get("resolution_state")).lower()
        if resolution_state and resolution_state not in {"linked", "unresolved"}:
            continue
        subject_type = normalize_str(row.get("subject_type")).lower()
        subject_fqn = normalize_str(row.get("subject_fqn"))
        if not subject_type or not subject_fqn:
            continue
        column_name = normalize_str(row.get("column_name"))
        key = f"{subject_type}:{subject_fqn}:{column_name}"
        lookup.setdefault(key, []).append(glossary_link_record(row, term_lookup))
    for links in lookup.values():
        links.sort(
            key=lambda item: (
                0 if item.get("isPrimary") else 1,
                normalize_str(item.get("term")).lower(),
                normalize_str(item.get("termId")).lower(),
                normalize_str(item.get("createdAt")),
            )
        )
    return lookup


def _glossary_terms_for_subject(
    subject_type: str,
    subject_fqn: str,
    link_lookup: Dict[str, List[Dict[str, Any]]],
    *,
    column_name: str | None = None,
) -> List[Dict[str, Any]]:
    key = f"{normalize_str(subject_type).lower()}:{normalize_str(subject_fqn)}:{normalize_str(column_name)}"
    return list(link_lookup.get(key, []))


def _column_constraint_lookup(
    constraints_df: Optional[pd.DataFrame],
) -> Dict[str, List[Dict[str, str]]]:
    """Group constraint rows by column_name.

    Returns a {column_name: [{"name", "type"}]} lookup. Safe against missing/empty frames.
    Each constraint is deduplicated per column (name + type).
    """

    if constraints_df is None or constraints_df.empty:
        return {}
    lookup: Dict[str, List[Dict[str, str]]] = {}
    seen: Dict[str, set] = {}
    for _, row in constraints_df.iterrows():
        column_name = normalize_str(row.get("column_name"))
        if not column_name:
            continue
        constraint_name = normalize_str(row.get("constraint_name")) or "constraint"
        constraint_type = (
            normalize_str(row.get("constraint_type")) or "Constraint"
        )
        key = f"{constraint_type.upper()}::{constraint_name}"
        column_seen = seen.setdefault(column_name, set())
        if key in column_seen:
            continue
        column_seen.add(key)
        lookup.setdefault(column_name, []).append(
            {"name": constraint_name, "type": constraint_type}
        )
    return lookup


def _normalize_nullable_flag(value: Any) -> Optional[bool]:
    """Convert information_schema.is_nullable-style values into True, False, or None.

    Returns True / False for recognised affirmative / negative values, and None when
    the upstream metadata is missing or unrecognised so the UI can render a placeholder.
    """

    text = normalize_str(value).upper()
    if not text:
        return None
    if text in {"YES", "Y", "TRUE", "T", "1"}:
        return True
    if text in {"NO", "N", "FALSE", "F", "0"}:
        return False
    return None


def column_records(
    columns_df: pd.DataFrame,
    column_tags_df: Optional[pd.DataFrame] = None,
    column_links_df: Optional[pd.DataFrame] = None,
    term_lookup: Optional[Dict[str, Dict[str, Any]]] = None,
    subject_fqn: str = "",
    constraints_df: Optional[pd.DataFrame] = None,
) -> List[Dict[str, Any]]:
    if columns_df is None or columns_df.empty:
        return []
    tag_lookup = column_tag_lookup(column_tags_df)
    link_lookup = glossary_link_lookup(column_links_df, term_lookup)
    constraint_lookup = _column_constraint_lookup(constraints_df)
    rows: List[Dict[str, Any]] = []
    for _, row in columns_df.head(50).iterrows():
        column_name = normalize_str(row.get("column_name"))
        tags = tag_lookup.get(column_name, [])
        glossary_links = _glossary_terms_for_subject(
            "column",
            subject_fqn,
            link_lookup,
            column_name=column_name,
        )
        glossary_terms = [
            normalize_str(item.get("term"))
            for item in glossary_links
            if normalize_str(item.get("term"))
        ]
        glossary_term = (
            glossary_terms[0]
            if glossary_terms
            else next(
                (
                    normalize_str(item.get("value"))
                    for item in tags
                    if normalize_str(item.get("name")).lower() == "glossary_term"
                ),
                "",
            )
        )
        nullable_flag = _normalize_nullable_flag(row.get("is_nullable"))
        default_value = normalize_str(row.get("column_default"))
        column_constraints = list(constraint_lookup.get(column_name, []))
        rows.append(
            {
                "name": column_name,
                "type": normalize_str(row.get("data_type")),
                "description": normalize_str(row.get("comment")) or "No description",
                "tags": tags,
                "tagLabels": [
                    f"{normalize_str(item.get('name'))}: {normalize_str(item.get('value'))}"
                    if normalize_str(item.get("value"))
                    else normalize_str(item.get("name"))
                    for item in tags
                    if normalize_str(item.get("name"))
                ],
                "glossaryLinks": glossary_links,
                "glossaryTerms": glossary_terms,
                "glossaryTerm": glossary_term,
                "nullable": nullable_flag,
                "defaultValue": default_value,
                "constraints": column_constraints,
            }
        )
    return rows


def owner_assignment_records(store: Any, asset_fqn: str) -> List[Dict[str, str]]:
    if store is None or not hasattr(store, "get_owners"):
        return []
    try:
        owners_df = store.get_owners(asset_fqn)
    except Exception:
        return []
    if owners_df is None or owners_df.empty:
        return []
    rows: List[Dict[str, str]] = []
    for _, row in owners_df.iterrows():
        owner_email = normalize_str(row.get("owner_email"))
        owner_type = normalize_str(row.get("owner_type"))
        if not owner_email:
            continue
        rows.append(
            {
                "ownerEmail": owner_email,
                "ownerType": owner_type or "steward",
                "updatedAt": normalize_str(row.get("updated_at")),
                "updatedBy": normalize_str(row.get("updated_by")),
            }
        )
    return rows


def activity_records(
    store: Any, asset_fqn: str, limit: int = 20
) -> List[Dict[str, str]]:
    if store is None:
        return []
    if hasattr(store, "list_activity_events"):
        try:
            events_df = store.list_activity_events(entity_fqn=asset_fqn, limit=limit)
        except Exception:
            events_df = pd.DataFrame()
        if events_df is not None and not events_df.empty:
            rows: List[Dict[str, str]] = []
            for _, row in events_df.iterrows():
                payload = {}
                raw_payload = row.get("payload_json")
                if normalize_str(raw_payload):
                    try:
                        parsed = json.loads(str(raw_payload))
                        if isinstance(parsed, dict):
                            payload = parsed
                    except Exception:
                        payload = {}
                event_type = normalize_str(row.get("event_type")).lower()
                resolution_code = normalize_str(payload.get("resolutionCode")).lower()
                task_status = normalize_str(payload.get("status")).lower()
                status = "Pending"
                if resolution_code == "approved" or task_status in {
                    "resolved",
                    "closed",
                }:
                    status = "Approved"
                elif resolution_code == "rejected" or task_status == "rejected":
                    status = "Rejected"
                title = {
                    "comment_created": "Comment added",
                    "task_created": "Task created",
                    "task_state_changed": "Task updated",
                }.get(event_type)
                if not title:
                    # Humanize unknown event slugs server-side so the
                    # timeline never mixes "Task updated" with raw
                    # "task-triage-updated" strings (teardown P1-7).
                    words = [
                        word
                        for word in event_type.replace("_", "-").split("-")
                        if word.strip()
                    ]
                    title = (
                        " ".join(word.capitalize() for word in words)
                        if words
                        else "Governance activity"
                    )
                detail = (
                    normalize_str(payload.get("body"))
                    or normalize_str(payload.get("title"))
                    or normalize_str(payload.get("reviewNote"))
                    or normalize_str(payload.get("status"))
                    or title
                )
                actor = normalize_str(row.get("actor_email")) or normalize_str(
                    row.get("actor_display_name")
                )
                rows.append(
                    {
                        "id": normalize_str(row.get("event_id")),
                        "title": title,
                        "detail": detail,
                        "status": status,
                        "createdAt": normalize_str(row.get("created_at")),
                        # BOTH names on purpose (teardown P1-7): renderers
                        # read actorEmail while this row historically only
                        # carried createdBy, so the actor was fetched but
                        # never shown. Emit both so no field-name mismatch
                        # can drop the actor again.
                        "createdBy": actor,
                        "actorEmail": actor,
                        # Deep-link ids from the store row: the task/thread
                        # were persisted all along but dropped from the
                        # payload, forcing generic Stewardship navigation.
                        "taskId": normalize_str(row.get("task_id")),
                        "threadId": normalize_str(row.get("thread_id")),
                        # Priority from payload_json when the task carries
                        # one ("p1"); empty means the row truly has none.
                        "priority": normalize_str(payload.get("priority")),
                        "reviewNote": normalize_str(payload.get("reviewNote")),
                    }
                )
            return rows
    if not hasattr(store, "list_change_requests"):
        return []
    try:
        requests_df = store.list_change_requests(limit=200)
    except Exception:
        return []
    if requests_df is None or requests_df.empty:
        return []
    scoped = requests_df[
        requests_df["uc_full_name"].fillna("").astype(str).eq(asset_fqn)
    ].head(limit)
    rows: List[Dict[str, str]] = []
    for _, row in scoped.iterrows():
        note = normalize_str(row.get("review_note"))
        raw_title = normalize_str(row.get("new_comment")) or "Governance request"
        actor = normalize_str(row.get("created_by"))
        rows.append(
            {
                "id": normalize_str(row.get("request_id")),
                "title": raw_title.split(":")[0] if ":" in raw_title else raw_title,
                "detail": raw_title,
                "status": normalize_str(row.get("status")).title() or "Pending",
                "createdAt": normalize_str(row.get("created_at")),
                # Both actor field names, same reason as the events branch
                # above (teardown P1-7 field-name mismatch).
                "createdBy": actor,
                "actorEmail": actor,
                "reviewNote": note,
                "reviewedAt": normalize_str(row.get("reviewed_at")),
                "reviewedBy": normalize_str(row.get("reviewed_by")),
            }
        )
    return rows


def metadata_audit_records(
    store: Any, asset_fqn: str, limit: int = 20
) -> List[Dict[str, str]]:
    if store is None:
        return []
    try:
        if hasattr(store, "list_metadata_audit_log"):
            audit_df = store.list_metadata_audit_log(entity_fqn=asset_fqn, limit=limit)
        elif hasattr(store, "list_metadata_audit"):
            audit_df = store.list_metadata_audit(entity_fqn=asset_fqn, limit=limit)
        else:
            return []
    except Exception:
        return []
    if audit_df is None or audit_df.empty:
        return []
    # Lazy import: axiom_metrics imports this module at load time, so the
    # stable-AUD-id helper must be resolved at call time to avoid a cycle.
    from axiom.services.axiom_metrics import audit_display_id

    rows: List[Dict[str, str]] = []
    for _, row in audit_df.iterrows():
        rows.append(
            {
                "id": normalize_str(row.get("audit_id")),
                # Stable customer-facing AUD id (same derivation as Audit
                # Evidence) so asset-timeline rows join to /evidence events.
                "displayAuditId": audit_display_id(row.get("audit_id"), row=row),
                "action": normalize_str(row.get("action")) or "metadata change",
                "entityType": normalize_str(row.get("entity_type")),
                "entityId": normalize_str(row.get("entity_id")),
                "columnName": normalize_str(row.get("column_name")),
                "status": normalize_str(row.get("status")).title() or "Success",
                "detail": normalize_str(row.get("detail")),
                "actorEmail": normalize_str(row.get("actor_email")),
                "actorRole": normalize_str(row.get("actor_role")),
                "createdAt": normalize_str(row.get("created_at")),
                "createdBy": normalize_str(row.get("created_by")),
                "beforeJson": normalize_str(row.get("before_json")),
                "afterJson": normalize_str(row.get("after_json")),
                "requestId": normalize_str(row.get("request_id")),
                "source": normalize_str(row.get("source")) or "store",
            }
        )
    return rows


def _operational_entity_label(raw: Any) -> str:
    normalized = normalize_str(raw).upper().replace(" ", "_").replace("-", "_")
    mapping = {
        "JOB": "Job",
        "WORKFLOW": "Workflow",
        "PIPELINE": "Pipeline",
        "DLT_PIPELINE": "DLT Pipeline",
        "LAKEFLOW_PIPELINE": "Lakeflow Pipeline",
        "NOTEBOOK": "Notebook",
        "SQL": "SQL Query",
        "SQL_QUERY": "SQL Query",
        "DBSQL_QUERY": "DBSQL Query",
        "QUERY": "Query",
        "DASHBOARD": "Dashboard",
        "DBSQL_DASHBOARD": "DBSQL Dashboard",
    }
    return mapping.get(
        normalized, normalize_str(raw).replace("_", " ").title() or "Operational Entity"
    )


def _metadata_name_candidate(raw_metadata: Any) -> str:
    raw_text = normalize_str(raw_metadata)
    if not raw_text:
        return ""
    try:
        parsed = json.loads(raw_text)
    except Exception:
        return ""

    candidate_keys = [
        "display_name",
        "displayName",
        "name",
        "title",
        "job_name",
        "jobName",
        "pipeline_name",
        "pipelineName",
        "query_name",
        "queryName",
        "dashboard_name",
        "dashboardName",
        "dashboard_title",
        "dashboardTitle",
        "notebook_path",
        "notebookPath",
        "path",
    ]
    queue: List[Any] = [parsed]
    while queue:
        current = queue.pop(0)
        if isinstance(current, dict):
            for key in candidate_keys:
                candidate = normalize_str(current.get(key))
                if candidate:
                    if "/" in candidate:
                        return candidate.rstrip("/").split("/")[-1] or candidate
                    return candidate
            queue.extend(
                value for value in current.values() if isinstance(value, (dict, list))
            )
        elif isinstance(current, list):
            queue.extend(value for value in current if isinstance(value, (dict, list)))
    return ""


def operational_entity_records(
    uc,
    operational_df: pd.DataFrame,
) -> List[Dict[str, Any]]:
    if operational_df is None or operational_df.empty:
        return []
    grouped: Dict[str, Dict[str, Any]] = {}
    for _, row in operational_df.iterrows():
        entity_type = normalize_str(row.get("entity_type"))
        entity_id = normalize_str(row.get("entity_id"))
        statement_id = normalize_str(row.get("statement_id"))
        run_id = normalize_str(row.get("entity_run_id"))
        group_key = entity_type or entity_id or statement_id or str(len(grouped))
        key = f"{group_key}:{entity_id or statement_id or run_id or len(grouped)}"
        current = grouped.get(key)
        if current is None:
            resolved_name = (
                uc.resolve_operational_entity_name(entity_type, entity_id)
                if entity_type and entity_id
                else ""
            )
            entity_label = _operational_entity_label(entity_type)
            fallback_identifier = entity_id or statement_id or run_id
            fallback_name = (
                resolved_name
                or normalize_str(row.get("entity_name"))
                or _metadata_name_candidate(row.get("entity_metadata"))
            )
            if not fallback_name and fallback_identifier:
                fallback_name = f"{entity_label} {fallback_identifier[:8]}".strip()
            current = {
                "key": key,
                "entityType": entity_type,
                "entityLabel": entity_label,
                "entityId": entity_id,
                "statementId": statement_id,
                "runId": run_id,
                "name": fallback_name or entity_label or "Unknown entity",
                "metadata": normalize_str(row.get("entity_metadata")),
                "relatedAssets": [],
            }
            grouped[key] = current
        related_asset = normalize_str(row.get("related_table_full_name"))
        if related_asset and related_asset not in current["relatedAssets"]:
            current["relatedAssets"].append(related_asset)
    return sorted(
        grouped.values(),
        key=lambda item: (
            item["entityLabel"],
            item["name"].lower(),
            item["statementId"],
        ),
    )


def query_records(
    operational_entities: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    query_types = {"SQL", "SQL_QUERY", "DBSQL_QUERY", "QUERY"}
    return [
        entity
        for entity in operational_entities
        if normalize_str(entity.get("entityType")).upper() in query_types
    ]


def profiler_payload(
    asset: Dict[str, Any],
    columns: Sequence[Dict[str, Any]],
    preview: Sequence[Dict[str, Any]],
    related_assets: Sequence[str],
    activity: Sequence[Dict[str, str]],
    operational_context: Dict[str, Sequence[Dict[str, Any]]],
    *,
    include_preview: bool = True,
    include_operational: bool = True,
) -> Dict[str, Any]:
    column_count = len(columns)
    described_count = sum(
        1
        for column in columns
        if normalize_str(column.get("description")) not in {"", "No description"}
    )
    classified_count = sum(1 for column in columns if column.get("tags"))
    glossary_count = sum(
        1
        for column in columns
        if normalize_str(column.get("glossaryTerm"))
        or any(normalize_str(term) for term in column.get("glossaryTerms", []))
    )
    producer_count = len(operational_context.get("producers", []))
    consumer_count = len(operational_context.get("consumers", []))

    def status_for(count: int, total: int) -> str:
        if total <= 0:
            return "missing"
        if count == total:
            return "good"
        if count > 0:
            return "warn"
        return "bad"

    cards = [
        {
            "title": "Description Coverage",
            "value": f"{described_count}/{column_count}"
            if column_count
            else "No schema",
            "status": status_for(described_count, column_count),
            "note": "Columns with captured descriptions.",
        },
        {
            "title": "Classification Coverage",
            "value": f"{classified_count}/{column_count}"
            if column_count
            else "No schema",
            "status": status_for(classified_count, column_count),
            "note": "Columns with at least one governance tag.",
        },
        {
            "title": "Glossary Coverage",
            "value": f"{glossary_count}/{column_count}"
            if column_count
            else "No schema",
            "status": status_for(glossary_count, column_count),
            "note": "Columns linked to glossary terms.",
        },
    ]
    if include_preview:
        cards.append(
            {
                "title": "Sample Data",
                "value": "Available" if preview else "Missing",
                "status": "good" if preview else "warn",
                "note": "Sample rows surfaced from the live asset.",
            }
        )
    cards.append(
        {
            "title": "Lineage Context",
            "value": f"{len(related_assets)} assets",
            "status": "good" if related_assets else "warn",
            "note": "Connected assets surfaced in lineage.",
        }
    )
    if include_operational:
        cards.append(
            {
                "title": "Operational Usage",
                "value": f"{producer_count + consumer_count} workloads",
                "status": "good" if producer_count or consumer_count else "warn",
                "note": "Jobs, queries, pipelines, and dashboards linked through UC lineage.",
            }
        )
    cards.append(
        {
            "title": "Open Work",
            "value": str(len(activity)),
            "status": "warn" if activity else "good",
            "note": "Governance tasks or requests currently tied to this asset.",
        }
    )

    return {
        "cards": cards,
        "summary": {
            "columnCount": column_count,
            "describedColumns": described_count,
            "classifiedColumns": classified_count,
            "glossaryLinkedColumns": glossary_count,
            "hasSampleData": bool(preview),
            "openActivityCount": len(activity),
            "producerCount": producer_count,
            "consumerCount": consumer_count,
            "governanceStatus": normalize_str(asset.get("governanceStatus"))
            or "Needs Work",
        },
    }


def asset_detail_payload(
    uc,
    inventory_or_store,
    asset_fqn: str,
    *,
    cache_scope: str = "",
    hidden_catalogs: Sequence[str] = HIDDEN_CATALOGS,
    sections: Optional[Sequence[str]] = None,
    allow_direct_metadata_write: bool = True,
    force_rebuild: bool = False,
) -> Dict[str, Any]:
    normalized_scope = normalize_str(cache_scope) or "shared"
    requested_sections = normalize_asset_detail_sections(sections)
    section_key = ",".join(requested_sections)
    cache_key = f"asset_detail:{_warehouse_key(uc)}:{normalized_scope}:{normalize_str(asset_fqn)}:{section_key}"

    if not force_rebuild:
        cached_payload = cached_asset_detail_payload(
            uc,
            asset_fqn,
            cache_scope=normalized_scope,
            sections=requested_sections,
        )
        if cached_payload is not None:
            return cached_payload

    def load() -> Dict[str, Any]:
        store = (
            None if isinstance(inventory_or_store, pd.DataFrame) else inventory_or_store
        )
        inventory = _resolve_inventory_df(
            inventory_or_store if isinstance(inventory_or_store, pd.DataFrame) else uc,
            store,
            hidden_catalogs=hidden_catalogs,
        )
        if isinstance(inventory_or_store, pd.DataFrame):
            row = inventory_row(inventory, asset_fqn)
            inventory_columns = (
                list(inventory.columns) if isinstance(inventory, pd.DataFrame) else None
            )
        else:
            row = inventory_row(
                uc, inventory_or_store, asset_fqn, hidden_catalogs=hidden_catalogs
            )
            inventory_columns = (
                list(inventory.columns) if isinstance(inventory, pd.DataFrame) else None
            )
            row = merge_identity_row(
                row,
                exact_identity_row(
                    uc,
                    asset_fqn,
                    inventory_columns,
                ),
            )
        base = base_asset_payload(row)
        catalog, schema, table = split_uc_name(base["fqn"])
        detail_df = pd.DataFrame()
        detail = {}
        columns_df = pd.DataFrame()
        sample_df = pd.DataFrame()
        properties_df = pd.DataFrame()
        constraints_df = pd.DataFrame()
        column_tags_df = pd.DataFrame()
        glossary_terms_df = pd.DataFrame()
        glossary_links_df = pd.DataFrame()
        operational_upstream_df = pd.DataFrame()
        operational_downstream_df = pd.DataFrame()
        loaded_sections = set(requested_sections)

        base["columnCount"] = 0
        base["ownerAssignments"] = []
        base["activity"] = []
        base["metadataAudit"] = []
        base["tableProperties"] = []
        base["constraints"] = []
        base["customProperties"] = []
        base["operationalContext"] = {"producers": [], "consumers": []}
        base["queries"] = []
        base["usage"] = {"queryCount": 0, "producerCount": 0, "consumerCount": 0}
        base["profiler"] = {"cards": [], "summary": {}}

        try:
            glossary_terms_df = (
                store.list_glossary_terms(limit=500)
                if store is not None
                else pd.DataFrame()
            )
        except Exception:
            glossary_terms_df = pd.DataFrame()
        try:
            glossary_links_df = (
                store.list_glossary_term_links()
                if store is not None and hasattr(store, "list_glossary_term_links")
                else pd.DataFrame()
            )
        except Exception:
            glossary_links_df = pd.DataFrame()
        glossary_term_index = glossary_term_lookup(glossary_terms_df)
        glossary_link_index = glossary_link_lookup(
            glossary_links_df, glossary_term_index
        )
        asset_glossary_links = _glossary_terms_for_subject(
            "asset", base["fqn"], glossary_link_index
        )
        fallback_glossary_term = normalize_str(base.get("glossaryTerm"))
        if not asset_glossary_links and fallback_glossary_term:
            fallback_term = next(
                (
                    term
                    for term in glossary_term_index.values()
                    if normalize_str(term.get("name")).lower()
                    == fallback_glossary_term.lower()
                ),
                None,
            )
            asset_glossary_links = [
                {
                    "linkId": "",
                    "termId": normalize_str(fallback_term.get("termId"))
                    if fallback_term
                    else "",
                    "term": normalize_str(fallback_term.get("name"))
                    if fallback_term
                    else fallback_glossary_term,
                    "definition": normalize_str(fallback_term.get("definition"))
                    if fallback_term
                    else "",
                    "domain": normalize_str(fallback_term.get("domain"))
                    if fallback_term
                    else "",
                    "ownerEmail": normalize_str(fallback_term.get("ownerEmail"))
                    if fallback_term
                    else "",
                    "status": normalize_str(fallback_term.get("status"))
                    if fallback_term
                    else "",
                    "subjectType": "asset",
                    "subjectFqn": base["fqn"],
                    "columnName": "",
                    "isPrimary": True,
                    "source": "uc_tag",
                    "sourceValue": fallback_glossary_term,
                    "resolutionState": "linked",
                    "createdAt": "",
                    "createdBy": "",
                    "updatedAt": "",
                    "updatedBy": "",
                    "removedAt": "",
                    "removedBy": "",
                }
            ]
        base["glossaryLinks"] = asset_glossary_links
        base["glossaryTerms"] = [
            normalize_str(link.get("term"))
            for link in asset_glossary_links
            if normalize_str(link.get("term"))
        ]
        if base["glossaryTerms"]:
            base["glossaryTerm"] = base["glossaryTerms"][0]

        if "header" in loaded_sections:
            # Warm the four independent header round trips concurrently
            # (DESCRIBE DETAIL, DESCRIBE HISTORY, information_schema.tables,
            # table comment) so the sequential reads below all hit the TTL
            # cache. Serializing these was the dominant cold-header cost
            # (~5-7s wall-clock for four mutually-independent ~1.2s queries).
            metadata_service.prefetch_asset_header(uc, catalog, schema, table)
            try:
                detail_df = cached_table_detail(uc, catalog, schema, table)
            except Exception:
                detail_df = pd.DataFrame()
            if detail_df.empty:
                try:
                    detail_df = uc.get_table_detail(catalog, schema, table)
                except Exception:
                    detail_df = pd.DataFrame()
            detail = detail_map(detail_df)

            # base_asset_payload now emits the real (possibly empty)
            # description. When it's empty, try the live comment sources;
            # if nothing is captured we keep it empty — the CLIENT renders
            # the "No description..." placeholder, never the API.
            if not normalize_str(base["description"]):
                try:
                    base["description"] = cached_comment(uc, catalog, schema, table)
                except Exception:
                    base["description"] = ""
                if not normalize_str(base["description"]):
                    try:
                        base["description"] = uc.get_table_comment(
                            catalog, schema, table
                        )
                    except Exception:
                        base["description"] = ""
                if not normalize_str(base["description"]):
                    base["description"] = ""

            try:
                row_count = coalesce(
                    detail.get("numrows"),
                    cached_table_row_count(uc, catalog, schema, table),
                )
            except Exception:
                row_count = coalesce(detail.get("numrows"))
            base["rows"] = f"{safe_int(row_count):,}" if safe_int(row_count) else "—"
            raw_detail_type = _prefer_specific_table_type(
                detail.get("type"),
                base.get("tableTypeRaw"),
            )
            raw_detail_format = coalesce(
                detail.get("format"), base.get("storageFormat")
            )
            base["tableTypeRaw"] = raw_detail_type or base.get("tableTypeRaw", "")
            base["objectType"] = coalesce(
                friendly_table_type(raw_detail_type, raw_detail_format),
                base["objectType"],
            )
            base["managementType"] = management_type(base.get("tableTypeRaw"))
            base["storageFormat"] = coalesce(
                friendly_storage_format(raw_detail_format),
                base.get("storageFormat"),
            )
            if base["storageFormat"] == "—":
                try:
                    properties_for_identity_df = uc.get_table_properties(
                        catalog, schema, table
                    )
                except Exception:
                    properties_for_identity_df = pd.DataFrame()
                inferred_storage_format = infer_storage_format_from_properties(
                    properties_for_identity_df
                )
                if inferred_storage_format:
                    base["storageFormat"] = inferred_storage_format
            base["format"] = base["storageFormat"] or "—"
            base["size"] = human_bytes(detail.get("sizeinbytes"))
            base["files"] = (
                str(safe_int(detail.get("numfiles")))
                if safe_int(detail.get("numfiles"))
                else "—"
            )
            # ----------------------------------------------------------
            # Last-updated freshness: scan Delta history for the most
            # recent DATA-CHANGING op (matching UC's "Last updated" card
            # behavior). For non-Delta tables fall back to
            # information_schema.last_altered. Stored as ISO 8601 string
            # at base["updatedAt"] so the frontend can render relative
            # time consistently.
            # ----------------------------------------------------------
            base["updatedAt"] = ""
            try:
                history_df = cached_table_history(uc, catalog, schema, table)
            except Exception:
                history_df = pd.DataFrame()
            if not history_df.empty and "operation" in history_df.columns:
                # UC convention: write/update/delete/merge/streaming-update
                # ops mutate data; optimize/vacuum/upgrade-schema do not.
                _DATA_OPS = {
                    "WRITE",
                    "STREAMING UPDATE",
                    "MERGE",
                    "UPDATE",
                    "DELETE",
                    "REPLACE TABLE AS SELECT",
                    "CREATE TABLE",
                    "CREATE TABLE AS SELECT",
                    "CREATE OR REPLACE TABLE AS SELECT",
                    "RESTORE",
                    "TRUNCATE",
                }
                ops_upper = history_df["operation"].astype(str).str.upper()
                data_rows = history_df[ops_upper.isin(_DATA_OPS)]
                if not data_rows.empty and "timestamp" in data_rows.columns:
                    try:
                        ts_series = pd.to_datetime(
                            data_rows["timestamp"], utc=True, errors="coerce"
                        ).dropna()
                        if not ts_series.empty:
                            base["updatedAt"] = (
                                ts_series.max().isoformat().replace("+00:00", "Z")
                            )
                            # Freshness split (cohesion law 4): a data-op
                            # timestamp from Delta history IS a data write,
                            # so it also populates the unambiguous field.
                            base["dataUpdatedAt"] = base["updatedAt"]
                    except Exception:
                        pass
            if not base.get("dataUpdatedAt"):
                # DESCRIBE DETAIL's lastModified is the last write to the
                # table files — a data signal, already warm in the detail
                # cache. Used only for the split field; the legacy updatedAt
                # fallback chain below is left untouched.
                try:
                    last_modified = pd.to_datetime(
                        detail.get("lastmodified"), utc=True, errors="coerce"
                    )
                    if last_modified is not None and pd.notna(last_modified):
                        base["dataUpdatedAt"] = (
                            last_modified.isoformat().replace("+00:00", "Z")
                        )
                except Exception:
                    pass
            # ----------------------------------------------------------
            # UC information_schema.tables — authoritative `created_by`,
            # `table_owner`, `last_altered`. Used as a fallback for owner
            # when the local governance store has nothing assigned, and
            # as a fallback for updatedAt for non-Delta tables.
            # ----------------------------------------------------------
            try:
                ist_df = cached_information_schema_table_metadata(
                    uc, catalog, schema, table
                )
            except Exception:
                ist_df = pd.DataFrame()
            if not ist_df.empty:
                row0 = ist_df.iloc[0].to_dict()
                # Freshness split (cohesion law 4): last_altered is ALWAYS
                # emitted under its honest name — it is a metadata-change
                # time from information_schema, regardless of whether the
                # legacy conflated updatedAt fell back to it below.
                altered = row0.get("last_altered")
                if altered:
                    try:
                        altered_ts = pd.to_datetime(
                            altered, utc=True, errors="coerce"
                        )
                        if pd.notna(altered_ts):
                            base["lastAltered"] = (
                                altered_ts.isoformat().replace("+00:00", "Z")
                            )
                            # Legacy conflated fallback, unchanged behavior:
                            # only when Delta history yielded no data write.
                            if not base["updatedAt"]:
                                base["updatedAt"] = base["lastAltered"]
                    except Exception:
                        pass
                # UC table_owner is the SOURCE OF TRUTH for who owns
                # the asset — it's enforced by Databricks itself. Local
                # governance-store owner assignments are SUPPLEMENTARY
                # (typically business stewards layered on top of the
                # technical UC owner). When both exist, the UC owner
                # leads and local stewards follow as additional entries.
                # This avoids the case the user reported where a stale
                # / fake seed assignment in the local store
                # (e.g. "finance-steward@shorecp.com") was masking the
                # real UC owner ("abarreto@shorecp.com") on the asset
                # card and lineage rail.
                uc_owner_principal = (
                    normalize_str(row0.get("table_owner"))
                    or normalize_str(row0.get("created_by"))
                )
                if uc_owner_principal:
                    is_email = "@" in uc_owner_principal
                    uc_owner_entry = {
                        "name": uc_owner_principal,
                        "displayName": uc_owner_principal,
                        "email": uc_owner_principal if is_email else "",
                        "title": "Unity Catalog owner",
                        "source": "uc.information_schema",
                    }
                    existing_owners = base.get("owners") or []
                    # De-dupe: if local store happens to reference the
                    # same UC owner principal, drop the duplicate so
                    # the user doesn't see them twice. Match on email
                    # then name (case-insensitive).
                    uc_principal_lc = uc_owner_principal.lower()
                    deduped = [
                        owner
                        for owner in existing_owners
                        if normalize_str(owner.get("email")).lower() != uc_principal_lc
                        and normalize_str(owner.get("name")).lower() != uc_principal_lc
                    ]
                    base["owners"] = [uc_owner_entry] + deduped
            metadata_write_supported = supports_direct_metadata_write(
                base.get("tableTypeRaw")
            ) and bool(allow_direct_metadata_write)
            base["metadataEditor"] = {
                "available": metadata_write_supported,
                "updatePath": "/api/assets/:fqn/metadata",
                "updateMethod": "PATCH",
                "message": (
                    ""
                    if metadata_write_supported
                    else "Direct metadata edits are unavailable for this relation type or until Databricks per-user authorization / OBO is implemented for the current actor."
                ),
                "fields": [
                    {
                        "key": "description",
                        "label": "Description",
                        "type": "textarea",
                        "placeholder": "Add a description for this asset",
                    },
                    {"key": "domain", "label": "Domain", "type": "text"},
                    {"key": "tier", "label": "Tier", "type": "text"},
                    {"key": "certification", "label": "Certification", "type": "text"},
                    {"key": "sensitivity", "label": "Sensitivity", "type": "text"},
                    {"key": "criticality", "label": "Criticality", "type": "text"},
                    {"key": "dataProduct", "label": "Data Product", "type": "text"},
                    {
                        "key": "freeformTags",
                        "label": "Freeform Tags",
                        "type": "text",
                        "placeholder": "owner_team=FinOps, product_area=ERP",
                        "helpText": "Comma-separated key=value pairs for non-structured Unity Catalog tags.",
                    },
                ],
            }

        if "activity" in loaded_sections:
            base["ownerAssignments"] = owner_assignment_records(store, base["fqn"])
            base["activity"] = activity_records(store, base["fqn"])
            base["metadataAudit"] = metadata_audit_records(store, base["fqn"])

        if "schema" in loaded_sections:
            # The schema tab needs three independent reads: column list,
            # column tags, and constraints. Fire them concurrently so a cold
            # schema tab pays one round trip of latency, not three serialized.
            # column_tags is NOT cache-backed, so we capture the gather result
            # directly rather than prefetch-then-reread (which would double the
            # query). columns / constraints self-cache, so we re-read those
            # from cache below for the empty-fallback logic.
            _schema_results = metadata_service.gather_parallel(
                (
                    lambda: cached_columns(uc, catalog, schema, table),
                    lambda: uc.get_table_column_tags(catalog, schema, table),
                    lambda: cached_table_constraints(uc, catalog, schema, table),
                ),
                max_workers=3,
            )
            columns_df = _schema_results[0]
            column_tags_df = _schema_results[1]
            schema_constraints_df = _schema_results[2]
            if not isinstance(columns_df, pd.DataFrame) or columns_df.empty:
                try:
                    columns_df = uc.get_table_columns(catalog, schema, table)
                except Exception:
                    columns_df = pd.DataFrame()
            if not isinstance(column_tags_df, pd.DataFrame):
                column_tags_df = pd.DataFrame()
            # Constraints live under the "properties" section in the public payload,
            # but the schema tab needs per-column PK/FK/NOT NULL chips, so surface
            # them here too via column_records.
            if not isinstance(schema_constraints_df, pd.DataFrame):
                schema_constraints_df = pd.DataFrame()
            column_links_df = pd.DataFrame()
            if not glossary_links_df.empty:
                column_links_df = glossary_links_df[
                    glossary_links_df["subject_type"]
                    .fillna("")
                    .astype(str)
                    .str.lower()
                    .eq("column")
                    & glossary_links_df["subject_fqn"]
                    .fillna("")
                    .astype(str)
                    .eq(base["fqn"])
                ].copy()
            base["columns"] = column_records(
                columns_df,
                column_tags_df,
                column_links_df=column_links_df,
                term_lookup=glossary_term_index,
                subject_fqn=base["fqn"],
                constraints_df=schema_constraints_df,
            )
            base["columnCount"] = len(base["columns"])

        if "preview" in loaded_sections:
            try:
                sample_df = cached_sample_rows(uc, catalog, schema, table)
            except Exception:
                sample_df = pd.DataFrame()
            if sample_df.empty:
                try:
                    sample_df = uc.get_table_sample(catalog, schema, table, limit=15)
                except Exception:
                    sample_df = pd.DataFrame()
            base["preview"] = preview_records(sample_df)

        if "properties" in loaded_sections:
            # Two independent reads — run concurrently.
            _prop_results = metadata_service.gather_parallel(
                (
                    lambda: uc.get_table_properties(catalog, schema, table),
                    lambda: uc.get_table_constraints(catalog, schema, table),
                ),
                max_workers=2,
            )
            properties_df = _prop_results[0]
            constraints_df = _prop_results[1]
            if not isinstance(properties_df, pd.DataFrame):
                properties_df = pd.DataFrame()
            if not isinstance(constraints_df, pd.DataFrame):
                constraints_df = pd.DataFrame()
            base["tableProperties"] = table_property_records(properties_df)
            base["constraints"] = constraint_records(constraints_df)
            base["customProperties"] = list(base["tableProperties"])

        if "operational" in loaded_sections:
            # Upstream / downstream operational-context reads are independent —
            # run concurrently.
            _op_results = metadata_service.gather_parallel(
                (
                    lambda: uc.get_operational_context_upstream(catalog, schema, table),
                    lambda: uc.get_operational_context_downstream(catalog, schema, table),
                ),
                max_workers=2,
            )
            operational_upstream_df = _op_results[0]
            operational_downstream_df = _op_results[1]
            if not isinstance(operational_upstream_df, pd.DataFrame):
                operational_upstream_df = pd.DataFrame()
            if not isinstance(operational_downstream_df, pd.DataFrame):
                operational_downstream_df = pd.DataFrame()
            base["relatedAssets"] = related_assets(
                uc,
                catalog,
                schema,
                table,
                base["fqn"],
                inventory_df=inventory,
            )
            base["operationalContext"] = {
                "producers": operational_entity_records(uc, operational_upstream_df),
                "consumers": operational_entity_records(uc, operational_downstream_df),
            }
            base["queries"] = query_records(
                [
                    *base["operationalContext"]["producers"],
                    *base["operationalContext"]["consumers"],
                ]
            )
            base["usage"] = {
                "queryCount": len(base["queries"]),
                "producerCount": len(base["operationalContext"]["producers"]),
                "consumerCount": len(base["operationalContext"]["consumers"]),
            }

        if "profiler" in loaded_sections:
            base["profiler"] = profiler_payload(
                base,
                base["columns"],
                base["preview"],
                base["relatedAssets"],
                base["activity"],
                base["operationalContext"],
                include_preview="preview" in loaded_sections,
                include_operational="operational" in loaded_sections,
            )

        base["loadedSections"] = list(requested_sections)
        base["deferredSections"] = [
            section
            for section in ASSET_DETAIL_SECTIONS
            if section not in loaded_sections
        ]
        # Envelope honesty: stamp the wall-clock instant this metadata was
        # observed from Unity Catalog. The freshness fields (updatedAt /
        # dataUpdatedAt / lastAltered) are real source timestamps; this is the
        # OBSERVATION time. It lets the cache live longer than the old 300s
        # (see ASSET_DETAIL_FRESH_TTL_S) without lying — the UI can render "as
        # of N min ago" and revalidate, rather than blocking cold every 5 min.
        observed_at = _now_iso()
        base["metadataObservedAt"] = observed_at
        base["metadataStaleAfter"] = _iso_after(ASSET_DETAIL_FRESH_TTL_S)
        # Identity-integrity honesty: badge every owner/steward block with
        # whether the principal is a real workspace member. Roster is cached,
        # so this is a set lookup, not a per-asset SCIM round-trip.
        annotate_account_member(uc, base.get("owners") or [])
        annotate_account_member(uc, base.get("ownerAssignments") or [])
        return base

    # Stale-while-revalidate: when a still-usable (live-signal) payload is
    # cached but past its fresh window, serve it immediately and rebuild in
    # the background instead of blocking the request on a cold load. This is
    # what keeps a return-visit warm (<0.7s) even after the fresh TTL lapses.
    stale = None if force_rebuild else _TTL_CACHE.get(cache_key)
    if stale is not None:
        age = time.time() - stale[0]
        stale_payload = stale[1]
        if (
            ASSET_DETAIL_FRESH_TTL_S <= age < ASSET_DETAIL_STALE_TTL_S
            and asset_payload_has_live_signals(stale_payload)
        ):
            _revalidate_asset_detail_async(
                uc,
                inventory_or_store,
                asset_fqn,
                cache_scope=normalized_scope,
                hidden_catalogs=hidden_catalogs,
                sections=requested_sections,
                allow_direct_metadata_write=allow_direct_metadata_write,
                cache_key=cache_key,
            )
            return stale_payload

    payload = load()
    _TTL_CACHE[cache_key] = (time.time(), payload)
    return payload


# Asset-detail cache windows. Freshness fields inside the payload are real
# source timestamps; the cache carries `metadataObservedAt` so a longer TTL
# stays honest (the UI shows observed-age + revalidates). Live-signal payloads
# serve fresh for 15 min, then stale-while-revalidate for up to 1 hr; empty /
# no-signal payloads keep the old short 20s window so a transient cold-start
# self-heals fast.
ASSET_DETAIL_FRESH_TTL_S = 900
ASSET_DETAIL_STALE_TTL_S = 3600
ASSET_DETAIL_EMPTY_TTL_S = 20

_ASSET_DETAIL_REVALIDATING: set[str] = set()
_ASSET_DETAIL_REVALIDATING_GUARD = threading.Lock()


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _iso_after(seconds: int) -> str:
    from datetime import datetime, timedelta, timezone

    return (
        (datetime.now(timezone.utc) + timedelta(seconds=seconds))
        .isoformat()
        .replace("+00:00", "Z")
    )


def _revalidate_asset_detail_async(
    uc,
    inventory_or_store,
    asset_fqn: str,
    *,
    cache_scope: str,
    hidden_catalogs: Sequence[str],
    sections: Sequence[str],
    allow_direct_metadata_write: bool,
    cache_key: str,
) -> None:
    """Rebuild an asset-detail payload off-request (stale-while-revalidate).

    Guarded so a burst of stale re-hits triggers ONE rebuild, not N
    (thundering-herd guard). The rebuild pops nothing until it has a fresh
    payload, so readers keep seeing the stale (but honest, observedAt-stamped)
    body until the swap.
    """
    import threading

    with _ASSET_DETAIL_REVALIDATING_GUARD:
        if cache_key in _ASSET_DETAIL_REVALIDATING:
            return
        _ASSET_DETAIL_REVALIDATING.add(cache_key)

    def _run() -> None:
        try:
            fresh = asset_detail_payload(
                uc,
                inventory_or_store,
                asset_fqn,
                cache_scope=cache_scope,
                hidden_catalogs=hidden_catalogs,
                sections=sections,
                allow_direct_metadata_write=allow_direct_metadata_write,
                force_rebuild=True,
            )
            _TTL_CACHE[cache_key] = (time.time(), fresh)
        except Exception:
            pass
        finally:
            with _ASSET_DETAIL_REVALIDATING_GUARD:
                _ASSET_DETAIL_REVALIDATING.discard(cache_key)

    threading.Thread(
        target=_run,
        name=f"axiom-asset-detail-revalidate-{asset_fqn}",
        daemon=True,
    ).start()


def cached_asset_detail_payload(
    uc,
    asset_fqn: str,
    *,
    cache_scope: str = "",
    sections: Optional[Sequence[str]] = None,
) -> Optional[Dict[str, Any]]:
    normalized_scope = normalize_str(cache_scope) or "shared"
    requested_sections = normalize_asset_detail_sections(sections)
    section_key = ",".join(requested_sections)
    cache_key = f"asset_detail:{_warehouse_key(uc)}:{normalized_scope}:{normalize_str(asset_fqn)}:{section_key}"
    cached = _TTL_CACHE.get(cache_key)
    if not cached:
        return None
    age = time.time() - cached[0]
    payload = cached[1]
    # Live-signal payloads carry metadataObservedAt, so a 15-min fresh window
    # stays honest (was 300s). Empty payloads keep the short self-healing TTL.
    ttl_s = (
        ASSET_DETAIL_FRESH_TTL_S
        if asset_payload_has_live_signals(payload)
        else ASSET_DETAIL_EMPTY_TTL_S
    )
    if age < ttl_s:
        return payload
    return None


def asset_payload_has_live_signals(payload: Dict[str, Any]) -> bool:
    if not payload:
        return False
    description = normalize_str(payload.get("description"))
    if description and description not in {"—", PLACEHOLDER_DESCRIPTION}:
        return True
    if payload.get("rows") not in {"", None, "—"}:
        return True
    if payload.get("size") not in {"", None, "—"}:
        return True
    if payload.get("files") not in {"", None, "—"}:
        return True
    if payload.get("columns") or payload.get("preview"):
        return True
    return False


def asset_payload_has_structured_detail(payload: Dict[str, Any]) -> bool:
    if not payload:
        return False
    return bool(payload.get("columns") or payload.get("preview"))
