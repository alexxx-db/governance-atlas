"""Phase 4 Tranche 2 / Phase 12 — governed-metadata export.

Ships the minimum needed to offer a sync CSV export for actor-scoped,
visible assets. Async/large exports are deferred to a future slice; this
module captures the OBO-freshness contract + stale-auth boundary so
adding async later doesn't require schema or API changes.

Key invariants:
- No raw OBO/user tokens are persisted. ExportJob records the
  token_captured_at timestamp only.
- token_captured_at > 55 minutes fails with STALE_AUTH (Databricks OBO
  tokens typically expire at 1 hour server-side; 5-minute safety).
- filter_snapshot_json captures the asset list + visibility scope at
  request time so the materialization can't silently widen.
- Asset list is capped at SYNC_EXPORT_MAX_ROWS for sync exports.
"""

from __future__ import annotations

import csv
import hashlib
import html
import io
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, List

STALE_AUTH_MINUTES = 55
SYNC_EXPORT_MAX_ROWS = 500
EXPORT_TTL_HOURS = 24


@dataclass(frozen=True)
class ExportDecision:
    """Outcome of the pre-materialization capability + freshness check."""

    allowed: bool
    reason: str = ""
    status: str = "queued"


def _parse_ts(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).strip()
    if not text:
        return None
    # Normalize "Z" and strip fractional/tz cruft that datetime.fromisoformat
    # can't parse on older Python versions.
    text = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def evaluate_export_request(
    *,
    actor_scoped: bool,
    token_captured_at: Any,
    asset_count: int,
    sync: bool,
    now: datetime | None = None,
) -> ExportDecision:
    """Decide whether a pending export should materialize or fail closed.

    Pure function — no I/O. Tests hit this directly.
    """
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if not actor_scoped:
        return ExportDecision(
            allowed=False,
            status="failed",
            reason=(
                "Export is actor-scoped only. Connect as a user with Databricks "
                "per-user authorization (OBO) to run an export."
            ),
        )
    if asset_count <= 0:
        return ExportDecision(
            allowed=False,
            status="failed",
            reason="Select at least one asset to export.",
        )
    if sync and asset_count > SYNC_EXPORT_MAX_ROWS:
        return ExportDecision(
            allowed=False,
            status="failed",
            reason=(
                f"Sync exports are capped at {SYNC_EXPORT_MAX_ROWS} assets. "
                "Split the request or queue an async export."
            ),
        )
    captured = _parse_ts(token_captured_at)
    if captured is None:
        # If the caller couldn't record token capture time, treat as fresh;
        # the request-time OBO token itself is still enforced by Databricks.
        return ExportDecision(allowed=True, status="materializing")
    age = current - captured
    if age.total_seconds() > STALE_AUTH_MINUTES * 60:
        return ExportDecision(
            allowed=False,
            status="stale_auth",
            reason=(
                "Authorization expired. Re-run the export from a fresh page "
                "load to capture current credentials."
            ),
        )
    return ExportDecision(allowed=True, status="materializing")


def build_csv(rows: Iterable[dict[str, Any]], columns: List[str]) -> str:
    """Render the rows as CSV. Escaping happens via csv.writer; missing
    keys are written as empty strings so missing fields never leak raw
    None into the artifact."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(columns)
    for row in rows:
        writer.writerow([_coerce_cell(row.get(column)) for column in columns])
    return buffer.getvalue()


def _coerce_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set)):
        return ", ".join(str(item) for item in value)
    if isinstance(value, dict):
        try:
            return json.dumps(value, sort_keys=True, default=str)
        except Exception:
            return str(value)
    return str(value)


def build_filter_snapshot(
    *,
    asset_fqns: List[str],
    actor_email: str,
    visibility_scope: str,
    format: str,
    requested_at: datetime,
) -> str:
    payload = {
        "assetFqns": list(asset_fqns),
        "actorEmail": actor_email,
        "visibilityScope": visibility_scope,
        "format": format,
        "requestedAt": requested_at.astimezone(timezone.utc).isoformat(),
    }
    return json.dumps(payload, sort_keys=True)


def new_job_id() -> str:
    return uuid.uuid4().hex


# ── G10: tamper-evident evidence pack (checksum + provenance manifest) ──────

def content_sha256(text: str) -> str:
    """SHA-256 of the exported content — the tamper-evidence anchor. A recipient
    re-hashes the data file and compares. This is checksum-based integrity, NOT
    a cryptographic signature (no key management / non-repudiation exists here)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build_provenance_manifest(
    *,
    job_id: str,
    actor_email: str,
    actor_role: str,
    generated_at: datetime,
    filter_snapshot: str,
    row_count: int,
    byte_count: int,
    sha256: str,
    data_filename: str,
    export_format: str = "csv",
) -> str:
    """JSON manifest bundled with the data file to make the export auditable +
    tamper-evident. Honestly labels itself as checksummed, not signed."""
    try:
        filter_obj = json.loads(filter_snapshot) if filter_snapshot else {}
    except (ValueError, TypeError):
        filter_obj = {}
    manifest = {
        "manifestVersion": "1.0",
        "kind": "axiom-evidence-pack",
        "dataFile": data_filename,
        "integrity": {
            "algorithm": "SHA-256",
            "contentSha256": sha256,
            "verify": (
                "Re-compute SHA-256 of the data file and compare to contentSha256. "
                "This pack is checksummed + provenance-stamped for tamper evidence; "
                "it is NOT cryptographically signed (no key-management / non-repudiation)."
            ),
        },
        "export": {
            "jobId": job_id,
            "actorEmail": actor_email,
            "actorRole": actor_role,
            "generatedAt": generated_at.astimezone(timezone.utc).isoformat(),
            "rowCount": int(row_count),
            "byteCount": int(byte_count),
            "format": export_format,
        },
        "filterSnapshot": filter_obj,
    }
    return json.dumps(manifest, sort_keys=True, indent=2)


# ── G8: board-ready executive report (self-contained print-ready HTML) ──────

_REPORT_CSS = """
:root { color-scheme: light; }
* { box-sizing: border-box; }
body { font-family: -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif;
  margin: 0; padding: 40px; color: #0c2138; background: #f4f7fb; }
.wrap { max-width: 960px; margin: 0 auto; background: #fff; border: 1px solid #d9e2ec;
  border-radius: 14px; padding: 40px 44px; }
h1 { font-size: 26px; margin: 0 0 4px; color: #0a2540; }
h2 { font-size: 15px; text-transform: uppercase; letter-spacing: 0.06em; color: #486581;
  margin: 34px 0 12px; border-bottom: 1px solid #e3ebf3; padding-bottom: 6px; }
.sub { color: #627d98; font-size: 13px; margin: 0 0 2px; }
.kpis { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; margin-top: 8px; }
.kpi { border: 1px solid #e0e8f0; border-radius: 10px; padding: 14px 16px; }
.kpi .label { font-size: 12px; color: #627d98; text-transform: uppercase; letter-spacing: 0.04em; }
.kpi .value { font-size: 24px; font-weight: 700; color: #0a2540; margin-top: 4px; }
.kpi .na { font-size: 13px; color: #9aa5b1; font-weight: 600; }
.kpi .reason { font-size: 11px; color: #829ab1; margin-top: 4px; }
table { width: 100%; border-collapse: collapse; font-size: 13px; margin-top: 4px; }
th { text-align: left; padding: 8px 10px; color: #627d98; font-size: 11px; text-transform: uppercase;
  letter-spacing: 0.04em; border-bottom: 2px solid #e3ebf3; }
td { padding: 8px 10px; border-bottom: 1px solid #eef2f7; }
.bar { height: 8px; border-radius: 4px; background: #e3ebf3; overflow: hidden; min-width: 80px; }
.bar > span { display: block; height: 100%; background: #2f80ed; }
ul.recs { margin: 6px 0 0; padding-left: 18px; }
ul.recs li { margin: 6px 0; font-size: 13px; }
.foot { margin-top: 32px; padding-top: 14px; border-top: 1px solid #e3ebf3; color: #829ab1; font-size: 11px; }
.hero { display: flex; align-items: baseline; gap: 14px; }
.hero .score { font-size: 44px; font-weight: 800; color: #0a2540; }
.hero .state { font-size: 13px; color: #627d98; }
@media print { body { padding: 0; background: #fff; } .wrap { border: none; } }
"""


def _esc(value: Any) -> str:
    return html.escape(str("" if value is None else value))


def _kpi_html(label: str, value: Any, *, fmt: str = "", state: str = "", reason: str = "") -> str:
    if state and state.lower() == "unavailable":
        body = f'<div class="na">Unavailable</div><div class="reason">{_esc(reason)}</div>'
    else:
        display = value
        if value is None:
            display = "—"
        elif fmt == "percent":
            display = f"{value}%"
        rendered = f'<div class="value">{_esc(display)}</div>'
        body = rendered + (f'<div class="reason">{_esc(reason)}</div>' if reason else "")
    return f'<div class="kpi"><div class="label">{_esc(label)}</div>{body}</div>'


def build_board_report_html(
    *,
    command_center: dict,
    insights: dict,
    actor_email: str,
    generated_at: datetime,
    org_name: str = "Axiom",
) -> str:
    """Assemble a self-contained, print-ready executive governance report from
    the SAME live payloads the dashboard renders. Metrics that are unavailable
    stay honestly labeled 'Unavailable' with their reason — never fabricated."""
    cc = command_center or {}
    ins = insights or {}
    estate = cc.get("estate") or {}
    posture = cc.get("posture") or {}
    kpis = {k.get("key"): k for k in (cc.get("kpis") or []) if isinstance(k, dict)}

    def _kpi(key: str, label: str, fmt: str = "") -> str:
        entry = kpis.get(key) or {}
        return _kpi_html(
            label,
            entry.get("value"),
            fmt=entry.get("format") or fmt,
            state=entry.get("state") or "",
            reason=entry.get("reason") or "",
        )

    # Posture hero
    posture_state = posture.get("state") or ""
    posture_val = posture.get("overall")
    hero = (
        f'<div class="hero"><div class="score">{_esc(posture_val if posture_val is not None else "—")}</div>'
        f'<div class="state">{_esc(posture.get("reason") or ("Governance posture score" if posture_val is not None else "Unavailable"))}</div></div>'
    )

    # KPI grid
    kpi_grid = "".join(
        [
            _kpi("governedAssets", "Governed assets"),
            _kpi("certifiedCriticalAssets", "Certified critical assets"),
            _kpi("metadataCoverage", "Metadata coverage", "percent"),
            _kpi("openStewardship", "Open change requests"),
            _kpi("policyExceptions", "Policy exceptions"),
            _kpi("auditReadiness", "Audit readiness", "percent"),
        ]
    )

    # Coverage by domain
    domain_rows = ""
    for d in (posture.get("byDomain") or [])[:12]:
        score = d.get("score")
        pct = max(0, min(100, int(score))) if isinstance(score, (int, float)) else 0
        domain_rows += (
            f"<tr><td>{_esc(d.get('label') or d.get('domain'))}</td>"
            f"<td>{_esc(d.get('assetCount'))}</td>"
            f'<td><div class="bar"><span style="width:{pct}%"></span></div></td>'
            f"<td>{_esc(score)}</td></tr>"
        )
    domain_table = (
        f'<table><thead><tr><th>Domain</th><th>Assets</th><th>Governance score</th><th></th></tr></thead>'
        f"<tbody>{domain_rows}</tbody></table>"
        if domain_rows
        else '<p class="sub">No domain breakdown is available in the current scope.</p>'
    )

    # Certification by tier (insights)
    tier_rows = ""
    for t in ins.get("certificationCoverageByTier") or []:
        tier_rows += (
            f"<tr><td>{_esc(t.get('label') or t.get('tier'))}</td>"
            f"<td>{_esc(t.get('certified'))}/{_esc(t.get('total'))}</td>"
            f"<td>{_esc(t.get('value'))}%</td></tr>"
        )
    tier_table = (
        f"<table><thead><tr><th>Tier</th><th>Certified</th><th>Certification %</th></tr></thead>"
        f"<tbody>{tier_rows}</tbody></table>"
        if tier_rows
        else '<p class="sub">No certification-by-tier breakdown is available.</p>'
    )

    # Recommendations
    rec_items = ""
    for rec in (ins.get("recommendations") or [])[:6]:
        if isinstance(rec, dict):
            title = rec.get("title") or rec.get("label") or rec.get("summary") or ""
            detail = rec.get("detail") or rec.get("description") or ""
            rec_items += f"<li><strong>{_esc(title)}</strong>{(' — ' + _esc(detail)) if detail else ''}</li>"
    rec_list = f"<ul class='recs'>{rec_items}</ul>" if rec_items else '<p class="sub">No open recommendations.</p>'

    estate_label = estate.get("estateLabel") or "Data estate"
    generated_iso = generated_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(org_name)} — Governance Board Report</title><style>{_REPORT_CSS}</style></head>
<body><div class="wrap">
  <p class="sub">{_esc(org_name)} · Executive governance report</p>
  <h1>{_esc(estate_label)} — governance posture</h1>
  <p class="sub">Generated {_esc(generated_iso)} · by {_esc(actor_email)}</p>
  <h2>Posture</h2>
  {hero}
  <h2>Key metrics</h2>
  <div class="kpis">{kpi_grid}</div>
  <h2>Coverage by domain</h2>
  {domain_table}
  <h2>Certification by tier</h2>
  {tier_table}
  <h2>Priority recommendations</h2>
  {rec_list}
  <div class="foot">
    Every figure is sourced from the live Unity Catalog + governance-store signals shown on the
    Axiom dashboard. Metrics marked "Unavailable" have no authoritative source configured
    and are not estimated. This is a print-ready HTML report — use your browser's Print → Save as PDF.
  </div>
</div></body></html>"""


def expiry_for(requested_at: datetime, hours: int = EXPORT_TTL_HOURS) -> datetime:
    return requested_at + timedelta(hours=hours)


def evaluate_download_request(
    *,
    actor_scoped: bool,
    actor_email: str,
    requester_email: str | None,
    status: str | None,
    expires_at: Any,
    token_captured_at: Any,
    now: datetime | None = None,
) -> ExportDecision:
    """Gate a re-download attempt against the original requester, current
    status, expiry, and stale-auth clock. Pure function — no I/O."""
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if not actor_scoped:
        return ExportDecision(
            allowed=False,
            status="failed",
            reason=(
                "Downloads require per-user authorization (OBO). Open "
                "Axiom in a user-authorized session."
            ),
        )
    if not requester_email or (actor_email or "").lower() != requester_email.lower():
        return ExportDecision(
            allowed=False,
            status="forbidden",
            reason="Only the original requester can re-download this export.",
        )
    state = (status or "").lower()
    if state != "ready":
        return ExportDecision(
            allowed=False,
            status=state or "failed",
            reason=(
                "Export is not ready for download."
                if state in {"", "queued", "materializing"}
                else "This export is no longer available."
            ),
        )
    expiry = _parse_ts(expires_at)
    if expiry is not None and expiry <= current:
        return ExportDecision(
            allowed=False,
            status="expired",
            reason="Export artifact has expired; re-run the export.",
        )
    captured = _parse_ts(token_captured_at)
    if captured is not None:
        age = current - captured
        if age.total_seconds() > STALE_AUTH_MINUTES * 60:
            return ExportDecision(
                allowed=False,
                status="stale_auth",
                reason=(
                    "Authorization captured with this export has expired. "
                    "Re-run the export from a fresh session."
                ),
            )
    return ExportDecision(allowed=True, status="ready")
