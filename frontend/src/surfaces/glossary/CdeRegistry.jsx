import { useEffect, useMemo, useRef, useState } from "react";
import {
  Badge,
  Button,
  DataTable,
  EmptyState,
  EntityChip,
  FilterBar,
  SectionCard,
  StatTile,
  SuggestInput,
  toast,
} from "../../components/system";
import { useCdeDetail } from "../../hooks/useCdeDashboard";
import { useWorkspaceRoster } from "../../hooks/useWorkspaceRoster";
import { useAxiomMutation } from "../../hooks/useAxiomQuery";
import { createGovernanceRequest, upsertGovernanceOwner } from "../../lib/api";
import {
  buildCdeCsv,
  cdeHealthEvidenceSummary,
  cdeLastReviewSummary,
  cdeRecertEvidenceSummary,
  cdeSourceSummary,
  compactDate,
  normalizeCdeRow,
  sourceAssetFqnForCde,
  statusLabelFor,
  statusToneFor,
  text,
} from "./glossaryPresentation";

/*
 * CdeRegistry — the CDE Registry tab of /glossary (?tab=cdes). Registry
 * DataTable whose name column is a real anchor to the canonical CDE address
 * (?tab=cdes&cde=<id>) — selection IS the URL, so back/forward and shared
 * links restore it. Sensitivity stays labeling language (a label, not a
 * control), untagged sources render an honest "Not tagged", and the CSV
 * download is built client-side from the very rows on screen (the old
 * permanently-disabled Download button is dead).
 */

function numberOrNull(value) {
  if (value === null || value === undefined || value === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function downloadCsv(rows) {
  const csv = buildCdeCsv(rows);
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = "cde-registry.csv";
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

function CdeDetailPanel({ cde, onClose }) {
  // Detail enrichment (controls, linked assets, activity) from the CDE
  // detail endpoint; the registry row renders instantly as the seed.
  const detailQuery = useCdeDetail(cde.id);
  const detail = useMemo(() => {
    const payload = detailQuery.data;
    const data = payload && typeof payload === "object" && "data" in payload ? payload.data : payload;
    return data && typeof data === "object" ? normalizeCdeRow({ ...cde, ...data }) : cde;
  }, [cde, detailQuery.data]);

  const sourceAssetFqn = sourceAssetFqnForCde(detail);

  const [ownerFormOpen, setOwnerFormOpen] = useState(false);
  const [ownerEmail, setOwnerEmail] = useState("");
  // Autofill owner from real account principals while the form is open.
  const roster = useWorkspaceRoster({ enabled: ownerFormOpen });

  // Recertification routes through governance-request creation — the same
  // path Lineage uses (POST /governance/requests).
  const requestRecert = useAxiomMutation({
    mutate: () =>
      createGovernanceRequest(
        {
          assetFqn: sourceAssetFqn,
          title: `Recertification requested: ${detail.name}`,
          note: `Recertification requested from the CDE registry for ${detail.name} (${sourceAssetFqn}).`,
        },
        { fast: true },
      ),
  });
  const assignOwner = useAxiomMutation({
    mutate: (email) =>
      upsertGovernanceOwner({ assetFqn: sourceAssetFqn, ownerEmail: email, ownerType: "steward" }),
    invalidates: [["axiom", "cde-dashboard"], ["axiom", "taxonomy-overview"]],
  });

  useEffect(() => {
    setOwnerFormOpen(false);
    setOwnerEmail("");
  }, [cde.id]);

  const handleRequestRecert = async () => {
    if (!sourceAssetFqn || requestRecert.submitting) return;
    try {
      const response = await requestRecert.mutate();
      const requestId = response?.requestId || response?.id || "";
      toast(
        requestId
          ? `Recertification request ${requestId} created for ${detail.name}.`
          : `Recertification request created for ${detail.name}.`,
        { tone: "success" },
      );
    } catch (error) {
      toast(error?.message || "Recertification request failed — please try again.", { tone: "danger" });
    }
  };

  const handleAssignOwner = async (event) => {
    event.preventDefault();
    const email = ownerEmail.trim();
    if (!email || !sourceAssetFqn || assignOwner.submitting) return;
    try {
      await assignOwner.mutate(email);
      toast(`Owner ${email} assigned to ${sourceAssetFqn}.`, { tone: "success" });
      setOwnerEmail("");
      setOwnerFormOpen(false);
    } catch {
      /* assignOwner.errorMessage renders inline below the form. */
    }
  };

  return (
    <section aria-label={`${detail.name} detail`} className="ax-glos-cde-detail">
      <header className="ax-glos-detail-head">
        <div>
          <span className="ax-glos-eyebrow">CDE detail</span>
          <h2>{detail.name}</h2>
        </div>
        <div className="ax-glos-detail-head-actions">
          <Button
            disabled={!sourceAssetFqn}
            loading={requestRecert.submitting}
            onClick={handleRequestRecert}
            size="sm"
            title={
              sourceAssetFqn
                ? "Create a governance request asking stewards to recertify this CDE"
                : "Recertification requests require a source asset FQN"
            }
            variant="secondary"
          >
            Request recertification
          </Button>
          <Button
            disabled={!sourceAssetFqn}
            onClick={() => setOwnerFormOpen((current) => !current)}
            size="sm"
            title={sourceAssetFqn ? "Assign a steward owner to the source asset" : "Owner assignment requires a source asset FQN"}
            variant="secondary"
          >
            {ownerFormOpen ? "Cancel owner assignment" : "Assign owner"}
          </Button>
          <Button aria-label={`Close ${detail.name} detail`} onClick={onClose} size="sm" variant="tertiary">
            Close
          </Button>
        </div>
      </header>

      {ownerFormOpen ? (
        <form
          aria-label={`Assign owner for ${detail.name}`}
          className="ax-glos-inline-form"
          onSubmit={handleAssignOwner}
        >
          <label className="ax-glos-field">
            <span>Owner email</span>
            <SuggestInput
              disabled={assignOwner.submitting}
              onChange={(event) => setOwnerEmail(event.target.value)}
              options={roster.emails}
              placeholder="steward@your-company.ai"
              required
              type="email"
              value={ownerEmail}
            />
          </label>
          {assignOwner.errorMessage ? (
            <p className="ax-glos-form-error" role="alert">
              {assignOwner.errorMessage}
            </p>
          ) : null}
          <Button disabled={!ownerEmail.trim()} loading={assignOwner.submitting} size="sm" type="submit" variant="primary">
            Assign owner
          </Button>
        </form>
      ) : null}

      <div className="ax-glos-detail-grid">
        <SectionCard className="ax-glos-detail-card" title="Source of record">
          <p className="ax-glos-mono">{detail.column || "Not tagged"}</p>
          <p className="ax-glos-muted">{cdeSourceSummary(detail)}</p>
          <div className="ax-glos-owner-line">
            <span className="ax-glos-kv-label">Source asset</span>
            {sourceAssetFqn ? (
              <EntityChip appearance="inline" entity={{ kind: "asset", fqn: sourceAssetFqn }} />
            ) : (
              <span className="ax-glos-muted">No source asset FQN is recorded on this registry row.</span>
            )}
          </div>
          {sourceAssetFqn ? (
            <div className="ax-glos-owner-line">
              <span className="ax-glos-kv-label">Lineage</span>
              <EntityChip
                appearance="inline"
                entity={{ kind: "lineage", fqn: sourceAssetFqn, label: "Open lineage" }}
              />
            </div>
          ) : null}
        </SectionCard>

        <SectionCard className="ax-glos-detail-card" title="Ownership & certification">
          <div className="ax-glos-kv-grid">
            <div className="ax-glos-owner-line">
              <span className="ax-glos-kv-label">Owner</span>
              {detail.owner && detail.owner !== "Unassigned" ? (
                <EntityChip appearance="inline" entity={{ kind: "owner", id: detail.owner, label: detail.owner }} />
              ) : (
                <span className="ax-glos-muted">Unassigned</span>
              )}
            </div>
            <div className="ax-glos-owner-line">
              <span className="ax-glos-kv-label">Certification</span>
              <Badge tone={statusToneFor(detail.status)}>{statusLabelFor(detail.status, "Certification pending")}</Badge>
            </div>
            <div className="ax-glos-owner-line">
              <span className="ax-glos-kv-label">Recertification</span>
              <span>{statusLabelFor(detail.recert)}</span>
            </div>
            <div className="ax-glos-owner-line">
              <span className="ax-glos-kv-label">Last review</span>
              <span>{cdeLastReviewSummary(detail)}</span>
            </div>
            {detail.sensitivity ? (
              <div className="ax-glos-owner-line">
                <span className="ax-glos-kv-label">Sensitivity label</span>
                {/* A label, not a protection control — labeling language only. */}
                <Badge tone={statusToneFor(detail.sensitivity)}>{detail.sensitivity}</Badge>
              </div>
            ) : null}
            <div className="ax-glos-owner-line">
              <span className="ax-glos-kv-label">SOX</span>
              <span>{detail.sox ? "SOX-relevant" : "Not marked SOX"}</span>
            </div>
          </div>
        </SectionCard>

        <SectionCard className="ax-glos-detail-card" title="Recertification evidence">
          <p>{cdeRecertEvidenceSummary(detail)}</p>
        </SectionCard>

        <SectionCard className="ax-glos-detail-card" title="Quality evidence">
          <p>{cdeHealthEvidenceSummary(detail)}</p>
        </SectionCard>

        {detail.linkedAssets.length ? (
          <SectionCard className="ax-glos-detail-card" title="Linked assets">
            <div className="ax-glos-linked-assets">
              {detail.linkedAssets.map((asset) => (
                <EntityChip
                  appearance="row"
                  entity={{ kind: "asset", fqn: asset.fqn, label: asset.fqn || asset.label, meta: asset.type }}
                  key={asset.id}
                />
              ))}
            </div>
          </SectionCard>
        ) : null}
      </div>
    </section>
  );
}

export function CdeRegistry({
  rows,
  summary = /** @type {Record<string, any>} */ ({}),
  loading = false,
  filters,
  onFiltersChange,
  selectedCdeId = "",
  onCloseDetail,
}) {
  const detailRef = useRef(null);

  const domains = useMemo(
    () => Array.from(new Set(rows.map((row) => text(row.domain) || "Unassigned"))).sort(),
    [rows],
  );

  const visibleRows = useMemo(() => {
    const query = text(filters.q).toLowerCase();
    return rows.filter((row) => {
      if (filters.domain && (text(row.domain) || "Unassigned") !== filters.domain) return false;
      if (!query) return true;
      return [row.name, row.rawName, row.column, row.domain, row.owner, row.status]
        .join(" ")
        .toLowerCase()
        .includes(query);
    });
  }, [filters.domain, filters.q, rows]);

  const selectedCde = selectedCdeId ? rows.find((row) => row.id === selectedCdeId) || null : null;

  // Selection arrives via the URL (?cde=): bring the detail into view.
  useEffect(() => {
    if (!selectedCde || typeof window === "undefined") return;
    window.requestAnimationFrame(() => {
      const node = detailRef.current;
      if (!node || typeof node.scrollIntoView !== "function") return;
      const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches;
      node.scrollIntoView({ behavior: reduced ? "auto" : "smooth", block: "start" });
    });
  }, [selectedCde]);

  const totalCdes = numberOrNull(summary.totalCdes) ?? rows.length;
  const sensitivityLabeledCount = numberOrNull(summary.sensitivityLabeledCdes);
  const sensitivityLabeledLabel = text(summary.sensitivityLabeledLabel) || "Sensitivity-labeled";
  const overdueReviews = numberOrNull(summary.overdueReviews);
  const domainsCovered = numberOrNull(summary.domainsCovered) ?? (rows.length ? domains.length : null);

  const columns = [
    {
      key: "name",
      header: "CDE",
      render: (row) => (
        <span className="ax-glos-cde-name">
          {row.name}
          {row.sox ? (
            <Badge size="sm" tone="warn">
              SOX
            </Badge>
          ) : null}
        </span>
      ),
    },
    {
      key: "column",
      header: "Source-of-record column",
      render: (row) =>
        row.column ? (
          <span className="ax-glos-mono" title={cdeSourceSummary(row)}>
            {row.column}
          </span>
        ) : (
          // Honest state, not instruction text masquerading as a value: the
          // remediation hint lives in the tooltip.
          <em className="ax-glos-untagged" title={cdeSourceSummary(row)}>
            Not tagged
          </em>
        ),
    },
    {
      key: "assetFqn",
      header: "Source asset",
      render: (row) => {
        const fqn = sourceAssetFqnForCde(row);
        return fqn ? <EntityChip appearance="inline" entity={{ kind: "asset", fqn }} /> : "—";
      },
    },
    {
      key: "owner",
      header: "Owner",
      render: (row) =>
        row.owner && row.owner !== "Unassigned" ? (
          <EntityChip appearance="inline" entity={{ kind: "owner", id: row.owner, label: row.owner }} />
        ) : (
          <span className="ax-glos-muted">Unassigned</span>
        ),
    },
    {
      key: "recert",
      header: "Recert",
      render: (row) => (
        <span title={cdeRecertEvidenceSummary(row)}>{statusLabelFor(row.recert)}</span>
      ),
    },
    {
      key: "status",
      header: "Certification",
      render: (row) => (
        <span title={`${cdeSourceSummary(row)}. ${cdeHealthEvidenceSummary(row)}`}>
          <Badge tone={statusToneFor(row.status)}>{statusLabelFor(row.status, "Certification pending")}</Badge>
        </span>
      ),
    },
    {
      key: "lastReview",
      header: "Last review",
      render: (row) => (row.lastReview ? compactDate(row.lastReview) : "—"),
    },
  ];

  return (
    <div className="ax-glos-cde-registry">
      <div aria-label="CDE metrics" className="ax-glos-stat-row">
        <StatTile
          hint={`${visibleRows.length.toLocaleString()} visible in this view`}
          label="Total CDEs"
          value={loading && !rows.length ? "…" : totalCdes.toLocaleString()}
        />
        <StatTile
          hint="Sensitivity label stronger than internal — a label, not a control"
          label={sensitivityLabeledLabel}
          value={
            loading && !rows.length
              ? "…"
              : sensitivityLabeledCount == null
                ? "—"
                : sensitivityLabeledCount.toLocaleString()
          }
        />
        <StatTile
          hint={overdueReviews == null ? "Review cadence not configured" : "Backed by review metadata"}
          label="Overdue reviews"
          value={overdueReviews == null ? "—" : overdueReviews.toLocaleString()}
        />
        <StatTile
          label="Domains covered"
          value={loading && !rows.length ? "…" : domainsCovered == null ? "—" : domainsCovered.toLocaleString()}
        />
      </div>

      <div className="ax-glos-toolbar">
        <FilterBar
          facets={[
            { key: "q", type: "search", label: "Search CDEs", placeholder: "Search CDEs by name, column, or owner…" },
            {
              key: "domain",
              type: "select",
              label: "Domain",
              options: domains.map((domain) => ({ value: domain, label: domain })),
            },
          ]}
          label="CDE filters"
          onChange={onFiltersChange}
          value={{ q: filters.q || "", domain: filters.domain || "" }}
        />
        <Button
          disabled={!visibleRows.length}
          onClick={() => {
            downloadCsv(visibleRows);
            toast(`Downloaded ${visibleRows.length.toLocaleString()} CDE registry rows as CSV.`, {
              tone: "success",
            });
          }}
          title="Download the visible registry rows as CSV"
          variant="secondary"
        >
          Download CSV
        </Button>
      </div>

      <p aria-busy={loading && !rows.length ? true : undefined} className="ax-glos-caption" role="status">
        {loading && !rows.length
          ? "Loading the CDE registry…"
          : `Showing ${visibleRows.length} of ${rows.length} CDE registry rows`}
      </p>

      <DataTable
        caption="CDE registry"
        columns={columns}
        emptyState={
          <EmptyState
            body={
              rows.length
                ? "Adjust or clear the search and domain filters to see the full registry."
                : "Flag an asset as a CDE with + New CDE to start the registry."
            }
            title={rows.length ? "No CDEs match this view" : "No Critical Data Elements yet"}
          />
        }
        loading={loading && !rows.length}
        rows={visibleRows}
        rowTarget={(row) => ({ kind: "cde", id: row.id })}
        stickyHeader
      />

      <p className="ax-glos-footnote">
        Status and recertification are registry metadata values. Quality test-run or recertification
        workflow proof appears only when backed evidence is returned.
      </p>

      {selectedCde ? (
        <div ref={detailRef}>
          <CdeDetailPanel cde={selectedCde} onClose={onCloseDetail} />
        </div>
      ) : null}
    </div>
  );
}

export default CdeRegistry;
