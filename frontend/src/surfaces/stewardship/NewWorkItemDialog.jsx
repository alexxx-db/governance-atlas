import { useState } from "react";
import { Button, Drawer, StatusBanner, SuggestInput } from "../../components/system";
import { useAssetSuggestions } from "../../hooks/useAssetSuggestions";

/*
 * surfaces/stewardship/NewWorkItemDialog.jsx — files a REAL governance
 * request through the create API (Wave C3). This flow used to be a
 * hardcoded "unavailable" placard even though the same actor could create
 * requests from other surfaces.
 */

export function NewWorkItemDialog({
  open = false,
  onClose,
  onSubmit,
  submitting = false,
  error = "",
  canFile = false,
  fileDisabledReason = "",
  initialAssetFqn = "",
}) {
  const [draft, setDraft] = useState({ assetFqn: initialAssetFqn, title: "", note: "" });
  // Autofill the asset FQN from the visible-asset inventory (fetched only while
  // the dialog is open) so the user picks a real asset instead of typing blind.
  const assetSuggestions = useAssetSuggestions({ enabled: open });

  const missingFields = !draft.assetFqn.trim() || !draft.title.trim();
  const disabledReason = !canFile
    ? fileDisabledReason
    : missingFields
      ? "Enter an asset FQN and a title to create the work item."
      : "";

  const submit = () => {
    if (disabledReason || submitting) return;
    onSubmit?.({
      assetFqn: draft.assetFqn.trim(),
      title: draft.title.trim(),
      note: draft.note.trim(),
    });
  };

  return (
    <Drawer
      className="ax-stew-new-item"
      onClose={onClose}
      open={open}
      title="File a governance work item"
      footer={
        <div className="ax-stew-new-item-controls">
          <Button
            disabled={Boolean(disabledReason) || submitting}
            loading={submitting}
            onClick={submit}
            title={disabledReason || "File this as a real governance request."}
            variant="primary"
          >
            Create work item
          </Button>
          <Button onClick={onClose} variant="tertiary">
            Cancel
          </Button>
        </div>
      }
    >
      <p className="ax-stew-new-item-lede">
        Creates a real governance request for the asset you name. It lands in this queue and in the
        governance audit trail.
      </p>
      <div className="ax-stew-new-item-form">
        <label>
          <span>Asset FQN</span>
          <SuggestInput
            aria-label="New work item asset FQN"
            onChange={(event) => setDraft((current) => ({ ...current, assetFqn: event.target.value }))}
            options={assetSuggestions.fqns}
            placeholder="catalog.schema.table"
            type="text"
            value={draft.assetFqn}
          />
        </label>
        <label>
          <span>Title</span>
          <input
            aria-label="New work item title"
            onChange={(event) => setDraft((current) => ({ ...current, title: event.target.value }))}
            placeholder="What needs to happen?"
            type="text"
            value={draft.title}
          />
        </label>
        <label>
          <span>Note</span>
          <textarea
            aria-label="New work item note"
            onChange={(event) => setDraft((current) => ({ ...current, note: event.target.value }))}
            placeholder="Optional context for the steward who picks this up"
            rows={3}
            value={draft.note}
          />
        </label>
        {error ? <StatusBanner message={error} title="Work item creation failed" tone="danger" /> : null}
      </div>
    </Drawer>
  );
}

export default NewWorkItemDialog;
