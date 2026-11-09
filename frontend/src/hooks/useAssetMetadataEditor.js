import { useEffect, useMemo } from "react";
import {
  fetchAssetMetadataEditor,
  getAssetMetadataApiContract,
  updateAssetMetadata,
} from "../lib/api";
import { useAxiomMutation, useAxiomQuery } from "./useAxiomQuery";

const EDITABLE_FIELD_KEYS = [
  "description",
  "domain",
  "tier",
  "certification",
  "sensitivity",
  "criticality",
  "businessCriticality",
  "dataProduct",
  "isCde",
  "cdeRationale",
  "freeformTags",
];

export const BUSINESS_CRITICALITY_OPTIONS = [
  "Mission Critical",
  "Business Critical",
  "Operational",
  "Low Impact",
  "Not Assessed",
];

function titleCase(value) {
  return value
    .replace(/([A-Z])/g, " $1")
    .replace(/^./, (char) => char.toUpperCase())
    .trim();
}

function fieldOptions(key, bootstrap, field) {
  if (Array.isArray(field?.options) && field.options.length) {
    return field.options.filter(Boolean);
  }

  const discovery = bootstrap?.discovery || {};
  if (key === "domain") return (discovery.domains || []).filter((value) => value && value !== "All domains");
  if (key === "tier") return (discovery.tiers || []).filter((value) => value && value !== "All tiers");
  if (key === "certification") {
    return (discovery.certifications || []).filter(
      (value) => value && value !== "All certifications",
    );
  }
  if (key === "sensitivity") {
    return (discovery.sensitivities || []).filter(
      (value) => value && value !== "All sensitivities",
    );
  }
  if (key === "criticality") {
    return ["Tier 0", "Tier 1", "Tier 2", "Tier 3"];
  }
  if (key === "businessCriticality") {
    return BUSINESS_CRITICALITY_OPTIONS;
  }
  return [];
}

function normalizeField(field, bootstrap) {
  const key = field?.key || field?.name;
  if (!EDITABLE_FIELD_KEYS.includes(key)) return null;
  const options = fieldOptions(key, bootstrap, field);
  const requestedType = (field?.type || field?.kind || (key === "description" ? "textarea" : "select"))
    .toString()
    .toLowerCase();
  let resolvedType;
  if (key === "description" || key === "cdeRationale") {
    resolvedType = "textarea";
  } else if (key === "isCde") {
    resolvedType = "toggle";
  } else if (requestedType === "text") {
    resolvedType = "text";
  } else if (options.length) {
    resolvedType = "select";
  } else {
    resolvedType = "text";
  }
  const defaultHelpText =
    key !== "description" && !options.length
      ? `No preset ${titleCase(key).toLowerCase()} options are configured yet. Type a value to save it directly on this asset.`
      : "";
  const helpTextOverride =
    key === "freeformTags"
      ? "Comma-separated key=value pairs. Structured classification tags stay in their own fields above."
      : "";
  const placeholderOverride =
    key === "freeformTags"
      ? "owner_team=FinOps, product_area=ERP"
      : "";

  return {
    key,
    label: field?.label || titleCase(key),
    type: resolvedType,
    placeholder:
      field?.placeholder ||
      placeholderOverride ||
      (key === "description"
        ? "Add a description for this asset"
        : resolvedType === "text"
          ? `Enter ${titleCase(key).toLowerCase()}`
          : `Select ${titleCase(key).toLowerCase()}`),
    helpText: field?.helpText || field?.description || helpTextOverride || defaultHelpText,
    options,
  };
}

function normalizeConfig(config, bootstrap) {
  if (!config || typeof config !== "object") return null;

  const definedFields = Array.isArray(config.fields) ? config.fields : [];
  const fields = (definedFields.length ? definedFields : EDITABLE_FIELD_KEYS.map((key) => ({ key })))
    .map((field) => normalizeField(field, bootstrap))
    .filter(Boolean);

  return {
    available: config.available !== false,
    endpoint: config.endpoint || config.path || config.url || "",
    updatePath: config.updatePath || config.savePath || config.endpoint || config.path || config.url || "",
    updateMethod: (config.updateMethod || config.method || "PATCH").toString().toUpperCase(),
    fields,
    message: config.message || config.note || "",
  };
}

function inlineEditorConfig(asset) {
  return (
    asset?.metadataEditor ||
    asset?.metadataEdit ||
    asset?.editableMetadata ||
    asset?.metadataEditing ||
    null
  );
}

export function useAssetMetadataEditor({ assetFqn, asset, bootstrap }) {
  const contract = useMemo(() => getAssetMetadataApiContract(assetFqn), [assetFqn]);
  const localConfig = useMemo(
    () => normalizeConfig(inlineEditorConfig(asset), bootstrap),
    [asset, bootstrap],
  );

  // Capability inspection (was a hand-rolled fetch effect with a cancelled
  // flag): only fires when the asset carries no inline editor config AND the
  // API contract claims editing exists. Resolution order is preserved —
  // inline config wins, then the remote probe, then nothing.
  const remoteEnabled = Boolean(assetFqn) && !localConfig && contract.available;
  const editorProbe = useAxiomQuery({
    key: ["assetMetadataEditor", String(assetFqn || "")],
    enabled: remoteEnabled,
    fetch: () => fetchAssetMetadataEditor(assetFqn),
    staleTime: 60_000,
  });
  const remoteConfig = useMemo(
    () =>
      remoteEnabled && editorProbe.query.data
        ? normalizeConfig(editorProbe.query.data, bootstrap)
        : null,
    [bootstrap, editorProbe.query.data, remoteEnabled],
  );

  const config = localConfig || remoteConfig || null;
  const available = localConfig
    ? localConfig.available
    : remoteConfig
      ? remoteConfig.available || false
      : false;

  const saveMutation = useAxiomMutation({
    mutate: (payload) => updateAssetMetadata(assetFqn, payload, config || {}),
  });

  // Switching assets must clear stale submit feedback (the old state machine
  // reset submitError/submitSuccess on every fqn change).
  const resetSave = saveMutation.reset;
  useEffect(() => {
    resetSave();
  }, [assetFqn, resetSave]);

  // Derive the bespoke submit copy from the mutation result instead of a
  // parallel useState machine — one source of truth for write status.
  const response = saveMutation.data;
  const responseWarning = String(response?.warning || "").trim();
  const approvalPending =
    String(response?.approval?.status || "").trim().toLowerCase() === "pending";
  const submitSuccess = !response
    ? ""
    : approvalPending
      ? "Submitted for approval. A steward needs to review before it applies to Unity Catalog."
      : responseWarning
        ? "Metadata saved with warning."
        : "Metadata saved.";
  const submitError = saveMutation.error
    ? saveMutation.error?.message || "Failed to save metadata."
    : response && !approvalPending
      ? responseWarning
      : "";

  return {
    loading: remoteEnabled && editorProbe.query.isPending,
    error:
      remoteEnabled && editorProbe.query.isError
        ? editorProbe.query.error?.message || "Failed to inspect metadata editing capabilities."
        : "",
    available,
    config,
    submitting: saveMutation.submitting,
    submitError,
    submitSuccess,
    hasContract: contract.available,
    // save() keeps its original promise semantics: resolves with the API
    // response, rethrows on failure so callers can branch.
    save: saveMutation.mutate,
  };
}
