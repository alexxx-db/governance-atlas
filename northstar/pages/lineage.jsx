/* eslint-disable */
/** Lineage Atlas — full graph */
const { useState: uS4 } = React;

function LineageGraph({ compact }) {
  const { LINEAGE } = window.GA;
  const [hover, setHover] = uS4(null);
  const [colMode, setColMode] = uS4(false);

  // Compute "depth" from focus node by BFS on edges (this IS computable from UC table_lineage)
  // Negative = upstream of focus, 0 = focus, positive = downstream
  const focusId = LINEAGE.focus || (LINEAGE.nodes.find(n => n.focus) || {}).id;
  const depth = {};
  if (focusId) {
    depth[focusId] = 0;
    // upstream BFS (follow edges in reverse)
    let frontier = [focusId];
    while (frontier.length) {
      const next = [];
      frontier.forEach(id => {
        LINEAGE.edges.forEach(([a, b]) => {
          if (b === id && depth[a] === undefined) { depth[a] = depth[id] - 1; next.push(a); }
        });
      });
      frontier = next;
    }
    // downstream BFS
    frontier = [focusId];
    while (frontier.length) {
      const next = [];
      frontier.forEach(id => {
        LINEAGE.edges.forEach(([a, b]) => {
          if (a === id && depth[b] === undefined) { depth[b] = depth[id] + 1; next.push(b); }
        });
      });
      frontier = next;
    }
  }
  // Default any orphan to layer
  LINEAGE.nodes.forEach(n => {
    if (depth[n.id] === undefined) {
      const layer = (n.layer === undefined || n.layer === null) ? 0 : n.layer;
      depth[n.id] = layer - 4;
    }
  });

  const minD = Math.min(...Object.values(depth));
  const maxD = Math.max(...Object.values(depth));
  const cols = maxD - minD + 1;

  const W = compact ? 580 : 1100;
  const H = compact ? 320 : 520;
  const colW = W / cols;

  // Group nodes by depth
  const byCol = {};
  LINEAGE.nodes.forEach(n => {
    const c = depth[n.id] - minD;
    (byCol[c] = byCol[c] || []).push(n);
  });

  const positions = {};
  Object.entries(byCol).forEach(([c, ns]) => {
    const count = ns.length;
    ns.forEach((n, i) => {
      const x = +c * colW + colW / 2;
      const y = ((i + 0.5) / count) * (H - 56) + 28;
      positions[n.id] = { x, y };
    });
  });

  const nodeColor = (n) => {
    if (n.cert === 'restricted') return '#F4B740';
    if (n.cert === 'certified') return '#34D399';
    if (n.cert === 'uncertified') return '#6B829A';
    if (n.type === 'job') return '#C8C8C8';
    return '#5B7FD0';
  };

  const edgeSet = LINEAGE.edges;
  const traceConnected = (id) => {
    if (!id) return new Set();
    const set = new Set([id]);
    let changed = true;
    while (changed) {
      changed = false;
      edgeSet.forEach(([a, b]) => {
        if (set.has(a) && !set.has(b)) { set.add(b); changed = true; }
        if (set.has(b) && !set.has(a)) { set.add(a); changed = true; }
      });
    }
    return set;
  };
  const traced = traceConnected(hover);

  return (
    <div className="lineage-canvas" style={{ border: '1px solid var(--srf-line-soft)', borderRadius: 12, position: 'relative', overflow: 'hidden' }}>
      {!compact && (
        <div style={{ display: 'flex', justifyContent: 'space-between', padding: '14px 18px', borderBottom: '1px solid var(--srf-line-soft)', background: 'rgba(7,16,26,0.4)' }}>
          <div style={{ display: 'flex', gap: 16, fontSize: 11.5, color: 'var(--txt-muted)', alignItems: 'center' }}>
            <LegendDot color="#34D399" label="Certified"/>
            <LegendDot color="#5B7FD0" label="Source"/>
            <LegendDot color="#C8C8C8" label="Job / Pipeline"/>
            <LegendDot color="#F4B740" label="Restricted"/>
            <span style={{ color: 'var(--txt-subtle)', borderLeft: '1px solid var(--srf-line)', paddingLeft: 14, marginLeft: 4 }}>
              <Icon name="info" size={11} style={{ marginRight: 4 }}/>
              Topology from <span className="mono" style={{ color: 'var(--accent)' }}>system.access.table_lineage</span>
            </span>
          </div>
          <div style={{ display: 'flex', gap: 6 }}>
            <button className={`btn btn-sm ${colMode ? 'btn-primary' : 'btn-secondary'}`} onClick={() => setColMode(!colMode)}><Icon name="columns-3" size={12}/>Column lineage</button>
            <button className="btn btn-secondary btn-sm"><Icon name="zoom-in" size={12}/></button>
            <button className="btn btn-secondary btn-sm"><Icon name="download" size={12}/>Export</button>
          </div>
        </div>
      )}
      <svg width="100%" height={H} viewBox={`0 0 ${W} ${H}`} style={{ display: 'block' }}>
        <defs>
          <marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto">
            <path d="M0,0 L10,5 L0,10 z" fill="#2A4D6B"/>
          </marker>
          <marker id="arr-hi" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto">
            <path d="M0,0 L10,5 L0,10 z" fill="#5B7FD0"/>
          </marker>
          <linearGradient id="edgeGrad" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0%" stopColor="#5B7FD0" stopOpacity="0.95"/>
            <stop offset="100%" stopColor="#7497DC" stopOpacity="0.9"/>
          </linearGradient>
          <filter id="glowSoft" x="-50%" y="-50%" width="200%" height="200%">
            <feGaussianBlur stdDeviation="2" result="b"/>
            <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
          </filter>
        </defs>

        {/* upstream / focus / downstream column hint (computed, not medallion) */}
        {[...Array(cols)].map((_, c) => {
          const d = c + minD;
          const label = d === 0 ? 'FOCUS' : d < 0 ? `${Math.abs(d)} HOP${Math.abs(d) > 1 ? 'S' : ''} UPSTREAM` : `${d} HOP${d > 1 ? 'S' : ''} DOWNSTREAM`;
          return (
            <g key={c}>
              <rect x={c * colW} y="0" width={colW} height={H}
                fill={d === 0 ? 'rgba(91,127,208,0.06)' : c % 2 === 0 ? 'rgba(91,127,208,0.018)' : 'transparent'}/>
              <text x={c * colW + colW/2} y={14} fontSize="9"
                fill={d === 0 ? 'var(--accent)' : 'var(--txt-subtle)'}
                textAnchor="middle" letterSpacing="2.2" fontWeight="700" opacity={d === 0 ? 0.85 : 0.5}>
                {label}
              </text>
            </g>
          );
        })}

        {LINEAGE.edges.map(([a, b], i) => {
          const p1 = positions[a], p2 = positions[b];
          if (!p1 || !p2) return null;
          const isHi = hover && traced.has(a) && traced.has(b);
          const isFocusEdge = a === focusId || b === focusId;
          const cx = (p1.x + p2.x) / 2;
          const d = `M${p1.x + 65},${p1.y} C${cx},${p1.y} ${cx},${p2.y} ${p2.x - 65},${p2.y}`;
          const pid = `edge-${i}`;
          return (
            <g key={i}>
              <path id={pid} className="lineage-edge" d={d}
                fill="none"
                stroke={isHi ? 'url(#edgeGrad)' : isFocusEdge ? 'rgba(91,127,208,0.65)' : 'var(--srf-line)'}
                strokeWidth={isHi ? 2.4 : isFocusEdge ? 1.8 : 1.2}
                markerEnd={isHi ? 'url(#arr-hi)' : 'url(#arr)'}
                opacity={hover && !isHi ? 0.18 : 1}
                strokeLinecap="round"/>
              {(isFocusEdge || isHi) && !compact && (
                <FlowParticles path={pid} count={isHi ? 3 : 2} dur={isHi ? 1.6 : 2.4}
                  color={isHi ? '#5B7FD0' : 'rgba(91,127,208,0.75)'}/>
              )}
            </g>
          );
        })}

        {LINEAGE.nodes.map(n => {
          const p = positions[n.id];
          if (!p) return null;
          const isFocus = n.focus || n.id === focusId;
          const isHover = hover === n.id;
          const isTraced = hover && traced.has(n.id);
          const dimmed = hover && !isTraced;
          const w = compact ? 110 : 140;
          const h = compact ? 36 : 48;
          const color = nodeColor(n);
          return (
            <g key={n.id} transform={`translate(${p.x - w/2}, ${p.y - h/2})`} style={{ cursor: 'pointer', opacity: dimmed ? 0.32 : 1, transition: 'opacity 200ms' }}
               onMouseEnter={() => setHover(n.id)} onMouseLeave={() => setHover(null)}>
              {isFocus && !compact && (
                <rect className="lineage-focus-ring" x="-4" y="-4" width={w+8} height={h+8} rx="10"
                  fill="none" stroke="#5B7FD0" strokeWidth="1.5" opacity="0.9"/>
              )}
              {(isHover || isFocus) && !compact && (
                <rect x="-2" y="-2" width={w+4} height={h+4} rx="9" fill={color} opacity="0.12" filter="url(#glowSoft)"/>
              )}
              <rect className="lineage-node-bg" width={w} height={h} rx="8"
                fill={isFocus ? 'rgba(91,127,208,0.16)' : n.type === 'restricted' ? 'rgba(244,183,64,0.06)' : 'var(--srf-3)'}
                stroke={isFocus ? '#5B7FD0' : (isHover || isTraced) ? color : 'var(--srf-line)'}
                strokeWidth={isFocus ? 1.5 : 1}/>
              <rect x="0" y="0" width="3" height={h} rx="1.5" fill={color}/>
              <circle cx="14" cy={h/2} r="3.5" fill={color} filter={isHover ? 'url(#glowSoft)' : ''}/>
              <text x="24" y={compact ? h/2 - 1 : h/2 - 3} fontSize={compact ? 9 : 11} fill="#FFFFFF" fontWeight="600" fontFamily="var(--font-mono)" letterSpacing="-0.01em">
                {compact ? n.label.slice(-22) : n.label.length > 24 ? '…' + n.label.slice(-23) : n.label}
              </text>
              <text x="24" y={compact ? h/2 + 9 : h/2 + 11} fontSize={compact ? 8 : 9} fill="#6B829A" textTransform="uppercase" letterSpacing="1.4" fontWeight="600">
                {n.type === 'restricted' ? 'PERMISSION-LIMITED' : `${n.type.toUpperCase()} · ${n.domain}`}
              </text>
              {n.type === 'restricted' && (
                <g transform={`translate(${w-22}, ${h/2 - 8})`}>
                  <rect width="16" height="16" rx="3" fill="rgba(244,183,64,0.12)" stroke="rgba(244,183,64,0.4)"/>
                  <foreignObject x="2" y="2" width="12" height="12">
                    <i data-lucide="lock" style={{ width: 10, height: 10, color: '#F4B740' }}></i>
                  </foreignObject>
                </g>
              )}
              {n.cert === 'certified' && !compact && (
                <g transform={`translate(${w-20}, ${h/2 - 6})`}>
                  <circle cx="6" cy="6" r="6" fill="rgba(52,211,153,0.15)" stroke="rgba(52,211,153,0.5)"/>
                  <path d="M3,6 L5,8 L9,4" stroke="#34D399" strokeWidth="1.4" fill="none" strokeLinecap="round" strokeLinejoin="round"/>
                </g>
              )}
            </g>
          );
        })}
      </svg>

      {!compact && hover && (() => {
        const n = LINEAGE.nodes.find(x => x.id === hover);
        if (!n) return null;
        return (
          <div style={{ position: 'absolute', bottom: 16, left: 18, right: 18, background: 'linear-gradient(180deg, rgba(15,30,45,0.96), rgba(11,22,34,0.96))', backdropFilter: 'blur(8px)', border: '1px solid var(--srf-line)', borderRadius: 10, padding: '12px 16px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: 12, boxShadow: '0 12px 32px rgba(0,0,0,0.5)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <span style={{ width: 6, height: 6, borderRadius: 999, background: nodeColor(n) }}></span>
              <span className="mono" style={{ color: 'var(--txt-strong)', fontWeight: 700 }}>{n.label}</span>
              <span style={{ color: 'var(--txt-subtle)', fontSize: 11 }}>· {n.type} · {n.domain}</span>
            </div>
            {n.type === 'restricted'
              ? <span className="chip warn"><Icon name="lock" size={11}/>Hidden by Unity Catalog permissions</span>
              : <span className="link" style={{ display: 'flex', alignItems: 'center', gap: 4 }}>Open asset <Icon name="arrow-right" size={11}/></span>}
          </div>
        );
      })()}
    </div>
  );
}
function LegendDot({ color, label }) { return <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}><span style={{ width: 8, height: 8, borderRadius: 999, background: color }}></span>{label}</span>; }

function LineagePage({ onAsset }) {
  useLucide();
  const [downstream, setDownstream] = uS4(null);
  return (
    <div className="page">
      <PageHead
        eyebrow="Lineage Atlas"
        title="finance_prod.curated.revenue_daily"
        sub="Permission-aware end-to-end lineage from operational sources through to consumer dashboards. Hidden segments mean a node exists, but you don't have UC permission to view it."
        actions={<>
          <button className="btn btn-secondary"><Icon name="git-branch" size={14}/>Compare versions</button>
          <button className="btn btn-primary"><Icon name="alert-octagon" size={14}/>Run impact analysis</button>
        </>}
      />

      <div style={{ display: 'flex', gap: 8, marginBottom: 16, flexWrap: 'wrap' }}>
        <Chip tone="good" icon="badge-check">Certified</Chip>
        <Chip tone="info" icon="clock">14 min ago · within 15 min SLA</Chip>
        <Chip tone="teal" icon="key-round">5 CDEs</Chip>
        <Chip icon="user">Owner: Marisol Reyes</Chip>
        <Chip icon="git-fork">5 upstream · 23 downstream</Chip>
      </div>

      <LineageGraph/>

      <div className="grid grid-12" style={{ marginTop: 16 }}>
        <div className="col-7">
          <Card title="Impact analysis" sub="If you change `net_revenue_usd`, these consumers are affected" actions={<button className="btn btn-secondary btn-sm">Notify owners</button>}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {[
                { name: 'CFO Quarterly Dashboard', kind: 'dashboard', owner: 'Finance Stewards', risk: 'high', meta: 'Used in last 24h · 142 views' },
                { name: 'Board Pack — Revenue', kind: 'dashboard', owner: 'Marisol Reyes', risk: 'high', meta: 'Quarterly distribution to board' },
                { name: 'finance_prod.ml.revenue_forecast', kind: 'model', owner: 'Finance Data Platform', risk: 'med', meta: 'Trains nightly · last run 4h ago' },
                { name: 'finance_prod.gold.arr_snapshot', kind: 'table', owner: 'Finance Stewards', risk: 'med', meta: 'Downstream of net_revenue_usd' },
                { name: '4 downstream assets', kind: 'restricted', owner: '—', risk: 'unknown', meta: 'Hidden by UC permissions' },
              ].map((c, i) => (
                <div key={i} onClick={() => c.kind !== 'restricted' && setDownstream(c)} style={{
                  display: 'flex', alignItems: 'center', gap: 14,
                  padding: '12px 14px', background: 'var(--srf-2)', border: '1px solid var(--srf-line-soft)', borderRadius: 8,
                  cursor: c.kind !== 'restricted' ? 'pointer' : 'default',
                }}>
                  <Icon name={window.GA.ASSET_ICON[c.kind] || 'table-2'} size={16} style={{ color: c.kind === 'restricted' ? 'var(--warn)' : 'var(--accent)' }}/>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontWeight: 600, color: 'var(--txt-strong)', fontSize: 13.5 }}>{c.name}</div>
                    <div style={{ fontSize: 11.5, color: 'var(--txt-subtle)' }}>{c.owner} · {c.meta}</div>
                  </div>
                  {c.risk === 'high' && <Chip tone="crit" dot>High impact</Chip>}
                  {c.risk === 'med' && <Chip tone="warn" dot>Medium</Chip>}
                  {c.risk === 'unknown' && <Chip tone="warn" icon="lock">Restricted</Chip>}
                </div>
              ))}
            </div>
          </Card>
        </div>

        <div className="col-5">
          <Card title="Column lineage · net_revenue_usd" sub="From system.access.column_lineage" >
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 12, lineHeight: 1.8, color: 'var(--txt-muted)' }}>
              <div style={{ color: 'var(--accent)' }}>net_revenue_usd</div>
              <div style={{ paddingLeft: 14 }}>← gross_revenue_usd <span className="subtle">(this table)</span></div>
              <div style={{ paddingLeft: 14 }}>← discount_usd <span className="subtle">(this table)</span></div>
              <div style={{ paddingLeft: 28, color: 'var(--txt-subtle)' }}>← discount.amount <span className="subtle">silver.payments</span></div>
              <div style={{ paddingLeft: 14 }}>← refund_usd <span className="subtle">silver.payments</span></div>
              <div style={{ paddingLeft: 28 }}>← stripe.refunds.amount <span className="subtle">bronze.charges_raw</span></div>
            </div>
            <div style={{ borderTop: '1px solid var(--srf-line-soft)', marginTop: 14, paddingTop: 12, fontSize: 12, color: 'var(--txt-subtle)' }}>
              <Icon name="info" size={11} style={{ marginRight: 5 }}/>
              Column-level lineage available where source jobs emit lineage events. <span className="link">Coverage report</span>
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
}

window.LineagePage = LineagePage;
window.LineageGraph = LineageGraph;
