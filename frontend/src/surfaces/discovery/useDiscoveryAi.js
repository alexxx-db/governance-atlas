/*
 * surfaces/discovery/useDiscoveryAi.js — Axiom AI recommendations for the
 * Discover surface (Wave C1 port of the legacy askAxiomForDiscovery machinery,
 * behavior-preserving: abort-on-scope-change, 60s timeout, request-sequence
 * guard, non-authoritative rejection, and a TTL-bounded session cache — now
 * through lib/prefs.js instead of raw sessionStorage).
 *
 * Genie recommendations are an explicit user action (a click), not a poll, so
 * this stays an imperative hook rather than a useAxiomQuery consumer.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { fetchAxiomAiRecommendations } from "../../lib/api";
import { isNonAuthoritativeMockEvidence } from "../../lib/nonAuthoritativeEvidence";
import { readSessionCache, removeSessionCache, writeSessionCache } from "../../lib/prefs";

const AI_CACHE_PREFIX = "discovery-ai.";
const AI_CACHE_TTL_MS = 10 * 60 * 1000;
const AI_REQUEST_TIMEOUT_MS = 60_000;

function cacheKeyFor(scopeKey = "default", query = "") {
  const raw = `${scopeKey || "default"}::${String(query || "").trim()}`;
  return `${AI_CACHE_PREFIX}${raw.replace(/[^a-z0-9._:-]+/gi, "_").slice(0, 180)}`;
}

/**
 * A response with no recommendations AND explicit non-authoritative /
 * unavailable markers yields its own reason string; "" means the response is
 * renderable (possibly empty for honest reasons).
 */
export function axiomAiUnavailableResponseMessage(response = null) {
  if (!response || response.nonAuthoritative) return "";
  const recommendations = Array.isArray(response.recommendations) ? response.recommendations : [];
  if (recommendations.length) return "";
  const state = String(
    response.state ||
      response.status ||
      response.intent ||
      response.meta?.state ||
      response.providerState?.state ||
      "",
  ).toLowerCase();
  const authorityFalse =
    response.authoritative === false ||
    response.meta?.authoritative === false ||
    response.liveDatabricksEvidence === false;
  if (!authorityFalse || !/(unavailable|degraded|error|limited|unknown)/i.test(state)) return "";
  const warnings = Array.isArray(response.warnings)
    ? response.warnings
    : Array.isArray(response.meta?.warnings)
      ? response.meta.warnings
      : [];
  return (
    warnings.map((warning) => String(warning || "").trim()).find(Boolean) ||
    String(
      response.warning ||
        response.message ||
        response.reason ||
        response.providerState?.message ||
        "",
    ).trim() ||
    "Axiom AI recommendations are unavailable until Databricks Genie returns evidence."
  );
}

function readAiCache(cacheKey) {
  const cached = readSessionCache(cacheKey, { ttlMs: AI_CACHE_TTL_MS });
  if (!cached) return null;
  if (axiomAiUnavailableResponseMessage(cached)) {
    // Never serve a stale "unavailable" verdict from cache — re-ask live.
    removeSessionCache(cacheKey);
    return null;
  }
  return cached;
}

export function useDiscoveryAi({
  scopeKey = "default",
  query = "",
  available = true,
  unavailableReason = "",
}) {
  const cacheKey = cacheKeyFor(scopeKey, query);
  const [state, setState] = useState({ loading: false, response: null, error: "", cacheKey: "" });
  const abortRef = useRef(null);
  const cacheKeyRef = useRef(cacheKey);
  const requestSeqRef = useRef(0);

  // Scope change: abort any in-flight ask, adopt the cached response for the
  // new scope (or a clean slate) so stale recommendations never linger.
  useEffect(() => {
    cacheKeyRef.current = cacheKey;
    abortRef.current?.abort?.();
    const cached = readAiCache(cacheKey);
    setState((current) => {
      if (cached) return { loading: false, response: cached, error: "", cacheKey };
      if (current.cacheKey === cacheKey) return current;
      return { loading: false, response: null, error: "", cacheKey };
    });
  }, [cacheKey]);

  useEffect(() => () => abortRef.current?.abort?.(), []);

  const run = useCallback(() => {
    if (!available) {
      setState({ loading: false, response: null, error: unavailableReason, cacheKey });
      return;
    }
    const requestCacheKey = cacheKey;
    const cached = readAiCache(requestCacheKey);
    if (cached) {
      setState({ loading: false, response: cached, error: "", cacheKey: requestCacheKey });
      return;
    }
    abortRef.current?.abort?.();
    const controller = new AbortController();
    abortRef.current = controller;
    const requestId = requestSeqRef.current + 1;
    requestSeqRef.current = requestId;
    const timeoutId = setTimeout(() => controller.abort(), AI_REQUEST_TIMEOUT_MS);

    setState((current) => ({
      loading: true,
      response: current.cacheKey === requestCacheKey ? current.response : null,
      error: "",
      cacheKey: requestCacheKey,
    }));

    fetchAxiomAiRecommendations(
      query
        ? `Recommend governed assets and priorities for this Discovery search: ${query}`
        : "Recommend the next governed assets and governance priorities for Discovery.",
      { signal: controller.signal },
    )
      .then((response) => {
        clearTimeout(timeoutId);
        // A newer ask or a scope change supersedes this response entirely.
        if (requestSeqRef.current !== requestId || cacheKeyRef.current !== requestCacheKey) return;
        if (abortRef.current === controller) abortRef.current = null;
        if (
          response?.nonAuthoritative ||
          isNonAuthoritativeMockEvidence(response, response?.recommendations, response?.warnings)
        ) {
          setState({
            loading: false,
            response: { nonAuthoritative: true, recommendations: [] },
            error: "",
            cacheKey: requestCacheKey,
          });
          return;
        }
        if (!axiomAiUnavailableResponseMessage(response)) {
          // Only renderable (authoritative, evidence-backed) responses cache.
          writeSessionCache(requestCacheKey, response);
        }
        setState({ loading: false, response, error: "", cacheKey: requestCacheKey });
      })
      .catch((error) => {
        clearTimeout(timeoutId);
        if (requestSeqRef.current !== requestId || cacheKeyRef.current !== requestCacheKey) return;
        if (abortRef.current === controller) abortRef.current = null;
        setState({
          loading: false,
          response: null,
          cacheKey: requestCacheKey,
          error:
            error?.name === "AbortError"
              ? "Axiom AI recommendations are taking longer than expected. Try again."
              : error?.message || "Axiom AI recommendations are unavailable.",
        });
      });
  }, [available, cacheKey, query, unavailableReason]);

  // Views into the state that never leak a previous scope's answer.
  const visible = state.cacheKey === cacheKey ? state : { loading: false, response: null, error: "" };
  const nonAuthoritative =
    Boolean(visible.response?.nonAuthoritative) ||
    isNonAuthoritativeMockEvidence(
      visible.response,
      visible.response?.recommendations,
      visible.response?.warnings,
    );
  const unavailableMessage = axiomAiUnavailableResponseMessage(visible.response);
  const recommendations =
    !nonAuthoritative && !unavailableMessage && Array.isArray(visible.response?.recommendations)
      ? visible.response.recommendations
      : [];

  return {
    loading: visible.loading,
    error: visible.error,
    response: visible.response,
    recommendations,
    nonAuthoritative,
    unavailableMessage,
    run,
  };
}

export default useDiscoveryAi;
