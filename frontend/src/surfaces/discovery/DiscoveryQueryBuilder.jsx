import "./discovery.css";
import { useEffect, useMemo, useState } from "react";
import { Button } from "../../components/system";
import {
  appendDiscoveryQueryClause,
  buildDiscoveryQueryClause,
  discoveryQueryFields,
} from "./discoveryPresentation";

/*
 * Structured Search Helper (Wave C1 port). Builds field:value clauses —
 * single, any-of, all-of — and inserts them into the live search box,
 * honoring the backend's supportedFields list and refusing to chain onto an
 * invalid query. The "Deleted and inaccessible" facts render as explanatory
 * copy, never permanently-disabled buttons (no dead controls).
 */

const MATCH_OPTIONS = [
  { value: "single", label: "Single value" },
  { value: "any", label: "Any of these" },
  { value: "all", label: "All of these" },
];

export function DiscoveryQueryBuilder({
  activeQuery = "",
  queryState = null,
  syntaxHint = "",
  supportedFields = [],
  resultsCount = null,
  onApplyQuery,
}) {
  const fieldOptions = useMemo(() => discoveryQueryFields(supportedFields), [supportedFields]);
  const [builderField, setBuilderField] = useState(fieldOptions[0]?.value || "name");
  const [builderJoin, setBuilderJoin] = useState("AND");
  const [builderMatchMode, setBuilderMatchMode] = useState("single");
  const [builderValue, setBuilderValue] = useState("");

  useEffect(() => {
    if (!fieldOptions.some((option) => option.value === builderField)) {
      setBuilderField(fieldOptions[0]?.value || "name");
    }
  }, [builderField, fieldOptions]);

  const normalizedActiveQuery = String(activeQuery || "").trim();
  const queryIsInvalid = String(queryState?.state || "").trim().toLowerCase() === "invalid";
  const canApplyClause =
    !queryIsInvalid &&
    Boolean(
      buildDiscoveryQueryClause({
        field: builderField,
        value: builderValue,
        matchMode: builderMatchMode,
      }),
    );

  const applyQueryClause = () => {
    const nextClause = buildDiscoveryQueryClause({
      field: builderField,
      value: builderValue,
      matchMode: builderMatchMode,
    });
    if (!nextClause) return;
    onApplyQuery?.(appendDiscoveryQueryClause(normalizedActiveQuery, nextClause, builderJoin));
    setBuilderValue("");
  };

  // "Clear clause" resets EVERY builder input back to first-use state.
  const clearClauseInputs = () => {
    setBuilderValue("");
    setBuilderJoin("AND");
    setBuilderMatchMode("single");
    const defaultField = fieldOptions[0]?.value || "";
    if (defaultField) setBuilderField(defaultField);
  };

  const numericResultsCount = Number(resultsCount);
  const visibleCountLabel =
    Number.isFinite(numericResultsCount) && numericResultsCount >= 0
      ? numericResultsCount.toLocaleString()
      : "Unavailable";

  return (
    <div className="ax-disc-query-builder">
      <section aria-label="Structured search helper">
        <div className="ax-disc-query-builder-head">
          <span className="ax-disc-query-builder-title">Structured Search Helper</span>
          <span className="ax-disc-query-builder-context">
            {normalizedActiveQuery
              ? "Adds a clause to the current search box."
              : "Adds the first structured clause to the current search box."}
          </span>
        </div>
        <div className="ax-disc-query-builder-grid">
          <label>
            <span>Field</span>
            <select
              aria-label="Query builder field"
              onChange={(event) => setBuilderField(event.target.value)}
              value={builderField}
            >
              {fieldOptions.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span>Match</span>
            <select
              aria-label="Query builder match mode"
              onChange={(event) => setBuilderMatchMode(event.target.value)}
              value={builderMatchMode}
            >
              {MATCH_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span>Join with</span>
            <select
              aria-label="Query builder boolean operator"
              disabled={!normalizedActiveQuery || queryIsInvalid}
              onChange={(event) => setBuilderJoin(event.target.value)}
              title={
                !normalizedActiveQuery
                  ? "Enter a search in the main query box before chaining another clause."
                  : queryIsInvalid
                    ? "Clear or correct the invalid search before chaining another clause."
                    : undefined
              }
              value={builderJoin}
            >
              <option value="AND">AND</option>
              <option value="OR">OR</option>
            </select>
          </label>
        </div>
        <label className="ax-disc-query-builder-value">
          <span>Value</span>
          <input
            aria-label="Query builder value"
            onChange={(event) => setBuilderValue(event.target.value)}
            placeholder={
              builderMatchMode === "single" ? 'finance or "Customer Orders"' : "finance, support"
            }
            value={builderValue}
          />
        </label>
        <p className="ax-disc-query-builder-note">
          {builderMatchMode === "single"
            ? "Single values become one field:value clause. Phrases are quoted automatically."
            : "Separate multiple values with commas to create a grouped clause joined by AND or OR."}
        </p>
        <p className="ax-disc-query-builder-note">
          {syntaxHint ||
            "Structured discovery supports field:value, AND/OR, parentheses, and quoted phrases."}
        </p>
        {queryIsInvalid ? (
          <p className="ax-disc-query-builder-note">
            Clear or correct the invalid search in the main query box before inserting another
            helper clause.
          </p>
        ) : null}
        <div className="ax-disc-query-builder-actions">
          <Button
            disabled={!canApplyClause}
            onClick={applyQueryClause}
            title={
              queryIsInvalid
                ? "Clear or correct the invalid search before inserting this clause."
                : !builderValue?.trim()
                  ? "Enter a value for this clause to insert it."
                  : undefined
            }
            variant="secondary"
          >
            Insert into search
          </Button>
          <Button onClick={clearClauseInputs} variant="tertiary">
            Clear clause
          </Button>
        </div>
      </section>
      <section aria-label="Deleted and inaccessible handling">
        <div className="ax-disc-query-builder-head">
          <span className="ax-disc-query-builder-title">Deleted and inaccessible assets</span>
          <span className="ax-disc-query-builder-context">
            {visibleCountLabel} visible result{visibleCountLabel === "1" ? "" : "s"}
          </span>
        </div>
        <p className="ax-disc-query-builder-note">
          Discovery counts include only assets returned by the current permission-aware discovery
          payload. Deleted or inaccessible assets are not inferred into the result count.
        </p>
        <p className="ax-disc-query-builder-note">
          Deleted-asset search stays off because no authoritative deletion-state source is
          connected.
        </p>
        <p className="ax-disc-query-builder-note">
          Inaccessible assets stay hidden until Databricks returns metadata you can access for them.
        </p>
      </section>
    </div>
  );
}

export default DiscoveryQueryBuilder;
