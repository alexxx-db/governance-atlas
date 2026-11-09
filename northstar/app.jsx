/* eslint-disable */
/** Axiom — root */
const { useState: uSR, useEffect: uER } = React;

function App() {
  const [route, setRoute] = uSR('exec');
  const [asset, setAsset] = uSR(null);
  const [aiOpen, setAiOpen] = uSR(false);

  uER(() => { try { window.lucide && window.lucide.createIcons(); } catch (e) {} });

  const openAsset = (idOrPath) => {
    // Allow lookup by id or path (path comes from activity feed strings)
    const a = window.GA.ASSETS.find(x => x.id === idOrPath || x.fullPath === idOrPath);
    if (a) setAsset(a.id);
    else if (idOrPath && idOrPath.includes('.')) {
      // create a minimal pseudo asset by best-guess match
      const guess = window.GA.ASSETS.find(x => idOrPath.includes(x.name)) || window.GA.ASSETS[0];
      setAsset(guess.id);
    }
  };

  return (
    <div className="app">
      <Sidebar route={route} onRoute={setRoute} openCounts={{ stew: 184 }}/>
      <Topbar onSearch={(q) => { setRoute('discover'); }} onAI={() => setAiOpen(o => !o)} onRoute={setRoute}/>
      <main className="main">
        {route === 'exec'     && <ExecPage onAsset={openAsset}/>}
        {route === 'discover' && <DiscoverPage onAsset={openAsset}/>}
        {route === 'sk'       && <StewardshipPage onAsset={openAsset}/>}
        {route === 'glossary' && <GlossaryPage onAsset={openAsset}/>}
        {route === 'lineage'  && <LineagePage onAsset={openAsset}/>}
        {route === 'audit'    && <AuditPage/>}
        {route === 'admin'    && <AdminPage/>}
      </main>

      <Asset360 assetId={asset} onClose={() => setAsset(null)} onLineage={() => { setAsset(null); setRoute('lineage'); }}/>

      <button className="ai-fab" onClick={() => setAiOpen(o => !o)}>
        <Icon name={aiOpen ? 'x' : 'sparkles'} size={22}/>
      </button>
      <AIPanel open={aiOpen} onClose={() => setAiOpen(false)} onAsset={(id) => { openAsset(id); setAiOpen(false); }} onRoute={setRoute}/>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(<App/>);
