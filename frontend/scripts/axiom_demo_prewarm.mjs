#!/usr/bin/env node

const DEFAULT_QUERY = process.env.AXIOM_PREWARM_QUERY || "mortgage";
const BASE_URL = (process.env.AXIOM_PREWARM_BASE_URL || "http://127.0.0.1:8000").replace(/\/+$/, "");
const ASSETS = (process.env.AXIOM_PREWARM_ASSETS || "")
  .split(",")
  .map((value) => value.trim())
  .filter(Boolean);
const TIMEOUT_MS = Number(process.env.AXIOM_PREWARM_TIMEOUT_MS || 120000);
const REQUEST_TIMEOUT_MS = Number(process.env.AXIOM_PREWARM_REQUEST_TIMEOUT_MS || 20000);
const DATABRICKS_TOKEN = process.env.AXIOM_DATABRICKS_TOKEN || "";

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function request(path, options = {}) {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    const response = await fetch(`${BASE_URL}${path}`, {
      ...options,
      headers: {
        "content-type": "application/json",
        ...(DATABRICKS_TOKEN ? { Authorization: `Bearer ${DATABRICKS_TOKEN}` } : {}),
        ...(options.headers || {}),
      },
      signal: controller.signal,
    });
    const text = await response.text();
    let body = {};
    try {
      body = text ? JSON.parse(text) : {};
    } catch {
      body = { raw: text };
    }
    return {
      ok: response.ok,
      status: response.status,
      path,
      body,
    };
  } finally {
    clearTimeout(timeoutId);
  }
}

function stateOf(payload) {
  return String(payload?.meta?.state || payload?.state || "").trim().toLowerCase();
}

async function poll(path, isReady) {
  const started = Date.now();
  let last = null;
  while (Date.now() - started < TIMEOUT_MS) {
    last = await request(path);
    if (last.ok && isReady(last.body)) return last;
    await sleep(3000);
  }
  return last;
}

function searchAssets(payload) {
  const candidates = [
    payload?.assets,
    payload?.results,
    payload?.items,
    payload?.data?.assets,
    payload?.data?.results,
  ];
  for (const candidate of candidates) {
    if (Array.isArray(candidate)) {
      return candidate.map((asset) => asset?.fqn || asset?.assetFqn).filter(Boolean);
    }
  }
  return [];
}

async function main() {
  const summary = [];
  for (const path of ["/api/bootstrap", "/api/runtime/status"]) {
    const result = await request(path);
    summary.push({ path, status: result.status, state: stateOf(result.body) || "returned" });
  }

  const searchPath = `/api/discovery/search?query=${encodeURIComponent(DEFAULT_QUERY)}&limit=12`;
  const search = await request(searchPath);
  summary.push({ path: searchPath, status: search.status, state: stateOf(search.body) || "returned" });
  const searchFqns = search.ok ? searchAssets(search.body) : [];
  const focusAssets = [...new Set([...ASSETS, ...searchFqns])].slice(0, 3);

  const recommendations = await poll(
    "/api/lineage/recommendations?limit=8",
    (body) => stateOf(body) !== "loading" && Array.isArray(body?.items),
  );
  summary.push({
    path: "/api/lineage/recommendations?limit=8",
    status: recommendations?.status || 0,
    state: stateOf(recommendations?.body) || "unknown",
    items: Array.isArray(recommendations?.body?.items) ? recommendations.body.items.length : 0,
  });

  if (focusAssets.length) {
    const headers = await request("/api/assets/headers", {
      method: "POST",
      body: JSON.stringify({ assets: focusAssets }),
    });
    summary.push({
      path: "/api/assets/headers",
      status: headers.status,
      state: stateOf(headers.body) || "returned",
      assets: focusAssets.length,
    });
  }

  for (const asset of focusAssets) {
    const encoded = encodeURIComponent(asset);
    const evidence = await request(`/api/assets/${encoded}/databricks-evidence`);
    summary.push({
      path: `/api/assets/${asset}/databricks-evidence`,
      status: evidence.status,
      state: stateOf(evidence.body) || "returned",
      qualityMonitoring: evidence.body?.data?.qualityMonitoring?.state || evidence.body?.qualityMonitoring?.state || "",
      lakeflow: evidence.body?.data?.lakeflow?.state || evidence.body?.lakeflow?.state || "",
    });
    const initial = await request(`/api/lineage/${encoded}?profile=initial`);
    summary.push({ path: `/api/lineage/${asset}?profile=initial`, status: initial.status, state: stateOf(initial.body) || "returned" });
    const full = await poll(
      `/api/lineage/${encoded}?profile=full`,
      (body) => stateOf(body) !== "loading",
    );
    summary.push({ path: `/api/lineage/${asset}?profile=full`, status: full?.status || 0, state: stateOf(full?.body) || "unknown" });
  }

  console.log(JSON.stringify({ baseUrl: BASE_URL, generatedAt: new Date().toISOString(), summary }, null, 2));
}

main().catch((error) => {
  console.error(error?.stack || error?.message || error);
  process.exitCode = 1;
});
