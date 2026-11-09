import { afterEach, describe, expect, it, vi } from "vitest";
import {
  fetchemetOverview,
  fetchemetRun,
  fetchemetRunLive,
  fetchemetStatus,
  pollemetGenie,
  startemetGenie,
  triggeremetRun,
} from "./api";

function captureFetch() {
  const fetchMock = vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    headers: new Headers({ "content-type": "application/json" }),
    json: async () => ({ ok: true }),
    text: async () => "{}",
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function lastCall(fetchMock) {
  const [url, options] = fetchMock.mock.calls[fetchMock.mock.calls.length - 1];
  return { url: String(url), options: options || {} };
}

describe("emet API contract", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("reads status + overview via GET on the emet routes", async () => {
    const fetchMock = captureFetch();
    await fetchemetStatus();
    expect(lastCall(fetchMock).url).toMatch(/\/api\/emet\/status$/);
    expect((lastCall(fetchMock).options.method || "GET")).toBe("GET");

    await fetchemetOverview();
    expect(lastCall(fetchMock).url).toMatch(/\/api\/emet\/overview$/);

    await fetchemetOverview({ refresh: true });
    expect(lastCall(fetchMock).url).toMatch(/\/api\/emet\/overview\?refresh=1$/);
  });

  it("reads run detail + live status keyed by run id", async () => {
    const fetchMock = captureFetch();
    await fetchemetRun(987);
    expect(lastCall(fetchMock).url).toMatch(/\/api\/emet\/runs\/987$/);
    await fetchemetRunLive(987);
    expect(lastCall(fetchMock).url).toMatch(/\/api\/emet\/runs\/987\/live$/);
  });

  it("triggers a run via POST with an explicit confirm flag", async () => {
    const fetchMock = captureFetch();
    await triggeremetRun(55, { confirm: true, idempotencyToken: "tok" });
    const { url, options } = lastCall(fetchMock);
    expect(url).toMatch(/\/api\/emet\/jobs\/55\/run$/);
    expect(options.method).toBe("POST");
    expect(JSON.parse(options.body)).toEqual({ confirm: true, idempotencyToken: "tok" });
  });

  it("drives the Signal Room via genie start + poll POSTs", async () => {
    const fetchMock = captureFetch();
    await startemetGenie("How is trust trending?");
    let call = lastCall(fetchMock);
    expect(call.url).toMatch(/\/api\/emet\/genie\/start$/);
    expect(call.options.method).toBe("POST");
    expect(JSON.parse(call.options.body)).toEqual({ question: "How is trust trending?" });

    await pollemetGenie("conv-1", "msg-1");
    call = lastCall(fetchMock);
    expect(call.url).toMatch(/\/api\/emet\/genie\/poll$/);
    expect(JSON.parse(call.options.body)).toEqual({ conversationId: "conv-1", messageId: "msg-1" });
  });
});
