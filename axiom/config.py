from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List


def _split_csv(value: str) -> List[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


def _env_value(name: str) -> str:
    return os.getenv(name, "").strip()


def _normalize_workspace_host(raw: str) -> str:
    """Workspace host as an absolute https URL (no trailing slash).

    DATABRICKS_HOST may arrive schemeless (``dbc-xxx.cloud.databricks.com``).
    Every deep link built from it (`{host}/jobs/<id>`, `/sql/warehouses/<id>`)
    must be absolute or the browser resolves it relative to the Axiom app
    origin and 404s — that was the dead "Open" job run-link. Prepend https://
    when no scheme is present.
    """
    host = (raw or "").strip().rstrip("/")
    if not host:
        return ""
    if not host.startswith(("http://", "https://")):
        host = f"https://{host}"
    return host


def _env_optional(name: str) -> str:
    value = _env_value(name)
    return "" if value.lower() in {"not-configured", "__not_configured__", "none", "null"} else value


def _env_bool(name: str, default: bool = False) -> bool:
    raw = _env_value(name).lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = _env_value(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def ai_features_enabled_from_env() -> bool:
    """The AI extension flag, readable before AppConfig exists: routers are
    registered at import time, when the full config may not load yet."""
    return _env_bool("AXIOM_AI_FEATURES_ENABLED", False)


@dataclass(frozen=True)
class AppConfig:
    # Databricks / Unity Catalog
    warehouse_id: str
    gov_catalog: str
    gov_schema: str

    # Bootstrap admins (optional)
    admin_emails: List[str] = field(default_factory=list)
    build_id: str = ""
    diagnostics_enabled: bool = True
    slow_request_ms: int = 1500
    # Governance-schema DDL at startup: auto (run only when the schema
    # fingerprint is stale), verify (never run DDL; the axiom_schema_migrate
    # job owns it), or off.
    schema_bootstrap: str = "auto"
    environment_label: str = ""
    deploy_target: str = ""
    workspace_host: str = ""
    genie_space_id: str = ""
    genie_space_title: str = ""
    axiom_ai_provider: str = "local"
    axiom_ai_require_benchmark: bool = False
    # Foundation-model serving endpoint for generative/agentic features (AI
    # autofill, draft copy). Set via AXIOM_AI_GENERATION_ENDPOINT (default lives
    # in databricks.yml / app.yaml, not here); empty disables it.
    ai_generation_endpoint: str = ""
    lakebase_enabled: bool = False
    lakebase_endpoint_name: str = ""
    lakebase_schema: str = ""
    lakebase_uc_catalog: str = ""
    # emet integration (see axiom/services/emet.py). The catalog is the
    # one thing GA cannot know a priori — emet records it in a shared
    # workspace pointer file, but a baked env var makes detection deterministic
    # and skips a workspace-file read on the bootstrap hot path. Empty catalog
    # means "auto-discover from the pointer file at request time". The schema is
    # the emet managed-schema constant ("emet") unless overridden.
    emet_enabled: bool = True
    emet_catalog: str = ""
    emet_schema: str = "emet"
    # AI governance extension (docs/ai_extension/DESIGN.md section 12). Off by
    # default: when false no /api/ai routes register and the rail entry hides.
    ai_features_enabled: bool = False
    ai_intake_tag_key: str = "edw_intake_id"
    ai_tier_tag_key: str = "ai_risk_tier"
    # Empty catalog allowlist means "use discovery catalogs" (resolved by the
    # collector, not here, so config stays a plain reflection of env).
    ai_catalog_allowlist: List[str] = field(default_factory=list)
    ai_tool_schema_allowlist: List[str] = field(default_factory=list)
    ai_intake_grace_days: int = 30

    @staticmethod
    def from_env() -> "AppConfig":
        warehouse_id = os.getenv("DATABRICKS_WAREHOUSE_ID", "").strip()
        gov_catalog = _env_value("AXIOM_CATALOG")
        gov_schema = _env_value("AXIOM_SCHEMA")
        if not warehouse_id:
            raise ValueError(
                "Missing required env var DATABRICKS_WAREHOUSE_ID. "
                "Set this in app.yaml to your SQL Warehouse ID."
            )
        if not gov_catalog:
            raise ValueError(
                "Missing required env var AXIOM_CATALOG. "
                "Inject the governance catalog explicitly per deployment target."
            )
        if not gov_schema:
            raise ValueError(
                "Missing required env var AXIOM_SCHEMA. "
                "Inject the governance schema explicitly per deployment target."
            )
        return AppConfig(
            warehouse_id=warehouse_id,
            gov_catalog=gov_catalog,
            gov_schema=gov_schema,
            admin_emails=_split_csv(_env_value("AXIOM_ADMIN_EMAILS")),
            build_id=_env_value("AXIOM_BUILD_ID"),
            diagnostics_enabled=_env_bool("AXIOM_DIAGNOSTICS_ENABLED", True),
            slow_request_ms=_env_int("AXIOM_SLOW_REQUEST_MS", 1500),
            environment_label=_env_value("AXIOM_ENVIRONMENT_LABEL"),
            deploy_target=_env_value("AXIOM_DEPLOY_TARGET"),
            workspace_host=_normalize_workspace_host(_env_value("DATABRICKS_HOST")),
            genie_space_id=_env_optional("AXIOM_GENIE_SPACE_ID")
            or _env_optional("GENIE_SPACE_ID"),
            genie_space_title=_env_optional("AXIOM_GENIE_SPACE_TITLE")
            or "Axiom Metadata Room",
            axiom_ai_provider=(
                _env_value("AXIOM_AI_PROVIDER").lower()
                or ("genie" if (_env_optional("AXIOM_GENIE_SPACE_ID") or _env_optional("GENIE_SPACE_ID")) else "local")
            ),
            axiom_ai_require_benchmark=_env_bool("AXIOM_AI_REQUIRE_BENCHMARK", False),
            ai_generation_endpoint=(
                _env_optional("AXIOM_AI_GENERATION_ENDPOINT") or ""
            ),
            lakebase_enabled=_env_bool("AXIOM_LAKEBASE_ENABLED", False),
            lakebase_endpoint_name=_env_optional("AXIOM_LAKEBASE_ENDPOINT_NAME")
            or _env_optional("POSTGRES_ENDPOINT_NAME")
            or _env_optional("ENDPOINT_NAME"),
            lakebase_schema=_env_optional("AXIOM_LAKEBASE_SCHEMA") or "axiom_app",
            lakebase_uc_catalog=_env_optional("AXIOM_LAKEBASE_UC_CATALOG"),
            schema_bootstrap=(_env_optional("AXIOM_SCHEMA_BOOTSTRAP") or "auto").strip().lower(),
            emet_enabled=_env_bool("AXIOM_emet_ENABLED", True),
            emet_catalog=_env_optional("AXIOM_EMET_CATALOG"),
            emet_schema=_env_optional("AXIOM_emet_SCHEMA") or "emet",
            ai_features_enabled=ai_features_enabled_from_env(),
            ai_intake_tag_key=_env_optional("AXIOM_AI_INTAKE_TAG_KEY") or "edw_intake_id",
            ai_tier_tag_key=_env_optional("AXIOM_AI_TIER_TAG_KEY") or "ai_risk_tier",
            ai_catalog_allowlist=_split_csv(_env_optional("AXIOM_AI_CATALOG_ALLOWLIST")),
            ai_tool_schema_allowlist=_split_csv(_env_optional("AXIOM_AI_TOOL_SCHEMA_ALLOWLIST")),
            ai_intake_grace_days=max(0, _env_int("AXIOM_AI_INTAKE_GRACE_DAYS", 30)),
        )
