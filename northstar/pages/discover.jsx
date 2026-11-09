/* eslint-disable */
/** Discover (search) page */
const { useState: uS2, useMemo: uM } = React;

function DiscoverPage({ onAsset }) {
  useLucide();
  const { ASSETS } = window.GA;
  const [query, setQuery] = uS2('');
  const [filters, setFilters] = uS2({ cert: null, domain: null, classification: null, cde: false, pii: null });
  const [selected, setSelected] = uS2(null);

  const filtered = uM(() => {
    return ASSETS.filter(a => {
      if (query && !`${a.name} ${a.fullPath} ${a.description} ${a.tags.join(' ')}`.toLowerCase().includes(query.toLowerCase())) return false;
      if (filters.cert && a.certification !== filters.cert) return false;
      if (filters.domain && a.domain !== filters.domain) return false;
      if (filters.classification && a.classification !== filters.classification) return false;
      if (filters.cde && !a.cde) return false;
      if (filters.pii === true && !a.pii) return false;
      if (filters.pii === false && a.pii) return false;
      return true;
    });
  }, [query, filters]);

  const toggle = (k, v) => setFilters(f => ({ ...f, [k]: f[k] === v ? null : v }));

  return (
    <div className="page">
      <PageHead
        eyebrow="Discover"
        title="Find trusted, governed data"
        sub="Search across catalogs, schemas, tables, columns, models, and glossary terms. Results are permission-aware and ranked by trust signal."
      />

      {/* Search bar */}
      <div style={{ display: 'flex', gap: 12, marginBottom: 16 }}>
        <div style={{ flex: 1, display: 'flex', alignItems: 'center', gap: 10, background: 'var(--srf-2)', border: '1px solid var(--srf-line)', borderRadius: 12, padding: '10px 14px' }}>
          <Icon name="search" size={16} style={{ color: 'var(--accent)' }}/>
          <input
            placeholder="Try: revenue, customer_id, churn, marisol, sox-relevant…"
            value={query}
            onChange={e => setQuery(e.target.value)}
            style={{ flex: 1, background: 'transparent', border: 0, outline: 0, color: 'var(--txt)', fontSize: 14, fontFamily: 'inherit' }}
          />
          {query && <button className="btn btn-ghost btn-sm" onClick={() => setQuery('')}><Icon name="x" size={12}/></button>}
        </div>
        <button className="btn btn-secondary"><Icon name="bookmark" size={14}/>Saved searches</button>
        <button className="btn btn-secondary"><Icon name="filter" size={14}/>Advanced</button>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '240px 1fr', gap: 16 }}>
        {/* Filter rail */}
        <aside style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <FilterGroup label="Certification">
            <FilterPill active={filters.cert === 'Certified'}    onClick={() => toggle('cert', 'Certified')}><Chip tone="good" dot>Certified</Chip><span className="subtle" style={{marginLeft:'auto'}}>{ASSETS.filter(a => a.certification === 'Certified').length}</span></FilterPill>
            <FilterPill active={filters.cert === 'In Review'}    onClick={() => toggle('cert', 'In Review')}><Chip tone="warn" dot>In Review</Chip><span className="subtle" style={{marginLeft:'auto'}}>{ASSETS.filter(a => a.certification === 'In Review').length}</span></FilterPill>
            <FilterPill active={filters.cert === 'Uncertified'}  onClick={() => toggle('cert', 'Uncertified')}><Chip tone="crit" dot>Uncertified</Chip><span className="subtle" style={{marginLeft:'auto'}}>{ASSETS.filter(a => a.certification === 'Uncertified').length}</span></FilterPill>
          </FilterGroup>

          <FilterGroup label="Domain">
            {window.GA.DOMAINS.map(d => (
              <FilterPill key={d.name} active={filters.domain === d.name} onClick={() => toggle('domain', d.name)}>
                <span style={{ width: 8, height: 8, borderRadius: 2, background: d.color, display:'inline-block' }}></span>
                {d.name}
              </FilterPill>
            ))}
          </FilterGroup>

          <FilterGroup label="Classification">
            {['Restricted','Confidential','Internal','Unclassified'].map(c => (
              <FilterPill key={c} active={filters.classification === c} onClick={() => toggle('classification', c)}><ClassChip value={c}/></FilterPill>
            ))}
          </FilterGroup>

          <FilterGroup label="Attributes">
            <FilterPill active={filters.cde} onClick={() => setFilters(f => ({...f, cde: !f.cde}))}><Icon name="key-round" size={12} style={{color:'var(--teal)'}}/>Critical Data Element</FilterPill>
            <FilterPill active={filters.pii === true} onClick={() => setFilters(f => ({...f, pii: f.pii === true ? null : true}))}><Icon name="shield-alert" size={12} style={{color:'var(--crit)'}}/>Contains PII</FilterPill>
            <FilterPill active={filters.pii === false} onClick={() => setFilters(f => ({...f, pii: f.pii === false ? null : false}))}><Icon name="shield-off" size={12}/>No PII</FilterPill>
          </FilterGroup>
        </aside>

        {/* Results */}
        <div>
          <div style={{ display:'flex', alignItems:'center', justifyContent:'space-between', marginBottom: 12 }}>
            <div className="muted" style={{ fontSize: 13 }}>
              <span className="strong" style={{ color: 'var(--txt-strong)', fontWeight: 700 }}>{filtered.length}</span> results
              {query && <> for <span className="mono" style={{ color: 'var(--accent)' }}>"{query}"</span></>}
            </div>
            <div style={{ display: 'flex', gap: 6 }}>
              <button className="btn btn-ghost btn-sm">Sort: Trust score<Icon name="chevron-down" size={12}/></button>
              <button className="btn btn-ghost btn-sm"><Icon name="layout-grid" size={12}/></button>
              <button className="btn btn-secondary btn-sm"><Icon name="list" size={12}/></button>
            </div>
          </div>

          {filtered.length === 0 ? (
            <Card><Empty icon="search-x" title="No matching assets" sub="Try a different term or clear filters."/></Card>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              {filtered.map(a => (
                <SearchResult key={a.id} asset={a} onClick={() => onAsset(a.id)}/>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function FilterGroup({ label, children }) {
  return (
    <div>
      <div className="eyebrow" style={{ marginBottom: 8 }}>{label}</div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>{children}</div>
    </div>
  );
}
function FilterPill({ active, onClick, children }) {
  return (
    <div onClick={onClick} style={{
      display: 'flex', alignItems: 'center', gap: 8,
      padding: '6px 10px', borderRadius: 6,
      border: `1px solid ${active ? 'var(--accent)' : 'transparent'}`,
      background: active ? 'rgba(91,127,208,0.10)' : 'transparent',
      cursor: 'pointer', fontSize: 12.5, color: 'var(--txt)',
      transition: 'all 160ms',
    }} onMouseEnter={e => !active && (e.currentTarget.style.background = 'var(--srf-2)')} onMouseLeave={e => !active && (e.currentTarget.style.background = 'transparent')}>
      {children}
    </div>
  );
}

function SearchResult({ asset, onClick }) {
  return (
    <div className="card" onClick={onClick} style={{ cursor: 'pointer', padding: 16, transition: 'all 160ms' }}
         onMouseEnter={e => { e.currentTarget.style.borderColor = 'var(--srf-line-strong)'; e.currentTarget.style.background = 'var(--srf-3)'; }}
         onMouseLeave={e => { e.currentTarget.style.borderColor = 'var(--srf-line-soft)'; e.currentTarget.style.background = 'var(--srf-2)'; }}>
      <div style={{ display: 'flex', gap: 14, alignItems: 'flex-start' }}>
        <div style={{ width: 38, height: 38, borderRadius: 8, background: 'var(--srf-3)', display:'flex', alignItems:'center', justifyContent:'center', color: 'var(--accent)', flexShrink: 0 }}>
          <Icon name={window.GA.ASSET_ICON[asset.type] || 'table-2'} size={18}/>
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4, flexWrap: 'wrap' }}>
            <span style={{ fontWeight: 700, color: 'var(--txt-strong)', fontSize: 15 }}>{asset.name}</span>
            <span className="mono subtle" style={{ fontSize: 12 }}>{asset.fullPath}</span>
            <CertBadge status={asset.certification}/>
            <ClassChip value={asset.classification}/>
            {asset.cde && <Chip tone="teal" icon="key-round">CDE</Chip>}
            {asset.pii && <Chip tone="crit" icon="shield-alert">PII</Chip>}
          </div>
          <div style={{ fontSize: 13, color: 'var(--txt-muted)', lineHeight: 1.5, marginBottom: 10 }}>{asset.description}</div>
          <div style={{ display: 'flex', gap: 16, fontSize: 12, color: 'var(--txt-subtle)', flexWrap: 'wrap' }}>
            <span><Icon name="user" size={11}/> <span style={{color:'var(--txt-muted)'}}>{asset.owner.name}</span></span>
            <span><Icon name="clock" size={11}/> Fresh {asset.freshness}</span>
            <span><Icon name="activity" size={11}/> {asset.queries30d.toLocaleString()} queries / 30d</span>
            <span><Icon name="git-fork" size={11}/> {asset.upstream}↑ {asset.downstream}↓</span>
            {asset.rows && <span><Icon name="rows-3" size={11}/> {(asset.rows/1e6).toFixed(1)}M rows</span>}
          </div>
        </div>
        <div style={{ textAlign: 'right', minWidth: 90 }}>
          <div style={{ fontFamily: 'var(--font-display)', fontWeight: 800, fontSize: 22, color: asset.qualityScore >= 90 ? 'var(--good)' : asset.qualityScore >= 75 ? 'var(--warn)' : 'var(--crit)', letterSpacing: '-0.02em' }}>{asset.qualityScore}</div>
          <div className="eyebrow">Trust</div>
        </div>
      </div>
    </div>
  );
}

window.DiscoverPage = DiscoverPage;
