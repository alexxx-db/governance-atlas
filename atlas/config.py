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
    must be absolute or the browser resolves it relative to the Atlas app
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
    environment_label: str = ""
    deploy_target: str = ""
    workspace_host: str = ""
    genie_space_id: str = ""
    genie_space_title: str = ""
    atlas_ai_provider: str = "local"
    atlas_ai_require_benchmark: bool = False
    # Foundation-model serving endpoint for generative/agentic features (AI
    # autofill, draft copy). Set via GOVAT_AI_GENERATION_ENDPOINT (default lives
    # in databricks.yml / app.yaml, not here); empty disables it.
    ai_generation_endpoint: str = ""
    lakebase_enabled: bool = False
    lakebase_endpoint_name: str = ""
    lakebase_schema: str = ""
    lakebase_uc_catalog: str = ""
    # DataPact integration (see atlas/services/datapact.py). The catalog is the
    # one thing GA cannot know a priori — DataPact records it in a shared
    # workspace pointer file, but a baked env var makes detection deterministic
    # and skips a workspace-file read on the bootstrap hot path. Empty catalog
    # means "auto-discover from the pointer file at request time". The schema is
    # the DataPact managed-schema constant ("datapact") unless overridden.
    datapact_enabled: bool = True
    datapact_catalog: str = ""
    datapact_schema: str = "datapact"

    @staticmethod
    def from_env() -> "AppConfig":
        warehouse_id = os.getenv("DATABRICKS_WAREHOUSE_ID", "").strip()
        gov_catalog = _env_value("GOVAT_CATALOG")
        gov_schema = _env_value("GOVAT_SCHEMA")
        if not warehouse_id:
            raise ValueError(
                "Missing required env var DATABRICKS_WAREHOUSE_ID. "
                "Set this in app.yaml to your SQL Warehouse ID."
            )
        if not gov_catalog:
            raise ValueError(
                "Missing required env var GOVAT_CATALOG. "
                "Inject the governance catalog explicitly per deployment target."
            )
        if not gov_schema:
            raise ValueError(
                "Missing required env var GOVAT_SCHEMA. "
                "Inject the governance schema explicitly per deployment target."
            )
        return AppConfig(
            warehouse_id=warehouse_id,
            gov_catalog=gov_catalog,
            gov_schema=gov_schema,
            admin_emails=_split_csv(_env_value("GOVAT_ADMIN_EMAILS")),
            build_id=_env_value("GOVAT_BUILD_ID"),
            diagnostics_enabled=_env_bool("GOVAT_DIAGNOSTICS_ENABLED", True),
            slow_request_ms=_env_int("GOVAT_SLOW_REQUEST_MS", 1500),
            environment_label=_env_value("GOVAT_ENVIRONMENT_LABEL"),
            deploy_target=_env_value("GOVAT_DEPLOY_TARGET"),
            workspace_host=_normalize_workspace_host(_env_value("DATABRICKS_HOST")),
            genie_space_id=_env_optional("GOVAT_GENIE_SPACE_ID")
            or _env_optional("GENIE_SPACE_ID"),
            genie_space_title=_env_optional("GOVAT_GENIE_SPACE_TITLE")
            or "Governance Atlas Metadata Room",
            atlas_ai_provider=(
                _env_value("GOVAT_ATLAS_AI_PROVIDER").lower()
                or ("genie" if (_env_optional("GOVAT_GENIE_SPACE_ID") or _env_optional("GENIE_SPACE_ID")) else "local")
            ),
            atlas_ai_require_benchmark=_env_bool("GOVAT_ATLAS_AI_REQUIRE_BENCHMARK", False),
            ai_generation_endpoint=(
                _env_optional("GOVAT_AI_GENERATION_ENDPOINT") or ""
            ),
            lakebase_enabled=_env_bool("GOVAT_LAKEBASE_ENABLED", False),
            lakebase_endpoint_name=_env_optional("GOVAT_LAKEBASE_ENDPOINT_NAME")
            or _env_optional("POSTGRES_ENDPOINT_NAME")
            or _env_optional("ENDPOINT_NAME"),
            lakebase_schema=_env_optional("GOVAT_LAKEBASE_SCHEMA") or "atlas_app",
            lakebase_uc_catalog=_env_optional("GOVAT_LAKEBASE_UC_CATALOG"),
            datapact_enabled=_env_bool("GOVAT_DATAPACT_ENABLED", True),
            datapact_catalog=_env_optional("GOVAT_DATAPACT_CATALOG"),
            datapact_schema=_env_optional("GOVAT_DATAPACT_SCHEMA") or "datapact",
        )
