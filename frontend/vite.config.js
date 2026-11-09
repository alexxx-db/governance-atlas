import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

const GRAPH_PACKAGES =
  /[\\/]node_modules[\\/](@xyflow|dagre|graphlib|lodash|d3-[^\\/]+|classcat|zustand)[\\/]/;

export default defineConfig({
  plugins: [react()],
  base: "/",
  build: {
    outDir: "dist",
    emptyOutDir: true,
    rollupOptions: {
      output: {
        // Graph libraries (React Flow + dagre) only load with the lineage
        // surfaces, not with every page.
        manualChunks(id) {
          if (!id.includes("node_modules")) return undefined;
          if (GRAPH_PACKAGES.test(id)) return "graph";
          return "vendor";
        },
      },
    },
  },
  server: {
    host: "0.0.0.0",
    port: 3000,
    // Live-API dev loop: AXIOM_DEV_PROXY_TARGET + AXIOM_DEV_PROXY_TOKEN proxy
    // /api to a deployed app so visual work renders real governed data
    // without a deploy round-trip. No env vars → no proxy (unchanged).
    proxy: process.env.AXIOM_DEV_PROXY_TARGET
      ? {
          "/api": {
            target: process.env.AXIOM_DEV_PROXY_TARGET,
            changeOrigin: true,
            headers: process.env.AXIOM_DEV_PROXY_TOKEN
              ? { Authorization: `Bearer ${process.env.AXIOM_DEV_PROXY_TOKEN}` }
              : {},
          },
        }
      : undefined,
  },
  test: {
    environment: "jsdom",
    fileParallelism: false,
    setupFiles: "./src/test/setup.js",
    testTimeout: 30_000,
  },
});
