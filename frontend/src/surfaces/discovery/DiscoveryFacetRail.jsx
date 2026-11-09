import "./discovery.css";
import { useState } from "react";
import { facetCount, facetEntries } from "./discoveryPresentation";

/*
 * Quick-facet rail (Wave C1 port of the legacy prototype filter rail).
 * Facet-bucket honesty rules preserved:
 *   - the backend emits EVERY bucket (including "Unassigned") summing to the
 *     result total; nothing truncates silently — lists cap visually with an
 *     explicit "Show all N" expander;
 *   - zero-count options are hidden (a filter that can only produce an empty
 *     result is noise) unless actively selected, so they stay un-toggleable.
 */

const FACET_VISUAL_CAPS = { domains: 6, sensitivities: 4, certifications: 4 };

function railOptions(facets, facetKey, selected, fallbackValues = []) {
  const live = facetEntries(facets, facetKey).map((entry) => String(entry.value));
  const values = [...new Set([...fallbackValues, ...selected, ...live])].filter(
    (value) => value && !/^all\s/i.test(value),
  );
  return values.filter(
    (value) => selected.includes(value) || facetCount(facets, facetKey, value) > 0,
  );
}

function RailGroup({ eyebrow, count = null, children }) {
  return (
    <section className="ax-disc-facet-group">
      <header>
        <span>{eyebrow}</span>
      </header>
      {count !== null ? (
        <small className="ax-disc-facet-group-count">
          {Number(count || 0).toLocaleString()} results
        </small>
      ) : null}
      <div>{children}</div>
    </section>
  );
}

export function DiscoveryFacetRail({
  facets = {},
  selections = { certifications: [], domains: [], sensitivities: [] },
  onToggle,
  onAppendQueryClause,
}) {
  const [expanded, setExpanded] = useState({});

  const visibleOptions = (facetKey, options) =>
    expanded[facetKey] ? options : options.slice(0, FACET_VISUAL_CAPS[facetKey]);

  const expander = (facetKey, options) => {
    if (options.length <= FACET_VISUAL_CAPS[facetKey]) return null;
    const isExpanded = Boolean(expanded[facetKey]);
    return (
      <button
        aria-expanded={isExpanded}
        className="ax-disc-facet-show-all"
        onClick={() => setExpanded((current) => ({ ...current, [facetKey]: !current[facetKey] }))}
        type="button"
      >
        {isExpanded ? "Show fewer" : `Show all ${options.length}`}
      </button>
    );
  };

  const facetButton = (facetKey, paramKey, option, marker) => {
    const active = (selections[facetKey] || []).includes(option);
    return (
      <button aria-pressed={active} key={option} onClick={() => onToggle?.(paramKey, option)} type="button">
        {marker}
        <span>{option}</span>
        <small>{facetCount(facets, facetKey, option).toLocaleString()}</small>
      </button>
    );
  };

  const certificationOptions = railOptions(
    facets,
    "certifications",
    selections.certifications || [],
    ["Certified", "In Review", "Uncertified"],
  );
  const domainOptions = railOptions(facets, "domains", selections.domains || []);
  const classificationOptions = railOptions(facets, "sensitivities", selections.sensitivities || []);

  // Header count reflects the facet counts of the options actually shown,
  // never the unrelated total result count.
  const certificationShownCount = certificationOptions.reduce(
    (sum, option) => sum + facetCount(facets, "certifications", option),
    0,
  );

  return (
    <aside aria-label="Discovery quick facets" className="ax-disc-facet-rail">
      <RailGroup count={certificationShownCount} eyebrow="Certification">
        {visibleOptions("certifications", certificationOptions).map((option) =>
          facetButton(
            "certifications",
            "certification",
            option,
            <span
              className={`ax-disc-facet-dot tone-${
                /cert/i.test(option) ? "good" : /review|draft/i.test(option) ? "warn" : "bad"
              }`}
            />,
          ),
        )}
        {expander("certifications", certificationOptions)}
      </RailGroup>
      <RailGroup eyebrow="Domain">
        {visibleOptions("domains", domainOptions).map((option) =>
          facetButton("domains", "domain", option, <span className="ax-disc-facet-square" />),
        )}
        {expander("domains", domainOptions)}
      </RailGroup>
      <RailGroup eyebrow="Classification">
        {visibleOptions("sensitivities", classificationOptions).map((option) =>
          facetButton(
            "sensitivities",
            "sensitivity",
            option,
            <span
              className={`ax-disc-facet-dot tone-${
                /restrict/i.test(option) ? "bad" : /conf/i.test(option) ? "warn" : "info"
              }`}
            />,
          ),
        )}
        {expander("sensitivities", classificationOptions)}
      </RailGroup>
      <RailGroup eyebrow="Attributes">
        <button onClick={() => onAppendQueryClause?.("tag:CDE")} type="button">
          <span className="ax-disc-facet-square tone-teal" />
          <span>Critical Data Element</span>
        </button>
        <button onClick={() => onAppendQueryClause?.("tag:pii")} type="button">
          <span className="ax-disc-facet-dot tone-bad" />
          <span>Contains PII</span>
        </button>
        <button onClick={() => onAppendQueryClause?.("tag:no_pii")} type="button">
          <span className="ax-disc-facet-dot tone-muted" />
          <span>No PII</span>
        </button>
      </RailGroup>
    </aside>
  );
}

export default DiscoveryFacetRail;
