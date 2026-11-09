import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  pushRecentAsset,
  readDiscoveryDensity,
  readFavoriteAssets,
  readLastAsset,
  readPref,
  readSavedSearches,
  readSessionCache,
  toggleFavoriteAsset,
  writeLastAsset,
  writePref,
  writeSessionCache,
} from "./prefs";

// The vitest environment ships no real web storage; install in-memory stubs
// so the persistence contract (incl. legacy-key migration) is assertable.
function storageStub() {
  let map = new Map();
  return {
    getItem: (key) => (map.has(key) ? map.get(key) : null),
    setItem: (key, value) => map.set(key, String(value)),
    removeItem: (key) => map.delete(key),
    clear: () => {
      map = new Map();
    },
  };
}

beforeEach(() => {
  Object.defineProperty(window, "localStorage", {
    value: storageStub(),
    configurable: true,
    writable: true,
  });
  Object.defineProperty(window, "sessionStorage", {
    value: storageStub(),
    configurable: true,
    writable: true,
  });
});

describe("lib/prefs — namespaced preferences", () => {
  it("round-trips a registered pref under the ga.prefs namespace", () => {
    writePref("favoriteAssets", ["a.b.c"]);
    expect(readFavoriteAssets()).toEqual(["a.b.c"]);
    expect(JSON.parse(window.localStorage.getItem("ax.prefs.favoriteAssets"))).toEqual(["a.b.c"]);
  });

  it("reads legacy gh-* keys backward-compatibly and migrates them forward", () => {
    window.localStorage.setItem("gh-favorite-assets", JSON.stringify(["x.y.z"]));
    window.localStorage.setItem(
      "gh-saved-searches",
      JSON.stringify([{ id: "s1", name: "Finance", query: "revenue" }]),
    );
    window.localStorage.setItem("gh-discovery-density", "compact");

    expect(readFavoriteAssets()).toEqual(["x.y.z"]);
    expect(readSavedSearches()).toEqual([{ id: "s1", name: "Finance", query: "revenue" }]);
    expect(readDiscoveryDensity()).toBe("compact");
    // Migrated forward: the new key now exists.
    expect(window.localStorage.getItem("ax.prefs.favoriteAssets")).not.toBeNull();
  });

  it("maps the legacy density vocabulary (normal/spacious) to comfortable", () => {
    window.localStorage.setItem("gh-discovery-density", "spacious");
    expect(readDiscoveryDensity()).toBe("comfortable");
  });

  it("toggleFavoriteAsset adds then removes", () => {
    expect(toggleFavoriteAsset("a.b.c")).toEqual(["a.b.c"]);
    expect(toggleFavoriteAsset("a.b.c")).toEqual([]);
  });

  it("pushRecentAsset dedupes, front-loads, and caps at 20", () => {
    for (let index = 0; index < 25; index += 1) pushRecentAsset(`asset.${index}`);
    const next = pushRecentAsset("asset.3");
    expect(next[0]).toBe("asset.3");
    expect(next.length).toBeLessThanOrEqual(20);
    expect(new Set(next).size).toBe(next.length);
  });

  it("remembers the last opened Asset 360 record (empty by default)", () => {
    expect(readLastAsset()).toBe("");
    writeLastAsset("main.sales.orders");
    expect(readLastAsset()).toBe("main.sales.orders");
    // Non-string / clearing writes normalize to "".
    writeLastAsset("");
    expect(readLastAsset()).toBe("");
  });

  it("degrades to fallbacks when storage is unavailable", () => {
    Object.defineProperty(window, "localStorage", {
      get() {
        throw new Error("blocked");
      },
      configurable: true,
    });
    expect(readFavoriteAssets()).toEqual([]);
    expect(readPref("discoveryLayout")).toBe("list");
  });
});

describe("lib/prefs — session caches", () => {
  it("round-trips values and honors the TTL", () => {
    writeSessionCache("k", { hello: "world" });
    expect(readSessionCache("k")).toEqual({ hello: "world" });
    const nowSpy = vi.spyOn(Date, "now").mockReturnValue(Date.now() + 11 * 60 * 1000);
    expect(readSessionCache("k", { ttlMs: 10 * 60 * 1000 })).toBeNull();
    nowSpy.mockRestore();
  });
});
