/* eslint-disable */
/** Audit Evidence + Glossary + Admin + AI panel */
const { useState: uS6 } = React;

function AuditPage() {
  useLucide();
  const { AUDIT_EVENTS } = window.GA;
  const [filter, setFilter] = uS6('all');
  const filtered = filter === 'all' ? AUDIT_EVENTS : AUDIT_EVENTS.filter(e => e.actorType === filter || e.sev === filter);

  return (
    <div className="page">
      <PageHead
        eyebrow="Audit Evidence"
        title="Immutable governance event log"
        sub="Every governance action — by humans or services — is appended to a Delta audit log. Events are searchable, cryptographically ordered, and exportable for SOC 2 / SOX evidence."
        actions={<>
          <button className="btn btn-secondary"><Icon name="filter" size={14}/>Date range</button>
          <button className="btn btn-secondary"><Icon name="file-text" size={14}/>Generate report</button>
          <button className="btn btn-primary"><Icon name="download" size={14}/>Export CSV</button>
        </>}
      />

      <div className="grid grid-4" style={{ marginBottom: 16 }}>
        <Kpi label="Events · 24h" value="2,184" delta="+312"/>
        <Kpi label="Policy violations · 7d" value="6" delta="-2" tone="good"/>
        <Kpi label="Access reviews · open" value="3" delta="0"/>
        <Kpi label="Retention" value="7 yr" sub="Delta · time-travel enabled"/>
      </div>

      <div style={{ display: 'flex', gap: 6, marginBottom: 12 }}>
        {[['all','All events'],['user','By users'],['service','By services'],['crit','Violations']].map(([k, l]) => (
          <button key={k} className={`btn btn-sm ${filter === k ? 'btn-primary' : 'btn-secondary'}`} onClick={() => setFilter(k)}>{l}</button>
        ))}
      </div>

      <Card padded={false}>
        <table className="tbl">
          <thead><tr><th>Time (UTC)</th><th>Actor</th><th>Event</th><th>Target</th><th>Evidence</th><th></th></tr></thead>
          <tbody>
            {filtered.map(e => (
              <tr key={e.id}>
                <td className="mono subtle" style={{ fontSize: 11.5, whiteSpace: 'nowrap' }}>{e.ts}</td>
                <td>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <Icon name={e.actorType === 'service' ? 'cpu' : 'user'} size={13} style={{ color: e.actorType === 'service' ? 'var(--teal)' : 'var(--accent)' }}/>
                    <span className="mono" style={{ fontSize: 12, color: 'var(--txt)' }}>{e.actor}</span>
                  </div>
                </td>
                <td>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span className={`sev ${e.sev}`}></span>
                    <div>
                      <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--txt-strong)' }}>{e.kind}</div>
                      <div style={{ fontSize: 12, color: 'var(--txt-muted)' }}>{e.summary}</div>
                    </div>
                  </div>
                </td>
                <td className="mono subtle" style={{ fontSize: 11.5, maxWidth: 220, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{e.target}</td>
                <td style={{ fontSize: 11.5, color: 'var(--txt-muted)', maxWidth: 240 }}>{e.evidence}</td>
                <td><Icon name="external-link" size={13} style={{ color: 'var(--txt-subtle)' }}/></td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>

      <div style={{ marginTop: 16, padding: '14px 18px', background: 'var(--srf-2)', border: '1px solid var(--srf-line-soft)', borderRadius: 8, display: 'flex', alignItems: 'center', gap: 12, fontSize: 12.5, color: 'var(--txt-muted)' }}>
        <Icon name="shield-check" size={15} style={{ color: 'var(--good)' }}/>
        <span>Append-only Delta table <span className="mono" style={{ color: 'var(--accent)' }}>governance_state.audit_log</span> · 7-year retention · time-travel queries via <span className="mono">VERSION AS OF</span>. No raw row values are stored — only metadata + references.</span>
      </div>
    </div>
  );
}

function Kpi({ label, value, delta, sub, tone }) {
  return (
    <div className="kpi">
      <div className="label">{label}</div>
      <div className="v">{value}</div>
      {delta && <div className={`delta ${delta.startsWith('-') ? (tone === 'good' ? 'up' : 'down') : delta.startsWith('+') ? (tone === 'good' ? 'down' : 'up') : 'flat'}`}>{delta} vs prev</div>}
      {sub && <div style={{ fontSize: 12, color: 'var(--txt-subtle)', marginTop: 8 }}>{sub}</div>}
    </div>
  );
}

function GlossaryPage({ onAsset }) {
  useLucide();
  const { GLOSSARY, CDES } = window.GA;
  const [tab, setTab] = uS6('terms');
  return (
    <div className="page">
      <PageHead
        eyebrow="Glossary & CDE Registry"
        title="Shared business meaning, anchored to data"
        sub="Glossary terms link to source-of-record assets. Critical Data Elements have stricter ownership, certification, and lineage requirements."
        actions={<button className="btn btn-primary"><Icon name="plus" size={14}/>New term</button>}
      />

      <div className="tabs" style={{ padding: 0, marginBottom: 16 }}>
        <div className={`tab ${tab === 'terms' ? 'active' : ''}`} onClick={() => setTab('terms')}>Glossary <span className="count">{GLOSSARY.length}</span></div>
        <div className={`tab ${tab === 'cdes' ? 'active' : ''}`} onClick={() => setTab('cdes')}>CDE Registry <span className="count">{CDES.length}</span></div>
      </div>

      {tab === 'terms' && (
        <div className="grid grid-2">
          {GLOSSARY.map(t => (
            <Card key={t.term}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 8 }}>
                <div>
                  <h3 style={{ margin: 0, fontFamily: 'var(--font-display)', fontSize: 17, fontWeight: 700, color: 'var(--txt-strong)' }}>{t.term}</h3>
                  <div className="subtle" style={{ fontSize: 11.5, marginTop: 2 }}>{t.domain} · {t.steward}</div>
                </div>
                {t.status === 'Approved' ? <Chip tone="good" dot>Approved</Chip> : <Chip tone="warn" dot>In Review</Chip>}
              </div>
              <p style={{ fontSize: 13, color: 'var(--txt-muted)', lineHeight: 1.55, margin: 0 }}>{t.def}</p>
              <div style={{ marginTop: 12, display: 'flex', gap: 12, fontSize: 12, color: 'var(--txt-subtle)' }}>
                <span><Icon name="link" size={11}/> {t.linkedAssets} assets</span>
                <span className="link">View lineage →</span>
              </div>
            </Card>
          ))}
        </div>
      )}

      {tab === 'cdes' && (
        <Card padded={false}>
          <table className="tbl">
            <thead><tr><th>CDE</th><th>Source-of-record column</th><th>Owner</th><th>Recert</th><th>Status</th></tr></thead>
            <tbody>
              {CDES.map(c => (
                <tr key={c.column}>
                  <td>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <Icon name="key-round" size={14} style={{ color: 'var(--teal)' }}/>
                      <span style={{ fontWeight: 600, color: 'var(--txt-strong)' }}>{c.name}</span>
                      {c.sox && <span className="tag" style={{ background:'rgba(244,113,116,0.10)', color:'var(--crit)', borderColor:'rgba(244,113,116,0.30)' }}>SOX</span>}
                    </div>
                  </td>
                  <td className="mono subtle" style={{ fontSize: 12 }}>{c.column}</td>
                  <td style={{ fontSize: 12.5 }}>{c.owner}</td>
                  <td><span className="chip">{c.recert}</span></td>
                  <td>{c.status === 'Healthy' ? <Chip tone="good" dot>Healthy</Chip> : <Chip tone="warn" dot>{c.status}</Chip>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </div>
  );
}

function AdminPage() {
  useLucide();
  return (
    <div className="page">
      <PageHead
        eyebrow="Control Center"
        title="Axiom runtime, integrations, and policy"
        sub="Configure scan jobs, policy engine, integrations, and tenant-level branding. Designed to run as a Databricks App against the host workspace."
      />

      <div className="grid grid-12">
        <div className="col-7">
          <Card title="Scheduled jobs" sub="Lakeflow Jobs powering Axiom" padded={false}>
            <table className="tbl">
              <thead><tr><th>Job</th><th>Schedule</th><th>Last run</th><th>Status</th></tr></thead>
              <tbody>
                {[
                  ['UC metadata sweeper', 'Every 15 min', '4 min ago', 'good'],
                  ['Lineage collector', 'Every 1 hr', '21 min ago', 'good'],
                  ['Quality + freshness check', 'Every 1 hr', '32 min ago', 'good'],
                  ['Policy engine evaluator', 'Hourly + on-write', '7 min ago', 'good'],
                  ['PII classifier (model serving)', 'Daily 02:00 UTC', '8 hr ago', 'good'],
                  ['Trust score recompute', 'Daily 03:00 UTC', '7 hr ago', 'warn'],
                ].map(([name, sch, last, st], i) => (
                  <tr key={i}>
                    <td><div style={{ display: 'flex', alignItems: 'center', gap: 10 }}><Icon name="workflow" size={14} style={{ color: 'var(--teal)' }}/><span style={{ fontWeight: 600, color: 'var(--txt-strong)', fontSize: 13 }}>{name}</span></div></td>
                    <td className="mono subtle" style={{ fontSize: 12 }}>{sch}</td>
                    <td style={{ fontSize: 12.5, color: 'var(--txt-muted)' }}>{last}</td>
                    <td><Chip tone={st} dot>{st === 'good' ? 'Healthy' : 'Slow'}</Chip></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        </div>
        <div className="col-5">
          <Card title="Integrations">
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              {[
                ['Unity Catalog', 'database', 'Connected · live'],
                ['Databricks SQL Warehouse', 'server', '`gov_axiom_wh` · M'],
                ['Lakeflow Jobs', 'workflow', '6 jobs scheduled'],
                ['Model Serving · classifier-v2', 'brain', 'Endpoint healthy'],
                ['Slack · #governance-alerts', 'message-circle', 'Connected'],
                ['PagerDuty · P1 stewardship', 'bell', 'Connected'],
              ].map(([name, ic, status]) => (
                <div key={name} style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '10px 12px', background: 'var(--srf-2)', border: '1px solid var(--srf-line-soft)', borderRadius: 6 }}>
                  <Icon name={ic} size={15} style={{ color: 'var(--accent)' }}/>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 13, color: 'var(--txt-strong)', fontWeight: 600 }}>{name}</div>
                    <div style={{ fontSize: 11, color: 'var(--txt-subtle)' }}>{status}</div>
                  </div>
                  <Chip tone="good" dot>OK</Chip>
                </div>
              ))}
            </div>
          </Card>

          <div style={{ height: 16 }}/>

          <Card title="Policy coverage" sub="Active policies · auto-evaluated">
            {[
              ['Owner required on production', 96],
              ['CDEs must have description', 100],
              ['PII columns require tag', 92],
              ['90-day re-certification', 87],
              ['Restricted catalogs require justified grant', 100],
            ].map(([p, v]) => (
              <div key={p} style={{ marginBottom: 12 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12.5, marginBottom: 4 }}>
                  <span style={{ color: 'var(--txt)' }}>{p}</span>
                  <span className="tnum strong" style={{ color: 'var(--txt-strong)', fontWeight: 700 }}>{v}%</span>
                </div>
                <div className="score-bar"><span className={v >= 95 ? 'good' : v >= 85 ? '' : 'warn'} style={{ width: v + '%' }}></span></div>
              </div>
            ))}
          </Card>
        </div>
      </div>
    </div>
  );
}

// ----------- Axiom AI panel -----------
function AIPanel({ open, onClose, onAsset, onRoute }) {
  useLucide();
  const [stage, setStage] = uS6('idle'); // idle | thinking | done
  const [q, setQ] = uS6('');
  const [thread, setThread] = uS6([]);

  const ask = (text) => {
    setStage('thinking');
    setThread(t => [...t, { role: 'user', text }]);
    setQ('');
    setTimeout(() => {
      setThread(t => [...t, window.GA.AI_THREADS[1]]);
      setStage('done');
    }, 1100);
  };

  const suggestions = [
    "What's powering the CFO Quarterly Dashboard, and is anything at risk this week?",
    "Which uncertified tables are queried by executives?",
    "Summarize PII coverage in customer_360.",
    "Who owns net_revenue_usd and when was it last certified?",
  ];

  return (
    <div className={`ai-pop ${open ? 'open' : ''}`}>
      <div style={{ padding: '16px 18px', borderBottom: '1px solid var(--srf-line-soft)', display: 'flex', alignItems: 'center', gap: 12, background: 'linear-gradient(180deg, rgba(91,127,208,0.08), transparent)' }}>
        <div style={{ position: 'relative', width: 34, height: 34, borderRadius: 9, background: 'linear-gradient(135deg, var(--hi), var(--blue))', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#051522', boxShadow: '0 8px 24px rgba(116,151,220,0.35)' }}>
          <Icon name="sparkles" size={17}/>
          <span style={{ position: 'absolute', bottom: -2, right: -2, width: 10, height: 10, borderRadius: 999, background: 'var(--good)', border: '2px solid var(--srf-1)' }}></span>
        </div>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--txt-strong)', letterSpacing: '-0.005em' }}>Axiom AI</div>
          <div style={{ fontSize: 11, color: 'var(--txt-subtle)', display: 'flex', alignItems: 'center', gap: 5 }}>
            <Icon name="shield-check" size={10} style={{ color: 'var(--good)' }}/>
            Grounded in UC metadata · No raw rows read
          </div>
        </div>
        <button className="btn btn-ghost btn-icon" onClick={onClose}><Icon name="x" size={15}/></button>
      </div>

      <div style={{ flex: 1, overflow: 'auto', padding: 16, display: 'flex', flexDirection: 'column', gap: 14 }}>
        {thread.length === 0 && (
          <>
            <div className="ai-msg-grad" style={{ fontSize: 13, color: 'var(--txt)', lineHeight: 1.55 }}>
              I answer questions about your governed data using Unity Catalog metadata, lineage, and the governance state tables. <strong style={{ color: 'var(--txt-strong)' }}>I never read raw row values.</strong> Every claim cites evidence you can click into.
            </div>
            <div className="eyebrow" style={{ marginTop: 6 }}>Try asking</div>
            {suggestions.map((s, i) => (
              <div key={s} onClick={() => ask(s)} style={{ padding: '11px 13px', background: 'var(--srf-2)', border: '1px solid var(--srf-line-soft)', borderRadius: 8, fontSize: 12.5, color: 'var(--txt)', cursor: 'pointer', lineHeight: 1.5, display: 'flex', alignItems: 'center', gap: 10, transition: 'all 180ms' }}
                onMouseEnter={e => { e.currentTarget.style.borderColor = 'rgba(91,127,208,0.5)'; e.currentTarget.style.background = 'rgba(91,127,208,0.07)'; }}
                onMouseLeave={e => { e.currentTarget.style.borderColor = ''; e.currentTarget.style.background = ''; }}>
                <Icon name="message-circle-question" size={14} style={{ color: 'var(--accent)', flexShrink: 0 }}/>
                <span style={{ flex: 1 }}>{s}</span>
                <Icon name="arrow-right" size={12} style={{ color: 'var(--txt-subtle)' }}/>
              </div>
            ))}
          </>
        )}

        {thread.map((m, i) => m.role === 'user' ? (
          <div key={i} style={{ alignSelf: 'flex-end', maxWidth: '85%', padding: '10px 14px', background: 'var(--accent)', color: '#051522', borderRadius: '14px 14px 4px 14px', fontSize: 13, fontWeight: 500 }}>{m.text}</div>
        ) : (
          <div key={i} className="pop-in" style={{ maxWidth: '95%' }}>
            <div style={{ padding: '14px 16px', background: 'var(--srf-2)', border: '1px solid var(--srf-line-soft)', borderRadius: '4px 14px 14px 14px', fontSize: 13, color: 'var(--txt)', lineHeight: 1.6 }}
              dangerouslySetInnerHTML={{ __html: m.answer.replace(/\*\*(.+?)\*\*/g, '<strong style="color:var(--txt-strong)">$1</strong>').replace(/`([^`]+)`/g, '<span style="font-family:var(--font-mono); font-size:0.9em; color: var(--accent); background: rgba(116,151,220,0.08); padding: 1px 5px; border-radius: 3px;">$1</span>') }}
            />
            {m.plan && (
              <details style={{ marginTop: 10, padding: '8px 12px', background: 'var(--srf-2)', border: '1px solid var(--srf-line-soft)', borderRadius: 8 }}>
                <summary style={{ fontSize: 11.5, color: 'var(--txt-subtle)', cursor: 'pointer', textTransform: 'uppercase', letterSpacing: '0.12em', fontWeight: 600 }}>How I answered this</summary>
                <ol style={{ margin: '8px 0 0 18px', padding: 0, fontSize: 12, color: 'var(--txt-muted)', lineHeight: 1.6 }}>
                  {m.plan.map((p, j) => <li key={j}>{p}</li>)}
                </ol>
              </details>
            )}
            {m.citations && (
              <div style={{ marginTop: 10 }}>
                <div className="eyebrow" style={{ marginBottom: 6 }}>Evidence</div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                  {m.citations.map((c, j) => (
                    <div key={j} onClick={() => c.target && onAsset(c.target)} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 10px', background: 'var(--srf-2)', border: '1px solid var(--srf-line-soft)', borderRadius: 6, cursor: c.target ? 'pointer' : 'default' }}>
                      <Icon name={c.kind === 'asset' ? 'table-2' : c.kind === 'lineage' ? 'git-fork' : c.kind === 'work' ? 'list-checks' : 'shield-check'} size={13} style={{ color: 'var(--accent)' }}/>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--txt-strong)' }}>{c.label}</div>
                        <div style={{ fontSize: 11, color: 'var(--txt-subtle)' }}>{c.meta}</div>
                      </div>
                      {c.target && <Icon name="external-link" size={11} style={{ color: 'var(--txt-subtle)' }}/>}
                    </div>
                  ))}
                </div>
              </div>
            )}
            {m.grounding && (
              <div style={{ marginTop: 8, fontSize: 11, color: 'var(--txt-subtle)', display: 'flex', alignItems: 'center', gap: 6 }}>
                <Icon name="shield-check" size={11} style={{ color: 'var(--good)' }}/>
                {m.grounding}
              </div>
            )}
          </div>
        ))}

        {stage === 'thinking' && (
          <div style={{ padding: '12px 14px', color: 'var(--txt)', fontSize: 12.5, display: 'flex', flexDirection: 'column', gap: 8, background: 'rgba(91,127,208,0.05)', border: '1px solid rgba(91,127,208,0.18)', borderRadius: 8 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: 'var(--txt-muted)' }}>
              <span style={{ width: 8, height: 8, borderRadius: 999, background: 'var(--accent)', animation: 'caret 0.9s steps(2) infinite' }}></span>
              <span>Querying Unity Catalog<span className="stream-caret"></span></span>
            </div>
            <div style={{ fontSize: 11, color: 'var(--txt-subtle)', paddingLeft: 16, lineHeight: 1.6 }}>
              <div>· Reading <span className="mono" style={{ color: 'var(--accent)' }}>system.access.table_lineage</span></div>
              <div>· Joining <span className="mono" style={{ color: 'var(--accent)' }}>governance_state.cdes</span> + ownership</div>
              <div>· Filtering by your UC permissions…</div>
            </div>
          </div>
        )}
      </div>

      <div style={{ borderTop: '1px solid var(--srf-line-soft)', padding: 12, display: 'flex', gap: 8 }}>
        <input
          placeholder="Ask about an asset, dashboard, or owner…"
          value={q}
          onChange={e => setQ(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter' && q.trim()) ask(q); }}
          style={{ flex: 1, background: 'var(--srf-2)', border: '1px solid var(--srf-line)', borderRadius: 8, padding: '9px 12px', color: 'var(--txt)', fontSize: 13, outline: 'none', fontFamily: 'inherit' }}
        />
        <button className="btn btn-primary" onClick={() => q.trim() && ask(q)}><Icon name="arrow-up" size={14}/></button>
      </div>
    </div>
  );
}

Object.assign(window, { AuditPage, GlossaryPage, AdminPage, AIPanel });
