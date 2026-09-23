from __future__ import annotations

import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Deque, Dict, List, Optional, Sequence, Set, Tuple

import pandas as pd

from atlas.util import lineage_window_predicate

from atlas.uc import UCSQLClient, sql_literal

from atlas.services import assets as asset_service
from atlas.services import live_metadata as metadata_service


_TTL_CACHE: Dict[str, Tuple[float, Any]] = {}
# Per-key locks serialize concurrent loaders so a burst of 8 parallel
# requests for the same lineage asset turns into one SQL round-trip, not
# eight. The outer dict is guarded by _TTL_CACHE_LOCKS_GUARD so lock
# creation is itself thread-safe.
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
TABLE_LINEAGE_LIMIT = 40
COLUMN_LINEAGE_LIMIT = 250
OPERATIONAL_CONTEXT_LIMIT = 80
SECOND_HOP_SEED_LIMIT = 6
SECOND_HOP_NEIGHBOR_LIMIT = 25
SECOND_HOP_SAMPLE_LIMIT = 8
# Keep both profiles bounded enough for first-use interaction. The full profile
# hydrates real one-hop topology, operational context, and column lineage; deeper
# expansion must stay explicit so one page open cannot turn into many slow
# system-table scans.
LINEAGE_GRAPH_DEPTH_LIMIT = 1
LINEAGE_GRAPH_NODE_LIMIT = 48
LINEAGE_GRAPH_PER_HOP_LIMIT = 16
LINEAGE_GRAPH_SECONDARY_SEED_LIMIT = 0
LINEAGE_RECOMMENDATION_VISIBLE_ASSET_LIMIT = 600
LINEAGE_RECOMMENDATION_CANDIDATE_LIMIT = 600
LINEAGE_RECOMMENDATION_BATCH_SIZE = 60
LINEAGE_RECOMMENDATION_PER_SEED_LIMIT = 40
LINEAGE_PROFILE_FULL = "full"
LINEAGE_PROFILE_INITIAL = "initial"
GOVERNED_LINEAGE_FOCUS_TAG = "governance_atlas_lineage_focus_asset"
GOVERNED_LINEAGE_PROVENANCE = "system.information_schema.table_tags"
GOVERNED_OPERATIONAL_CONSUMER_JOB_ID_TAG = "governance_atlas_operational_consumer_job_id"
GOVERNED_OPERATIONAL_CONSUMER_JOB_NAME_TAG = "governance_atlas_operational_consumer_job_name"
GOVERNED_OPERATIONAL_PRODUCER_JOB_ID_TAG = "governance_atlas_operational_producer_job_id"
GOVERNED_OPERATIONAL_PRODUCER_JOB_NAME_TAG = "governance_atlas_operational_producer_job_name"


def _lineage_profile(value: str = "") -> str:
    normalized = asset_service.normalize_str(value).lower()
    if normalized in {"initial", "fast", "first-pass", "first_pass"}:
        return LINEAGE_PROFILE_INITIAL
    return LINEAGE_PROFILE_FULL


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


def _warehouse_key(uc: UCSQLClient) -> str:
    return asset_service.normalize_str(getattr(uc, "warehouse_id", "")) or "default"


def _cache_scope_key(cache_scope: str = "") -> str:
    return asset_service.normalize_str(cache_scope) or "shared"


def invalidate_lineage_caches(asset_fqn: str | None = None) -> None:
    if asset_fqn is None:
        _TTL_CACHE.clear()
        return
    suffix = f":{asset_service.normalize_str(asset_fqn)}"
    for key in list(_TTL_CACHE):
        if key.endswith(suffix) and key.startswith("lineage:"):
            _TTL_CACHE.pop(key, None)


FOCUS_COLUMN_PREVIEW_LIMIT = 20


def _exact_lineage_row(
    uc: UCSQLClient,
    asset_fqn: str,
    *,
    inventory_columns: Optional[Sequence[str]] = None,
) -> Optional[pd.Series]:
    try:
        if asset_service.asset_fqn_is_hidden(asset_fqn):
            return None
        return asset_service.exact_identity_row(
            uc,
            asset_fqn,
            inventory_columns=inventory_columns,
        )
    except Exception:
        return None


def _focus_lineage_inventory(
    uc: UCSQLClient,
    asset_fqn: str,
) -> tuple[pd.Series, pd.DataFrame, Set[str]]:
    normalized_fqn = asset_service.normalize_str(asset_fqn)
    exact_row = _exact_lineage_row(uc, normalized_fqn)
    if exact_row is not None:
        row = exact_row
        direct_openable_assets = {normalized_fqn}
    else:
        row = asset_service.lineage_asset_stub(pd.DataFrame(), normalized_fqn)
        direct_openable_assets = set()
    return row, pd.DataFrame([row.to_dict()]), direct_openable_assets


def _lineage_rows_for_assets(
    uc: UCSQLClient,
    asset_fqns: Sequence[str],
    *,
    inventory_columns: Optional[Sequence[str]] = None,
) -> pd.DataFrame:
    normalized_assets: List[str] = []
    parsed_assets: List[Tuple[str, str, str, str]] = []
    for raw_fqn in asset_fqns:
        normalized_fqn = asset_service.normalize_str(raw_fqn)
        if not normalized_fqn or normalized_fqn in normalized_assets:
            continue
        if asset_service.asset_fqn_is_hidden(normalized_fqn):
            continue
        try:
            catalog, schema, table = asset_service.split_uc_name(normalized_fqn)
        except ValueError:
            continue
        normalized_assets.append(normalized_fqn)
        parsed_assets.append((normalized_fqn, catalog, schema, table))
    if not parsed_assets:
        return pd.DataFrame(columns=list(inventory_columns or []))

    predicate = " OR ".join(
        "("
        f"table_catalog = {sql_literal(catalog)} "
        f"AND table_schema = {sql_literal(schema)} "
        f"AND table_name = {sql_literal(table)}"
        ")"
        for _, catalog, schema, table in parsed_assets
    )
    try:
        identity_df = uc.query_df(
            f"""
SELECT
  table_catalog,
  table_schema,
  table_name,
  table_type,
  data_source_format,
  comment
FROM system.information_schema.tables
WHERE {predicate}
"""
        )
    except Exception:
        identity_df = pd.DataFrame()
    if identity_df is None or identity_df.empty:
        return pd.DataFrame(columns=list(inventory_columns or []))

    identity_df = identity_df.copy()
    for column in ["table_catalog", "table_schema", "table_name"]:
        if column not in identity_df.columns:
            return pd.DataFrame(columns=list(inventory_columns or []))
        identity_df[column] = identity_df[column].fillna("").astype(str)
    if "data_source_format" not in identity_df.columns:
        identity_df["data_source_format"] = ""
    if "comment" not in identity_df.columns:
        identity_df["comment"] = ""

    tag_predicate = " OR ".join(
        "("
        f"catalog_name = {sql_literal(catalog)} "
        f"AND schema_name = {sql_literal(schema)} "
        f"AND table_name = {sql_literal(table)}"
        ")"
        for _, catalog, schema, table in parsed_assets
    )
    tags_by_fqn: Dict[str, Dict[str, str]] = {}
    try:
        tags_df = uc.query_df(
            f"""
SELECT
  catalog_name,
  schema_name,
  table_name,
  tag_name,
  tag_value
FROM system.information_schema.table_tags
WHERE {tag_predicate}
"""
        )
    except Exception:
        tags_df = pd.DataFrame()
    if tags_df is not None and not tags_df.empty:
        for _, tag_row in tags_df.iterrows():
            tag_fqn = ".".join(
                asset_service.normalize_str(tag_row.get(column))
                for column in ["catalog_name", "schema_name", "table_name"]
            )
            tag_name = asset_service.normalize_str(tag_row.get("tag_name"))
            if not tag_fqn or not tag_name:
                continue
            tags_by_fqn.setdefault(tag_fqn, {})[tag_name] = asset_service.normalize_str(
                tag_row.get("tag_value")
            )

    base_columns = list(inventory_columns or [])
    rows: List[Dict[str, Any]] = []
    for _, row in identity_df.iterrows():
        fqn = ".".join(
            asset_service.normalize_str(row.get(column))
            for column in ["table_catalog", "table_schema", "table_name"]
        )
        if not fqn:
            continue
        tags = tags_by_fqn.get(fqn, {})
        payload: Dict[str, Any] = {column: "" for column in base_columns}
        payload.update(
            {
                "fqn": fqn,
                "table_catalog": asset_service.normalize_str(row.get("table_catalog")),
                "table_schema": asset_service.normalize_str(row.get("table_schema")),
                "table_name": asset_service.normalize_str(row.get("table_name")),
                "table_type": asset_service.normalize_str(row.get("table_type")),
                "data_source_format": asset_service.normalize_str(row.get("data_source_format")),
                "comment": asset_service.normalize_str(row.get("comment")),
                "tags": tags,
                "domain": asset_service.tag_value(tags, "domain"),
                "tier": asset_service.tag_value(tags, "tier"),
                "certification": asset_service.tag_value(tags, "certification"),
                "sensitivity": asset_service.tag_value(tags, "sensitivity"),
                "criticality": asset_service.tag_value(tags, "criticality"),
                "glossary_term": asset_service.tag_value(tags, "glossary_term"),
                "glossaryTerm": asset_service.tag_value(tags, "glossary_term"),
                "data_product": asset_service.tag_value(tags, "data_product"),
                "governance_status": "Needs Work",
            }
        )
        rows.append(payload)
    if not rows:
        return pd.DataFrame(columns=base_columns)
    return pd.DataFrame(rows)


def _focus_columns_payload(
    uc: UCSQLClient,
    asset_fqn: str,
    *,
    limit: int = FOCUS_COLUMN_PREVIEW_LIMIT,
) -> List[Dict[str, Any]]:
    """Return a compact column-preview list for the focus node.

    Defect 6 + 8 — the lineage payload previously omitted `columns` on
    every node, which meant the front-end's "Include Columns" toggle had
    nothing to surface on the focused card and the Details tab could not
    render a schema preview. We fetch the column list via the cached
    `uc.get_table_columns` path (same source the entity workspace uses),
    clamp to `limit` rows to keep the payload cheap, and emit the minimal
    shape the UI expects (`name`, `type`, optional `qualityTone`).

    Any failure is swallowed silently — missing columns degrade the
    focus card gracefully (it falls back to the non-column layout) but
    must never break the lineage graph itself.
    """
    try:
        catalog, schema, table = asset_service.split_uc_name(asset_fqn)
    except ValueError:
        return []
    try:
        columns_df = uc.get_table_columns(catalog, schema, table)
    except Exception:
        return []
    if columns_df is None or columns_df.empty:
        return []
    rows: List[Dict[str, Any]] = []
    for _, row in columns_df.head(limit).iterrows():
        name = asset_service.normalize_str(row.get("column_name"))
        if not name:
            continue
        rows.append(
            {
                "name": name,
                "type": asset_service.normalize_str(row.get("data_type")),
            }
        )
    return rows


def graph_node_for_asset(
    uc: UCSQLClient,
    store: Any,
    asset_fqn: str,
    role: str,
    x: int,
    y: int,
    *,
    kicker: str,
    kind: str = "",
    foot: Optional[List[str]] = None,
    depth: int = 1,
    visible_inventory: Optional[pd.DataFrame] = None,
    include_columns: bool = False,
    direct_openable_assets: Optional[Set[str]] = None,
) -> Dict[str, Any]:
    normalized_fqn = asset_service.normalize_str(asset_fqn)
    direct_openable = normalized_fqn in (direct_openable_assets or set())
    visible_inventory_df = (
        visible_inventory
        if isinstance(visible_inventory, pd.DataFrame)
        else asset_service.visible_assets(uc, store)
    )
    visible_match = (
        isinstance(visible_inventory_df, pd.DataFrame)
        and asset_service.asset_is_visible(visible_inventory_df, asset_fqn)
    )
    if visible_match:
        row = asset_service.inventory_row(visible_inventory_df, asset_fqn)
    elif direct_openable and isinstance(visible_inventory_df, pd.DataFrame):
        exact_row = asset_service.exact_identity_row(
            uc,
            asset_fqn,
            inventory_columns=list(visible_inventory_df.columns),
        )
        row = exact_row if exact_row is not None else asset_service.inventory_row(visible_inventory_df, asset_fqn)
    elif isinstance(visible_inventory_df, pd.DataFrame):
        row = asset_service.inventory_row(visible_inventory_df, asset_fqn)
    else:
        row = asset_service.inventory_row(uc, store, asset_fqn)
    identity_resolved = bool(asset_service.normalize_str(row.get("table_type")))
    is_openable = visible_match or direct_openable
    label = asset_service.normalize_str(row.get("table_name")) or asset_fqn.split(".")[-1]
    subtitle = " / ".join(
        part
        for part in [
            asset_service.normalize_str(row.get("table_catalog")),
            asset_service.normalize_str(row.get("table_schema")),
        ]
        if part
    )
    item_kind = kind or asset_service.friendly_table_type(
        row.get("table_type"),
        row.get("data_source_format"),
    )
    if not identity_resolved and not item_kind:
        item_kind = "Lineage Reference"
    footer = foot or [item_kind]
    if not is_openable:
        # L9: non-openable nodes previously stacked two vague lines
        # ("Metadata unavailable" + "Metadata record unavailable") in the
        # card footer. Collapse to ONE clear permission-honest line so a
        # restricted node reads intentionally instead of broken.
        footer = ["Not visible to your account"]
    metadata_unavailable = not is_openable or not identity_resolved
    governance_status = asset_service.normalize_str(row.get("governance_status"))
    domain = asset_service.normalize_str(row.get("domain"))
    tier = asset_service.normalize_str(row.get("tier"))
    certification = asset_service.normalize_str(row.get("certification"))
    sensitivity = asset_service.normalize_str(row.get("sensitivity"))
    # Defect 6 + 8 — only the focus node receives a column preview so the
    # payload stays cheap (non-focus nodes render as compact icon + name
    # cards per round-18 design). `include_columns=False` skips the
    # column fetch entirely so this helper stays cheap for peer nodes.
    columns_payload = (
        _focus_columns_payload(uc, asset_fqn)
        if include_columns and is_openable
        else []
    )
    return {
        "id": f"{role}-{asset_fqn}",
        "assetFqn": asset_fqn,
        "label": label,
        "subtitle": subtitle,
        "kicker": kicker,
        "kind": item_kind,
        "role": role,
        "depth": depth,
        "x": x,
        "y": y,
        "foot": footer,
        "columns": columns_payload,
        "details": {
            "fqn": asset_fqn,
            "description": asset_service.normalize_str(row.get("comment"))
            or (
                "This related asset is present in lineage metadata, but its live record is not currently openable from this workspace."
                if not is_openable
                else asset_service.PLACEHOLDER_DESCRIPTION
            ),
            "governanceStatus": "Unavailable" if metadata_unavailable else governance_status or "Unassigned",
            "domain": "Unavailable" if metadata_unavailable else domain or "Unassigned",
            "tier": "Unavailable" if metadata_unavailable else tier or "Unassigned",
            "certification": "Unavailable" if metadata_unavailable else certification or "Unassigned",
            "sensitivity": "Unavailable" if metadata_unavailable else sensitivity or "Unassigned",
            "isOpenable": is_openable,
            "openabilityState": "verified" if is_openable else "unverified",
            "resolutionState": "resolved" if is_openable else "lineage-only",
        },
    }


def stack_positions(
    count: int,
    *,
    x: int,
    top: int = 22,
    bottom: int = 78,
) -> List[Tuple[int, int]]:
    if count <= 0:
        return []
    if count == 1:
        return [(x, 50)]
    span = max(bottom - top, 10)
    step = span / (count - 1)
    return [(x, round(top + idx * step)) for idx in range(count)]


def _data_edge_key(source_id: str, target_id: str) -> str:
    return f"data:{source_id}->{target_id}"


def _operational_edge_key(source_id: str, target_id: str) -> str:
    return f"operational:{source_id}->{target_id}"


def _column_lineage_payload(
    uc: UCSQLClient,
    asset_fqn: str,
    *,
    system_uc: Optional[UCSQLClient] = None,
) -> Dict[str, Any]:
    # system.access.column_lineage applies row-level filtering to match the
    # querying principal's SELECT grants on source/target tables. When the actor
    # has OBO but lacks SELECT on upstream bronze tables, the query returns zero
    # rows even though lineage exists. Catalog tools uniformly show crawler-view
    # lineage to authorized viewers, so route system-table reads through the
    # app-principal client when one is supplied.
    system_client = system_uc or uc
    catalog, schema, table = asset_service.split_uc_name(asset_fqn)

    def load_upstream() -> pd.DataFrame:
        try:
            return system_client.get_column_lineage_upstream(
                catalog,
                schema,
                table,
                limit=COLUMN_LINEAGE_LIMIT,
            )
        except Exception:
            return pd.DataFrame()

    def load_downstream() -> pd.DataFrame:
        try:
            return system_client.get_column_lineage_downstream(
                catalog,
                schema,
                table,
                limit=COLUMN_LINEAGE_LIMIT,
            )
        except Exception:
            return pd.DataFrame()

    with ThreadPoolExecutor(max_workers=2) as executor:
        upstream_future = executor.submit(load_upstream)
        downstream_future = executor.submit(load_downstream)
        upstream_df = upstream_future.result()
        downstream_df = downstream_future.result()

    upstream: Dict[str, List[Dict[str, str]]] = {}
    if upstream_df is not None and not upstream_df.empty:
        for _, row in upstream_df.iterrows():
            target_column = asset_service.normalize_str(row.get("target_column_name"))
            source_asset = asset_service.normalize_str(row.get("source_table_full_name"))
            source_column = asset_service.normalize_str(row.get("source_column_name"))
            if not target_column or not source_asset or not source_column:
                continue
            upstream.setdefault(target_column, []).append(
                {"assetFqn": source_asset, "column": source_column}
            )

    downstream: Dict[str, List[Dict[str, str]]] = {}
    if downstream_df is not None and not downstream_df.empty:
        for _, row in downstream_df.iterrows():
            source_column = asset_service.normalize_str(row.get("source_column_name"))
            target_asset = asset_service.normalize_str(row.get("target_table_full_name"))
            target_column = asset_service.normalize_str(row.get("target_column_name"))
            if not source_column or not target_asset or not target_column:
                continue
            downstream.setdefault(source_column, []).append(
                {"assetFqn": target_asset, "column": target_column}
            )

    return {
        "upstream": [
            {"column": column, "sources": sources}
            for column, sources in sorted(upstream.items())
        ],
        "downstream": [
            {"column": column, "targets": targets}
            for column, targets in sorted(downstream.items())
        ],
        "meta": {
            "limit": COLUMN_LINEAGE_LIMIT,
            "truncated": bool(
                (upstream_df is not None and len(upstream_df.index) >= COLUMN_LINEAGE_LIMIT)
                or (downstream_df is not None and len(downstream_df.index) >= COLUMN_LINEAGE_LIMIT)
            ),
        },
    }


def _data_edge_details(
    graph: Dict[str, Any],
    column_lineage: Dict[str, List[Dict[str, Any]]],
) -> Dict[str, Dict[str, Any]]:
    focus_node = next((node for node in graph.get("nodes", []) if node.get("role") == "focus"), None)
    focus_fqn = asset_service.normalize_str(focus_node.get("assetFqn")) if focus_node else ""
    upstream_lookup: Dict[str, List[Dict[str, str]]] = {}
    for entry in column_lineage.get("upstream", []):
        target_column = asset_service.normalize_str(entry.get("column"))
        for source in entry.get("sources", []) or []:
            source_fqn = asset_service.normalize_str(source.get("assetFqn"))
            if not source_fqn or not target_column:
                continue
            upstream_lookup.setdefault(source_fqn, []).append(
                {
                    "sourceColumn": asset_service.normalize_str(source.get("column")),
                    "targetColumn": target_column,
                }
            )
    downstream_lookup: Dict[str, List[Dict[str, str]]] = {}
    for entry in column_lineage.get("downstream", []):
        source_column = asset_service.normalize_str(entry.get("column"))
        for target in entry.get("targets", []) or []:
            target_fqn = asset_service.normalize_str(target.get("assetFqn"))
            if not target_fqn or not source_column:
                continue
            downstream_lookup.setdefault(target_fqn, []).append(
                {
                    "sourceColumn": source_column,
                    "targetColumn": asset_service.normalize_str(target.get("column")),
                }
            )

    details: Dict[str, Dict[str, Any]] = {}
    for edge in graph.get("edges", []) or []:
        source_id = edge.get("source")
        target_id = edge.get("target")
        source_node = next((node for node in graph.get("nodes", []) if node.get("id") == source_id), {})
        target_node = next((node for node in graph.get("nodes", []) if node.get("id") == target_id), {})
        key = edge.get("key") or _data_edge_key(source_id, target_id)
        source_fqn = asset_service.normalize_str(source_node.get("assetFqn"))
        target_fqn = asset_service.normalize_str(target_node.get("assetFqn"))
        provenance = (
            asset_service.normalize_str(edge.get("provenance"))
            or "system.access.table_lineage"
        )
        mappings = []
        if target_fqn == focus_fqn:
            mappings = upstream_lookup.get(source_fqn, [])
        elif source_fqn == focus_fqn:
            mappings = downstream_lookup.get(target_fqn, [])
        details[key] = {
            "kind": "data",
            "sourceAssetFqn": source_fqn,
            "targetAssetFqn": target_fqn,
            "provenance": provenance,
            "mappingCount": len(mappings),
            "columnMappings": mappings[:20],
            # A5.2 — reserved slot for the SQL snippet that produced the
            # relationship (view definition, job SQL, etc). Unity Catalog
            # system tables do not expose this uniformly yet, so we emit
            # None and let the frontend render a muted placeholder. When a
            # downstream crawler starts populating this field it flows
            # through to the edge drawer without frontend changes.
            "sqlSnippet": None,
            "summary": (
                "Governed lineage evidence recorded in Unity Catalog table tags"
                if provenance == GOVERNED_LINEAGE_PROVENANCE
                else
                f"{len(mappings)} column mapping{'s' if len(mappings) != 1 else ''}"
                if mappings
                else "Table-level lineage relationship"
            ),
        }
    return details


def _operational_edge_details(graph: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    details: Dict[str, Dict[str, Any]] = {}
    node_lookup = {node.get("id"): node for node in graph.get("nodes", [])}
    for edge in graph.get("edges", []) or []:
        source_node = node_lookup.get(edge.get("source"), {})
        target_node = node_lookup.get(edge.get("target"), {})
        key = edge.get("key") or _operational_edge_key(edge.get("source", ""), edge.get("target", ""))
        payload_node = source_node if source_node.get("role") != "focus" else target_node
        details[key] = {
            "kind": "operational",
            "summary": asset_service.normalize_str(payload_node.get("subtitle")) or "Operational context relationship",
            "entities": payload_node.get("details", []) or [],
        }
    return details


def _governed_operational_job_entities(
    uc: UCSQLClient,
    asset_fqn: str,
    *,
    role: str,
) -> List[Dict[str, Any]]:
    try:
        catalog, schema, table = asset_service.split_uc_name(asset_fqn)
    except ValueError:
        return []
    if role == "source":
        id_tag = GOVERNED_OPERATIONAL_PRODUCER_JOB_ID_TAG
        name_tag = GOVERNED_OPERATIONAL_PRODUCER_JOB_NAME_TAG
    else:
        id_tag = GOVERNED_OPERATIONAL_CONSUMER_JOB_ID_TAG
        name_tag = GOVERNED_OPERATIONAL_CONSUMER_JOB_NAME_TAG
    try:
        tags = uc.query_df(
            f"""
SELECT tag_name, tag_value
FROM system.information_schema.table_tags
WHERE catalog_name = {sql_literal(catalog)}
  AND schema_name = {sql_literal(schema)}
  AND table_name = {sql_literal(table)}
  AND tag_name IN ({sql_literal(id_tag)}, {sql_literal(name_tag)})
"""
        )
    except Exception:
        return []
    if tags is None or tags.empty:
        return []
    tag_values = {
        asset_service.normalize_str(row.get("tag_name")): asset_service.normalize_str(row.get("tag_value"))
        for _, row in tags.iterrows()
    }
    entity_id = tag_values.get(id_tag, "")
    name = tag_values.get(name_tag, "")
    if not entity_id and not name:
        return []
    resolved_name = ""
    if entity_id:
        try:
            resolved_name = uc.resolve_operational_entity_name("JOB", entity_id)
        except Exception:
            resolved_name = ""
    entity_name = resolved_name or name or f"Databricks Job {entity_id}".strip()
    return [
        {
            "key": f"governed-operational-job:{role}:{entity_id or entity_name}",
            "entityType": "JOB",
            "entityLabel": "Job",
            "entityId": entity_id,
            "statementId": GOVERNED_LINEAGE_PROVENANCE,
            "runId": "",
            "name": entity_name,
            "metadata": "Operational context backed by Unity Catalog table tags and Databricks Jobs API lookup.",
            "relatedAssets": [asset_service.normalize_str(asset_fqn)],
            "provenance": GOVERNED_LINEAGE_PROVENANCE,
        }
    ]


def _first_hop_assets(data_graph: Dict[str, Any]) -> Dict[str, List[str]]:
    focus_id = asset_service.normalize_str(
        next(
            (node.get("id") for node in data_graph.get("nodes", []) if node.get("role") == "focus"),
            "",
        )
    )
    node_lookup = {
        asset_service.normalize_str(node.get("id")): node
        for node in data_graph.get("nodes", []) or []
    }
    upstream: List[str] = []
    downstream: List[str] = []
    for edge in data_graph.get("edges", []) or []:
        source_id = asset_service.normalize_str(edge.get("source"))
        target_id = asset_service.normalize_str(edge.get("target"))
        if target_id == focus_id:
            asset_fqn = asset_service.normalize_str(
                node_lookup.get(source_id, {}).get("assetFqn")
            )
            if asset_fqn:
                upstream.append(asset_fqn)
        elif source_id == focus_id:
            asset_fqn = asset_service.normalize_str(
                node_lookup.get(target_id, {}).get("assetFqn")
            )
            if asset_fqn:
                downstream.append(asset_fqn)
    return {
        "upstream": list(dict.fromkeys(upstream)),
        "downstream": list(dict.fromkeys(downstream)),
    }


def _lineage_graph_direction_counts(data_graph: Dict[str, Any]) -> Dict[str, int]:
    focus_id = asset_service.normalize_str(
        next(
            (node.get("id") for node in data_graph.get("nodes", []) if node.get("role") == "focus"),
            "",
        )
    )
    if not focus_id:
        return {
            "upstream": 0,
            "downstream": 0,
            "directUpstream": 0,
            "directDownstream": 0,
        }
    nodes_by_id = {
        asset_service.normalize_str(node.get("id")): node
        for node in data_graph.get("nodes", []) or []
        if asset_service.normalize_str(node.get("id"))
    }
    forward: Dict[str, Set[str]] = {}
    reverse: Dict[str, Set[str]] = {}
    for edge in data_graph.get("edges", []) or []:
        source_id = asset_service.normalize_str(edge.get("source"))
        target_id = asset_service.normalize_str(edge.get("target"))
        if not source_id or not target_id:
            continue
        forward.setdefault(source_id, set()).add(target_id)
        reverse.setdefault(target_id, set()).add(source_id)

    def traverse(start_id: str, adjacency: Dict[str, Set[str]]) -> Set[str]:
        visited: Set[str] = set()
        queue: Deque[str] = deque([start_id])
        while queue:
            current = queue.popleft()
            for next_id in adjacency.get(current, set()):
                if next_id in visited:
                    continue
                visited.add(next_id)
                queue.append(next_id)
        visited.discard(start_id)
        return {
            node_id
            for node_id in visited
            if asset_service.normalize_str(nodes_by_id.get(node_id, {}).get("assetFqn"))
        }

    direct_upstream = {
        node_id
        for node_id in reverse.get(focus_id, set())
        if asset_service.normalize_str(nodes_by_id.get(node_id, {}).get("assetFqn"))
    }
    direct_downstream = {
        node_id
        for node_id in forward.get(focus_id, set())
        if asset_service.normalize_str(nodes_by_id.get(node_id, {}).get("assetFqn"))
    }
    return {
        "upstream": len(traverse(focus_id, reverse)),
        "downstream": len(traverse(focus_id, forward)),
        "directUpstream": len(direct_upstream),
        "directDownstream": len(direct_downstream),
    }


def _row_text(row: Any, *keys: str) -> str:
    for key in keys:
        value = asset_service.normalize_str(row.get(key))
        if value:
            return value
    return ""


def _row_int(row: Any, *keys: str) -> int:
    for key in keys:
        value = row.get(key)
        try:
            number = int(value)
        except Exception:
            continue
        return max(0, number)
    return 0


def _recommendation_row_payload(row: Any, counts: Dict[str, int]) -> Dict[str, Any]:
    fqn = asset_service.normalize_str(row.get("fqn"))
    name = _row_text(row, "table_name", "name") or fqn.split(".")[-1]
    catalog = _row_text(row, "table_catalog", "catalogName", "catalog")
    schema = _row_text(row, "table_schema", "schemaName", "schema")
    return {
        "fqn": fqn,
        "name": name,
        "catalogName": catalog,
        "schemaName": schema,
        "objectType": asset_service.friendly_table_type(
            row.get("table_type"),
            row.get("data_source_format"),
        ),
        "domain": _row_text(row, "domain"),
        "tier": _row_text(row, "tier"),
        "certification": _row_text(row, "certification"),
        "sensitivity": _row_text(row, "sensitivity"),
        "criticality": _row_text(row, "criticality", "business_criticality", "businessCriticality"),
        "owner": _row_text(row, "owners_summary", "business_owner", "technical_owner", "steward"),
        "upstreamCount": int(counts.get("upstream", 0)),
        "downstreamCount": int(counts.get("downstream", 0)),
        "edgeCount": int(counts.get("upstream", 0)) + int(counts.get("downstream", 0)),
        "source": "system.access.table_lineage",
    }


def _rankable_visible_assets(uc: UCSQLClient, store: Any) -> pd.DataFrame:
    try:
        visible = asset_service.visible_assets(uc, store)
    except Exception:
        return pd.DataFrame()
    if visible is None or visible.empty or "fqn" not in visible.columns:
        return pd.DataFrame()
    filtered = visible.copy()
    filtered["fqn"] = filtered["fqn"].map(asset_service.normalize_str)
    filtered = filtered[filtered["fqn"].ne("")]
    if filtered.empty:
        return pd.DataFrame()
    return filtered.head(LINEAGE_RECOMMENDATION_VISIBLE_ASSET_LIMIT).reset_index(drop=True)


def _lineage_density_candidates(system_client: UCSQLClient, *, limit: int) -> pd.DataFrame:
    resolved_limit = max(1, min(int(limit or LINEAGE_RECOMMENDATION_CANDIDATE_LIMIT), 500))
    query = f"""
WITH lineage_assets AS (
  SELECT
    CAST(source_table_full_name AS STRING) AS asset_fqn,
    0 AS upstream_count,
    COUNT(DISTINCT CAST(target_table_full_name AS STRING)) AS downstream_count
  FROM system.access.table_lineage
  WHERE {lineage_window_predicate()}
    AND source_table_full_name IS NOT NULL
    AND target_table_full_name IS NOT NULL
    AND source_table_full_name <> target_table_full_name
  GROUP BY CAST(source_table_full_name AS STRING)
  UNION ALL
  SELECT
    CAST(target_table_full_name AS STRING) AS asset_fqn,
    COUNT(DISTINCT CAST(source_table_full_name AS STRING)) AS upstream_count,
    0 AS downstream_count
  FROM system.access.table_lineage
  WHERE {lineage_window_predicate()}
    AND source_table_full_name IS NOT NULL
    AND target_table_full_name IS NOT NULL
    AND source_table_full_name <> target_table_full_name
  GROUP BY CAST(target_table_full_name AS STRING)
)
SELECT
  asset_fqn,
  SUM(upstream_count) AS upstreamCount,
  SUM(downstream_count) AS downstreamCount,
  SUM(upstream_count + downstream_count) AS edgeCount
FROM lineage_assets
WHERE asset_fqn IS NOT NULL AND asset_fqn <> ''
GROUP BY asset_fqn
HAVING SUM(upstream_count + downstream_count) > 0
ORDER BY edgeCount DESC, downstreamCount DESC, upstreamCount DESC, asset_fqn
LIMIT {resolved_limit}
"""
    df = system_client.query_df(query)
    if df is None or df.empty:
        return pd.DataFrame(columns=["asset_fqn", "upstreamCount", "downstreamCount", "edgeCount"])
    return df


def _visible_candidate_row(
    uc: UCSQLClient,
    rows_by_fqn: Dict[str, Any],
    asset_fqn: str,
) -> Optional[pd.Series]:
    normalized = asset_service.normalize_str(asset_fqn)
    if not normalized or asset_service.asset_fqn_is_hidden(normalized):
        return None
    if normalized in rows_by_fqn:
        return rows_by_fqn[normalized]
    try:
        return asset_service.exact_identity_row(uc, normalized)
    except Exception:
        return None


def lineage_recommendations_payload(
    uc: UCSQLClient,
    store: Any,
    *,
    system_uc: Optional[UCSQLClient] = None,
    limit: int = 8,
) -> Dict[str, Any]:
    """Rank visible assets by backed Unity Catalog table-lineage density.

    This is intentionally a recommendation list, not demo data. The payload only
    includes assets already present in the visible inventory and only counts
    relationships returned by ``system.access.table_lineage``. If the system
    table is unavailable or returns no rows, the caller gets an honest empty
    recommendation list with source metadata.
    """

    visible = _rankable_visible_assets(uc, store)
    if visible.empty:
        return {
            "items": [],
            "meta": {
                "source": "system.access.table_lineage",
                "visibleAssetCount": 0,
                "scannedAssetCount": 0,
                "edgeSampleLimit": LINEAGE_RECOMMENDATION_PER_SEED_LIMIT,
                "recommendationLimit": max(1, min(int(limit or 8), 25)),
                "unavailableReason": "No visible assets were available for lineage ranking.",
            },
        }

    system_client = system_uc or uc
    visible_fqns = [
        asset_service.normalize_str(value)
        for value in visible["fqn"].dropna().astype(str).tolist()
        if asset_service.normalize_str(value)
    ]
    rows_by_fqn = {
        asset_service.normalize_str(row.get("fqn")): row
        for _, row in visible.iterrows()
        if asset_service.normalize_str(row.get("fqn"))
    }
    resolved_limit = max(1, min(int(limit or 8), 25))
    visible_set = set(visible_fqns)
    counts: Dict[str, Dict[str, int]] = {
        fqn: {"upstream": 0, "downstream": 0} for fqn in visible_fqns
    }
    query_failed = False
    scanned = 0

    for start in range(0, len(visible_fqns), LINEAGE_RECOMMENDATION_BATCH_SIZE):
        batch = visible_fqns[start:start + LINEAGE_RECOMMENDATION_BATCH_SIZE]
        if not batch:
            continue
        scanned += len(batch)
        try:
            edges_df = system_client.get_table_lineage_edges_batch(
                batch,
                directions=("upstream", "downstream"),
                per_seed_limit=LINEAGE_RECOMMENDATION_PER_SEED_LIMIT,
            )
        except Exception:
            query_failed = True
            continue
        if edges_df is None or edges_df.empty:
            continue
        for _, edge in edges_df.iterrows():
            source = asset_service.normalize_str(edge.get("source_table_full_name"))
            target = asset_service.normalize_str(edge.get("target_table_full_name"))
            if source in visible_set and target and source != target:
                counts[source]["downstream"] += 1
            if target in visible_set and source and source != target:
                counts[target]["upstream"] += 1

    ranked = [
        _recommendation_row_payload(rows_by_fqn[fqn], asset_counts)
        for fqn, asset_counts in counts.items()
        if fqn in rows_by_fqn and (asset_counts.get("upstream", 0) or asset_counts.get("downstream", 0))
    ]
    ranked.sort(
        key=lambda item: (
            -int(item.get("edgeCount") or 0),
            -int(item.get("downstreamCount") or 0),
            -int(item.get("upstreamCount") or 0),
            item.get("fqn") or "",
        ),
    )
    if not ranked:
        density_candidates = pd.DataFrame()
        try:
            density_candidates = _lineage_density_candidates(
                system_client,
                limit=max(LINEAGE_RECOMMENDATION_CANDIDATE_LIMIT, resolved_limit * 10),
            )
        except Exception:
            density_candidates = pd.DataFrame()
        if density_candidates is not None and not density_candidates.empty:
            inspected = 0
            for _, candidate in density_candidates.iterrows():
                fqn = _row_text(candidate, "asset_fqn", "ASSET_FQN")
                row = _visible_candidate_row(uc, rows_by_fqn, fqn)
                inspected += 1
                if row is None:
                    continue
                ranked.append(
                    _recommendation_row_payload(
                        row,
                        {
                            "upstream": _row_int(candidate, "upstreamCount", "upstream_count", "UPSTREAMCOUNT"),
                            "downstream": _row_int(candidate, "downstreamCount", "downstream_count", "DOWNSTREAMCOUNT"),
                        },
                    )
                )
                if len(ranked) >= resolved_limit:
                    break
            if ranked:
                return {
                    "items": ranked[:resolved_limit],
                    "meta": {
                        "source": "system.access.table_lineage",
                        "rankingSource": "system.access.table_lineage.aggregate-fallback",
                        "visibleAssetCount": len(visible_fqns),
                        "scannedAssetCount": scanned + inspected,
                        "candidateLimit": max(LINEAGE_RECOMMENDATION_CANDIDATE_LIMIT, resolved_limit * 10),
                        "edgeSampleLimit": LINEAGE_RECOMMENDATION_PER_SEED_LIMIT,
                        "recommendationLimit": resolved_limit,
                        "bounded": True,
                        "scannedAssetLimit": LINEAGE_RECOMMENDATION_VISIBLE_ASSET_LIMIT,
                        "batchSize": LINEAGE_RECOMMENDATION_BATCH_SIZE,
                        "queryFailed": bool(query_failed),
                        "relationshipVisibilityScope": "actor-openable-candidate-aggregate",
                        "fallbackReason": "Visible-inventory lineage batches returned no ranked assets; used actor-openable density candidates from the Unity Catalog lineage aggregate.",
                        "unavailableReason": "",
                    },
                }
    return {
        "items": ranked[:resolved_limit],
        "meta": {
            "source": "system.access.table_lineage",
            "rankingSource": "visible-inventory-batched-lineage",
            "visibleAssetCount": len(visible_fqns),
            "scannedAssetCount": scanned,
            "candidateLimit": LINEAGE_RECOMMENDATION_CANDIDATE_LIMIT,
            "edgeSampleLimit": LINEAGE_RECOMMENDATION_PER_SEED_LIMIT,
            "recommendationLimit": resolved_limit,
            "bounded": True,
            "scannedAssetLimit": LINEAGE_RECOMMENDATION_VISIBLE_ASSET_LIMIT,
            "batchSize": LINEAGE_RECOMMENDATION_BATCH_SIZE,
            "queryFailed": bool(query_failed),
            "relationshipVisibilityScope": "visible-inventory-seed-lineage",
            "unavailableReason": (
                "Lineage ranking query failed for one or more visible-asset batches."
                if query_failed and not ranked
                else ""
            ),
        },
    }


def _governed_lineage_evidence_neighbors(
    uc: UCSQLClient,
    asset_fqn: str,
    *,
    limit: int,
) -> List[str]:
    normalized_asset = asset_service.normalize_str(asset_fqn)
    if not normalized_asset:
        return []
    try:
        df = uc.query_df(
            f"""
SELECT
  CONCAT(catalog_name, '.', schema_name, '.', table_name) AS target_table_full_name
FROM system.information_schema.table_tags
WHERE tag_name = {sql_literal(GOVERNED_LINEAGE_FOCUS_TAG)}
  AND tag_value = {sql_literal(normalized_asset)}
GROUP BY catalog_name, schema_name, table_name
ORDER BY target_table_full_name
LIMIT {int(limit)}
"""
        )
    except Exception:
        return []
    if df is None or df.empty or "target_table_full_name" not in df.columns:
        return []
    filtered = asset_service.filter_asset_rows(df, ["target_table_full_name"])
    if filtered.empty:
        return []
    return [
        asset_service.normalize_str(value)
        for value in filtered["target_table_full_name"].dropna().astype(str).tolist()
        if asset_service.normalize_str(value)
    ]


def _lineage_neighbor_records_batch(
    uc: UCSQLClient,
    asset_fqns: List[str],
    *,
    direction: str,
    per_seed_limit: int,
    system_uc: Optional[UCSQLClient] = None,
) -> Tuple[Dict[str, List[Dict[str, str]]], Dict[str, Any]]:
    """Batched neighbor lookup — ONE warehouse query per BFS frontier
    instead of one per (asset, direction) pair. Returns
    ``(by_seed, batch_meta)`` where ``by_seed`` is
    {seed_fqn: [{assetFqn, provenance}, ...]} preserving the same record
    shape `_lineage_neighbor_records` produced, and ``batch_meta`` is::

        {
            "queryFailed": bool,        # SQL failed — NOT the same as empty
            "totalsBySeed": {seed: int} # TOTAL partner edges per seed from
                                        # seed_total_edges, even past the
                                        # per-seed truncation cap
        }

    ``queryFailed`` exists because the previous version swallowed SQL
    errors into an empty dict, which made a broken query
    indistinguishable from "Unity Catalog has no lineage rows" — the
    root cause of every asset rendering 0 upstream edges as an
    "authoritative" empty state. Callers must propagate it as a
    degraded build, never an honest empty.

    For a graph with 8 first-hop neighbors at depth=1, this collapses
    16 round trips (8 nodes × upstream + 8 nodes × downstream) into 2
    (one per direction). At cold-cache the wall-clock improvement is
    typically 3-5x because warehouse round-trip latency dominates the
    cost of each individual query.
    """
    batch_meta: Dict[str, Any] = {"queryFailed": False, "totalsBySeed": {}}
    if not asset_fqns:
        return {}, batch_meta
    cleaned_seeds = [
        asset_service.normalize_str(fqn) for fqn in asset_fqns if fqn
    ]
    cleaned_seeds = [seed for seed in cleaned_seeds if seed]
    if not cleaned_seeds:
        return {}, batch_meta
    system_client = system_uc or uc
    try:
        edges_df = system_client.get_table_lineage_edges_batch(
            cleaned_seeds,
            directions=(direction,),
            per_seed_limit=per_seed_limit,
        )
    except Exception:
        # The SQL client already logged the failure. Mark it so the graph
        # build reports state=degraded instead of a fake empty graph.
        batch_meta["queryFailed"] = True
        edges_df = pd.DataFrame()
    by_seed: Dict[str, List[Dict[str, str]]] = {seed: [] for seed in cleaned_seeds}
    if edges_df is None or edges_df.empty:
        return by_seed, batch_meta
    if direction == "upstream":
        seed_col = "target_table_full_name"
        neighbor_col = "source_table_full_name"
    else:
        seed_col = "source_table_full_name"
        neighbor_col = "target_table_full_name"
    if seed_col not in edges_df.columns or neighbor_col not in edges_df.columns:
        return by_seed, batch_meta
    totals_by_seed: Dict[str, int] = batch_meta["totalsBySeed"]
    seen_pairs: Set[Tuple[str, str]] = set()
    for _, row in edges_df.iterrows():
        seed_value = asset_service.normalize_str(row.get(seed_col))
        neighbor_value = asset_service.normalize_str(row.get(neighbor_col))
        if not seed_value or not neighbor_value:
            continue
        if seed_value not in by_seed:
            # IN-list match returns rows where the seed column is one of
            # our seeds — but the warehouse may normalize/case-fold the
            # value, so we tolerate that by falling back to a fuzzy
            # match against our requested set.
            seed_value_lc = seed_value.lower()
            matched = next(
                (s for s in cleaned_seeds if s.lower() == seed_value_lc),
                None,
            )
            if matched is None:
                continue
            seed_value = matched
        # seed_total_edges rides on every row for its seed; record the max
        # so truncation copy can say "showing 40 of 655" honestly.
        try:
            seed_total = int(row.get("seed_total_edges"))
        except (TypeError, ValueError):
            seed_total = 0
        if seed_total > totals_by_seed.get(seed_value, 0):
            totals_by_seed[seed_value] = seed_total
        pair = (seed_value, neighbor_value)
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)
        by_seed.setdefault(seed_value, []).append(
            {"assetFqn": neighbor_value, "provenance": "system.access.table_lineage"}
        )
    return by_seed, batch_meta


def _lineage_neighbor_records(
    uc: UCSQLClient,
    asset_fqn: str,
    *,
    direction: str,
    limit: int,
    system_uc: Optional[UCSQLClient] = None,
    include_governed_tags: bool = True,
) -> List[Dict[str, str]]:
    system_client = system_uc or uc
    try:
        catalog, schema, table = asset_service.split_uc_name(asset_fqn)
    except ValueError:
        return []
    records: List[Dict[str, str]] = []
    seen: Set[str] = set()

    def add_neighbor(value: Any, provenance: str) -> None:
        neighbor_fqn = asset_service.normalize_str(value)
        if not neighbor_fqn or neighbor_fqn in seen:
            return
        seen.add(neighbor_fqn)
        records.append({"assetFqn": neighbor_fqn, "provenance": provenance})

    try:
        if direction == "upstream":
            df = system_client.get_table_lineage_upstream(catalog, schema, table, limit=limit)
            column = "source_table_full_name"
        else:
            df = system_client.get_table_lineage_downstream(catalog, schema, table, limit=limit)
            column = "target_table_full_name"
    except Exception:
        df = pd.DataFrame()
        column = ""
    if df is not None and not df.empty and column in df.columns:
        filtered = asset_service.filter_asset_rows(df, [column])
        if not filtered.empty and column in filtered.columns:
            for value in filtered[column].dropna().astype(str).tolist():
                add_neighbor(value, "system.access.table_lineage")

    if direction == "downstream" and include_governed_tags and len(records) < limit:
        remaining = max(0, limit - len(records))
        for value in _governed_lineage_evidence_neighbors(
            system_client,
            asset_fqn,
            limit=remaining,
        ):
            add_neighbor(value, GOVERNED_LINEAGE_PROVENANCE)

    return records


def _lineage_neighbors(
    uc: UCSQLClient,
    asset_fqn: str,
    *,
    direction: str,
    limit: int,
    system_uc: Optional[UCSQLClient] = None,
    include_governed_tags: bool = True,
) -> List[str]:
    return [
        record["assetFqn"]
        for record in _lineage_neighbor_records(
            uc,
            asset_fqn,
            direction=direction,
            limit=limit,
            system_uc=system_uc,
            include_governed_tags=include_governed_tags,
        )
    ]


def _recursive_branch_graph(
    uc: UCSQLClient,
    store: Any,
    focus_fqn: str,
    *,
    direction: str,
    depth_limit: int,
    node_limit: int,
    per_hop_limit: int,
    visible_inventory: Optional[pd.DataFrame] = None,
    system_uc: Optional[UCSQLClient] = None,
    secondary_seed_limit: int = SECOND_HOP_SEED_LIMIT,
    direct_openable_assets: Optional[Set[str]] = None,
) -> Dict[str, Any]:
    focus_fqn_n = asset_service.normalize_str(focus_fqn)
    branch_role = "source" if direction == "upstream" else "target"
    branch_kicker = "Upstream" if direction == "upstream" else "Downstream"
    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []
    seen_node_ids: Set[str] = set()
    seen_edges: Set[str] = set()
    visited_assets: Set[str] = {focus_fqn_n}
    queue: Deque[Tuple[str, int]] = deque([(focus_fqn_n, 0)])
    queued_secondary_seeds = 0
    truncated = False
    evidence_tag_neighbor_count = 0
    branch_direct_openable_assets = set(direct_openable_assets or set())
    # Honesty accounting: distinguish "query failed" (degraded build)
    # from "no rows" (true empty), and carry the focus asset's TOTAL
    # partner-edge count so truncation is surfaced, never silent.
    query_failed = False
    focus_neighbor_total = 0
    focus_neighbors_shown = 0
    # Per-asset openability, so edges into non-openable "Lineage
    # Reference" nodes can be marked kind="restricted" (dashed in the v2
    # canvas) instead of pretending they are fully-resolved data edges.
    openable_by_fqn: Dict[str, bool] = {focus_fqn_n: True}

    def node_id_for(asset_fqn: str) -> str:
        asset_fqn_n = asset_service.normalize_str(asset_fqn)
        if asset_fqn_n == focus_fqn_n:
            return f"focus-{focus_fqn_n}"
        return f"{branch_role}-{asset_fqn_n}"

    # Batched BFS: instead of popping one node at a time and querying
    # the warehouse per pop, we drain the entire current depth-frontier,
    # fire ONE batched query against system.access.table_lineage that
    # returns every neighbor for every frontier node in a single round
    # trip, then process the results. This collapses ~30 sequential
    # queries (typical 8-neighbor graph at depth=1) into 1-2.
    while queue:
        # Collect the entire frontier at the current depth before
        # querying — every queued entry shares (current_depth) until we
        # advance past depth_limit. Drain frontier into a list so we
        # can batch.
        if not queue:
            break
        frontier: List[Tuple[str, int]] = []
        frontier_depth = queue[0][1]
        while queue and queue[0][1] == frontier_depth:
            frontier.append(queue.popleft())
        if frontier_depth >= depth_limit:
            # All nodes at this depth are at-or-past the limit; skip
            # neighbor expansion for them but continue draining queue
            # in case deeper nodes are queued (shouldn't happen with
            # FIFO BFS but guards correctness).
            continue
        # Batched neighbor lookup — ONE warehouse query for the full
        # frontier instead of one per node. Per-seed truncation in the
        # SQL keeps a hot node from monopolizing the result set.
        frontier_fqns = [fqn for fqn, _ in frontier]
        batched_neighbors, batch_meta = _lineage_neighbor_records_batch(
            uc,
            frontier_fqns,
            direction=direction,
            per_seed_limit=max(TABLE_LINEAGE_LIMIT, per_hop_limit),
            system_uc=system_uc,
        )
        if batch_meta.get("queryFailed"):
            # A failed warehouse query is NOT an empty graph. Record it so
            # the payload reports state=degraded and is not cached as an
            # authoritative empty result.
            query_failed = True
        if frontier_depth == 0:
            focus_neighbor_total = int(
                (batch_meta.get("totalsBySeed") or {}).get(focus_fqn_n, 0)
            )

        # Now process each frontier node in turn, but using the
        # already-fetched neighbor map. The governed-tag fallback
        # (only at depth=0) still requires one extra query per call,
        # but only fires when the system table returned no neighbors
        # for the focus, which is the cold-edge case.
        for current_fqn, current_depth in frontier:
            neighbor_candidates: List[str] = []
            provenance_by_neighbor: Dict[str, str] = {}
            seed_records = list(batched_neighbors.get(current_fqn, []))
            # For depth=0 only, supplement with the governed-tag
            # evidence trail if the system table returned nothing —
            # mirrors prior behavior in _lineage_neighbor_records.
            if (
                current_depth == 0
                and direction == "downstream"
                and not seed_records
            ):
                supp = _lineage_neighbor_records(
                    uc,
                    current_fqn,
                    direction=direction,
                    limit=max(TABLE_LINEAGE_LIMIT, per_hop_limit),
                    system_uc=system_uc,
                    include_governed_tags=True,
                )
                seed_records.extend(supp)
            for record in seed_records:
                neighbor_fqn = asset_service.normalize_str(record.get("assetFqn"))
                if (
                    not neighbor_fqn
                    or neighbor_fqn == current_fqn
                    or neighbor_fqn == focus_fqn_n
                    or neighbor_fqn in neighbor_candidates
                ):
                    continue
                neighbor_candidates.append(neighbor_fqn)
                provenance_by_neighbor[neighbor_fqn] = (
                    asset_service.normalize_str(record.get("provenance"))
                    or "system.access.table_lineage"
                )
                if provenance_by_neighbor[neighbor_fqn] == GOVERNED_LINEAGE_PROVENANCE:
                    evidence_tag_neighbor_count += 1

            if len(neighbor_candidates) > per_hop_limit:
                truncated = True
            neighbors = neighbor_candidates[:per_hop_limit]
            if current_depth == 0:
                # Governed-tag supplements can push the observed count past
                # the SQL total; keep the larger so "N of M" never claims
                # M < N.
                focus_neighbor_total = max(
                    focus_neighbor_total, len(neighbor_candidates)
                )
                focus_neighbors_shown = len(neighbors)
                if focus_neighbor_total > focus_neighbors_shown:
                    truncated = True
            missing_inventory_rows = [
                neighbor_fqn
                for neighbor_fqn in neighbors
                if neighbor_fqn not in branch_direct_openable_assets
                and not (
                    isinstance(visible_inventory, pd.DataFrame)
                    and asset_service.asset_is_visible(visible_inventory, neighbor_fqn)
                )
            ]
            if missing_inventory_rows:
                fetched_rows = _lineage_rows_for_assets(
                    uc,
                    missing_inventory_rows,
                    inventory_columns=(
                        list(visible_inventory.columns)
                        if isinstance(visible_inventory, pd.DataFrame)
                        else None
                    ),
                )
                if fetched_rows is not None and not fetched_rows.empty:
                    branch_direct_openable_assets.update(
                        asset_service.normalize_str(value)
                        for value in fetched_rows["fqn"].dropna().astype(str).tolist()
                    )
                    visible_inventory = (
                        pd.concat([visible_inventory, fetched_rows], ignore_index=True)
                        if isinstance(visible_inventory, pd.DataFrame)
                        else fetched_rows
                    )

            for neighbor_fqn in neighbors:
                if len(nodes) >= node_limit and neighbor_fqn not in visited_assets:
                    truncated = True
                    break

                if neighbor_fqn not in visited_assets:
                    node = graph_node_for_asset(
                        uc,
                        store,
                        neighbor_fqn,
                        branch_role,
                        0,
                        0,
                        kicker=branch_kicker,
                        # kind is intentionally NOT hard-coded to "Table":
                        # graph_node_for_asset resolves the real kind from
                        # inventory, and unresolved out-of-inventory
                        # neighbors honestly become "Lineage Reference"
                        # instead of a fabricated Table label.
                        depth=current_depth + 1,
                        visible_inventory=visible_inventory,
                        direct_openable_assets=branch_direct_openable_assets,
                    )
                    node_id = asset_service.normalize_str(node.get("id"))
                    if node_id not in seen_node_ids:
                        nodes.append(node)
                        seen_node_ids.add(node_id)
                    visited_assets.add(neighbor_fqn)
                    openable_by_fqn[neighbor_fqn] = bool(
                        (node.get("details") or {}).get("isOpenable")
                    )
                    if current_depth + 1 < depth_limit:
                        if current_depth == 0 and queued_secondary_seeds >= secondary_seed_limit:
                            truncated = True
                        else:
                            queue.append((neighbor_fqn, current_depth + 1))
                            if current_depth == 0:
                                queued_secondary_seeds += 1

                current_node_id = node_id_for(current_fqn)
                neighbor_node_id = node_id_for(neighbor_fqn)
                source_id = neighbor_node_id if direction == "upstream" else current_node_id
                target_id = current_node_id if direction == "upstream" else neighbor_node_id
                edge_key = _data_edge_key(source_id, target_id)
                if edge_key in seen_edges:
                    continue
                edges.append(
                    {
                        "source": source_id,
                        "target": target_id,
                        "depth": current_depth + 1,
                        "key": edge_key,
                        # v2 contract: edge kind "restricted" renders dashed
                        # for edges whose far endpoint is a non-openable
                        # Lineage Reference node; plain data edges are
                        # "lineage".
                        "kind": (
                            "lineage"
                            if openable_by_fqn.get(neighbor_fqn, True)
                            and openable_by_fqn.get(current_fqn, True)
                            else "restricted"
                        ),
                        "provenance": provenance_by_neighbor.get(
                            neighbor_fqn,
                            "system.access.table_lineage",
                        ),
                    }
                )
                seen_edges.add(edge_key)

            if len(nodes) >= node_limit:
                truncated = True
                break

    return {
        "nodes": nodes,
        "edges": edges,
        "truncated": truncated,
        "nodeLimit": node_limit,
        "depthLimit": depth_limit,
        "perHopLimit": per_hop_limit,
        "secondaryBranchLimit": secondary_seed_limit,
        "governedLineageEvidenceTagNeighborCount": evidence_tag_neighbor_count,
        # Honesty accounting for the payload meta: a failed query is a
        # degraded build (never cached as an authoritative empty), and
        # focus totals feed meta.truncation ("showing N of M").
        "queryFailed": query_failed,
        "focusNeighborTotal": focus_neighbor_total,
        "focusNeighborsShown": focus_neighbors_shown,
    }


def _second_hop_payload(
    uc: UCSQLClient,
    focus_fqn: str,
    first_hop_assets: List[str],
    *,
    direction: str,
    system_uc: Optional[UCSQLClient] = None,
) -> Dict[str, Any]:
    if not first_hop_assets:
        return {
            "startingAssetCount": 0,
            "processedStartingAssetCount": 0,
            "uniqueNeighborCount": 0,
            "neighborSamples": [],
            "startingAssetSummaries": [],
            "limit": {
                "startingAssets": SECOND_HOP_SEED_LIMIT,
                "neighborsPerStartingAsset": SECOND_HOP_NEIGHBOR_LIMIT,
            },
        }

    discovered: List[str] = []
    seed_summaries: List[Dict[str, Any]] = []
    first_hop_set = {asset_service.normalize_str(value) for value in first_hop_assets}
    focus_n = asset_service.normalize_str(focus_fqn)
    for seed_asset in first_hop_assets[:SECOND_HOP_SEED_LIMIT]:
        seed_n = asset_service.normalize_str(seed_asset)
        neighbors = _lineage_neighbors(
            uc,
            seed_n,
            direction=direction,
            limit=SECOND_HOP_NEIGHBOR_LIMIT,
            system_uc=system_uc,
            include_governed_tags=False,
        )
        clean_neighbors: List[str] = []
        for neighbor in neighbors:
            neighbor_n = asset_service.normalize_str(neighbor)
            if not neighbor_n or neighbor_n == focus_n or neighbor_n in first_hop_set:
                continue
            clean_neighbors.append(neighbor_n)
            if neighbor_n not in discovered:
                discovered.append(neighbor_n)
        seed_summaries.append(
            {
                "assetFqn": seed_n,
                "neighborCount": len(clean_neighbors),
                "neighbors": clean_neighbors[:5],
            }
        )

    return {
        "startingAssetCount": len(first_hop_assets),
        "processedStartingAssetCount": min(len(first_hop_assets), SECOND_HOP_SEED_LIMIT),
        "uniqueNeighborCount": len(discovered),
        "neighborSamples": discovered[:SECOND_HOP_SAMPLE_LIMIT],
        "startingAssetSummaries": seed_summaries,
        "limit": {
            "startingAssets": SECOND_HOP_SEED_LIMIT,
            "neighborsPerStartingAsset": SECOND_HOP_NEIGHBOR_LIMIT,
        },
    }


def _lineage_depth_payload(
    uc: UCSQLClient,
    focus_fqn: str,
    data_graph: Dict[str, Any],
    *,
    system_uc: Optional[UCSQLClient] = None,
    include_second_hop: bool = False,
) -> Dict[str, Any]:
    """Compute first-hop asset lists (cheap — derived from the already-built
    data_graph) plus optionally the second-hop neighbor expansion.

    The two-hop expansion costs 2×SECOND_HOP_SEED_LIMIT system.access
    queries (6 upstream + 6 downstream by default), which on cold loads
    adds seconds to the primary lineage fetch. Neither the frontend nor
    any current test consumes the `lineageDepth.twoHop` payload, so we
    default to ``include_second_hop=False`` on the main build and expose
    the full expansion via a separate `/api/lineage/{fqn}/depth` endpoint
    for clients that want the richer summary.
    """

    first_hop = _first_hop_assets(data_graph)
    if not include_second_hop:
        deferred = {
            "startingAssetCount": 0,
            "processedStartingAssetCount": 0,
            "uniqueNeighborCount": 0,
            "neighborSamples": [],
            "startingAssetSummaries": [],
            "deferred": True,
            "limit": {
                "startingAssets": SECOND_HOP_SEED_LIMIT,
                "neighborsPerStartingAsset": SECOND_HOP_NEIGHBOR_LIMIT,
            },
        }
        return {
            "oneHop": first_hop,
            "twoHop": {
                "upstream": deferred,
                "downstream": dict(deferred),
            },
        }

    upstream_second_hop = _second_hop_payload(
        uc,
        focus_fqn,
        first_hop.get("upstream", []),
        direction="upstream",
        system_uc=system_uc,
    )
    downstream_second_hop = _second_hop_payload(
        uc,
        focus_fqn,
        first_hop.get("downstream", []),
        direction="downstream",
        system_uc=system_uc,
    )
    return {
        "oneHop": first_hop,
        "twoHop": {
            "upstream": upstream_second_hop,
            "downstream": downstream_second_hop,
        },
    }


def build_data_graph(
    uc: UCSQLClient,
    store: Any,
    asset_fqn: str,
    *,
    system_uc: Optional[UCSQLClient] = None,
) -> Dict[str, Any]:
    row, visible_inventory, direct_openable_assets = _focus_lineage_inventory(uc, asset_fqn)
    focus = graph_node_for_asset(
        uc,
        store,
        asset_fqn,
        "focus",
        50,
        50,
        kicker="Focus",
        kind=asset_service.friendly_table_type(
            row.get("table_type"),
            row.get("data_source_format"),
        ),
        foot=[asset_service.normalize_str(row.get("certification")) or "Unassigned"],
        depth=0,
        visible_inventory=visible_inventory,
        include_columns=True,
        direct_openable_assets=direct_openable_assets,
    )
    per_branch_limit = max(8, LINEAGE_GRAPH_NODE_LIMIT // 2)
    with ThreadPoolExecutor(max_workers=2) as executor:
        upstream_future = executor.submit(
            _recursive_branch_graph,
            uc,
            store,
            asset_fqn,
            direction="upstream",
            depth_limit=LINEAGE_GRAPH_DEPTH_LIMIT,
            node_limit=per_branch_limit,
            per_hop_limit=LINEAGE_GRAPH_PER_HOP_LIMIT,
            visible_inventory=visible_inventory,
            system_uc=system_uc,
            secondary_seed_limit=LINEAGE_GRAPH_SECONDARY_SEED_LIMIT,
            direct_openable_assets=direct_openable_assets,
        )
        downstream_future = executor.submit(
            _recursive_branch_graph,
            uc,
            store,
            asset_fqn,
            direction="downstream",
            depth_limit=LINEAGE_GRAPH_DEPTH_LIMIT,
            node_limit=per_branch_limit,
            per_hop_limit=LINEAGE_GRAPH_PER_HOP_LIMIT,
            visible_inventory=visible_inventory,
            system_uc=system_uc,
            secondary_seed_limit=0,
            direct_openable_assets=direct_openable_assets,
        )
        upstream_branch = upstream_future.result()
        downstream_branch = downstream_future.result()

    nodes = [focus, *upstream_branch["nodes"], *downstream_branch["nodes"]]
    edges = [*upstream_branch["edges"], *downstream_branch["edges"]]

    # Honesty accounting (audit P0/P1):
    # - lineageQueryFailed: at least one direction's warehouse query FAILED
    #   (degraded build) — must never be presented, or cached, as an
    #   authoritative empty graph.
    # - truncation: exact "showing N of M" counts. Totals come from
    #   seed_total_edges in the batched SQL, so they are honest even when
    #   the per-seed cap truncated the result (e.g. 20 of 659 for
    #   main.datapact.run_history). Totals count DISTINCT partner tables
    #   per direction — the SQL collapses entity-type churn so a partner
    #   recorded under several source_type/target_type values counts once
    #   (false-truncation fix, adversarial verify P1); a partner appearing
    #   both upstream and downstream still counts once per direction.
    query_failed = bool(upstream_branch.get("queryFailed")) or bool(
        downstream_branch.get("queryFailed")
    )
    upstream_total = int(upstream_branch.get("focusNeighborTotal") or 0)
    downstream_total = int(downstream_branch.get("focusNeighborTotal") or 0)
    nodes_shown = len(nodes)
    edges_shown = len(edges)
    edges_total = max(edges_shown, upstream_total + downstream_total)
    nodes_total = max(nodes_shown, 1 + upstream_total + downstream_total)
    if not edges_shown:
        # Distinguish the three empty-ish cases the frontend renders:
        # build failure vs Unity Catalog truly having no rows.
        empty_reason = "lineage-query-failed" if query_failed else "no-lineage-rows"
    else:
        empty_reason = ""

    return {
        "nodes": nodes,
        "edges": edges,
        "meta": {
            "lineageQueryFailed": query_failed,
            "emptyReason": empty_reason,
            "truncation": {
                "nodesShown": nodes_shown,
                "nodesTotal": nodes_total,
                "edgesShown": edges_shown,
                "edgesTotal": edges_total,
            },
            "upstreamLimit": TABLE_LINEAGE_LIMIT,
            "downstreamLimit": TABLE_LINEAGE_LIMIT,
            "graphDepthLimit": LINEAGE_GRAPH_DEPTH_LIMIT,
            "graphNodeLimit": LINEAGE_GRAPH_NODE_LIMIT,
            "graphBranchNodeLimit": per_branch_limit,
            "graphPerHopLimit": LINEAGE_GRAPH_PER_HOP_LIMIT,
            "graphSecondarySeedLimit": LINEAGE_GRAPH_SECONDARY_SEED_LIMIT,
            "upstreamTruncated": bool(upstream_branch.get("truncated")),
            "downstreamTruncated": bool(downstream_branch.get("truncated")),
            "lineageEvidenceSources": sorted(
                {
                    "system.access.table_lineage",
                    *(
                        [GOVERNED_LINEAGE_PROVENANCE]
                        if (
                            int(upstream_branch.get("governedLineageEvidenceTagNeighborCount") or 0)
                            + int(downstream_branch.get("governedLineageEvidenceTagNeighborCount") or 0)
                        )
                        else []
                    ),
                }
            ),
            "governedLineageEvidenceTagNeighborCount": (
                int(upstream_branch.get("governedLineageEvidenceTagNeighborCount") or 0)
                + int(downstream_branch.get("governedLineageEvidenceTagNeighborCount") or 0)
            ),
        },
    }


def _peek_cached_visible_inventory(uc: UCSQLClient) -> Optional[pd.DataFrame]:
    """Return the already-cached visible inventory, or None — never scans.

    L4: the initial lineage profile must stay cheap (no inventory scans),
    but when the inventory is ALREADY warm in either TTL cache we can
    resolve the focus asset's identity for free instead of rendering the
    focus card as an anonymous "Lineage Reference / Metadata unavailable"
    stub on every cold lineage cache. Only peeks — a cache miss returns
    None and the caller emits an explicit loading state.
    """
    now = time.time()
    for cache, key in (
        # assets.inventory() cache — the same frame visible_assets() serves.
        (asset_service._TTL_CACHE, f"inventory:{asset_service._warehouse_key(uc)}"),
        # live_metadata.cached_asset_inventory() cache — warmed by bootstrap.
        (metadata_service._TTL_CACHE, f"asset_inventory:{metadata_service._warehouse_key(uc)}"),
    ):
        try:
            cached = cache.get(key)
            if not cached:
                continue
            fetched_at, payload = cached[0], cached[1]
            if not isinstance(payload, pd.DataFrame) or payload.empty:
                continue
            if now - fetched_at >= 600:
                continue
            visible = asset_service.visible_assets(payload)
            if isinstance(visible, pd.DataFrame) and not visible.empty:
                return visible
        except Exception:
            continue
    return None


def build_initial_data_graph(
    uc: UCSQLClient,
    store: Any,
    asset_fqn: str,
) -> Dict[str, Any]:
    """Return a bounded first-paint graph shell without system lineage scans.

    The initial profile exists to unblock the page while cold
    system.access.table_lineage queries hydrate in the full profile. It must
    not call upstream/downstream lineage APIs, visible inventory scans, column
    previews, or operational context. When the visible inventory is already
    cached we resolve the focus identity from it (free); otherwise the focus
    renders as an explicit LOADING state — never "Metadata unavailable" — so
    the frontend can show honest hydration instead of a false negative.
    """

    normalized_fqn = asset_service.normalize_str(asset_fqn)
    try:
        catalog, schema, table = asset_service.split_uc_name(normalized_fqn)
    except ValueError:
        catalog, schema, table = "", "", normalized_fqn.split(".")[-1] or normalized_fqn

    cached_inventory = _peek_cached_visible_inventory(uc)
    if cached_inventory is not None and asset_service.asset_is_visible(
        cached_inventory, normalized_fqn
    ):
        # Warm-inventory path: full identity resolution at zero extra cost.
        row = asset_service.inventory_row(cached_inventory, normalized_fqn)
        focus = graph_node_for_asset(
            uc,
            store,
            normalized_fqn,
            "focus",
            50,
            50,
            kicker="Focus",
            kind=asset_service.friendly_table_type(
                row.get("table_type"),
                row.get("data_source_format"),
            ),
            foot=[asset_service.normalize_str(row.get("certification")) or "Unassigned"],
            depth=0,
            visible_inventory=cached_inventory,
            include_columns=False,
            direct_openable_assets={normalized_fqn},
        )
    else:
        # Cold-cache path: identity is genuinely unknown RIGHT NOW but the
        # full profile is already hydrating in the background. Emit a
        # loading-state focus (openabilityState "loading", foot "Loading
        # metadata…") rather than routing through graph_node_for_asset,
        # which would mislabel the focus as a non-openable "Lineage
        # Reference" with unavailable metadata — the L4 defect.
        focus = {
            "id": f"focus-{normalized_fqn}",
            "assetFqn": normalized_fqn,
            "label": table or normalized_fqn.split(".")[-1],
            "subtitle": " / ".join(part for part in [catalog, schema] if part),
            "kicker": "Focus",
            "kind": "",
            "role": "focus",
            "depth": 0,
            "x": 50,
            "y": 50,
            "foot": ["Loading metadata…"],
            "columns": [],
            "details": {
                "fqn": normalized_fqn,
                "description": "Asset metadata is hydrating from live Unity Catalog inventory.",
                "governanceStatus": "",
                "domain": "",
                "tier": "",
                "certification": "",
                "sensitivity": "",
                # The user navigated here; the full profile / destination
                # page surfaces the truth. Do not block clicks on a
                # not-yet-resolved identity (bootstrap-pessimism rule).
                "isOpenable": True,
                "openabilityState": "loading",
                "resolutionState": "loading",
            },
        }
    return {
        "nodes": [focus],
        "edges": [],
        "meta": {
            "profile": LINEAGE_PROFILE_INITIAL,
            "tableLineageDeferred": True,
            "deferred": True,
            "reason": "Table-lineage topology loads in the full lineage profile.",
            "upstreamLimit": TABLE_LINEAGE_LIMIT,
            "downstreamLimit": TABLE_LINEAGE_LIMIT,
            "graphDepthLimit": LINEAGE_GRAPH_DEPTH_LIMIT,
            "graphNodeLimit": LINEAGE_GRAPH_NODE_LIMIT,
            "graphBranchNodeLimit": max(8, LINEAGE_GRAPH_NODE_LIMIT // 2),
            "graphPerHopLimit": LINEAGE_GRAPH_PER_HOP_LIMIT,
            "upstreamTruncated": False,
            "downstreamTruncated": False,
        },
    }


def build_operational_graph(
    uc: UCSQLClient,
    store: Any,
    asset_fqn: str,
    *,
    system_uc: Optional[UCSQLClient] = None,
) -> Dict[str, Any]:
    system_client = system_uc or uc
    row, visible_inventory, direct_openable_assets = _focus_lineage_inventory(uc, asset_fqn)
    catalog, schema, table = asset_service.split_uc_name(
        asset_service.normalize_str(row.get("fqn"))
    )
    focus = graph_node_for_asset(
        uc,
        store,
        asset_fqn,
        "focus",
        50,
        48,
        kicker="Focus",
        kind=asset_service.friendly_table_type(
            row.get("table_type"),
            row.get("data_source_format"),
        ),
        foot=["Operational center"],
        depth=0,
        visible_inventory=visible_inventory,
        include_columns=True,
        direct_openable_assets=direct_openable_assets,
    )
    def load_upstream() -> pd.DataFrame:
        try:
            return metadata_service.enrich_operational_context_names(
                uc,
                system_client.get_operational_context_upstream(
                    catalog,
                    schema,
                    table,
                    limit=OPERATIONAL_CONTEXT_LIMIT,
                ),
            )
        except Exception:
            return pd.DataFrame()

    def load_downstream() -> pd.DataFrame:
        try:
            return metadata_service.enrich_operational_context_names(
                uc,
                system_client.get_operational_context_downstream(
                    catalog,
                    schema,
                    table,
                    limit=OPERATIONAL_CONTEXT_LIMIT,
                ),
            )
        except Exception:
            return pd.DataFrame()

    with ThreadPoolExecutor(max_workers=2) as executor:
        upstream_future = executor.submit(load_upstream)
        downstream_future = executor.submit(load_downstream)
        upstream_df = upstream_future.result()
        downstream_df = downstream_future.result()
    upstream_entities = asset_service.operational_entity_records(uc, upstream_df)
    downstream_entities = asset_service.operational_entity_records(uc, downstream_df)
    if not upstream_entities:
        upstream_entities = _governed_operational_job_entities(uc, asset_fqn, role="source")
    if not downstream_entities:
        downstream_entities = _governed_operational_job_entities(uc, asset_fqn, role="target")

    nodes = [focus]
    edges: List[Dict[str, Any]] = []

    for idx, (x, y) in enumerate(stack_positions(len(upstream_entities), x=21)):
        entity = upstream_entities[idx]
        node = {
            "id": f"op-up-{idx + 1}",
            "label": entity["name"],
            "subtitle": entity.get("statementId") or entity.get("entityId") or "Operational producer",
            "kicker": entity["entityLabel"],
            "kind": entity["entityLabel"],
            "role": "source",
            "depth": 1,
            "x": x,
            "y": y,
            "foot": [f"{len(entity.get('relatedAssets', []))} related asset(s)"],
            "details": [entity],
        }
        nodes.append(node)
        edges.append(
            {
                "source": node["id"],
                "target": focus["id"],
                "depth": 1,
                "key": _operational_edge_key(node["id"], focus["id"]),
            }
        )

    for idx, (x, y) in enumerate(stack_positions(len(downstream_entities), x=79)):
        entity = downstream_entities[idx]
        node = {
            "id": f"op-down-{idx + 1}",
            "label": entity["name"],
            "subtitle": entity.get("statementId") or entity.get("entityId") or "Operational consumer",
            "kicker": entity["entityLabel"],
            "kind": entity["entityLabel"],
            "role": "target",
            "depth": 1,
            "x": x,
            "y": y,
            "foot": [f"{len(entity.get('relatedAssets', []))} related asset(s)"],
            "details": [entity],
        }
        nodes.append(node)
        edges.append(
            {
                "source": focus["id"],
                "target": node["id"],
                "depth": 1,
                "key": _operational_edge_key(focus["id"], node["id"]),
            }
        )

    return {
        "nodes": nodes,
        "edges": edges,
        "meta": {
            "producerLimit": OPERATIONAL_CONTEXT_LIMIT,
            "consumerLimit": OPERATIONAL_CONTEXT_LIMIT,
            "producerTruncated": bool(
                upstream_df is not None and len(upstream_df.index) >= OPERATIONAL_CONTEXT_LIMIT
            ),
            "consumerTruncated": bool(
                downstream_df is not None and len(downstream_df.index) >= OPERATIONAL_CONTEXT_LIMIT
            ),
        },
    }


# Successful builds cache for 5 minutes; degraded builds (a lineage query
# failed mid-build) only for 15 seconds. The 15s floor exists purely to
# avoid hammering a struggling warehouse — a degraded payload must never
# pin the "0 edges" failure for the full 300s TTL (the audited P0: failed
# builds were cached 300s and served as state=available/authoritative).
LINEAGE_CACHE_TTL_S = 300
LINEAGE_DEGRADED_CACHE_TTL_S = 15


def _payload_build_degraded(payload: Any) -> bool:
    try:
        return (
            asset_service.normalize_str(payload.get("buildState")).lower() == "degraded"
        )
    except Exception:
        return False


def _payload_cache_ttl_s(payload: Any, ttl_s: int) -> int:
    return (
        min(int(ttl_s), LINEAGE_DEGRADED_CACHE_TTL_S)
        if _payload_build_degraded(payload)
        else int(ttl_s)
    )


def lineage_payload(
    uc: UCSQLClient,
    store: Any,
    asset_fqn: str,
    *,
    cache_scope: str = "",
    system_uc: Optional[UCSQLClient] = None,
    profile: str = LINEAGE_PROFILE_FULL,
) -> Dict[str, Any]:
    profile_name = _lineage_profile(profile)
    cache_key = lineage_cache_key(uc, asset_fqn, cache_scope=cache_scope, profile=profile_name)

    def _fresh(cached: Optional[Tuple[float, Any]]) -> Optional[Dict[str, Any]]:
        # Degraded builds intentionally expire after ~15s (see TTL comment
        # above) so a transient warehouse failure retries quickly instead
        # of serving a fake-empty graph for 5 minutes.
        if not cached:
            return None
        ttl = _payload_cache_ttl_s(cached[1], LINEAGE_CACHE_TTL_S)
        if time.time() - cached[0] < ttl:
            return cached[1]
        return None

    hit = _fresh(_TTL_CACHE.get(cache_key))
    if hit is not None:
        return hit
    lock = _ttl_cache_lock(cache_key)
    with lock:
        hit = _fresh(_TTL_CACHE.get(cache_key))
        if hit is not None:
            return hit
        value = _build_lineage_payload(
            uc, store, asset_fqn, system_uc=system_uc, profile=profile_name
        )
        _TTL_CACHE[cache_key] = (time.time(), value)
        return value


def lineage_cache_key(
    uc: UCSQLClient,
    asset_fqn: str,
    *,
    cache_scope: str = "",
    profile: str = LINEAGE_PROFILE_FULL,
) -> str:
    profile_name = _lineage_profile(profile)
    profile_key = "" if profile_name == LINEAGE_PROFILE_FULL else f":{profile_name}"
    return (
        f"lineage{profile_key}:{_warehouse_key(uc)}:{_cache_scope_key(cache_scope)}:"
        f"{asset_service.normalize_str(asset_fqn)}"
    )


def cached_lineage_payload(
    uc: UCSQLClient,
    asset_fqn: str,
    *,
    cache_scope: str = "",
    profile: str = LINEAGE_PROFILE_FULL,
    ttl_s: int = 300,
) -> Optional[Dict[str, Any]]:
    cache_key = lineage_cache_key(uc, asset_fqn, cache_scope=cache_scope, profile=profile)
    cached = _TTL_CACHE.get(cache_key)
    # Degraded builds are only fresh for ~15s — same policy as
    # lineage_payload — so the API peek never resurrects a stale failure.
    if cached and time.time() - cached[0] < _payload_cache_ttl_s(cached[1], ttl_s):
        return cached[1]
    return None


def _build_lineage_payload(
    uc: UCSQLClient,
    store: Any,
    asset_fqn: str,
    *,
    system_uc: Optional[UCSQLClient] = None,
    profile: str = LINEAGE_PROFILE_FULL,
) -> Dict[str, Any]:
    profile_name = _lineage_profile(profile)
    # Data graph, operational graph, and column lineage are independent
    # network-bound SQL paths. Running them concurrently cuts cold-load
    # wall time roughly 3x vs. the old sequential build.
    if profile_name == LINEAGE_PROFILE_INITIAL:
        data_graph = build_initial_data_graph(uc, store, asset_fqn)
        operational_graph = {
            "nodes": [],
            "edges": [],
            "meta": {
                "deferred": True,
                "profile": LINEAGE_PROFILE_INITIAL,
                "reason": "Operational context loads in the full lineage profile.",
            },
        }
        column_lineage = {
            "upstream": [],
            "downstream": [],
            "meta": {
                "limit": COLUMN_LINEAGE_LIMIT,
                "truncated": False,
                "deferred": True,
                "profile": LINEAGE_PROFILE_INITIAL,
                "reason": "Column lineage loads in the full lineage profile.",
            },
        }
    else:
        with ThreadPoolExecutor(max_workers=3) as executor:
            data_future = executor.submit(
                build_data_graph, uc, store, asset_fqn, system_uc=system_uc
            )
            operational_future = executor.submit(
                build_operational_graph, uc, store, asset_fqn, system_uc=system_uc
            )
            column_future = executor.submit(
                _column_lineage_payload, uc, asset_fqn, system_uc=system_uc
            )
            data_graph = data_future.result()
            operational_graph = operational_future.result()
            column_lineage = column_future.result()
    lineage_depth = _lineage_depth_payload(uc, asset_fqn, data_graph, system_uc=system_uc)
    data_edge_details = _data_edge_details(data_graph, column_lineage)
    operational_edge_details = _operational_edge_details(operational_graph)
    direction_counts = _lineage_graph_direction_counts(data_graph)

    # buildState/buildWarnings tell the API layer (and the cache policy)
    # whether this build is trustworthy. A failed table-lineage query is a
    # DEGRADED build: it must surface state="degraded" + a warning, never
    # an authoritative empty graph, and it only gets a short cache TTL so
    # the next request retries instead of pinning the failure for 300s.
    build_failed = bool((data_graph.get("meta") or {}).get("lineageQueryFailed"))
    build_state = "degraded" if build_failed else "ok"
    build_warnings = (
        ["Lineage query failed; showing cached/partial data."] if build_failed else []
    )

    return {
        "fqn": asset_fqn,
        "profile": profile_name,
        "buildState": build_state,
        "buildWarnings": build_warnings,
        "generatedAt": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
        "graphs": {
            "data": data_graph,
            "operational": operational_graph,
        },
        "columnLineage": column_lineage,
        "lineageDepth": lineage_depth,
        "edgeDetails": {
            **data_edge_details,
            **operational_edge_details,
        },
        "stats": {
            "upstreamCount": direction_counts["upstream"],
            "downstreamCount": direction_counts["downstream"],
            "directUpstreamCount": direction_counts["directUpstream"],
            "directDownstreamCount": direction_counts["directDownstream"],
            "operationalProducerCount": sum(
                1 for node in operational_graph.get("nodes", []) if node.get("role") == "source"
            ),
            "operationalConsumerCount": sum(
                1 for node in operational_graph.get("nodes", []) if node.get("role") == "target"
            ),
            "generatedAt": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
            "limits": {
                "tableLineage": TABLE_LINEAGE_LIMIT,
                "columnLineage": COLUMN_LINEAGE_LIMIT,
                "operationalContext": OPERATIONAL_CONTEXT_LIMIT,
                "secondHopSeedAssets": SECOND_HOP_SEED_LIMIT,
                "secondHopNeighborsPerSeed": SECOND_HOP_NEIGHBOR_LIMIT,
                "graphDepth": LINEAGE_GRAPH_DEPTH_LIMIT,
                "graphNodes": LINEAGE_GRAPH_NODE_LIMIT,
                "graphNeighborsPerHop": LINEAGE_GRAPH_PER_HOP_LIMIT,
                "graphSecondarySeedAssets": LINEAGE_GRAPH_SECONDARY_SEED_LIMIT,
            },
            "truncated": {
                "upstream": bool(data_graph.get("meta", {}).get("upstreamTruncated")),
                "downstream": bool(data_graph.get("meta", {}).get("downstreamTruncated")),
                "columnLineage": bool(column_lineage.get("meta", {}).get("truncated")),
                "operationalProducers": bool(operational_graph.get("meta", {}).get("producerTruncated")),
                "operationalConsumers": bool(operational_graph.get("meta", {}).get("consumerTruncated")),
            },
            "progressive": {
                "profile": profile_name,
                "fullProfileAvailable": profile_name == LINEAGE_PROFILE_INITIAL,
                "tableLineageDeferred": bool(data_graph.get("meta", {}).get("tableLineageDeferred")),
                "operationalDeferred": bool(operational_graph.get("meta", {}).get("deferred")),
                "columnLineageDeferred": bool(column_lineage.get("meta", {}).get("deferred")),
            },
            "depth": {
                "oneHopUpstreamAssets": len(lineage_depth.get("oneHop", {}).get("upstream", [])),
                "oneHopDownstreamAssets": len(lineage_depth.get("oneHop", {}).get("downstream", [])),
                "twoHopUpstreamAssets": int(
                    lineage_depth.get("twoHop", {}).get("upstream", {}).get("uniqueNeighborCount", 0)
                ),
                "twoHopDownstreamAssets": int(
                    lineage_depth.get("twoHop", {}).get("downstream", {}).get("uniqueNeighborCount", 0)
                ),
            },
        },
    }


# -----------------------------------------------------------------------------
# Phase 9 — multi-hop column lineage
# -----------------------------------------------------------------------------


COLUMN_LINEAGE_HOP_LIMIT = 4
COLUMN_LINEAGE_MAX_NODES = 64
COLUMN_LINEAGE_PER_HOP_FANOUT = 8


def trace_multi_hop_column_lineage(
    *,
    asset_fqn: str,
    column_name: str,
    direction: str,
    depth: int,
    fetch_neighbors: Callable[[str, str], List[Dict[str, str]]],
    hop_limit: int = COLUMN_LINEAGE_HOP_LIMIT,
    per_hop_fanout: int = COLUMN_LINEAGE_PER_HOP_FANOUT,
    max_nodes: int = COLUMN_LINEAGE_MAX_NODES,
) -> Dict[str, Any]:
    """Walk column lineage depth-first with bounded fan-out + node budget.

    `fetch_neighbors(asset_fqn, column_name)` returns a list of
    {assetFqn, column} dicts representing neighbours in the given
    direction. The traversal is direction-specific — the caller picks
    upstream vs downstream and wires the right callback.

    Returns:
        {
            "nodes": [ { "id", "assetFqn", "column", "depth" }, ... ],
            "edges": [ { "source", "target", "depth" }, ... ],
            "meta": { "direction", "depthLimit", "truncated", "reason" }
        }

    Pure function — the fetch callback is the only I/O and is supplied
    by the router. That keeps this unit-testable and the production
    shape injectable against live UC or a mock.
    """
    direction_norm = (direction or "").strip().lower()
    if direction_norm not in ("upstream", "downstream"):
        raise ValueError("direction must be 'upstream' or 'downstream'")
    depth_requested = max(1, min(int(depth or 1), hop_limit))

    root_id = f"{asset_fqn}#{column_name}"
    nodes: Dict[str, Dict[str, Any]] = {
        root_id: {
            "id": root_id,
            "assetFqn": asset_fqn,
            "column": column_name,
            "depth": 0,
        }
    }
    edges: List[Dict[str, Any]] = []
    seen_edges: Set[Tuple[str, str]] = set()
    truncated = False
    truncation_reason: Optional[str] = None

    frontier: Deque[Tuple[str, str, int]] = deque([(asset_fqn, column_name, 0)])
    while frontier:
        current_asset, current_column, current_depth = frontier.popleft()
        if current_depth >= depth_requested:
            continue
        try:
            neighbors = fetch_neighbors(current_asset, current_column) or []
        except Exception:
            neighbors = []
        if len(neighbors) > per_hop_fanout:
            truncated = True
            truncation_reason = truncation_reason or "per-hop fanout cap"
            neighbors = neighbors[:per_hop_fanout]
        current_id = f"{current_asset}#{current_column}"
        for neighbor in neighbors:
            neighbor_asset = asset_service.normalize_str(neighbor.get("assetFqn"))
            neighbor_column = asset_service.normalize_str(neighbor.get("column"))
            if not neighbor_asset or not neighbor_column:
                continue
            neighbor_id = f"{neighbor_asset}#{neighbor_column}"
            if neighbor_id not in nodes:
                if len(nodes) >= max_nodes:
                    truncated = True
                    truncation_reason = truncation_reason or "node budget"
                    continue
                nodes[neighbor_id] = {
                    "id": neighbor_id,
                    "assetFqn": neighbor_asset,
                    "column": neighbor_column,
                    "depth": current_depth + 1,
                }
            # Direction of the edge matches the requested direction —
            # for upstream, neighbor feeds current (neighbor -> current).
            if direction_norm == "upstream":
                edge_key = (neighbor_id, current_id)
            else:
                edge_key = (current_id, neighbor_id)
            if edge_key not in seen_edges:
                seen_edges.add(edge_key)
                edges.append(
                    {"source": edge_key[0], "target": edge_key[1], "depth": current_depth + 1}
                )
            if current_depth + 1 < depth_requested:
                frontier.append((neighbor_asset, neighbor_column, current_depth + 1))

    return {
        "nodes": list(nodes.values()),
        "edges": edges,
        "meta": {
            "direction": direction_norm,
            "depthLimit": depth_requested,
            "hopLimit": hop_limit,
            "maxNodes": max_nodes,
            "perHopFanout": per_hop_fanout,
            "truncated": bool(truncated),
            "reason": truncation_reason,
            "rootAssetFqn": asset_fqn,
            "rootColumn": column_name,
        },
    }


def build_upstream_column_fetcher(
    system_uc: UCSQLClient,
    *,
    limit_per_call: int = COLUMN_LINEAGE_LIMIT,
) -> Callable[[str, str], List[Dict[str, str]]]:
    """Return a closure that queries system.access.column_lineage for a
    single (asset, column) to its immediate upstream neighbors. The
    closure is suitable as the fetch_neighbors callback."""

    def _fetch(asset_fqn: str, column_name: str) -> List[Dict[str, str]]:
        catalog, schema, table = asset_service.split_uc_name(asset_fqn)
        if not (catalog and schema and table and column_name):
            return []
        frame = system_uc.get_column_lineage_upstream(catalog, schema, table, limit=limit_per_call)
        if frame is None or frame.empty:
            return []
        results: List[Dict[str, str]] = []
        for _, row in frame.iterrows():
            target_column = asset_service.normalize_str(row.get("target_column_name"))
            if target_column.lower() != column_name.lower():
                continue
            results.append(
                {
                    "assetFqn": asset_service.normalize_str(row.get("source_table_full_name")),
                    "column": asset_service.normalize_str(row.get("source_column_name")),
                }
            )
        return results

    return _fetch


def build_downstream_column_fetcher(
    system_uc: UCSQLClient,
    *,
    limit_per_call: int = COLUMN_LINEAGE_LIMIT,
) -> Callable[[str, str], List[Dict[str, str]]]:
    def _fetch(asset_fqn: str, column_name: str) -> List[Dict[str, str]]:
        catalog, schema, table = asset_service.split_uc_name(asset_fqn)
        if not (catalog and schema and table and column_name):
            return []
        frame = system_uc.get_column_lineage_downstream(catalog, schema, table, limit=limit_per_call)
        if frame is None or frame.empty:
            return []
        results: List[Dict[str, str]] = []
        for _, row in frame.iterrows():
            source_column = asset_service.normalize_str(row.get("source_column_name"))
            if source_column.lower() != column_name.lower():
                continue
            results.append(
                {
                    "assetFqn": asset_service.normalize_str(row.get("target_table_full_name")),
                    "column": asset_service.normalize_str(row.get("target_column_name")),
                }
            )
        return results

    return _fetch
