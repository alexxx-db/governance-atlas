/* eslint-disable */
/** Stewardship Workbench */
const { useState: uS5 } = React;

function StewardshipPage({ onAsset }) {
  useLucide();
  const { STEW_ITEMS } = window.GA;
  const [filter, setFilter] = uS5('all');
  const [selected, setSelected] = uS5(null);

  const filtered = STEW_ITEMS.filter(i =>
    filter === 'all' ? true :
    filter === 'p1' ? i.priority === 'P1' :
    filter === 'mine' ? i.assigned === 'Marisol Reyes' :
    filter === 'overdue' ? i.slaState === 'crit' :
    true
  );

  const counts = {
    all: STEW_ITEMS.length,
    p1: STEW_ITEMS.filter(i => i.priority === 'P1').length,
    mine: STEW_ITEMS.filter(i => i.assigned === 'Marisol Reyes').length,
    overdue: STEW_ITEMS.filter(i => i.slaState === 'crit').length,
  };

  const sel = filtered.find(i => i.id === selected) || filtered[0];

  return (
    <div className="page">
      <PageHead
        eyebrow="Stewardship Workbench"
        title="184 open work items · 7 SLA breaches"
        sub="Auto-generated and human-filed governance work. Items are routed to teams by domain ownership; SLA timers run on a Lakeflow schedule."
        actions={<>
          <button className="btn btn-secondary"><Icon name="filter" size={14}/>Filter</button>
          <button className="btn btn-secondary"><Icon name="users" size={14}/>Bulk assign</button>
          <button className="btn btn-primary"><Icon name="plus" size={14}/>New work item</button>
        </>}
      />

      <div style={{ display: 'flex', gap: 6, marginBottom: 12 }}>
        {[['all','All',counts.all],['p1','P1 critical',counts.p1],['overdue','Overdue',counts.overdue],['mine','Assigned to me',counts.mine]].map(([k, label, c]) => (
          <button key={k} className={`btn btn-sm ${filter === k ? 'btn-primary' : 'btn-secondary'}`} onClick={() => setFilter(k)}>{label} <span style={{opacity:0.7, marginLeft: 4}}>{c}</span></button>
        ))}
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 420px', gap: 16 }}>
        <Card title="Work queue" sub={`${filtered.length} items · sorted by SLA risk`} padded={false}>
          <table className="tbl">
            <thead><tr><th>ID</th><th>Item</th><th>Asset</th><th>Assigned</th><th>SLA</th><th>Priority</th></tr></thead>
            <tbody>
              {filtered.map(i => (
                <tr key={i.id} className={sel?.id === i.id ? 'selected' : ''} onClick={() => setSelected(i.id)} style={{ cursor: 'pointer' }}>
                  <td className="mono subtle">{i.id}</td>
                  <td>
                    <div style={{ fontWeight: 600, color: 'var(--txt-strong)', fontSize: 13 }}>{i.kind}</div>
                    <div style={{ fontSize: 11, color: 'var(--txt-subtle)' }}>Age {i.age}</div>
                  </td>
                  <td className="mono subtle" style={{ fontSize: 12, maxWidth: 220, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{i.asset}</td>
                  <td style={{ fontSize: 12.5, color: 'var(--txt-muted)' }}>{i.assigned}</td>
                  <td><Chip tone={i.slaState === 'crit' ? 'crit' : i.slaState === 'warn' ? 'warn' : 'good'} dot>{i.sla}</Chip></td>
                  <td>{i.priority === 'P1' ? <Chip tone="crit">P1</Chip> : i.priority === 'P2' ? <Chip tone="warn">P2</Chip> : <Chip>P3</Chip>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>

        <div>
          {sel && <WorkItemDetail item={sel} onAsset={onAsset}/>}
        </div>
      </div>
    </div>
  );
}

function WorkItemDetail({ item, onAsset }) {
  return (
    <Card title={item.id} sub={item.kind}>
      <div style={{ display: 'flex', gap: 8, marginBottom: 14, flexWrap: 'wrap' }}>
        {item.priority === 'P1' ? <Chip tone="crit">P1 · Critical</Chip> : item.priority === 'P2' ? <Chip tone="warn">P2</Chip> : <Chip>P3</Chip>}
        <Chip tone={item.slaState === 'crit' ? 'crit' : item.slaState === 'warn' ? 'warn' : 'good'} icon="clock">{item.sla}</Chip>
        <Chip icon="user">{item.assigned}</Chip>
      </div>

      <div className="eyebrow" style={{ marginBottom: 6 }}>Affected asset</div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: 10, background: 'var(--srf-3)', borderRadius: 6, marginBottom: 14, cursor: 'pointer' }} onClick={() => onAsset && onAsset(item.asset)}>
        <Icon name="table-2" size={15} style={{ color: 'var(--accent)' }}/>
        <span className="mono" style={{ fontSize: 12.5, color: 'var(--txt-strong)', flex: 1 }}>{item.asset}</span>
        <Icon name="external-link" size={12} style={{ color: 'var(--txt-subtle)' }}/>
      </div>

      <div className="eyebrow" style={{ marginBottom: 6 }}>Why this is open</div>
      <div style={{ fontSize: 13, color: 'var(--txt)', lineHeight: 1.55, marginBottom: 14 }}>{item.evidence}</div>

      <div className="eyebrow" style={{ marginBottom: 8 }}>Suggested actions</div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginBottom: 16 }}>
        {item.kind === 'Owner missing' && <>
          <ActionRow icon="user-plus" label="Assign owner from suggested teams" detail="Sales Engineering · 92% match (queries, tags)"/>
          <ActionRow icon="archive" label="Archive · sandbox cleanup" detail="No queries in 30+ days"/>
        </>}
        {item.kind === 'Description missing' && <>
          <ActionRow icon="sparkles" label="Auto-draft description with Axiom AI" detail="Cited from upstream lineage and column tags"/>
          <ActionRow icon="user-cog" label="Reassign to Customer Stewards"/>
        </>}
        {item.kind === 'Re-certification due' && <>
          <ActionRow icon="badge-check" label="Approve re-certification" detail="All 6 quality checks pass · lineage verified"/>
          <ActionRow icon="alert-triangle" label="Flag for compliance review"/>
        </>}
        {!['Owner missing','Description missing','Re-certification due'].includes(item.kind) && <>
          <ActionRow icon="check" label="Mark resolved"/>
          <ActionRow icon="user-cog" label="Reassign"/>
          <ActionRow icon="bell" label="Snooze · 7 days"/>
        </>}
      </div>

      <div style={{ display: 'flex', gap: 8 }}>
        <button className="btn btn-secondary" style={{ flex: 1 }}><Icon name="message-square" size={14}/>Comment</button>
        <button className="btn btn-primary" style={{ flex: 1 }}><Icon name="check-circle-2" size={14}/>Resolve</button>
      </div>

      <div style={{ marginTop: 18, paddingTop: 14, borderTop: '1px solid var(--srf-line-soft)' }}>
        <div className="eyebrow" style={{ marginBottom: 6 }}>Implementation</div>
        <div style={{ fontSize: 11.5, color: 'var(--txt-subtle)', lineHeight: 1.6 }}>
          Items materialize from policy violations + auto-detection jobs into <span className="mono" style={{color:'var(--accent)'}}>governance_state.stewardship_items</span>. Resolution writes a row to the audit log and re-evaluates the policy on the next Lakeflow tick.
        </div>
      </div>
    </Card>
  );
}

function ActionRow({ icon, label, detail }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '10px 12px', background: 'var(--srf-2)', border: '1px solid var(--srf-line-soft)', borderRadius: 6, cursor: 'pointer' }}>
      <Icon name={icon} size={14} style={{ color: 'var(--accent)' }}/>
      <div style={{ flex: 1 }}>
        <div style={{ fontSize: 13, fontWeight: 500, color: 'var(--txt)' }}>{label}</div>
        {detail && <div style={{ fontSize: 11.5, color: 'var(--txt-subtle)' }}>{detail}</div>}
      </div>
      <Icon name="chevron-right" size={13} style={{ color: 'var(--txt-subtle)' }}/>
    </div>
  );
}

window.StewardshipPage = StewardshipPage;
