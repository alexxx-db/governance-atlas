/* eslint-disable */
/** Axiom — App Shell (sidebar + topbar) */
const { useState: useS, useEffect: useE } = React;

function Sidebar({ route, onRoute, openCounts }) {
  useLucide();
  const items = [
    { sec: 'Govern' },
    { id: 'exec',     label: 'Command Center',  icon: 'gauge-circle' },
    { id: 'discover', label: 'Discover',        icon: 'search' },
    { id: 'sk',       label: 'Stewardship',     icon: 'list-checks',  badge: openCounts?.stew },
    { sec: 'Knowledge' },
    { id: 'glossary', label: 'Glossary & CDEs', icon: 'book-text' },
    { id: 'lineage',  label: 'Lineage Atlas',   icon: 'git-fork' },
    { sec: 'Trust' },
    { id: 'audit',    label: 'Audit Evidence',  icon: 'shield-check' },
    { id: 'admin',    label: 'Control Center',  icon: 'sliders-horizontal' },
  ];
  return (
    <aside className="sidebar">
      <div className="sb-brand">
        <div className="mark">
          <img src="assets/scp-mark.svg" alt="Shore Capital Partners" width="32" height="32" style={{ display: 'block', borderRadius: 6 }}/>
        </div>
        <div className="name">Axiom<small>By Shore Capital Partners</small></div>
      </div>

      <nav style={{ flex: 1, overflow: 'auto', paddingBottom: 12 }}>
        {items.map((it, i) => it.sec
          ? <div className="sb-section" key={i}>{it.sec}</div>
          : (
            <div key={it.id} className="sb-nav">
              <div className={`sb-item ${route === it.id ? 'active' : ''}`} onClick={() => onRoute(it.id)}>
                <Icon name={it.icon} size={16}/>
                <span>{it.label}</span>
                {it.badge ? <span className="badge">{it.badge}</span> : null}
              </div>
            </div>
          )
        )}
      </nav>

      <div className="sb-foot">
        <Avatar name="Marisol Reyes" size={32} tone="blue"/>
        <div className="info">
          <div className="who">Marisol Reyes</div>
          <div className="role">Finance · Steward</div>
        </div>
        <Icon name="chevron-up" size={14} style={{ color: 'var(--txt-subtle)' }}/>
      </div>
    </aside>
  );
}

function Topbar({ onSearch, onRoute, onAI }) {
  useLucide();
  const [focus, setFocus] = useS(false);
  const [q, setQ] = useS('');
  return (
    <div className="topbar">
      <div className="tb-left">
        <Icon name="layout-grid" size={14} style={{ color: 'var(--txt-subtle)' }}/>
        <span style={{ color: 'var(--txt-subtle)', fontSize: 12 }}>Workspace</span>
        <Icon name="chevron-right" size={12} style={{ color: 'var(--txt-subtle)' }}/>
        <span style={{ color: 'var(--txt)', fontSize: 12, fontWeight: 600 }}>prod</span>
      </div>
      <div className={`tb-search ${focus ? 'focus' : ''}`}>
        <Icon name="search" size={15}/>
        <input
          placeholder="Search assets, columns, glossary terms, owners…"
          value={q}
          onChange={e => { setQ(e.target.value); }}
          onFocus={() => setFocus(true)}
          onBlur={() => setFocus(false)}
          onKeyDown={(e) => { if (e.key === 'Enter') onSearch && onSearch(q); }}
        />
        <kbd>⌘K</kbd>
      </div>
      <div className="tb-actions">
        <div className="tb-status"><span className="dot"></span>UC connected · 87.4% coverage</div>
        <button className="tb-btn"><Icon name="bell" size={15}/></button>
        <button className="tb-btn"><Icon name="help-circle" size={15}/></button>
        <button className="tb-btn primary" onClick={onAI}><Icon name="sparkles" size={14}/>Axiom AI</button>
      </div>
    </div>
  );
}

Object.assign(window, { Sidebar, Topbar });
