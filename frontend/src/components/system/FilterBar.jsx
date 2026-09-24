import "./system.css";
import { useEffect, useId, useRef, useState } from "react";
import { Button } from "./Button";
import { SuggestInput } from "./SuggestInput";

/*
 * The one filter bar (FRONTEND_BLUEPRINT §6): a declarative facet model so
 * Discovery/Audit/Taxonomy/Governance queues stop hand-rolling filter rows.
 *
 * facets: [{ key, label, type: "search"|"select"|"multi", options: [{value,
 * label, count?}], placeholder? }] — `value` is a flat {key: string|string[]}
 * map and `onChange(nextValue)` receives the whole next map, which Wave
 * A3's useSurfaceParams can serialize straight into the URL.
 */

function facetHasValue(facet, value) {
  const current = value?.[facet.key];
  return Array.isArray(current) ? current.length > 0 : current != null && current !== "";
}

function MultiFacet({ facet, selected = [], onSelect }) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef(null);
  const labelId = useId();

  useEffect(() => {
    if (!open) return undefined;
    const handlePointer = (event) => {
      if (rootRef.current && !rootRef.current.contains(event.target)) setOpen(false);
    };
    const handleKey = (event) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", handlePointer);
    document.addEventListener("keydown", handleKey);
    return () => {
      document.removeEventListener("mousedown", handlePointer);
      document.removeEventListener("keydown", handleKey);
    };
  }, [open]);

  const toggleOption = (optionValue) => {
    const set = new Set(selected);
    if (set.has(optionValue)) set.delete(optionValue);
    else set.add(optionValue);
    onSelect([...set]);
  };

  return (
    <div className="ga-sys-filter-facet is-multi" ref={rootRef}>
      <button
        type="button"
        className={`ga-sys-filter-trigger ${selected.length ? "has-value" : ""}`.trim()}
        aria-haspopup="true"
        aria-expanded={open}
        onClick={() => setOpen((current) => !current)}
      >
        <span>{facet.label}</span>
        {selected.length ? <span className="ga-sys-filter-count">{selected.length}</span> : null}
      </button>
      {open ? (
        <div className="ga-sys-filter-pop" role="group" aria-labelledby={labelId}>
          <span id={labelId} className="ga-sys-visually-hidden">
            {facet.label}
          </span>
          {(facet.options ?? []).map((option) => (
            <label key={option.value} className="ga-sys-filter-option">
              <input
                type="checkbox"
                checked={selected.includes(option.value)}
                onChange={() => toggleOption(option.value)}
              />
              <span className="ga-sys-filter-option-label">{option.label ?? option.value}</span>
              {option.count != null ? (
                <span className="ga-sys-filter-option-count">{option.count}</span>
              ) : null}
            </label>
          ))}
        </div>
      ) : null}
    </div>
  );
}

export function FilterBar({
  facets = [],
  value = {},
  onChange = null,
  onClear = null,
  label = "Filters",
  className = "",
}) {
  const anyValue = facets.some((facet) => facetHasValue(facet, value));

  const setFacet = (key, facetValue) => {
    if (!onChange) return;
    const next = { ...value };
    const isEmpty = Array.isArray(facetValue) ? facetValue.length === 0 : facetValue == null || facetValue === "";
    if (isEmpty) delete next[key];
    else next[key] = facetValue;
    onChange(next);
  };

  const handleClear = () => {
    if (onClear) onClear();
    else onChange?.({});
  };

  return (
    <div className={`ga-sys-filter-bar ${className}`.trim()} role="group" aria-label={label}>
      {facets.map((facet) => {
        const type = facet.type ?? "select";
        if (type === "search") {
          // A search facet with `suggestions` autocompletes from that list
          // (roster emails for an actor facet, asset FQNs for an asset facet)
          // while still accepting free text.
          if (Array.isArray(facet.suggestions) && facet.suggestions.length) {
            return (
              <SuggestInput
                key={facet.key}
                className="ga-sys-filter-search"
                aria-label={facet.label}
                placeholder={facet.placeholder ?? facet.label}
                options={facet.suggestions}
                value={value[facet.key] ?? ""}
                onChange={(event) => setFacet(facet.key, event.target.value)}
              />
            );
          }
          return (
            <input
              key={facet.key}
              type="search"
              className="ga-sys-filter-search"
              aria-label={facet.label}
              placeholder={facet.placeholder ?? facet.label}
              value={value[facet.key] ?? ""}
              onChange={(event) => setFacet(facet.key, event.target.value)}
            />
          );
        }
        if (type === "multi") {
          return (
            <MultiFacet
              key={facet.key}
              facet={facet}
              selected={Array.isArray(value[facet.key]) ? value[facet.key] : []}
              onSelect={(next) => setFacet(facet.key, next)}
            />
          );
        }
        return (
          <label key={facet.key} className="ga-sys-filter-facet is-select">
            <span className="ga-sys-filter-facet-label">{facet.label}</span>
            <select
              className="ga-sys-filter-select"
              value={value[facet.key] ?? ""}
              onChange={(event) => setFacet(facet.key, event.target.value)}
            >
              {/* allLabel names what the empty value really shows when a
                  surface defaults it to a subset (e.g. open findings). */}
              <option value="">{facet.allLabel ?? "All"}</option>
              {(facet.options ?? []).map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label ?? option.value}
                  {option.count != null ? ` (${option.count})` : ""}
                </option>
              ))}
            </select>
          </label>
        );
      })}
      {anyValue ? (
        <Button variant="tertiary" size="sm" onClick={handleClear}>
          Clear filters
        </Button>
      ) : null}
    </div>
  );
}

export default FilterBar;
