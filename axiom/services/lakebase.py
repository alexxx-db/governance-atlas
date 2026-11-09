from __future__ import annotations

import atexit
import os
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Iterator

import pandas as pd

from axiom.config import AppConfig


LAKEBASE_OPERATIONAL_TABLES: tuple[str, ...] = (
    "user_roles",
    "user_profiles",
    "identity_directory_entries",
    "identity_directory_memberships",
    "entity_registry",
    "entity_aliases",
    "data_owners",
    "glossaries",
    "glossary_terms",
    "glossary_term_reviewers",
    "glossary_term_links",
    "threads",
    "thread_posts",
    "tasks",
    "activity_events",
    "notifications",
    "notification_receipts",
    "notification_preferences",
    "classification_recommendations",
    "custom_property_definitions",
    "custom_property_assignments",
    "quality_test_definitions",
    "quality_suites",
    "quality_test_cases",
    "export_jobs",
    "background_work_items",
    "background_work_runs",
    "background_dead_letters",
)

DELTA_RETAINED_TABLES: tuple[str, ...] = (
    "metadata_audit_log",
    "change_events",
    "change_event_consumers",
    "change_event_consumer_offsets",
    "entity_versions",
    "entity_relationships",
    "glossary_term_versions",
    "custom_property_definition_versions",
    "profile_runs",
    "profile_table_metrics",
    "profile_column_metrics",
    "quality_test_definition_versions",
    "quality_runs",
    "quality_run_results",
    "quality_alerts",
    "governance_queue_projection",
    "glossary_summary_projection",
    "schema_migrations",
)


@dataclass(frozen=True)
class LakebaseStatus:
    state: str
    message: str = ""
    endpoint_name: str = ""
    database: str = ""
    host: str = ""
    schema: str = ""
    uc_catalog: str = ""
    enabled: bool = False

    def as_dict(self) -> Dict[str, Any]:
        return {
            "state": self.state,
            "message": self.message,
            "endpointName": self.endpoint_name,
            "database": self.database,
            "host": self.host,
            "schema": self.schema,
            "ucCatalog": self.uc_catalog,
            "enabled": self.enabled,
            "operationalTables": list(LAKEBASE_OPERATIONAL_TABLES),
            "deltaRetainedTables": list(DELTA_RETAINED_TABLES),
        }


def _env(name: str) -> str:
    return os.getenv(name, "").strip()


def is_configured(config: AppConfig) -> bool:
    return bool(
        getattr(config, "lakebase_enabled", False)
        and (_env("PGHOST") or getattr(config, "lakebase_endpoint_name", ""))
        and _env("PGDATABASE")
        and _env("PGUSER")
    )


def status(config: AppConfig) -> Dict[str, Any]:
    endpoint_name = getattr(config, "lakebase_endpoint_name", "")
    schema = getattr(config, "lakebase_schema", "") or "axiom_app"
    uc_catalog = getattr(config, "lakebase_uc_catalog", "")
    if not getattr(config, "lakebase_enabled", False):
        return LakebaseStatus(
            state="disabled",
            message="Lakebase is not enabled for this deployment.",
            endpoint_name=endpoint_name,
            schema=schema,
            uc_catalog=uc_catalog,
            enabled=False,
        ).as_dict()
    missing = [
        name
        for name in ["PGDATABASE", "PGUSER"]
        if not _env(name)
    ]
    if not (_env("PGHOST") or endpoint_name):
        missing.append("PGHOST or AXIOM_LAKEBASE_ENDPOINT_NAME")
    if missing:
        return LakebaseStatus(
            state="unavailable",
            message=f"Lakebase is enabled but missing {', '.join(missing)}.",
            endpoint_name=endpoint_name,
            database=_env("PGDATABASE"),
            host=_env("PGHOST"),
            schema=schema,
            uc_catalog=uc_catalog,
            enabled=True,
        ).as_dict()
    return LakebaseStatus(
        state="available",
        message="Lakebase connection environment is configured.",
        endpoint_name=endpoint_name or _env("AXIOM_LAKEBASE_ENDPOINT_NAME"),
        database=_env("PGDATABASE"),
        host=_env("PGHOST"),
        schema=schema,
        uc_catalog=uc_catalog,
        enabled=True,
    ).as_dict()


def _psycopg_modules():
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:
        raise RuntimeError(
            "Lakebase support requires psycopg. Install requirements.txt before enabling AXIOM_LAKEBASE_ENABLED."
        ) from exc
    return psycopg, dict_row


def _workspace_client():
    try:
        from databricks.sdk import WorkspaceClient
    except ImportError as exc:
        raise RuntimeError("databricks-sdk is required for Lakebase OAuth credential rotation.") from exc
    from axiom.services.workspace_clients import cached_workspace_client

    return cached_workspace_client("default", "", WorkspaceClient, WorkspaceClient)


def _connection_kwargs(config: AppConfig) -> Dict[str, str]:
    host = _env("PGHOST")
    database = _env("PGDATABASE")
    user = _env("PGUSER")
    endpoint = (
        getattr(config, "lakebase_endpoint_name", "")
        or _env("AXIOM_LAKEBASE_ENDPOINT_NAME")
        or _env("ENDPOINT_NAME")
    )
    if not host or not database or not user:
        raise RuntimeError("Lakebase PGHOST, PGDATABASE, and PGUSER must be present.")
    kwargs = {
        "dbname": database,
        "user": user,
        "host": host,
        "port": _env("PGPORT") or "5432",
        "sslmode": _env("PGSSLMODE") or "require",
    }
    password = _env("PGPASSWORD")
    if password:
        kwargs["password"] = password
        return kwargs
    if not endpoint:
        raise RuntimeError("Lakebase OAuth credential rotation requires AXIOM_LAKEBASE_ENDPOINT_NAME.")
    kwargs["endpoint"] = endpoint
    return kwargs


# Lakebase OAuth tokens last one hour and are checked only at login, so a token
# is reused for new connections until shortly before it expires.
_TOKEN_TTL_S = 45 * 60
_TOKEN_LOCK = threading.Lock()
_TOKENS: Dict[str, tuple[str, float]] = {}


def _oauth_token(endpoint: str) -> str:
    with _TOKEN_LOCK:
        cached = _TOKENS.get(endpoint)
        if cached and time.monotonic() - cached[1] < _TOKEN_TTL_S:
            return cached[0]
        credential = _workspace_client().postgres.generate_database_credential(endpoint=endpoint)
        token = getattr(credential, "token", None)
        if not token:
            raise RuntimeError("Databricks did not return a Lakebase OAuth token.")
        _TOKENS[endpoint] = (token, time.monotonic())
        return token


def _resolved_connection_kwargs(config: AppConfig) -> Dict[str, str]:
    kwargs = dict(_connection_kwargs(config))
    endpoint = kwargs.pop("endpoint", None)
    if endpoint:
        kwargs["password"] = _oauth_token(endpoint)
    return kwargs


def _pool_class():
    try:
        from psycopg_pool import ConnectionPool
    except ImportError:
        return None
    return ConnectionPool


_POOL_LOCK = threading.Lock()
_POOLS: Dict[tuple, Any] = {}


def _env_int(name: str, default: int) -> int:
    try:
        return max(1, int(_env(name) or default))
    except ValueError:
        return default


def _pool_for(config: AppConfig):
    pool_class = _pool_class()
    if pool_class is None:
        return None
    kwargs = _connection_kwargs(config)
    key = tuple(sorted(kwargs.items()))
    with _POOL_LOCK:
        pool = _POOLS.get(key)
        if pool is not None:
            return pool
        psycopg, dict_row = _psycopg_modules()
        endpoint = kwargs.get("endpoint")
        connect_kwargs = {k: v for k, v in kwargs.items() if k != "endpoint"}

        class _LakebaseConnection(psycopg.Connection):
            @classmethod
            def connect(cls, conninfo: str = "", **params: Any):
                if endpoint:
                    params["password"] = _oauth_token(endpoint)
                return super().connect(conninfo, **params)

        # min_size=0 lets an idle Lakebase compute scale to zero; check= drops
        # connections the server closed while idle.
        pool = pool_class(
            conninfo="",
            kwargs={**connect_kwargs, "row_factory": dict_row},
            connection_class=_LakebaseConnection,
            min_size=0,
            max_size=_env_int("AXIOM_LAKEBASE_POOL_MAX_SIZE", 5),
            max_idle=300,
            max_lifetime=_TOKEN_TTL_S,
            timeout=15,
            check=pool_class.check_connection,
            name="axiom-lakebase",
            open=True,
        )
        _POOLS[key] = pool
        return pool


def close_pools() -> None:
    with _POOL_LOCK:
        pools = list(_POOLS.values())
        _POOLS.clear()
    for pool in pools:
        try:
            pool.close()
        except Exception:  # noqa: BLE001 - best effort at shutdown
            pass


atexit.register(close_pools)


@contextmanager
def connect(config: AppConfig) -> Iterator[Any]:
    """Yield a Lakebase connection; commits on success, rolls back on error.

    Connections come from a shared pool when psycopg_pool is installed.
    """
    pool = _pool_for(config)
    if pool is not None:
        with pool.connection() as conn:
            yield conn
        return
    psycopg, dict_row = _psycopg_modules()
    with psycopg.connect(**_resolved_connection_kwargs(config), row_factory=dict_row) as conn:
        yield conn


def _execute(conn, statement: str, params: Iterable[Any] | None = None) -> None:
    with conn.cursor() as cur:
        cur.execute(statement, tuple(params or ()))


def _pg_ident(value: str) -> str:
    return '"' + str(value or "").replace('"', '""') + '"'


def ensure_schema(config: AppConfig, *, include_upgrades: bool = True) -> Dict[str, Any]:
    if not is_configured(config):
        current = status(config)
        raise RuntimeError(current.get("message") or "Lakebase is not configured.")
    schema = getattr(config, "lakebase_schema", "") or "axiom_app"
    with connect(config) as conn:
        _execute(conn, f"CREATE SCHEMA IF NOT EXISTS {_pg_ident(schema)}")
        for statement in _operational_schema_ddl(schema):
            _execute(conn, statement)
        if include_upgrades:
            for statement in _operational_schema_upgrade_ddl(schema):
                _execute(conn, statement)
        conn.commit()
    current = status(config)
    return {**current, "createdTables": list(LAKEBASE_OPERATIONAL_TABLES)}


def probe(config: AppConfig) -> Dict[str, Any]:
    current = status(config)
    if current.get("state") != "available":
        return current
    try:
        with connect(config) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 AS ok")
                row = cur.fetchone() or {}
        return {**current, "probe": dict(row), "message": "Lakebase probe succeeded."}
    except Exception as exc:
        return {
            **current,
            "state": "degraded",
            "message": f"{exc.__class__.__name__}: {exc}",
            "errorType": exc.__class__.__name__,
        }


def table_classification() -> pd.DataFrame:
    rows = [
        {
            "table": table,
            "target": "lakebase",
            "rationale": "Mutable app-control-plane current state.",
        }
        for table in LAKEBASE_OPERATIONAL_TABLES
    ]
    rows.extend(
        {
            "table": table,
            "target": "delta_uc",
            "rationale": "Append-only, historical, analytical, or Genie-facing evidence.",
        }
        for table in DELTA_RETAINED_TABLES
    )
    return pd.DataFrame(rows)


def _operational_schema_ddl(schema: str) -> tuple[str, ...]:
    prefix = f"{_pg_ident(schema)}."
    return (
        f"""CREATE TABLE IF NOT EXISTS {prefix}"user_roles" (
            email TEXT PRIMARY KEY,
            role TEXT NOT NULL,
            updated_at TIMESTAMPTZ,
            updated_by TEXT
        )""",
        f"""CREATE TABLE IF NOT EXISTS {prefix}"user_profiles" (
            email TEXT PRIMARY KEY,
            display_name TEXT,
            avatar_url TEXT,
            preferences_json JSONB,
            updated_at TIMESTAMPTZ,
            updated_by TEXT
        )""",
        f"""CREATE TABLE IF NOT EXISTS {prefix}"identity_directory_entries" (
            entry_id TEXT PRIMARY KEY,
            external_key TEXT NOT NULL,
            principal_type TEXT NOT NULL,
            display_name TEXT,
            email TEXT,
            is_active BOOLEAN,
            source TEXT,
            attributes_json JSONB,
            synced_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ,
            created_by TEXT,
            updated_at TIMESTAMPTZ,
            updated_by TEXT,
            UNIQUE (external_key, source)
        )""",
        f"""CREATE TABLE IF NOT EXISTS {prefix}"identity_directory_memberships" (
            parent_entry_id TEXT NOT NULL,
            child_entry_id TEXT NOT NULL,
            relationship_type TEXT,
            source TEXT,
            attributes_json JSONB,
            synced_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ,
            updated_at TIMESTAMPTZ,
            PRIMARY KEY (parent_entry_id, child_entry_id)
        )""",
        f"""CREATE TABLE IF NOT EXISTS {prefix}"entity_registry" (
            entity_id TEXT PRIMARY KEY,
            entity_kind TEXT NOT NULL,
            entity_fqn TEXT,
            source_system TEXT,
            source_entity_id TEXT,
            reconciliation_state TEXT,
            reconciliation_confidence DOUBLE PRECISION,
            observed_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ,
            created_by TEXT,
            updated_at TIMESTAMPTZ,
            updated_by TEXT
        )""",
        f"""CREATE TABLE IF NOT EXISTS {prefix}"entity_aliases" (
            alias_id TEXT PRIMARY KEY,
            entity_id TEXT NOT NULL,
            alias_type TEXT NOT NULL,
            alias_value TEXT NOT NULL,
            source TEXT,
            created_at TIMESTAMPTZ,
            created_by TEXT,
            updated_at TIMESTAMPTZ,
            updated_by TEXT
        )""",
        f"""CREATE TABLE IF NOT EXISTS {prefix}"data_owners" (
            uc_full_name TEXT NOT NULL,
            owner_email TEXT NOT NULL,
            owner_type TEXT,
            updated_at TIMESTAMPTZ,
            updated_by TEXT,
            PRIMARY KEY (uc_full_name, owner_email)
        )""",
        f"""CREATE TABLE IF NOT EXISTS {prefix}"glossaries" (
            glossary_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT,
            status TEXT,
            created_at TIMESTAMPTZ,
            created_by TEXT,
            updated_at TIMESTAMPTZ,
            updated_by TEXT,
            UNIQUE (name)
        )""",
        f"""CREATE TABLE IF NOT EXISTS {prefix}"glossary_terms" (
            term_id TEXT PRIMARY KEY,
            glossary_id TEXT,
            parent_term_id TEXT,
            name TEXT NOT NULL,
            display_name TEXT,
            definition TEXT,
            synonyms_json JSONB,
            owners_json JSONB,
            domain TEXT,
            status TEXT,
            review_status TEXT,
            source TEXT,
            created_at TIMESTAMPTZ,
            created_by TEXT,
            updated_at TIMESTAMPTZ,
            updated_by TEXT
        )""",
        f"""CREATE TABLE IF NOT EXISTS {prefix}"glossary_term_reviewers" (
            term_id TEXT NOT NULL,
            reviewer_email TEXT NOT NULL,
            reviewer_type TEXT,
            updated_at TIMESTAMPTZ,
            updated_by TEXT,
            PRIMARY KEY (term_id, reviewer_email)
        )""",
        f"""CREATE TABLE IF NOT EXISTS {prefix}"glossary_term_links" (
            link_id TEXT PRIMARY KEY,
            term_id TEXT NOT NULL,
            subject_type TEXT NOT NULL,
            subject_fqn TEXT NOT NULL,
            column_name TEXT,
            link_state TEXT,
            source TEXT,
            created_at TIMESTAMPTZ,
            created_by TEXT,
            updated_at TIMESTAMPTZ,
            updated_by TEXT,
            removed_at TIMESTAMPTZ,
            removed_by TEXT
        )""",
        f"""CREATE TABLE IF NOT EXISTS {prefix}"threads" (
            thread_id TEXT PRIMARY KEY,
            entity_id TEXT,
            entity_fqn_snapshot TEXT,
            column_name TEXT,
            thread_type TEXT,
            status TEXT,
            created_by_entry_id TEXT,
            created_at TIMESTAMPTZ,
            updated_at TIMESTAMPTZ
        )""",
        f"""CREATE TABLE IF NOT EXISTS {prefix}"thread_posts" (
            post_id TEXT PRIMARY KEY,
            thread_id TEXT NOT NULL,
            body_markdown TEXT,
            diff_json JSONB,
            created_by_entry_id TEXT,
            created_at TIMESTAMPTZ,
            edited_at TIMESTAMPTZ
        )""",
        f"""CREATE TABLE IF NOT EXISTS {prefix}"tasks" (
            task_id TEXT PRIMARY KEY,
            thread_id TEXT NOT NULL,
            entity_id TEXT,
            entity_fqn_snapshot TEXT,
            column_name TEXT,
            task_type TEXT,
            diff_before_json JSONB,
            diff_after_json JSONB,
            requested_payload_json JSONB,
            assignee_entry_id TEXT,
            reviewer_entry_id TEXT,
            due_at TIMESTAMPTZ,
            status TEXT,
            resolution_code TEXT,
            resolved_payload_json JSONB,
            expected_version BIGINT,
            created_at TIMESTAMPTZ,
            updated_at TIMESTAMPTZ
        )""",
        f"""CREATE TABLE IF NOT EXISTS {prefix}"activity_events" (
            event_id TEXT PRIMARY KEY,
            event_type TEXT NOT NULL,
            entity_id TEXT,
            entity_fqn_snapshot TEXT,
            column_name TEXT,
            actor_entry_id TEXT,
            thread_id TEXT,
            task_id TEXT,
            payload_json JSONB,
            created_at TIMESTAMPTZ
        )""",
        f"""CREATE TABLE IF NOT EXISTS {prefix}"notifications" (
            notification_id TEXT PRIMARY KEY,
            event_id TEXT NOT NULL,
            channel TEXT NOT NULL,
            delivery_state TEXT,
            payload_json JSONB,
            created_at TIMESTAMPTZ,
            sent_at TIMESTAMPTZ,
            failed_at TIMESTAMPTZ,
            retry_count BIGINT
        )""",
        f"""CREATE TABLE IF NOT EXISTS {prefix}"notification_receipts" (
            notification_id TEXT NOT NULL,
            recipient_entry_id TEXT NOT NULL,
            inbox_state TEXT,
            seen_at TIMESTAMPTZ,
            read_at TIMESTAMPTZ,
            dismissed_at TIMESTAMPTZ,
            delivered_at TIMESTAMPTZ,
            PRIMARY KEY (notification_id, recipient_entry_id)
        )""",
        f"""CREATE TABLE IF NOT EXISTS {prefix}"notification_preferences" (
            entry_id TEXT NOT NULL,
            event_family TEXT NOT NULL,
            channel TEXT NOT NULL,
            muted_until TIMESTAMPTZ,
            scope_json JSONB,
            updated_at TIMESTAMPTZ,
            PRIMARY KEY (entry_id, event_family, channel)
        )""",
        f"""CREATE TABLE IF NOT EXISTS {prefix}"classification_recommendations" (
            recommendation_id TEXT PRIMARY KEY,
            asset_fqn TEXT NOT NULL,
            column_name TEXT NOT NULL,
            suggested_sensitivity TEXT,
            suggested_tier TEXT,
            suggested_certification TEXT,
            evidence_json JSONB,
            sample_redacted BOOLEAN,
            sample_values_json JSONB,
            status TEXT,
            remediation_suggestions_json JSONB,
            review_note TEXT,
            reviewed_by TEXT,
            reviewed_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ,
            created_by TEXT,
            updated_at TIMESTAMPTZ,
            updated_by TEXT
        )""",
        f"""CREATE TABLE IF NOT EXISTS {prefix}"custom_property_definitions" (
            definition_id TEXT PRIMARY KEY,
            entity_kind TEXT NOT NULL,
            property_key TEXT NOT NULL,
            display_name TEXT,
            description TEXT,
            data_type TEXT,
            enum_values_json JSONB,
            is_required BOOLEAN,
            is_multi BOOLEAN,
            scope_json JSONB,
            state TEXT,
            created_at TIMESTAMPTZ,
            created_by TEXT,
            updated_at TIMESTAMPTZ,
            updated_by TEXT,
            retired_at TIMESTAMPTZ,
            UNIQUE (entity_kind, property_key)
        )""",
        f"""CREATE TABLE IF NOT EXISTS {prefix}"custom_property_assignments" (
            assignment_id TEXT PRIMARY KEY,
            definition_id TEXT NOT NULL,
            definition_version BIGINT,
            entity_kind TEXT NOT NULL,
            entity_id TEXT,
            entity_fqn TEXT,
            column_name TEXT,
            value_json JSONB,
            source TEXT,
            created_at TIMESTAMPTZ,
            created_by TEXT,
            updated_at TIMESTAMPTZ,
            updated_by TEXT,
            removed_at TIMESTAMPTZ,
            removed_by TEXT
        )""",
        f"""CREATE TABLE IF NOT EXISTS {prefix}"quality_test_definitions" (
            definition_id TEXT PRIMARY KEY,
            entity_kind TEXT,
            entity_fqn TEXT,
            column_name TEXT,
            test_type TEXT,
            test_name TEXT,
            config_json JSONB,
            state TEXT,
            created_at TIMESTAMPTZ,
            created_by TEXT,
            updated_at TIMESTAMPTZ,
            updated_by TEXT
        )""",
        f"""CREATE TABLE IF NOT EXISTS {prefix}"quality_suites" (
            suite_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT,
            scope_json JSONB,
            state TEXT,
            created_at TIMESTAMPTZ,
            created_by TEXT,
            updated_at TIMESTAMPTZ,
            updated_by TEXT
        )""",
        f"""CREATE TABLE IF NOT EXISTS {prefix}"quality_test_cases" (
            test_case_id TEXT PRIMARY KEY,
            suite_id TEXT,
            definition_id TEXT,
            entity_kind TEXT,
            entity_fqn TEXT,
            column_name TEXT,
            config_json JSONB,
            state TEXT,
            created_at TIMESTAMPTZ,
            created_by TEXT,
            updated_at TIMESTAMPTZ,
            updated_by TEXT
        )""",
        f"""CREATE TABLE IF NOT EXISTS {prefix}"export_jobs" (
            export_id TEXT PRIMARY KEY,
            export_type TEXT NOT NULL,
            status TEXT,
            requested_by TEXT,
            request_json JSONB,
            result_json JSONB,
            error_detail TEXT,
            created_at TIMESTAMPTZ,
            updated_at TIMESTAMPTZ,
            finished_at TIMESTAMPTZ
        )""",
        f"""CREATE TABLE IF NOT EXISTS {prefix}"background_work_items" (
            work_id TEXT PRIMARY KEY,
            work_kind TEXT NOT NULL,
            priority BIGINT,
            status TEXT,
            payload_json JSONB,
            dependency_work_id TEXT,
            actor_email TEXT,
            actor_role TEXT,
            token_captured_at TIMESTAMPTZ,
            scheduled_for TIMESTAMPTZ,
            claimed_at TIMESTAMPTZ,
            claimed_by TEXT,
            started_at TIMESTAMPTZ,
            finished_at TIMESTAMPTZ,
            attempt_count BIGINT,
            max_attempts BIGINT,
            last_error TEXT,
            result_json JSONB,
            created_at TIMESTAMPTZ,
            created_by TEXT,
            updated_at TIMESTAMPTZ,
            updated_by TEXT
        )""",
        f"""CREATE TABLE IF NOT EXISTS {prefix}"background_work_runs" (
            run_id TEXT PRIMARY KEY,
            work_id TEXT NOT NULL,
            worker_id TEXT,
            status TEXT,
            started_at TIMESTAMPTZ,
            finished_at TIMESTAMPTZ,
            heartbeat_at TIMESTAMPTZ,
            result_json JSONB,
            error_detail TEXT
        )""",
        f"""CREATE TABLE IF NOT EXISTS {prefix}"background_dead_letters" (
            dead_letter_id TEXT PRIMARY KEY,
            work_id TEXT,
            work_kind TEXT,
            payload_json JSONB,
            error_detail TEXT,
            failed_at TIMESTAMPTZ,
            archived_by TEXT
        )""",
    )


def _operational_schema_upgrade_ddl(schema: str) -> tuple[str, ...]:
    prefix = f"{_pg_ident(schema)}."
    classification_table = f'{prefix}"classification_recommendations"'
    custom_property_table = f'{prefix}"custom_property_definitions"'
    return (
        f'ALTER TABLE {classification_table} ADD COLUMN IF NOT EXISTS asset_fqn TEXT',
        f'ALTER TABLE {classification_table} ADD COLUMN IF NOT EXISTS suggested_sensitivity TEXT',
        f'ALTER TABLE {classification_table} ADD COLUMN IF NOT EXISTS suggested_tier TEXT',
        f'ALTER TABLE {classification_table} ADD COLUMN IF NOT EXISTS suggested_certification TEXT',
        f'ALTER TABLE {classification_table} ADD COLUMN IF NOT EXISTS sample_redacted BOOLEAN',
        f'ALTER TABLE {classification_table} ADD COLUMN IF NOT EXISTS sample_values_json JSONB',
        f'ALTER TABLE {classification_table} ADD COLUMN IF NOT EXISTS remediation_suggestions_json JSONB',
        f'ALTER TABLE {classification_table} ADD COLUMN IF NOT EXISTS review_note TEXT',
        f'ALTER TABLE {classification_table} ADD COLUMN IF NOT EXISTS reviewed_by TEXT',
        f'ALTER TABLE {classification_table} ADD COLUMN IF NOT EXISTS reviewed_at TIMESTAMPTZ',
        f'ALTER TABLE {custom_property_table} ADD COLUMN IF NOT EXISTS retired_at TIMESTAMPTZ',
    )
