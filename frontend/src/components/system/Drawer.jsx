import "./system.css";
import { useEffect, useId, useRef } from "react";
import { createPortal } from "react-dom";
import { Button } from "./Button";
import { CloseIcon } from "./icons.jsx";

/*
 * The one drawer/overlay base (FRONTEND_BLUEPRINT §6). Feature drawers
 * (Asset 360 peek, audit timeline, evidence) become thin content rendered
 * inside it in Waves B/C. Owns: portal, scrim, focus trap, ESC, scroll
 * lock, focus restore, width, footer slot. URL binding (`?peek=`) is the
 * caller's job via the nav fabric — the drawer itself is controlled by
 * `open`/`onClose` only, so it composes with any state source.
 */

const FOCUSABLE =
  "a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex='-1'])";

export function Drawer({
  open = false,
  onClose = null,
  title = "",
  width = undefined,
  footer = null,
  closeLabel = "Close",
  className = "",
  children,
}) {
  const panelRef = useRef(null);
  const titleId = useId();
  // onClose lives in a ref so the open-effect below keys ONLY on `open`:
  // consumers pass inline closures every render, and re-running the effect
  // would steal focus back to the panel mid-interaction.
  const onCloseRef = useRef(onClose);
  useEffect(() => {
    onCloseRef.current = onClose;
  });

  useEffect(() => {
    if (!open) return undefined;
    const previouslyFocused = /** @type {HTMLElement | null} */ (document.activeElement);
    const panel = panelRef.current;
    panel?.focus();

    const handleKeyDown = (event) => {
      if (event.key === "Escape") {
        event.stopPropagation();
        onCloseRef.current?.();
        return;
      }
      if (event.key !== "Tab" || !panel) return;
      // Focus trap: Tab cycles within the panel in both directions.
      const focusables = panel.querySelectorAll(FOCUSABLE);
      if (!focusables.length) {
        event.preventDefault();
        return;
      }
      const first = focusables[0];
      const last = focusables[focusables.length - 1];
      const active = document.activeElement;
      if (event.shiftKey && (active === first || active === panel)) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && active === last) {
        event.preventDefault();
        first.focus();
      }
    };

    document.addEventListener("keydown", handleKeyDown, true);
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", handleKeyDown, true);
      document.body.style.overflow = previousOverflow;
      if (previouslyFocused && typeof previouslyFocused.focus === "function") {
        previouslyFocused.focus();
      }
    };
  }, [open]);

  // Early return AFTER all hooks (CLAUDE.md hook-order rule).
  if (!open) return null;

  const style =
    width != null
      ? /** @type {import('react').CSSProperties} */ ({
          "--ax-sys-drawer-width": typeof width === "number" ? `${width}px` : String(width),
        })
      : undefined;

  return createPortal(
    <div className="ax-sys-drawer-root">
      <div className="ax-sys-drawer-scrim" onClick={() => onCloseRef.current?.()} aria-hidden="true" />
      <aside
        className={`ax-sys-drawer ${className}`.trim()}
        role="dialog"
        aria-modal="true"
        aria-labelledby={title ? titleId : undefined}
        ref={panelRef}
        tabIndex={-1}
        style={style}
      >
        <header className="ax-sys-drawer-header">
          {title ? <h2 id={titleId}>{title}</h2> : <span />}
          <Button
            variant="icon"
            size="sm"
            aria-label={closeLabel}
            icon={CloseIcon}
            onClick={() => onCloseRef.current?.()}
          />
        </header>
        <div className="ax-sys-drawer-body">{children}</div>
        {footer ? <footer className="ax-sys-drawer-footer">{footer}</footer> : null}
      </aside>
    </div>,
    document.body,
  );
}

export default Drawer;
