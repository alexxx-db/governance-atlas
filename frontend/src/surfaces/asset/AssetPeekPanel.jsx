import "./asset.css";
import { useMemo } from "react";
import { Badge, Button, Drawer, EntityChip } from "../../components/system";
import { useAsset360 } from "../../hooks/useAsset360";
import { useAssetDetail } from "../../hooks/useAssetDetail";
import { useAtlasNavigate } from "../../nav/useAtlasNavigate";
import { AssetTrustHero } from "./AssetTrustHero";
import { ExternalLink, catalogExplorerUrl, useWorkspaceHost } from "./ExternalLink";

/*
 * AssetPeekPanel — the ?peek=<fqn> quick preview (teardown item 11 / P3-15).
 * Identity + the SAME trust-verdict component the hub renders (so drawer and
 * page can never contradict each other) + a few honest key facts + one door:
 * "Open full record". No dead tabs, no developer "Buildability note" copy.
 *
 * The shell binds ?peek= via nav/usePeek and mounts this with {fqn, open,
 * onClose}; the panel owns its own data (same two parallel queries as the
 * hub, header sections only).
 */

const PEEK_SECTIONS = ["header"];

function fact(label, value) {
  const text = value == null || value === "" ? "—" : String(value);
  return { label, text };
}

export function AssetPeekPanel({ fqn = "", open = true, onClose = null }) {
  const active = Boolean(fqn) && open;
  const detail = useAssetDetail(fqn, { sections: PEEK_SECTIONS, enabled: active });
  const a360 = useAsset360(fqn, { enabled: active });
  const navigate = useAtlasNavigate();

  // Same stub guards as AssetHubPage: hydrating inventory stubs are not
  // assets, and unknown owner slots stay busy while /360 is pending —
  // without this the peek contradicted the hub (score-0 flash, permanent
  // "Unassigned" owners; C1/C2 verifier BLOCK).
  const isHydratingStub = (candidate) =>
    Boolean(candidate) &&
    (candidate.hydrating === true ||
      String(candidate.headerSource || "") === "live-metadata-hydrating");
  const a360Asset = a360.data?.sameAsset ? a360.data.asset : null;
  const asset =
    (isHydratingStub(detail.detail) ? null : detail.detail) ||
    (isHydratingStub(a360Asset) ? null : a360Asset) ||
    null;
  const freshness = a360.data?.freshness || null;
  const ownership = a360.data?.ownership || null;
  const ownershipPending = a360.loading || isHydratingStub(a360Asset);

  const facts = useMemo(
    () => [
      fact("Type", asset?.objectType),
      fact("Rows", asset?.rows),
      fact("Size", asset?.size),
      fact("Format", asset?.storageFormat || asset?.format),
    ],
    [asset],
  );

  // Owner directive 2: the peek drawer gets the SAME first-class "Open in
  // Databricks" affordance as the hub header — deepLink preferred, constructed
  // Catalog Explorer URL as the fallback for any real FQN.
  const workspaceHost = useWorkspaceHost();
  const explorerHref = catalogExplorerUrl(fqn, a360.data?.access?.deepLinks?.catalogExplorer, workspaceHost);

  const openFullRecord = () => {
    onClose?.();
    navigate({ kind: "asset", fqn });
  };

  return (
    <Drawer
      open={active}
      onClose={onClose}
      title={asset?.name || fqn}
      className="ga-asset-peek"
      footer={
        <div className="ga-asset-peek-footer">
          <ExternalLink href={explorerHref} />
          <Button variant="primary" tone="accent" onClick={openFullRecord}>
            Open full record
          </Button>
        </div>
      }
    >
      <p className="ga-asset-peek-fqn" title={fqn}>
        {fqn}
      </p>

      <AssetTrustHero
        asset={asset}
        freshness={freshness}
        ownership={ownership}
        hydrating={!asset && (detail.loading || a360.loading)}
        ownershipPending={ownershipPending}
        compact
      />

      <dl className="ga-asset-facts ga-asset-peek-facts">
        {facts.map((item) => (
          <div key={item.label} className="ga-asset-fact">
            <dt>{item.label}</dt>
            <dd>{item.text}</dd>
          </div>
        ))}
        {asset?.domain && asset.domain !== "Unassigned" ? (
          <div className="ga-asset-fact">
            <dt>Domain</dt>
            <dd>
              <EntityChip appearance="inline" entity={{ kind: "domain", name: asset.domain }} />
            </dd>
          </div>
        ) : null}
      </dl>

      {detail.error && !asset ? (
        <Badge tone="bad">{detail.error}</Badge>
      ) : null}
    </Drawer>
  );
}

export default AssetPeekPanel;
