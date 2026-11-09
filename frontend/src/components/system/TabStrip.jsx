import "./system.css";
import { useRef, useState } from "react";
import { useInRouterContext, useSearchParams } from "react-router-dom";
import { Badge } from "./Badge";

/*
 * The one tab strip (FRONTEND_BLUEPRINT §6). Controlled via value/onChange,
 * uncontrolled via defaultValue, or URL-bound via `param` so tabs become
 * addressable by default (`<TabStrip param="tab" …/>` → `?tab=`).
 *
 * `param` accepts:
 *   - a string: bind to that search param through react-router (requires a
 *     Router; falls back to internal state outside one). Writes use
 *     replace:true, matching the app's push/replace discipline for
 *     sub-state (FRONTEND_BLUEPRINT §8.5).
 *   - an adapter object {value, set}: Wave A3's useSurfaceParams hands this
 *     in, so the strip works identically before and after the nav fabric.
 *
 * Hook-safety: the dispatcher below renders one of two distinct child
 * components rather than calling useSearchParams conditionally — each child
 * has its own stable hook order, and a runtime flip of `param` remounts.
 */

function tabId(idPrefix, key) {
  return `${idPrefix}-tab-${key}`;
}

function TabList({
  tabs = [],
  value,
  onChange,
  ariaLabel = "Tabs",
  className = "",
  idPrefix = "ax-sys",
}) {
  const listRef = useRef(null);

  const enabledKeys = tabs.filter((tab) => !tab.disabled).map((tab) => tab.key);
  const activeKey = value ?? enabledKeys[0];

  const select = (key) => {
    if (key !== activeKey) onChange?.(key);
  };

  const handleKeyDown = (event) => {
    if (!["ArrowRight", "ArrowLeft", "Home", "End"].includes(event.key)) return;
    if (!enabledKeys.length) return;
    event.preventDefault();
    const currentIndex = Math.max(0, enabledKeys.indexOf(activeKey));
    let nextIndex = currentIndex;
    if (event.key === "ArrowRight") nextIndex = (currentIndex + 1) % enabledKeys.length;
    if (event.key === "ArrowLeft") nextIndex = (currentIndex - 1 + enabledKeys.length) % enabledKeys.length;
    if (event.key === "Home") nextIndex = 0;
    if (event.key === "End") nextIndex = enabledKeys.length - 1;
    const nextKey = enabledKeys[nextIndex];
    select(nextKey);
    // Selection follows focus (simplest correct tablist pattern). Located
    // via dataset compare, not a CSS selector — keys need no escaping and
    // CSS.escape is missing from the jsdom test environment.
    const node = Array.from(listRef.current?.querySelectorAll("[role='tab']") ?? []).find(
      (el) => el.dataset.tabKey === String(nextKey),
    );
    node?.focus();
  };

  return (
    <div
      className={`ax-sys-tabstrip ${className}`.trim()}
      role="tablist"
      aria-label={ariaLabel}
      ref={listRef}
      onKeyDown={handleKeyDown}
    >
      {tabs.map((tab) => {
        const selected = tab.key === activeKey;
        return (
          <button
            key={tab.key}
            id={tabId(idPrefix, tab.key)}
            data-tab-key={tab.key}
            type="button"
            role="tab"
            aria-selected={selected}
            aria-controls={tab.controls || undefined}
            className={`ax-sys-tab ${selected ? "is-active" : ""}`.trim()}
            tabIndex={selected ? 0 : -1}
            disabled={Boolean(tab.disabled)}
            // Honest disabled state: surface WHY, not just a dead control.
            title={tab.disabled && tab.disabledReason ? tab.disabledReason : undefined}
            onClick={() => select(tab.key)}
          >
            {tab.icon ? (
              <span className="ax-sys-tab-icon" aria-hidden="true">
                {tab.icon}
              </span>
            ) : null}
            <span className="ax-sys-tab-label">{tab.label}</span>
            {tab.badge != null && tab.badge !== "" ? (
              <Badge size="sm" tone="accent" className="ax-sys-tab-badge">
                {tab.badge}
              </Badge>
            ) : null}
          </button>
        );
      })}
    </div>
  );
}

/**
 * @param {{ tabs?: any[], value?: any, defaultValue?: any, onChange?: Function, [key: string]: any }} props
 */
function PlainTabStrip({ tabs = [], value, defaultValue, onChange, ...rest }) {
  const [internal, setInternal] = useState(
    defaultValue ?? tabs.find((tab) => !tab.disabled)?.key,
  );
  const controlled = value !== undefined;
  const active = controlled ? value : internal;
  const handleChange = (key) => {
    if (!controlled) setInternal(key);
    onChange?.(key);
  };
  return <TabList tabs={tabs} value={active} onChange={handleChange} {...rest} />;
}

/**
 * @param {{ param?: any, tabs?: any[], defaultValue?: any, onChange?: Function, [key: string]: any }} props
 */
function UrlTabStrip({ param, tabs = [], defaultValue, onChange, ...rest }) {
  const [searchParams, setSearchParams] = useSearchParams();
  const urlValue = searchParams.get(param);
  const known = urlValue != null && tabs.some((tab) => tab.key === urlValue);
  const active = known ? urlValue : defaultValue ?? tabs.find((tab) => !tab.disabled)?.key;
  const handleChange = (key) => {
    setSearchParams(
      (previous) => {
        const next = new URLSearchParams(previous);
        next.set(param, key);
        return next;
      },
      // Tab flips are sub-state: replace, don't grow history per click.
      { replace: true },
    );
    onChange?.(key);
  };
  return <TabList tabs={tabs} value={active} onChange={handleChange} {...rest} />;
}

/**
 * @param {{ param?: any, tabs?: any[], defaultValue?: any, onChange?: Function, [key: string]: any }} props
 */
function AdapterTabStrip({ param, tabs = [], defaultValue, onChange, ...rest }) {
  const active = param.value ?? defaultValue ?? tabs.find((tab) => !tab.disabled)?.key;
  const handleChange = (key) => {
    param.set?.(key);
    onChange?.(key);
  };
  return <TabList tabs={tabs} value={active} onChange={handleChange} {...rest} />;
}

export function TabStrip({ param = null, ...props }) {
  // Safe everywhere: returns false outside a Router instead of throwing.
  const inRouter = useInRouterContext();
  if (param && typeof param === "object" && typeof param.set === "function") {
    return <AdapterTabStrip param={param} {...props} />;
  }
  if (typeof param === "string" && param && inRouter) {
    return <UrlTabStrip param={param} {...props} />;
  }
  return <PlainTabStrip {...props} />;
}

export default TabStrip;
