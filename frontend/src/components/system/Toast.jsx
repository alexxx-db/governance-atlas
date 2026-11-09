import "./system.css";
import { useSyncExternalStore } from "react";
import { Button } from "./Button";
import { CloseIcon } from "./icons.jsx";

/*
 * Module-level toast bus + single host (FRONTEND_BLUEPRINT §6). Satisfies
 * the CLAUDE.md rule that unwired buttons must stage intent visibly:
 * `toast("Saved view — sharing arrives in Wave C")` from anywhere, no
 * context plumbing. `<ToastHost/>` mounts ONCE in the app shell (Wave B).
 *
 * The store is module-scoped on purpose: toasts are ephemeral UI chrome,
 * not app state, and a module singleton keeps `toast()` callable from
 * non-React code (mutation callbacks, adapters).
 */

const listeners = new Set();
const timers = new Map();
let toasts = [];
let sequence = 0;

function notify() {
  for (const listener of listeners) listener();
}

function subscribe(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function getSnapshot() {
  return toasts;
}

function dismiss(id) {
  const timer = timers.get(id);
  if (timer) {
    clearTimeout(timer);
    timers.delete(id);
  }
  const next = toasts.filter((item) => item.id !== id);
  if (next.length !== toasts.length) {
    toasts = next;
    notify();
  }
}

const TONES = new Set(["neutral", "success", "warning", "danger", "accent"]);

/**
 * toast(message, {tone, action: {label, onClick}, duration})
 * duration defaults to 5s (8s with an action so it can be reached);
 * duration: 0 makes it persistent until dismissed.
 *
 * @param {string} message
 * @param {{ tone?: string, action?: ({ label?: string, onClick?: () => void } | null), duration?: number }} [options]
 */
export function toast(message, { tone = "neutral", action = null, duration } = {}) {
  const id = ++sequence;
  const resolvedTone = TONES.has(tone) ? tone : "neutral";
  const ms = duration ?? (action ? 8000 : 5000);
  toasts = [...toasts, { id, message, tone: resolvedTone, action }];
  notify();
  if (Number.isFinite(ms) && ms > 0) {
    timers.set(
      id,
      setTimeout(() => dismiss(id), ms),
    );
  }
  return id;
}

toast.dismiss = dismiss;
toast.clear = () => {
  for (const timer of timers.values()) clearTimeout(timer);
  timers.clear();
  if (toasts.length) {
    toasts = [];
    notify();
  }
};

export function ToastHost() {
  const items = useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
  return (
    <div className="ax-sys-toast-host" role="region" aria-label="Notifications">
      {items.map((item) => (
        <div
          key={item.id}
          className={`ax-sys-toast tone-${item.tone}`}
          // danger interrupts AT (alert); everything else is polite status.
          role={item.tone === "danger" ? "alert" : "status"}
        >
          <span className="ax-sys-toast-message">{item.message}</span>
          {item.action ? (
            <Button
              variant="tertiary"
              size="sm"
              onClick={() => {
                item.action.onClick?.();
                dismiss(item.id);
              }}
            >
              {item.action.label}
            </Button>
          ) : null}
          <Button
            variant="icon"
            size="sm"
            aria-label="Dismiss notification"
            icon={CloseIcon}
            onClick={() => dismiss(item.id)}
          />
        </div>
      ))}
    </div>
  );
}

export default ToastHost;
