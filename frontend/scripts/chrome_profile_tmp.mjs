import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";

export async function resolveChromeProfileName(chromeProfileRoot, explicitName = "") {
  if (explicitName) return explicitName;
  try {
    const localStateRaw = await fs.readFile(path.join(chromeProfileRoot, "Local State"), "utf8");
    const localState = JSON.parse(localStateRaw);
    return localState?.profile?.last_used || "Default";
  } catch {
    return "Default";
  }
}

export async function copyChromeProfileToTemp({
  chromeProfileRoot,
  profileName,
  prefix = "axiom-chrome-profile-",
}) {
  const tempRoot = await fs.mkdtemp(path.join(os.tmpdir(), prefix));
  for (const sourcePath of [
    path.join(chromeProfileRoot, "Local State"),
    path.join(chromeProfileRoot, profileName),
  ]) {
    const targetPath = path.join(tempRoot, path.basename(sourcePath));
    try {
      const stats = await fs.stat(sourcePath);
      if (stats.isDirectory()) {
        await fs.cp(sourcePath, targetPath, { recursive: true, force: true });
      } else {
        await fs.copyFile(sourcePath, targetPath);
      }
    } catch {
      // Missing auth files surface as navigation failures.
    }
  }
  return {
    profileRoot: tempRoot,
    cleanup: async () => fs.rm(tempRoot, { recursive: true, force: true }).catch(() => {}),
  };
}
