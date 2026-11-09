import js from "@eslint/js";
import globals from "globals";
import react from "eslint-plugin-react";
import reactHooks from "eslint-plugin-react-hooks";
import unusedImports from "eslint-plugin-unused-imports";

/* ------------------------------------------------------------------ */
/* Wave A3 anti-dispersion guardrails (FRONTEND_BLUEPRINT §10)          */
/*                                                                      */
/* Flipped to ERRORS in Wave C8: every surface is migrated; new debt    */
/* fails the lint gate outright.                                        */
/*                                                                      */
/* NOTE on structure: `no-restricted-syntax` is NOT additive across     */
/* overlapping flat-config objects — the last matching object replaces  */
/* the whole rule. So the scopes below are DISJOINT, and each carries   */
/* the full union of selectors that apply to it.                        */
/* ------------------------------------------------------------------ */

const TEST_IGNORES = ["src/**/*.test.{js,jsx}", "src/**/__tests__/**", "src/test/**"];

// Data access goes through hooks/ + lib/ (useAxiomQuery / api.js) only.
const FETCH_SELECTORS = [
  {
    selector: "CallExpression[callee.name='fetch']",
    message:
      "Direct fetch() outside hooks/ + lib/ — data access goes through the hooks layer (useAxiomQuery). [enforced since Wave C8]",
  },
  {
    selector: "CallExpression[callee.object.name='window'][callee.property.name='fetch']",
    message:
      "Direct window.fetch() outside hooks/ + lib/ — data access goes through the hooks layer (useAxiomQuery). [enforced since Wave C8]",
  },
];

// Preference-state lives behind ONE typed helper: lib/prefs.js (Wave A2 owns
// creating it). URL state belongs in the URL (nav/useSurfaceParams).
const STORAGE_SELECTORS = [
  {
    selector: "MemberExpression[object.name=/^(sessionStorage|localStorage)$/]",
    message:
      "Direct web-storage access — preference state goes through lib/prefs.js; restorable view state goes in the URL (nav/useSurfaceParams). [enforced since Wave C8]",
  },
  {
    selector: "MemberExpression[property.name=/^(sessionStorage|localStorage)$/]",
    message:
      "Direct web-storage access — preference state goes through lib/prefs.js; restorable view state goes in the URL (nav/useSurfaceParams). [enforced since Wave C8]",
  },
];

// Custom window events were one of the 7 parallel navigation mechanisms.
// Cross-surface intent is navigate(ref) (nav/useAxiomNavigate); only the
// app-shell may broker window-level events (e.g. the palette opener).
const CUSTOM_EVENT_SELECTORS = [
  {
    selector: "NewExpression[callee.name='CustomEvent']",
    message:
      "Custom window events outside app-shell/ — use navigate(entityRef) from nav/useAxiomNavigate instead of event buses. [enforced since Wave C8]",
  },
];

// window.history bypasses the router and silently drops app state; banned
// EVERYWHERE — even app-shell goes through react-router.
const HISTORY_SELECTORS = [
  {
    selector: "MemberExpression[object.name='window'][property.name='history']",
    message:
      "window.history bypasses the router — use nav/useSurfaceParams (params) or nav/useAxiomNavigate (navigation). [enforced since Wave C8]",
  },
];

// Polling is always bounded and always owned by useAxiomQuery (§10 guardrail 3).
// Hooks keep their legacy refetchInterval until the Wave A2 refactor lands.
const REFETCH_SELECTORS = [
  {
    selector: "Property[key.name='refetchInterval']",
    message:
      "refetchInterval outside hooks/ — polling is owned (and bounded) by useAxiomQuery. [enforced since Wave C8]",
  },
];

const RESTRICTED_QUERY_IMPORTS = {
  "no-restricted-imports": [
    "error",
    {
      paths: [
        {
          name: "@tanstack/react-query",
          importNames: [
            "useQuery",
            "useQueries",
            "useInfiniteQuery",
            "useSuspenseQuery",
            "useMutation",
            "useQueryClient",
          ],
          message:
            "react-query hooks outside hooks/ + lib/ — components consume data via the hooks layer (useAxiomQuery). [enforced since Wave C8]",
        },
      ],
      patterns: [
        {
          group: ["**/lib/queryClient", "**/lib/queryClient.js"],
          message:
            "axiomQueryClient is not a cross-surface bus — cache coordination lives inside hooks/ + lib/. [enforced since Wave C8]",
        },
      ],
    },
  ],
};

const guardrailConfigs = [
  // Scope 1: components/surfaces — everything banned here.
  // main.jsx is exempt as the QueryClientProvider root (rewritten in Wave B1).
  {
    files: ["src/**/*.{js,jsx}"],
    ignores: [
      "src/hooks/**",
      "src/lib/**",
      "src/app-shell/**",
      "src/main.jsx",
      ...TEST_IGNORES,
    ],
    rules: {
      ...RESTRICTED_QUERY_IMPORTS,
      "no-restricted-syntax": [
        "error",
        ...FETCH_SELECTORS,
        ...STORAGE_SELECTORS,
        ...CUSTOM_EVENT_SELECTORS,
        ...HISTORY_SELECTORS,
        ...REFETCH_SELECTORS,
      ],
    },
  },
  // Scope 2: the data layer — fetch/react-query/refetchInterval are its job,
  // but storage, custom events, and history bypasses are still banned.
  // lib/prefs.js (the one sanctioned storage module, owned by Wave A2) is
  // carved out below in scope 3.
  {
    files: ["src/hooks/**/*.{js,jsx}", "src/lib/**/*.{js,jsx}"],
    ignores: ["src/lib/prefs.js", ...TEST_IGNORES],
    rules: {
      "no-restricted-syntax": [
        "error",
        ...STORAGE_SELECTORS,
        ...CUSTOM_EVENT_SELECTORS,
        ...HISTORY_SELECTORS,
      ],
    },
  },
  // Scope 3: lib/prefs.js — the ONLY file allowed to touch web storage.
  {
    files: ["src/lib/prefs.js"],
    rules: {
      "no-restricted-syntax": ["error", ...CUSTOM_EVENT_SELECTORS, ...HISTORY_SELECTORS],
    },
  },
  // Scope 4: app-shell (arrives in Wave B1) — may broker CustomEvents (palette
  // opener), but not fetch, storage, or history bypasses.
  {
    files: ["src/app-shell/**/*.{js,jsx}"],
    ignores: [...TEST_IGNORES],
    rules: {
      ...RESTRICTED_QUERY_IMPORTS,
      "no-restricted-syntax": [
        "error",
        ...FETCH_SELECTORS,
        ...STORAGE_SELECTORS,
        ...HISTORY_SELECTORS,
        ...REFETCH_SELECTORS,
      ],
    },
  },
];

export default [
  {
    ignores: ["dist/**", "node_modules/**"],
  },
  js.configs.recommended,
  {
    files: ["src/**/*.{js,jsx}", "vite.config.js"],
    languageOptions: {
      ecmaVersion: "latest",
      sourceType: "module",
      parserOptions: {
        ecmaFeatures: {
          jsx: true,
        },
      },
      globals: {
        ...globals.browser,
        ...globals.node,
      },
    },
    plugins: {
      react,
      "react-hooks": reactHooks,
      "unused-imports": unusedImports,
    },
    settings: {
      react: {
        version: "detect",
      },
    },
    rules: {
      "no-undef": "error",
      "no-unused-vars": "off",
      "unused-imports/no-unused-imports": "error",
      "react/jsx-uses-vars": "error",
      "react-hooks/rules-of-hooks": "error",
      "react-hooks/exhaustive-deps": "warn",
      ...reactHooks.configs.recommended.rules,
    },
  },
  ...guardrailConfigs,
];
