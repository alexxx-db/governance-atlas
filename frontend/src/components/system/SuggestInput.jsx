import { useEffect, useId, useMemo, useRef, useState } from "react";

/*
 * SuggestInput — a free-text input with a VISIBLE, styled autocomplete
 * dropdown. Replaces the old native <datalist> (which was populated correctly
 * but too subtle to read as autocomplete — users kept reporting "it's not
 * autocompleting"). Used for owner/steward/reviewer emails (real account
 * principals), asset FQNs, and domains, so the value is filled from ground
 * truth instead of typed blind.
 *
 * Contract preserved from the datalist version: `onChange` receives an
 * event-shaped `{ target: { value } }` (so existing callers using
 * `event.target.value` keep working), it NEVER blocks a value that isn't in
 * the list (the server does authoritative validation), and any extra props
 * (placeholder, type, disabled, required, autoFocus, className, inputMode…)
 * pass through to the <input>.
 *
 * A11y: ARIA 1.2 combobox pattern — role=combobox on the input, a listbox
 * popup, aria-activedescendant for the highlighted option, full keyboard
 * support (Down/Up/Enter/Escape/Tab).
 */
function fireChange(onChange, value) {
  if (typeof onChange === "function") onChange({ target: { value } });
}

/**
 * @param {{ value?: any, onChange?: any, options?: any[], id?: any, className?: string,
 *   onKeyDown?: any, onBlur?: any, onFocus?: any, maxVisible?: number, [x: string]: any }} props
 */
export function SuggestInput({
  value,
  onChange,
  options = [],
  id,
  className = "",
  onKeyDown,
  onBlur,
  onFocus,
  maxVisible = 8,
  ...rest
}) {
  const generatedId = useId();
  const inputId = id || generatedId;
  const listId = `${inputId}-listbox`;
  const wrapRef = useRef(null);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);

  // Dedupe + normalize the option list once.
  const items = useMemo(() => {
    const seen = new Set();
    const out = [];
    for (const option of options) {
      const label = String(option ?? "").trim();
      if (!label) continue;
      const key = label.toLowerCase();
      if (seen.has(key)) continue;
      seen.add(key);
      out.push(label);
    }
    return out;
  }, [options]);

  const query = String(value ?? "").trim().toLowerCase();
  // Filter by substring; if the field is empty show the first maxVisible so a
  // focus/click reveals the roster. An exact single match (already chosen) is
  // suppressed so we don't hang a one-row popup off a completed field.
  const matches = useMemo(() => {
    const filtered = query
      ? items.filter((item) => item.toLowerCase().includes(query))
      : items;
    if (filtered.length === 1 && filtered[0].toLowerCase() === query) return [];
    return filtered.slice(0, maxVisible);
  }, [items, query, maxVisible]);

  // Close on outside click.
  useEffect(() => {
    if (!open) return undefined;
    const onDocClick = (event) => {
      if (!wrapRef.current?.contains(event.target)) setOpen(false);
    };
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, [open]);

  const showList = open && matches.length > 0;

  const choose = (label) => {
    fireChange(onChange, label);
    setOpen(false);
    setActive(-1);
  };

  const handleKeyDown = (event) => {
    if (typeof onKeyDown === "function") onKeyDown(event);
    if (event.defaultPrevented) return;
    if (!showList) {
      if (event.key === "ArrowDown" && matches.length) {
        setOpen(true);
        setActive(0);
        event.preventDefault();
      }
      return;
    }
    if (event.key === "ArrowDown") {
      setActive((index) => (index + 1) % matches.length);
      event.preventDefault();
    } else if (event.key === "ArrowUp") {
      setActive((index) => (index <= 0 ? matches.length - 1 : index - 1));
      event.preventDefault();
    } else if (event.key === "Enter" && active >= 0) {
      choose(matches[active]);
      event.preventDefault();
    } else if (event.key === "Escape") {
      setOpen(false);
      setActive(-1);
    }
  };

  return (
    <span className="ax-sys-suggest" ref={wrapRef}>
      <input
        autoComplete="off"
        {...rest}
        id={inputId}
        className={className}
        role="combobox"
        aria-expanded={showList}
        aria-controls={listId}
        aria-autocomplete="list"
        aria-activedescendant={showList && active >= 0 ? `${listId}-opt-${active}` : undefined}
        value={value ?? ""}
        onChange={(event) => {
          fireChange(onChange, event.target.value);
          setOpen(true);
          setActive(-1);
        }}
        onFocus={(event) => {
          setOpen(true);
          if (typeof onFocus === "function") onFocus(event);
        }}
        onBlur={(event) => {
          if (typeof onBlur === "function") onBlur(event);
        }}
        onKeyDown={handleKeyDown}
      />
      {showList ? (
        <ul className="ax-sys-suggest-list" id={listId} role="listbox">
          {matches.map((label, index) => (
            <li
              key={label}
              id={`${listId}-opt-${index}`}
              role="option"
              aria-selected={index === active}
              className={`ax-sys-suggest-option${index === active ? " is-active" : ""}`}
              // mousedown (not click) so selection fires before the input blur.
              onMouseDown={(event) => {
                event.preventDefault();
                choose(label);
              }}
              onMouseEnter={() => setActive(index)}
            >
              {label}
            </li>
          ))}
        </ul>
      ) : null}
    </span>
  );
}

export default SuggestInput;
