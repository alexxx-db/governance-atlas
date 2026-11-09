import "./help.css";
import { useEffect } from "react";
import { Button, PageShell, SectionCard } from "../../components/system";

/*
 * surfaces/help/HelpPage.jsx — the routed /help surface (cohesion follow-up
 * 3). Replaces components/HelpPage.jsx (the last routed legacy-shell
 * consumer): one PageShell, one SectionCard per help section, ax-help-*
 * classes only. Content is static, task-oriented copy — no data hooks.
 */

const SECTIONS = [
  {
    id: "getting-started",
    title: "Getting started",
    entries: [
      {
        heading: "What is Axiom?",
        body:
          "Axiom is a Databricks-native metadata command center. It discovers Unity Catalog tables, views, and columns in your workspace, then surfaces backed governance context such as domain, owner, sensitivity, glossary terms, workflow state, lineage, and quality evidence when those signals are available.",
      },
      {
        heading: "How do I find an asset?",
        body:
          "Use the global search bar at the top of the shell, the Discovery tab for faceted browsing across the catalog, or the Navigation tab for breadth-first catalog-tree browsing. Filters on the left rail narrow by catalog, schema, asset type, domain, owner, sensitivity, glossary term, and workflow state.",
      },
      {
        heading: "What do the coverage badges mean?",
        body:
          "The coverage score on each asset card reflects visible metadata completeness for fields such as description, owner, domain, sensitivity, tier, criticality, and data product. Quality evidence is shown separately when a backed quality source reports it.",
      },
    ],
  },
  {
    id: "authentication",
    title: "Who sees what",
    entries: [
      {
        heading: "On-behalf-of access",
        body:
          "When your workspace grants the app the OBO (on-behalf-of) scope, Axiom scopes every Unity Catalog read to your identity — you see only the catalogs, schemas, and tables your Databricks permissions allow. When OBO is unavailable, the app falls back to a workspace-wide view using the service principal, and a banner surfaces the degraded scope.",
      },
      {
        heading: "Why can't I see a catalog I have access to?",
        body:
          "If a catalog you own in Unity Catalog isn't appearing, verify: (1) your workspace grants the app the \"sql\" OBO scope, (2) the Databricks App has been re-authorized since the scope was granted, and (3) you have USE CATALOG on the catalog. The Settings → Diagnostics panel shows your current auth mode and visibility scope.",
      },
      {
        heading: "Signing out",
        body:
          "Open the profile menu in the top-right corner and choose Sign out to open your Databricks workspace sign-out page in a new tab. Axiom inherits your workspace session; signing out of Databricks also ends your app session.",
      },
    ],
  },
  {
    id: "shortcuts",
    title: "Keyboard shortcuts",
    entries: [
      {
        heading: "Quick action palette",
        body: "⌘K or Ctrl+K opens the command palette from any surface. / also opens the palette when no input is focused.",
      },
      {
        heading: "Discovery",
        body: "Click an asset card to open the preview rail. Press Enter on a focused card to open the full metadata record.",
      },
      {
        heading: "Lineage",
        body: "Arrow keys move between nodes in the lineage graph. ⌘F or Cmd+K searches within the active lineage view.",
      },
    ],
  },
  {
    id: "support",
    title: "Getting help",
    entries: [
      {
        heading: "Who owns this app in my organization?",
        body:
          "Axiom is deployed from your Databricks workspace. The workspace admin who deployed the app is the first contact for access issues, permission changes, and scope grants.",
      },
      {
        heading: "Report a bug or request a feature",
        body:
          "Use the GitHub issue tracker at github.com/alexxx-db/axiom/issues. Include: your workspace region, the surface you were on, the asset FQN (if applicable), and a screenshot. The app version is visible in Settings -> Diagnostics.",
      },
      {
        heading: "Security & compliance",
        body:
          "Axiom runs inside your Databricks workspace. No data leaves the workspace. All Unity Catalog reads respect your identity's permissions when OBO is enabled. Governance events (ownership changes, glossary edits, stewardship actions) are persisted in the governance schema you configured during setup.",
      },
    ],
  },
  {
    id: "privacy",
    title: "Privacy",
    entries: [
      {
        heading: "Data boundary",
        body:
          "Axiom runs inside your Databricks workspace. Metadata reads are scoped by the runtime authorization mode, and sample row values are not required for the Home command center.",
      },
      {
        heading: "Identity",
        body:
          "The app uses your Databricks identity for actor-scoped reads when on-behalf-of access is available. If the workspace falls back to app-principal reads, the shell surfaces that degraded visibility state.",
      },
    ],
  },
  {
    id: "terms",
    title: "Terms",
    entries: [
      {
        heading: "Operational use",
        body:
          "Use Axiom as an internal metadata and governance workspace. Review generated or AI-assisted recommendations before taking action.",
      },
      {
        heading: "Source of truth",
        body:
          "Unity Catalog, the configured governance schema, quality signals, lineage metadata, and audit events remain the authoritative sources for product surfaces.",
      },
    ],
  },
];

export function HelpPage({ onBack = null }) {
  useEffect(() => {
    if (typeof document === "undefined") return undefined;
    const previous = document.title;
    document.title = "Help — Axiom";
    return () => {
      document.title = previous;
    };
  }, []);

  return (
    <PageShell
      actions={
        onBack ? (
          <Button onClick={onBack} size="sm" variant="tertiary">
            ← Back to Discovery
          </Button>
        ) : null
      }
      className="ax-help-page"
      eyebrow="Help & docs"
      subtitle="A short, task-oriented guide to discovery, governance, and access. For a deeper reference and the full change log, visit the GitHub README."
      title="How Axiom works"
    >
      <nav aria-label="Help sections" className="ax-help-toc">
        {SECTIONS.map((section) => (
          <a className="ax-help-toc-link" href={`#${section.id}`} key={section.id}>
            {section.title}
          </a>
        ))}
      </nav>

      <div className="ax-help-sections">
        {SECTIONS.map((section) => (
          <div className="ax-help-anchor" id={section.id} key={section.id}>
            <SectionCard className="ax-help-section" title={section.title}>
              <div className="ax-help-entries">
                {section.entries.map((entry, index) => (
                  <article className="ax-help-entry" key={`${section.id}-${index}`}>
                    <h3 className="ax-help-entry-heading">{entry.heading}</h3>
                    <p className="ax-help-entry-body">{entry.body}</p>
                  </article>
                ))}
              </div>
            </SectionCard>
          </div>
        ))}
      </div>
    </PageShell>
  );
}

export default HelpPage;
