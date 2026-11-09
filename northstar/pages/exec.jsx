/* eslint-disable */
/** Executive Command Center */
const { useState: uS } = React;

function ExecPage({ onAsset }) {
  useLucide();
  const { KPIS, DOMAINS, RECENT_ACTIVITY, CATALOGS, COVERAGE_TIMESERIES, ASSETS } = window.GA;

  return (
    <div className="page" style={{ position: 'relative' }}>
      <div className="hero-strip"></div>
      <div style={{ position: 'relative', zIndex: 1 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 18 }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
              <span className="eyebrow" style={{ color: 'var(--accent)' }}>Executive Command Center</span>
              <span style={{ height: 4, width: 4, borderRadius: 999, background: 'var(--txt-subtle)' }}></span>
              <span style={{ fontSize: 11, color: 'var(--txt-subtle)', letterSpacing: '0.06em' }}>
                <span className="live-dot" style={{ display:'inline-block', verticalAlign:'middle', marginRight:6 }}></span>
                Live · refreshed 14s ago
              </span>
            </div>
            <h1 style={{ margin: 0, fontFamily: 'var(--font-display)', fontWeight: 800, fontSize: 36, letterSpacing: '-0.025em', color: 'var(--txt-strong)', lineHeight: 1.1 }}>
              Governance posture, <span style={{ background: 'linear-gradient(90deg, #7497DC, #CDDAF4)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent' }}>at a glance</span>
            </h1>
            <div style={{ color: 'var(--txt-muted)', fontSize: 14, marginTop: 6, maxWidth: 720, lineHeight: 1.5 }}>
              Axiom reads Unity Catalog directly — every number below is permission-aware, lineage-verified, and traceable to a system table.
            </div>
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <button className="btn btn-secondary"><Icon name="download" size={14}/>Export brief</button>
            <button className="btn btn-primary"><Icon name="presentation" size={14}/>Present mode</button>
          </div>
        </div>

        {/* HERO — trust ring + executive narrative */}
        <div className="posture-hero">
          <div className="grid-bg"></div>
          <div style={{ position: 'relative', display: 'grid', gridTemplateColumns: '220px 1fr 360px', gap: 36, alignItems: 'center' }}>
            <div style={{ display: 'flex', justifyContent: 'center' }}>
              <TrustRing value={87.4}/>
            </div>
            <div>
              <div style={{ fontSize: 11, fontWeight: 600, letterSpacing: '0.18em', color: 'var(--accent)', textTransform: 'uppercase', marginBottom: 10 }}>
                The state of finance_prod
              </div>
              <div style={{ fontFamily: 'var(--font-display)', fontSize: 22, lineHeight: 1.35, color: 'var(--txt-strong)', fontWeight: 600, letterSpacing: '-0.015em' }}>
                <span style={{ color: 'var(--good)' }}>1,247 of 1,427</span> productionized assets
                meet baseline policy. <span style={{ color: 'var(--txt-muted)', fontWeight: 500 }}>Coverage is up</span>{' '}
                <span style={{ color: 'var(--good)' }}>9 points</span> this quarter — on track to hit
                the <span style={{ color: 'var(--accent)' }}>90% Q2 target</span> by week 30.
              </div>
              <div style={{ display: 'flex', gap: 24, marginTop: 18, flexWrap: 'wrap' }}>
                <NarrativeStat icon="badge-check" label="Certified assets" value={1247} delta="+82 this quarter" tone="good"/>
                <NarrativeStat icon="alert-octagon" label="Open exposures" value={7} delta="3 require Compliance review" tone="crit"/>
                <NarrativeStat icon="key-round" label="CDEs tracked" value={42} delta="100% lineage-verified" tone="info"/>
              </div>
            </div>
            <div style={{ borderLeft: '1px solid var(--srf-line)', paddingLeft: 28 }}>
              <div style={{ fontSize: 10, fontWeight: 600, letterSpacing: '0.18em', color: 'var(--txt-subtle)', textTransform: 'uppercase', marginBottom: 12 }}>
                What changed today
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 11 }}>
                <DiffRow up label="Coverage" from="86.8%" to="87.4%" sub="+12 newly certified"/>
                <DiffRow up label="Quality SLA" from="94.1%" to="94.3%" sub="3 expectations passing"/>
                <DiffRow down label="High-risk exposures" from="9" to="7" sub="2 mitigated by Steward team"/>
                <DiffRow flat label="Lineage coverage" from="98.6%" to="98.6%" sub="No regressions"/>
              </div>
            </div>
          </div>
        </div>

        {/* KPI ROW */}
        <div className="grid grid-4" style={{ marginBottom: 16 }}>
          {KPIS.map(k => (
            <div key={k.id} className="kpi tile-glow">
              <div className="label">{k.label}</div>
              <div className="v">
                <CountUp to={k.value} dur={1100 + Math.random()*400}/>
                {k.unit && <small>{k.unit}</small>}
              </div>
              <div className={`delta ${k.delta > 0 ? (k.tone === 'crit' ? 'down' : 'up') : k.delta < 0 ? (k.tone === 'crit' ? 'up' : 'down') : 'flat'}`}>
                <Icon name={k.delta > 0 ? 'arrow-up-right' : k.delta < 0 ? 'arrow-down-right' : 'minus'} size={12}/>
                {k.deltaText}
              </div>
              <Sparkline data={k.spark} tone={k.tone}/>
            </div>
          ))}
        </div>

        {/* MAIN GRID */}
        <div className="grid grid-12" style={{ marginBottom: 16 }}>
          <div className="col-8">
            <Card title="Coverage trend · last 12 weeks" sub="Share of productionized assets meeting baseline policy" actions={<>
              <button className="btn btn-ghost btn-sm">12w</button>
              <button className="btn btn-secondary btn-sm">26w</button>
              <button className="btn btn-ghost btn-sm">52w</button>
            </>}>
              <AreaChart data={COVERAGE_TIMESERIES} h={210}/>
              <div style={{ display: 'flex', gap: 24, marginTop: 8, fontSize: 12, color: 'var(--txt-muted)', flexWrap: 'wrap' }}>
                <div><span style={{ color:'var(--good)', fontWeight:700 }}>+9.0 pts</span> over the last 12 weeks</div>
                <div>SLA: <span style={{ color:'var(--txt)' }}>≥ 90% by end of Q2</span></div>
                <div>Projected: <span style={{ color:'var(--good)', fontWeight:600 }}>91.2% by W30</span></div>
              </div>
            </Card>
          </div>

          <div className="col-4">
            <Card title="Posture by domain" sub="Coverage × certified asset count" padded>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                {DOMAINS.map(d => (
                  <div key={d.name}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 4 }}>
                      <div style={{ display:'flex', gap:8, alignItems:'center' }}>
                        <span style={{ width:8, height:8, borderRadius:2, background: d.color }}></span>
                        <span style={{ fontSize: 13, color: 'var(--txt)', fontWeight: 500 }}>{d.name}</span>
                      </div>
                      <div style={{ fontSize: 12, color: 'var(--txt-muted)' }}><span className="strong tnum" style={{ color: 'var(--txt-strong)', fontWeight: 700 }}>{d.coverage}%</span> · {d.certified} cert</div>
                    </div>
                    <div className="score-bar"><span className={d.coverage > 85 ? 'good' : d.coverage > 75 ? '' : 'warn'} style={{ width: d.coverage + '%', background: d.coverage > 85 ? 'var(--good)' : d.coverage > 75 ? d.color : 'var(--warn)' }}></span></div>
                  </div>
                ))}
              </div>
            </Card>
          </div>
        </div>

        {/* SECONDARY GRID */}
        <div className="grid grid-12" style={{ marginBottom: 16 }}>
          <div className="col-4">
            <Card title="Risk breakdown" sub="Open exposures by severity">
              <div style={{ display: 'flex', alignItems: 'center', gap: 18, marginBottom: 12 }}>
                <Donut value={92} sub="risk-clean" tone="good"/>
                <div style={{ flex:1, display: 'flex', flexDirection: 'column', gap: 8 }}>
                  <RiskRow tone="crit" count={7}  label="High-risk exposures"/>
                  <RiskRow tone="warn" count={28} label="Medium-risk findings"/>
                  <RiskRow tone="info" count={64} label="Informational"/>
                </div>
              </div>
              <div style={{ borderTop: '1px solid var(--srf-line-soft)', paddingTop: 12, fontSize: 12, color: 'var(--txt-muted)' }}>
                3 of 7 high-risk items require Compliance review · <span className="link">Open queue →</span>
              </div>
            </Card>
          </div>

          <div className="col-8">
            <Card title="Top catalogs · health snapshot" sub="From system.information_schema joined with governance state" padded={false}>
              <table className="tbl">
                <thead><tr>
                  <th>Catalog</th><th className="num">Tables</th><th>Coverage</th><th>Classification</th><th>Risk</th><th></th>
                </tr></thead>
                <tbody>
                  {CATALOGS.slice(0,6).map(c => (
                    <tr key={c.name}>
                      <td>
                        <div style={{ display:'flex', alignItems:'center', gap: 10 }}>
                          <Icon name="database" size={15} style={{ color: 'var(--accent)' }}/>
                          <span style={{ fontWeight: 600, color: 'var(--txt-strong)', fontFamily: 'var(--font-mono)', fontSize: 13 }}>{c.name}</span>
                        </div>
                      </td>
                      <td className="num tnum">{c.tables.toLocaleString()}</td>
                      <td style={{ minWidth: 140 }}>
                        <div style={{ display:'flex', alignItems: 'center', gap: 8 }}>
                          <span className="tnum" style={{ color: 'var(--txt-strong)', fontWeight: 600, minWidth: 36 }}>{c.coverage}%</span>
                          <div className="score-bar" style={{ flex: 1 }}>
                            <span className={c.coverage > 85 ? 'good' : c.coverage > 75 ? '' : 'warn'} style={{ width: c.coverage + '%' }}></span>
                          </div>
                        </div>
                      </td>
                      <td><ClassChip value={c.classified}/></td>
                      <td>
                        {c.risk === 'high' && <Chip tone="crit" dot>High</Chip>}
                        {c.risk === 'med'  && <Chip tone="warn" dot>Medium</Chip>}
                        {c.risk === 'low'  && <Chip tone="good" dot>Low</Chip>}
                      </td>
                      <td><Icon name="chevron-right" size={14} style={{ color: 'var(--txt-subtle)' }}/></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>
          </div>
        </div>

        {/* THIRD ROW */}
        <div className="grid grid-12">
          <div className="col-7">
            <Card title="Critical data elements" sub="Source-of-record metrics — owner-confirmed, lineage-verified" actions={<button className="btn btn-ghost btn-sm">View all<Icon name="chevron-right" size={12}/></button>}>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                {window.GA.CDES.slice(0,4).map(c => (
                  <div key={c.column} style={{ background: 'var(--srf-3)', border: '1px solid var(--srf-line-soft)', borderRadius: 8, padding: 14 }}>
                    <div style={{ display:'flex', alignItems:'center', justifyContent:'space-between' }}>
                      <div style={{ display:'flex', gap:6, alignItems:'center' }}>
                        <Icon name="key-round" size={13} style={{ color: 'var(--teal)' }}/>
                        <span style={{ fontWeight: 700, fontSize: 13, color: 'var(--txt-strong)' }}>{c.name}</span>
                      </div>
                      {c.sox && <span className="tag" style={{ background:'rgba(244,113,116,0.10)', color:'var(--crit)', borderColor:'rgba(244,113,116,0.30)' }}>SOX</span>}
                    </div>
                    <div className="mono" style={{ fontSize: 11, color: 'var(--txt-subtle)', marginTop: 4, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap' }}>{c.column}</div>
                    <div style={{ display:'flex', justifyContent:'space-between', marginTop: 10, fontSize: 12 }}>
                      <span style={{ color: 'var(--txt-muted)' }}>{c.owner}</span>
                      <span style={{ color: c.status.startsWith('Healthy') ? 'var(--good)' : 'var(--warn)', fontWeight: 600 }}>{c.status}</span>
                    </div>
                  </div>
                ))}
              </div>
            </Card>
          </div>

          <div className="col-5">
            <Card title="Activity stream" sub="Live audit log · permission-filtered">
              <div style={{ display:'flex', flexDirection:'column', gap: 14 }}>
                {RECENT_ACTIVITY.map((a, i) => (
                  <div key={i} style={{ display:'flex', gap: 12, alignItems:'flex-start' }}>
                    <span className={`sev ${a.sev}`} style={{ marginTop: 6 }}></span>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontSize: 13, color: 'var(--txt)', lineHeight: 1.45 }}>
                        <span style={{ fontWeight: 600, color: 'var(--txt-strong)' }}>{a.who}</span> {a.what} <span className="link mono" onClick={()=>onAsset && onAsset(a.target)}>{a.target}</span>
                      </div>
                      <div style={{ fontSize: 11, color: 'var(--txt-subtle)', marginTop: 2 }}>{a.ts}</div>
                    </div>
                  </div>
                ))}
              </div>
            </Card>
          </div>
        </div>
      </div>
    </div>
  );
}

function NarrativeStat({ icon, label, value, delta, tone }) {
  const color = tone === 'good' ? 'var(--good)' : tone === 'crit' ? 'var(--crit)' : tone === 'warn' ? 'var(--warn)' : 'var(--accent)';
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 2, minWidth: 140 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11, color: 'var(--txt-subtle)', textTransform: 'uppercase', letterSpacing: '0.1em', fontWeight: 600 }}>
        <Icon name={icon} size={11} style={{ color }}/>{label}
      </div>
      <div style={{ fontFamily: 'var(--font-display)', fontSize: 28, fontWeight: 800, color: 'var(--txt-strong)', letterSpacing: '-0.02em', lineHeight: 1.1 }}>
        <CountUp to={value}/>
      </div>
      <div style={{ fontSize: 11, color: 'var(--txt-muted)' }}>{delta}</div>
    </div>
  );
}

function DiffRow({ label, from, to, sub, up, down, flat }) {
  const color = up ? 'var(--good)' : down ? 'var(--crit)' : 'var(--txt-muted)';
  const icon = up ? 'arrow-up-right' : down ? 'arrow-down-right' : 'minus';
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: 12 }}>
      <Icon name={icon} size={12} style={{ color }}/>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 8 }}>
          <span style={{ color: 'var(--txt)', fontWeight: 500 }}>{label}</span>
          <span style={{ color: 'var(--txt-subtle)', fontFamily: 'var(--font-mono)', fontSize: 11 }}>
            {from} <span style={{ color: 'var(--txt-subtle)' }}>→</span> <span style={{ color: 'var(--txt-strong)', fontWeight: 700 }}>{to}</span>
          </span>
        </div>
        <div style={{ fontSize: 10.5, color: 'var(--txt-subtle)', marginTop: 1 }}>{sub}</div>
      </div>
    </div>
  );
}

function RiskRow({ tone, count, label }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
      <span className={`sev ${tone}`}></span>
      <span style={{ fontFamily: 'var(--font-display)', fontSize: 18, fontWeight: 800, color: 'var(--txt-strong)', minWidth: 32 }}>{count}</span>
      <span style={{ fontSize: 12, color: 'var(--txt-muted)', flex: 1 }}>{label}</span>
    </div>
  );
}

window.ExecPage = ExecPage;
