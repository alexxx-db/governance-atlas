/* eslint-disable */
/** Axiom — UI primitives shared across pages */
const { useState, useEffect, useRef, useMemo } = React;

const Icon = ({ name, size = 16, style, className }) => (
  <i data-lucide={name} style={{ width: size, height: size, display: 'inline-block', ...style }} className={className}></i>
);

// Auto-call lucide.createIcons after every render
function useLucide(dep) {
  useEffect(() => { try { window.lucide && window.lucide.createIcons(); } catch (e) {} });
}

// ---------- Sparkline ----------
function Sparkline({ data, w = 86, h = 30, tone = 'good' }) {
  if (!data || data.length === 0) return null;
  const min = Math.min(...data), max = Math.max(...data);
  const range = max - min || 1;
  const step = w / (data.length - 1);
  const pts = data.map((v, i) => `${i * step},${h - ((v - min) / range) * h}`).join(' ');
  const color = tone === 'crit' ? 'var(--crit)' : tone === 'warn' ? 'var(--warn)' : 'var(--accent)';
  const fillColor = tone === 'crit' ? 'rgba(244,113,116,0.18)' : tone === 'warn' ? 'rgba(244,183,64,0.18)' : 'rgba(91,127,208,0.22)';
  return (
    <svg width={w} height={h} className="spark" viewBox={`0 0 ${w} ${h}`}>
      <polyline points={`0,${h} ${pts} ${w},${h}`} fill={fillColor} stroke="none" />
      <polyline points={pts} fill="none" stroke={color} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

// ---------- Donut ----------
function Donut({ value, size = 110, stroke = 10, tone = 'good', label, sub }) {
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const off = c - (value / 100) * c;
  const color = tone === 'crit' ? 'var(--crit)' : tone === 'warn' ? 'var(--warn)' : tone === 'info' ? 'var(--accent)' : 'var(--good)';
  return (
    <div style={{ position: 'relative', width: size, height: size }}>
      <svg width={size} height={size} className="donut">
        <circle cx={size/2} cy={size/2} r={r} fill="none" strokeWidth={stroke} className="track" />
        <circle cx={size/2} cy={size/2} r={r} fill="none" strokeWidth={stroke} stroke={color} strokeDasharray={c} strokeDashoffset={off} className="val" />
      </svg>
      <div style={{ position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center' }}>
        <div style={{ fontFamily: 'var(--font-display)', fontWeight: 800, fontSize: 22, color: 'var(--txt-strong)', letterSpacing: '-0.02em' }}>{value}<span style={{fontSize: 12, color:'var(--txt-muted)', marginLeft:2}}>%</span></div>
        {sub && <div style={{ fontSize: 10, color: 'var(--txt-subtle)', textTransform: 'uppercase', letterSpacing: '0.12em', marginTop: 2 }}>{sub}</div>}
      </div>
    </div>
  );
}

// ---------- Pill chip ----------
function Chip({ tone, dot, icon, children, style }) {
  return <span className={`chip ${tone || ''}`} style={style}>
    {dot && <span className="dot"></span>}
    {icon && <Icon name={icon} size={11}/>}
    {children}
  </span>;
}

// ---------- Asset name + icon row ----------
function AssetRow({ asset, onClick, dense }) {
  const ic = window.GA.ASSET_ICON[asset.type] || 'table-2';
  return (
    <div className="asset-row" onClick={onClick} style={{ cursor: onClick ? 'pointer' : 'default' }}>
      <div className="ico" style={dense ? { width: 26, height: 26 } : {}}><Icon name={ic} size={dense ? 14 : 16}/></div>
      <div className="meta">
        <span className="nm">{asset.name}</span>
        <span className="path">{asset.fullPath || asset.path}</span>
      </div>
    </div>
  );
}

// ---------- Cert badge ----------
function CertBadge({ status }) {
  if (status === 'Certified')   return <Chip tone="good"  icon="badge-check">Certified</Chip>;
  if (status === 'In Review')   return <Chip tone="warn"  icon="hourglass">In Review</Chip>;
  if (status === 'Uncertified') return <Chip tone="crit"  icon="alert-triangle">Uncertified</Chip>;
  return <Chip tone="info">{status}</Chip>;
}

// ---------- Classification chip ----------
function ClassChip({ value }) {
  const map = { Restricted: 'crit', Confidential: 'warn', Internal: 'info', Unclassified: '' };
  return <Chip tone={map[value]}>{value}</Chip>;
}

// ---------- Empty / Loading / Permission states ----------
function Empty({ icon = 'inbox', title, sub, action }) {
  return (
    <div style={{ padding: '40px 24px', textAlign: 'center', color: 'var(--txt-subtle)' }}>
      <Icon name={icon} size={28} style={{ color: 'var(--txt-subtle)', marginBottom: 12 }}/>
      <div style={{ color: 'var(--txt)', fontWeight: 600, fontSize: 14, marginBottom: 4 }}>{title}</div>
      <div style={{ fontSize: 13 }}>{sub}</div>
      {action && <div style={{ marginTop: 12 }}>{action}</div>}
    </div>
  );
}

function Veil({ children }) {
  return <div className="veil"><Icon name="lock" size={14}/> <div>{children}</div></div>;
}

// ---------- Avatar ----------
function Avatar({ name, size = 26, tone = 'blue' }) {
  const initials = (name || '?').split(' ').map(s=>s[0]).slice(0,2).join('').toUpperCase();
  const grad = tone === 'teal' ? 'linear-gradient(135deg,var(--hi),var(--teal))' :
               tone === 'warn' ? 'linear-gradient(135deg,#7a4a08,#F4B740)' :
               'linear-gradient(135deg,var(--navy),var(--hi-bright))';
  return <div style={{ width: size, height: size, borderRadius: 999, background: grad, color: 'var(--navy-deep)', fontWeight: 700, display:'inline-flex', alignItems:'center', justifyContent:'center', fontSize: size * 0.42, flexShrink: 0 }}>{initials}</div>;
}

// ---------- Page header ----------
function PageHead({ eyebrow, title, sub, actions }) {
  return (
    <div className="page-head">
      <div>
        {eyebrow && <span className="eyebrow">{eyebrow}</span>}
        <h1>{title}</h1>
        {sub && <div className="sub">{sub}</div>}
      </div>
      {actions && <div className="actions">{actions}</div>}
    </div>
  );
}

// ---------- Card wrapper ----------
function Card({ title, sub, actions, children, padded = true, style, className }) {
  return (
    <div className={`card ${className || ''}`} style={style}>
      {(title || actions) && (
        <div className="card-head">
          <div>
            {title && <h3>{title}</h3>}
            {sub && <div className="sub">{sub}</div>}
          </div>
          {actions && <div className="actions">{actions}</div>}
        </div>
      )}
      <div className={padded ? 'card-body' : 'card-body flush'}>{children}</div>
    </div>
  );
}

// ---------- Bars (mini) ----------
function MiniBars({ data, max, h = 80, color = 'var(--accent)' }) {
  const m = max || Math.max(...data.map(d => d.value));
  return (
    <div style={{ display: 'flex', alignItems: 'flex-end', gap: 6, height: h, padding: '0 2px' }}>
      {data.map((d, i) => (
        <div key={i} style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 6, minWidth: 0 }}>
          <div style={{ width: '100%', height: `${(d.value / m) * (h - 18)}px`, background: d.color || color, borderRadius: '3px 3px 0 0', minHeight: 4, opacity: 0.9 }} title={`${d.label}: ${d.value}`}></div>
          <div style={{ fontSize: 10, color: 'var(--txt-subtle)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', width: '100%', textAlign:'center' }}>{d.short || d.label}</div>
        </div>
      ))}
    </div>
  );
}

// ---------- Area chart (svg) ----------
function AreaChart({ data, w = 600, h = 200, accent = 'var(--accent)' }) {
  const xs = data.map((d, i) => i);
  const min = Math.min(...data.map(d => d.value)) - 2;
  const max = Math.max(...data.map(d => d.value)) + 2;
  const range = max - min;
  const stepX = (w - 40) / (data.length - 1);
  const pad = 20;
  const pts = data.map((d, i) => [pad + i * stepX, h - 28 - ((d.value - min) / range) * (h - 50)]);
  const path = pts.map((p, i) => {
    if (i === 0) return `M${p[0]},${p[1]}`;
    const prev = pts[i-1];
    const cx1 = prev[0] + (p[0] - prev[0]) * 0.5;
    const cx2 = p[0] - (p[0] - prev[0]) * 0.5;
    return `C${cx1},${prev[1]} ${cx2},${p[1]} ${p[0]},${p[1]}`;
  }).join(' ');
  const fill = `${path} L${pts[pts.length-1][0]},${h-28} L${pts[0][0]},${h-28} Z`;
  return (
    <svg width="100%" height={h} viewBox={`0 0 ${w} ${h}`} style={{ display: 'block' }}>
      <defs>
        <linearGradient id="ar" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="rgba(116,151,220,0.40)"/>
          <stop offset="50%" stopColor="rgba(116,151,220,0.12)"/>
          <stop offset="100%" stopColor="rgba(116,151,220,0.0)"/>
        </linearGradient>
        <linearGradient id="arLine" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0%" stopColor="#5B7FD0"/>
          <stop offset="100%" stopColor="#7497DC"/>
        </linearGradient>
        <filter id="glowChart" x="-20%" y="-20%" width="140%" height="140%">
          <feGaussianBlur stdDeviation="3" result="b"/>
          <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
        </filter>
      </defs>
      {/* SLA target line */}
      <line x1={pad} x2={w-pad} y1={h-28-((90-min)/range)*(h-50)} y2={h-28-((90-min)/range)*(h-50)}
        stroke="rgba(244,183,64,0.35)" strokeDasharray="4,4" strokeWidth="1"/>
      <text x={w-pad-2} y={h-28-((90-min)/range)*(h-50)-4} fontSize="9" fill="rgba(244,183,64,0.7)" textAnchor="end" letterSpacing="0.5">SLA 90%</text>

      {[0,0.25,0.5,0.75,1].map((g,i) => (
        <line key={i} x1={pad} x2={w-pad} y1={h-28-(g*(h-50))} y2={h-28-(g*(h-50))} stroke="var(--srf-line-soft)" strokeDasharray="2,4" opacity="0.6"/>
      ))}
      <path d={fill} fill="url(#ar)"/>
      <path d={path} fill="none" stroke="url(#arLine)" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" filter="url(#glowChart)"/>
      <path d={path} fill="none" stroke="url(#arLine)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
      {pts.map((p,i) => i === pts.length - 1 ? (
        <g key={i}>
          <circle cx={p[0]} cy={p[1]} r="8" fill="rgba(91,127,208,0.28)">
            <animate attributeName="r" values="6;12;6" dur="2.4s" repeatCount="indefinite"/>
            <animate attributeName="opacity" values="0.4;0;0.4" dur="2.4s" repeatCount="indefinite"/>
          </circle>
          <circle cx={p[0]} cy={p[1]} r="4" fill="var(--accent)" stroke="var(--srf-1)" strokeWidth="2"/>
        </g>
      ) : null)}
      {data.map((d, i) => i % 2 === 0 ? <text key={i} x={pad + i * stepX} y={h - 8} fontSize="10" fill="var(--txt-subtle)" textAnchor="middle" letterSpacing="0.5">{d.week}</text> : null)}
    </svg>
  );
}

// ---------- CountUp ----------
function CountUp({ to, dur = 1200, decimals = 0, suffix = '', prefix = '' }) {
  const [v, setV] = useState(0);
  useEffect(() => {
    let raf, start;
    const ease = t => 1 - Math.pow(1 - t, 3);
    const step = (ts) => {
      if (!start) start = ts;
      const t = Math.min(1, (ts - start) / dur);
      setV(to * ease(t));
      if (t < 1) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [to, dur]);
  const fmt = decimals ? v.toFixed(decimals) : Math.round(v).toLocaleString();
  return <span className="tnum">{prefix}{fmt}{suffix}</span>;
}

// ---------- TrustRing — signature hero centerpiece ----------
function TrustRing({ value = 87.4, size = 200, segments }) {
  // segments: [{value, color, label}] — sums to value (sub-rings)
  const stroke = 14;
  const r = (size - stroke - 24) / 2;
  const c = 2 * Math.PI * r;
  const off = c - (value / 100) * c;
  return (
    <div className="trust-ring" style={{ width: size, height: size, position: 'relative' }}>
      <div className="glow"></div>
      <svg width={size} height={size}>
        <defs>
          <linearGradient id="ringGrad" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor="#5B7FD0"/>
            <stop offset="60%" stopColor="#7497DC"/>
            <stop offset="100%" stopColor="#C8C8C8"/>
          </linearGradient>
          <linearGradient id="ringTrack" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="rgba(255,255,255,0.04)"/>
            <stop offset="100%" stopColor="rgba(255,255,255,0.01)"/>
          </linearGradient>
        </defs>
        {/* outer subtle ring */}
        <circle cx={size/2} cy={size/2} r={r + 10} fill="none" stroke="rgba(91,127,208,0.12)" strokeWidth="1"/>
        {/* tick marks */}
        {Array.from({length: 60}).map((_, i) => {
          const a = (i / 60) * Math.PI * 2 - Math.PI / 2;
          const r1 = r + 14, r2 = r + (i % 5 === 0 ? 18 : 16);
          const x1 = size/2 + Math.cos(a) * r1, y1 = size/2 + Math.sin(a) * r1;
          const x2 = size/2 + Math.cos(a) * r2, y2 = size/2 + Math.sin(a) * r2;
          return <line key={i} x1={x1} y1={y1} x2={x2} y2={y2} stroke={i % 5 === 0 ? 'rgba(91,127,208,0.55)' : 'rgba(91,127,208,0.22)'} strokeWidth="1"/>;
        })}
        {/* track */}
        <circle cx={size/2} cy={size/2} r={r} fill="none" stroke="rgba(255,255,255,0.05)" strokeWidth={stroke}/>
        {/* value */}
        <circle cx={size/2} cy={size/2} r={r} fill="none" stroke="url(#ringGrad)"
          strokeWidth={stroke} strokeDasharray={c} strokeDashoffset={off} strokeLinecap="round"
          transform={`rotate(-90 ${size/2} ${size/2})`}
          style={{ transition: 'stroke-dashoffset 1500ms cubic-bezier(0.22,1,0.36,1)' }}/>
      </svg>
      <div className="center">
        <div style={{ fontSize: 10, fontWeight: 600, letterSpacing: '0.16em', color: 'var(--accent)', textTransform: 'uppercase', marginBottom: 4 }}>Posture</div>
        <div className="v"><CountUp to={value} dur={1400} decimals={1}/><span style={{fontSize: 18, color: 'var(--txt-muted)', fontWeight: 600, marginLeft: 2}}>%</span></div>
        <div style={{ fontSize: 11, color: 'var(--good)', fontWeight: 600, marginTop: 4, display:'flex', alignItems:'center', gap:4 }}>
          <Icon name="trending-up" size={11}/>+9.0 pts QoQ
        </div>
      </div>
    </div>
  );
}

// ---------- FlowParticles — animated dots traveling along a path ----------
function FlowParticles({ path, count = 3, dur = 2.2, color = 'var(--accent)' }) {
  return (
    <>
      {Array.from({ length: count }).map((_, i) => (
        <circle key={i} r="2.5" fill={color} opacity="0.9">
          <animateMotion dur={`${dur}s`} repeatCount="indefinite" begin={`${(i * dur / count).toFixed(2)}s`}>
            <mpath href={`#${path}`}/>
          </animateMotion>
          <animate attributeName="opacity" values="0;0.9;0.9;0" keyTimes="0;0.1;0.9;1" dur={`${dur}s`} repeatCount="indefinite" begin={`${(i * dur / count).toFixed(2)}s`}/>
        </circle>
      ))}
    </>
  );
}

Object.assign(window, { Icon, useLucide, Sparkline, Donut, Chip, AssetRow, CertBadge, ClassChip, Empty, Veil, Avatar, PageHead, Card, MiniBars, AreaChart, CountUp, TrustRing, FlowParticles });
