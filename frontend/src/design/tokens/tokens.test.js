import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { describe, expect, it } from "vitest";

const here = dirname(fileURLToPath(import.meta.url));
const colorsCss = readFileSync(join(here, "colors.css"), "utf8");

function tokenValue(name) {
  const match = colorsCss.match(new RegExp(`${name}:\\s*([^;]+);`));
  return match?.[1]?.trim() || "";
}

describe("Axiom design tokens", () => {
  it("uses dark shell tokens", () => {
    expect(tokenValue("--ax-bright-blue")).toBe("#7497dc");
    expect(tokenValue("--ax-bg")).toBe("#08172a");
  });

  it("defines only the compatibility aliases the surviving legacy sheets consume", () => {
    // Cohesion follow-up 3: app/entity/governance.css are dead, so only the
    // four aliases northstar.css + shell-rail.css still read may remain.
    ["--gh-bg", "--gh-line", "--gh-ink", "--gh-ink-muted"].forEach((token) => {
      expect(tokenValue(token)).not.toBe("");
    });
    // Aliases must not creep back once their last consumer died.
    ["--gh-surface", "--gh-border", "--gh-text", "--gh-accent", "--gh-font"].forEach((token) => {
      expect(tokenValue(token)).toBe("");
    });
  });
});
