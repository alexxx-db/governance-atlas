/* eslint-disable */
/**
 * Axiom — mock data contracts
 * Shape mirrors what we'd query from Unity Catalog system tables + governance Delta tables.
 * Comments map each shape to the feasible Databricks data source.
 */

// --- KPIs (governance posture) ---
// SOURCE: governance_state.kpi_snapshot Delta table, refreshed by a scheduled Lakeflow Job
const KPIS = [
  { id: 'coverage', label: 'Governance Coverage', value: 87.4, unit: '%', delta: +2.1, deltaText: '+2.1 pts vs last week', spark: [62,65,68,70,72,74,77,80,82,84,85,87], tone: 'good',
    note: '2,348 of 2,687 productionized assets meet baseline policy.' },
  { id: 'certified', label: 'Certified Assets', value: 612, unit: '', delta: +37, deltaText: '+37 this week', spark: [410,420,440,460,488,510,530,548,560,575,590,612], tone: 'good',
    note: 'Owners-confirmed, lineage-verified, freshness within SLA.' },
  { id: 'open',  label: 'Open Stewardship Items', value: 184, unit: '', delta: -11, deltaText: '-11 this week', spark: [240,232,228,222,218,212,205,200,196,192,190,184], tone: 'good',
    note: 'Across 6 work queues. SLA breach on 7.' },
  { id: 'risk', label: 'High-Risk Exposures', value: 7, unit: '', delta: +2, deltaText: '+2 new this week', spark: [5,5,5,5,5,5,6,6,6,7,7,7], tone: 'crit',
    note: '3 require review by Compliance.' },
];

// --- UC Catalogs (top-level) ---
// SOURCE: system.information_schema.catalogs joined with governance_state.catalog_health
const CATALOGS = [
  { name: 'finance_prod',   schemas: 14, tables: 412, coverage: 94, owners: 6, classified: 'Restricted',  risk: 'low'  },
  { name: 'sales_prod',     schemas: 22, tables: 781, coverage: 91, owners: 9, classified: 'Internal',    risk: 'low'  },
  { name: 'customer_360',   schemas: 18, tables: 528, coverage: 82, owners: 7, classified: 'Confidential', risk: 'med'  },
  { name: 'product_events', schemas: 9,  tables: 246, coverage: 76, owners: 4, classified: 'Internal',    risk: 'med'  },
  { name: 'marketing_mart', schemas: 11, tables: 192, coverage: 88, owners: 5, classified: 'Internal',    risk: 'low'  },
  { name: 'hr_secure',      schemas: 6,  tables: 84,  coverage: 71, owners: 3, classified: 'Restricted',  risk: 'high' },
  { name: 'ops_observability', schemas: 8, tables: 134, coverage: 81, owners: 4, classified: 'Internal',  risk: 'low'  },
  { name: 'experimental',   schemas: 5,  tables: 67,  coverage: 41, owners: 2, classified: 'Internal',    risk: 'med'  },
];

// --- Domains (business areas, derived from tag policy) ---
const DOMAINS = [
  { name: 'Revenue & Sales',   color: '#5B7FD0', coverage: 92, certified: 138, open: 22 },
  { name: 'Customer',          color: '#7497DC', coverage: 84, certified: 174, open: 41 },
  { name: 'Marketing',         color: '#C8C8C8', coverage: 88, certified: 89,  open: 14 },
  { name: 'Finance',           color: '#325396', coverage: 95, certified: 121, open: 8 },
  { name: 'Operations',        color: '#3D66B8', coverage: 79, certified: 64,  open: 27 },
  { name: 'People',            color: '#CDDAF4', coverage: 72, certified: 26,  open: 12 },
  { name: 'Risk & Compliance', color: '#8D8D8D', coverage: 81, certified: 48,  open: 19 },
];

// --- Search results / asset catalog ---
const ASSETS = [
  {
    id: 'fin_prod_revenue_daily',
    name: 'revenue_daily',
    fullPath: 'finance_prod.curated.revenue_daily',
    type: 'table',
    domain: 'Finance',
    owner: { name: 'Marisol Reyes', team: 'Finance Data Platform', avatar: 'MR' },
    steward: 'Finance Stewards',
    description: 'Authoritative day-grain revenue grain by product line, channel, and region. Source-of-record for the CFO dashboard and quarterly board reporting.',
    classification: 'Confidential',
    certification: 'Certified',
    cde: true,
    pii: false,
    rows: 1247835,
    cols: 18,
    sizeGb: 4.7,
    freshness: '14 min ago',
    freshnessSla: '15 min',
    freshnessOk: true,
    qualityScore: 96,
    usagePct: 98,
    queries30d: 14782,
    upstream: 5, downstream: 23,
    tags: ['CDE', 'sox-relevant', 'revenue', 'gold'],
    glossary: ['Net Revenue', 'Revenue Recognition'],
    risk: 'low',
  },
  {
    id: 'cust_360_profile',
    name: 'customer_profile',
    fullPath: 'customer_360.gold.customer_profile',
    type: 'table',
    domain: 'Customer',
    owner: { name: 'Aaron Chen', team: 'Customer Data Platform', avatar: 'AC' },
    steward: 'Customer Stewards',
    description: '360° unified customer profile: demographics, lifecycle stage, segments, contact channels. Driving personalization and CS routing.',
    classification: 'Restricted',
    certification: 'Certified',
    cde: true,
    pii: true,
    rows: 38400122,
    cols: 47,
    sizeGb: 64.2,
    freshness: '1 hr ago',
    freshnessSla: '1 hr',
    freshnessOk: true,
    qualityScore: 91,
    usagePct: 95,
    queries30d: 9210,
    upstream: 11, downstream: 41,
    tags: ['CDE', 'pii', 'gdpr-subject', 'gold'],
    glossary: ['Customer','Active Customer','Customer Segment'],
    risk: 'med',
  },
  {
    id: 'sales_orders_silver',
    name: 'orders',
    fullPath: 'sales_prod.silver.orders',
    type: 'table',
    domain: 'Revenue & Sales',
    owner: { name: 'Priya Natarajan', team: 'Sales Engineering', avatar: 'PN' },
    steward: 'Revenue Stewards',
    description: 'Cleansed order events with currency normalization. Feeds revenue, attribution, and finance pipelines.',
    classification: 'Confidential',
    certification: 'Certified',
    cde: true,
    pii: false,
    rows: 9148273,
    cols: 32,
    sizeGb: 28.4,
    freshness: '5 min ago',
    freshnessSla: '15 min',
    freshnessOk: true,
    qualityScore: 94,
    usagePct: 92,
    queries30d: 12044,
    upstream: 3, downstream: 17,
    tags: ['CDE', 'sox-relevant', 'gold-source'],
    glossary: ['Order','Booking','GMV'],
    risk: 'low',
  },
  {
    id: 'product_events_clickstream',
    name: 'clickstream_events',
    fullPath: 'product_events.bronze.clickstream_events',
    type: 'table',
    domain: 'Customer',
    owner: { name: 'Devon Park', team: 'Product Analytics', avatar: 'DP' },
    steward: 'Customer Stewards',
    description: 'Raw web + mobile click events from Snowplow. High volume; downstream pipelines aggregate into product_events.silver.sessions.',
    classification: 'Internal',
    certification: 'In Review',
    cde: false,
    pii: true,
    rows: 4287400000,
    cols: 22,
    sizeGb: 2840,
    freshness: '3 min ago',
    freshnessSla: '5 min',
    freshnessOk: true,
    qualityScore: 78,
    usagePct: 41,
    queries30d: 244,
    upstream: 1, downstream: 6,
    tags: ['high-volume','pii-ip','gdpr-subject'],
    glossary: ['Session','Page View'],
    risk: 'med',
  },
  {
    id: 'hr_compensation',
    name: 'compensation_band',
    fullPath: 'hr_secure.confidential.compensation_band',
    type: 'table',
    domain: 'People',
    owner: { name: 'Yuki Tanaka', team: 'People Analytics', avatar: 'YT' },
    steward: 'People Stewards',
    description: 'Compensation band metadata by job family + level. Restricted access. Permission-gated.',
    classification: 'Restricted',
    certification: 'Certified',
    cde: true,
    pii: true,
    rows: 1248,
    cols: 11,
    sizeGb: 0.02,
    freshness: '6 hr ago',
    freshnessSla: '1 day',
    freshnessOk: true,
    qualityScore: 99,
    usagePct: 12,
    queries30d: 86,
    upstream: 2, downstream: 0,
    tags: ['CDE','pii','restricted'],
    glossary: ['Compensation Band'],
    risk: 'low',
    permissionGated: true,
  },
  {
    id: 'mkt_attribution',
    name: 'attribution_daily',
    fullPath: 'marketing_mart.gold.attribution_daily',
    type: 'view',
    domain: 'Marketing',
    owner: { name: 'Lina Okafor', team: 'Marketing Analytics', avatar: 'LO' },
    steward: 'Marketing Stewards',
    description: 'Multi-touch attribution at the campaign × channel × day grain. Used by exec marketing dashboards.',
    classification: 'Internal',
    certification: 'Certified',
    cde: false,
    pii: false,
    rows: 412009,
    cols: 24,
    sizeGb: 1.1,
    freshness: '32 min ago',
    freshnessSla: '1 hr',
    freshnessOk: true,
    qualityScore: 88,
    usagePct: 73,
    queries30d: 2810,
    upstream: 6, downstream: 11,
    tags: ['gold','exec-dashboard'],
    glossary: ['Attribution','Touchpoint'],
    risk: 'low',
  },
  {
    id: 'churn_model',
    name: 'churn_propensity_v3',
    fullPath: 'customer_360.ml.churn_propensity_v3',
    type: 'model',
    domain: 'Customer',
    owner: { name: 'Aaron Chen', team: 'Customer Data Platform', avatar: 'AC' },
    steward: 'Customer Stewards',
    description: 'Gradient-boosted churn propensity served via Databricks Model Serving. Inputs: customer_profile, billing_events.',
    classification: 'Confidential',
    certification: 'Certified',
    cde: false,
    pii: false,
    rows: null,
    cols: null,
    sizeGb: null,
    freshness: '2 day ago',
    freshnessSla: '7 day',
    freshnessOk: true,
    qualityScore: 92,
    usagePct: 64,
    queries30d: 411,
    upstream: 3, downstream: 4,
    tags: ['model','served'],
    glossary: ['Churn Propensity'],
    risk: 'low',
  },
  {
    id: 'experimental_test',
    name: 'pricing_experiment_2025q4',
    fullPath: 'experimental.sandbox.pricing_experiment_2025q4',
    type: 'table',
    domain: 'Revenue & Sales',
    owner: { name: 'Unassigned', team: '—', avatar: '?' },
    steward: 'Unassigned',
    description: 'Sandbox table from a pricing experiment. No owner, no description until last week. Auto-flagged.',
    classification: 'Unclassified',
    certification: 'Uncertified',
    cde: false,
    pii: false,
    rows: 88401,
    cols: 14,
    sizeGb: 0.3,
    freshness: '12 day ago',
    freshnessSla: 'none',
    freshnessOk: false,
    qualityScore: 42,
    usagePct: 8,
    queries30d: 14,
    upstream: 1, downstream: 0,
    tags: ['sandbox','no-owner'],
    glossary: [],
    risk: 'high',
  },
];

// --- Asset 360: column metadata for revenue_daily ---
const ASSET_COLUMNS = {
  fin_prod_revenue_daily: [
    { name: 'reporting_date', type: 'DATE', null: 0, unique: 100, tags: ['partition-key'], desc: 'Calendar day, UTC.', cde: true },
    { name: 'product_line_id', type: 'STRING', null: 0, unique: 0.001, tags: ['fk:product_line'], desc: 'FK to product_line dim.', cde: false },
    { name: 'channel', type: 'STRING', null: 0.02, unique: 0.0002, tags: ['enum'], desc: 'Sales channel: direct/partner/online/retail.', cde: false },
    { name: 'region', type: 'STRING', null: 0, unique: 0.0001, tags: ['enum'], desc: 'NA / EMEA / APAC / LATAM.', cde: false },
    { name: 'gross_revenue_usd', type: 'DECIMAL(18,2)', null: 0, unique: 88, tags: ['CDE','currency:USD'], desc: 'Gross revenue in USD before discounts and refunds.', cde: true },
    { name: 'discount_usd', type: 'DECIMAL(18,2)', null: 0.001, unique: 41, tags: ['currency:USD'], desc: 'Discount applied at the order line.', cde: false },
    { name: 'net_revenue_usd', type: 'DECIMAL(18,2)', null: 0, unique: 92, tags: ['CDE','currency:USD','sox-relevant'], desc: 'Net revenue after discounts and refunds. Source-of-record metric.', cde: true },
    { name: 'order_count', type: 'BIGINT', null: 0, unique: 4, tags: [], desc: 'Number of orders aggregated to this grain.', cde: false },
    { name: 'is_recognized', type: 'BOOLEAN', null: 0, unique: 0.0001, tags: ['sox-relevant'], desc: 'Whether revenue is fully recognized per ASC 606.', cde: true },
    { name: 'load_ts', type: 'TIMESTAMP', null: 0, unique: 100, tags: ['audit'], desc: 'Load timestamp (UTC). Used for incremental loads.', cde: false },
  ],
  cust_360_profile: [
    { name: 'customer_id', type: 'STRING', null: 0, unique: 100, tags: ['pk','CDE'], desc: 'Stable customer identifier.', cde: true },
    { name: 'email_hash', type: 'STRING', null: 0.0, unique: 99.6, tags: ['pii','hashed'], desc: 'SHA-256 of email. Raw email is not stored here.', cde: false, masked: true },
    { name: 'first_name', type: 'STRING', null: 0.04, unique: 38, tags: ['pii'], desc: 'Given name. Permission-gated; masked for non-Restricted readers.', cde: false, masked: true },
    { name: 'last_name', type: 'STRING', null: 0.04, unique: 56, tags: ['pii'], desc: 'Family name. Permission-gated.', cde: false, masked: true },
    { name: 'lifecycle_stage', type: 'STRING', null: 0, unique: 0.0001, tags: ['enum'], desc: 'lead / active / dormant / churned.', cde: true },
    { name: 'segment_id', type: 'STRING', null: 0.01, unique: 0.0008, tags: ['fk:segment'], desc: 'Active marketing segment.', cde: false },
    { name: 'lifetime_value_usd', type: 'DECIMAL(18,2)', null: 0.001, unique: 87, tags: ['CDE','currency:USD'], desc: 'Modeled LTV.', cde: true },
    { name: 'consent_marketing', type: 'BOOLEAN', null: 0, unique: 0.0001, tags: ['gdpr','consent'], desc: 'Marketing consent. Sourced from CDP.', cde: true },
    { name: 'updated_at', type: 'TIMESTAMP', null: 0, unique: 12, tags: ['audit'], desc: 'Last update timestamp.', cde: false },
  ],
};

// --- Lineage graph for revenue_daily (permission-aware) ---
// SOURCE: system.access.table_lineage + system.access.column_lineage (Unity Catalog)
// Layered DAG: bronze → silver → gold → consumers
const LINEAGE = {
  focus: 'fin_prod_revenue_daily',
  nodes: [
    // upstream
    { id: 'sf_orders',         label: 'salesforce.orders',                  layer: 0, type: 'source',     domain: 'Sales',    cert: 'external',   x: 0, y: 0 },
    { id: 'stripe_charges',    label: 'stripe.charges',                     layer: 0, type: 'source',     domain: 'Payments', cert: 'external',   x: 0, y: 1 },
    { id: 'erp_invoices',      label: 'netsuite.invoices',                  layer: 0, type: 'source',     domain: 'Finance',  cert: 'external',   x: 0, y: 2 },

    { id: 'orders_bronze',     label: 'sales_prod.bronze.orders_raw',       layer: 1, type: 'table',      domain: 'Sales',    cert: 'uncertified',x: 1, y: 0 },
    { id: 'charges_bronze',    label: 'finance_prod.bronze.charges_raw',    layer: 1, type: 'table',      domain: 'Finance',  cert: 'uncertified',x: 1, y: 1 },
    { id: 'invoices_bronze',   label: 'finance_prod.bronze.invoices_raw',   layer: 1, type: 'table',      domain: 'Finance',  cert: 'uncertified',x: 1, y: 2 },

    { id: 'orders_silver',     label: 'sales_prod.silver.orders',           layer: 2, type: 'table',      domain: 'Sales',    cert: 'certified',  x: 2, y: 0 },
    { id: 'payments_silver',   label: 'finance_prod.silver.payments',       layer: 2, type: 'table',      domain: 'Finance',  cert: 'certified',  x: 2, y: 1.5 },

    { id: 'revenue_recognition', label: 'finance_prod.gold.revenue_recognition', layer: 3, type: 'job', domain: 'Finance', cert: 'job', x: 3, y: 1 },

    { id: 'fin_prod_revenue_daily', label: 'finance_prod.curated.revenue_daily', layer: 4, type: 'table', domain: 'Finance', cert: 'certified', focus: true, x: 4, y: 1 },

    // downstream
    { id: 'cfo_dash',          label: 'CFO Quarterly Dashboard',            layer: 5, type: 'dashboard',  domain: 'Finance',  cert: 'certified',  x: 5, y: 0 },
    { id: 'board_pack',        label: 'Board Pack — Revenue',               layer: 5, type: 'dashboard',  domain: 'Finance',  cert: 'certified',  x: 5, y: 1 },
    { id: 'rev_forecast',      label: 'finance_prod.ml.revenue_forecast',   layer: 5, type: 'model',      domain: 'Finance',  cert: 'certified',  x: 5, y: 2 },
    { id: 'restricted_view_1', label: '4 downstream assets',                 layer: 5, type: 'restricted', domain: '—',        cert: 'restricted', x: 5, y: 3 },
  ],
  edges: [
    ['sf_orders','orders_bronze'], ['stripe_charges','charges_bronze'], ['erp_invoices','invoices_bronze'],
    ['orders_bronze','orders_silver'], ['charges_bronze','payments_silver'], ['invoices_bronze','payments_silver'],
    ['orders_silver','revenue_recognition'], ['payments_silver','revenue_recognition'],
    ['revenue_recognition','fin_prod_revenue_daily'],
    ['fin_prod_revenue_daily','cfo_dash'], ['fin_prod_revenue_daily','board_pack'],
    ['fin_prod_revenue_daily','rev_forecast'], ['fin_prod_revenue_daily','restricted_view_1'],
  ],
};

// --- Stewardship work items ---
// SOURCE: governance_state.stewardship_items Delta table; SLA computed by job
const STEW_ITEMS = [
  { id: 'SI-2491', kind: 'Owner missing', priority: 'P1', asset: 'experimental.sandbox.pricing_experiment_2025q4', assigned: 'Revenue Stewards', sla: '4d overdue', slaState: 'crit', age: '11d', evidence: 'Auto-flag: no owner set; queries detected from 3 users.' },
  { id: 'SI-2487', kind: 'Description missing', priority: 'P2', asset: 'product_events.bronze.clickstream_events', assigned: 'Customer Stewards', sla: '2d left', slaState: 'warn', age: '5d', evidence: '4 columns lack descriptions on a high-volume bronze table.' },
  { id: 'SI-2482', kind: 'Re-certification due', priority: 'P2', asset: 'finance_prod.curated.revenue_daily', assigned: 'Marisol Reyes', sla: 'Today', slaState: 'warn', age: '89d', evidence: '90-day quarterly recert. Owner sign-off required.' },
  { id: 'SI-2479', kind: 'Tag policy violation', priority: 'P1', asset: 'customer_360.silver.contact_events', assigned: 'Customer Stewards', sla: '1d overdue', slaState: 'crit', age: '8d', evidence: 'PII columns missing required `pii` and `gdpr-subject` tags.' },
  { id: 'SI-2475', kind: 'Lineage gap', priority: 'P3', asset: 'marketing_mart.gold.attribution_daily', assigned: 'Marketing Stewards', sla: '6d left', slaState: 'good', age: '2d', evidence: '2 upstream sources not declared. Partial lineage.' },
  { id: 'SI-2471', kind: 'Quality regression', priority: 'P1', asset: 'sales_prod.silver.orders', assigned: 'Priya Natarajan', sla: '12h left', slaState: 'warn', age: '1d', evidence: 'Null rate on `currency_code` rose from 0.01% → 1.4%.' },
  { id: 'SI-2469', kind: 'Access exception', priority: 'P2', asset: 'hr_secure.confidential.compensation_band', assigned: 'People Stewards', sla: '3d left', slaState: 'good', age: '1d', evidence: 'Temporary grant requested by Comp Strategy — needs review.' },
  { id: 'SI-2462', kind: 'Glossary mapping', priority: 'P3', asset: 'customer_360.gold.customer_profile', assigned: 'Customer Stewards', sla: '8d left', slaState: 'good', age: '4d', evidence: '"Active Customer" definition diverges from glossary canonical.' },
];

// --- Audit events (immutable evidence) ---
// SOURCE: governance_state.audit_log (append-only Delta) + system.access.audit
const AUDIT_EVENTS = [
  { id: 'AE-78421', ts: '2026-04-27 09:14:22Z', actor: 'marisol.reyes@shorecp.com', actorType: 'user', kind: 'Certification', target: 'finance_prod.curated.revenue_daily', summary: 'Re-certified for Q2 2026.', evidence: '4 checks passed: owner, description, lineage coverage, freshness SLA.', sev: 'info' },
  { id: 'AE-78418', ts: '2026-04-27 08:52:09Z', actor: 'svc-governance-sweeper', actorType: 'service', kind: 'Tag applied',  target: 'customer_360.silver.contact_events', summary: 'Auto-tagged 6 columns as `pii` after classifier scan v2026.04.', evidence: 'Job run ID 9821044 · Classifier confidence ≥ 0.92.', sev: 'info' },
  { id: 'AE-78415', ts: '2026-04-27 08:31:44Z', actor: 'aaron.chen@shorecp.com', actorType: 'user', kind: 'Grant',  target: 'customer_360.gold.customer_profile', summary: 'Granted SELECT to `customer-success-leads` group.', evidence: 'Approved via stewardship workflow SI-2440. Justification on file.', sev: 'info' },
  { id: 'AE-78410', ts: '2026-04-27 07:58:01Z', actor: 'svc-policy-engine', actorType: 'service', kind: 'Policy violation', target: 'experimental.sandbox.pricing_experiment_2025q4', summary: 'Owner-required policy failed.', evidence: 'No principal in `owner` grant set. Quarantined from search index.', sev: 'crit' },
  { id: 'AE-78404', ts: '2026-04-27 07:14:55Z', actor: 'priya.natarajan@shorecp.com', actorType: 'user', kind: 'Quality alert', target: 'sales_prod.silver.orders', summary: 'Acknowledged quality regression on `currency_code`.', evidence: 'Linked to Lakeflow run 1029384 · DQ check `currency_code_not_null`.', sev: 'warn' },
  { id: 'AE-78401', ts: '2026-04-27 06:42:31Z', actor: 'svc-lineage-collector', actorType: 'service', kind: 'Lineage updated', target: 'finance_prod.gold.revenue_recognition', summary: 'Captured new column-level lineage for `is_recognized`.', evidence: 'Source: `system.access.column_lineage` · 38 new edges.', sev: 'info' },
  { id: 'AE-78395', ts: '2026-04-27 05:18:12Z', actor: 'devon.park@shorecp.com', actorType: 'user', kind: 'Description', target: 'product_events.bronze.clickstream_events', summary: 'Edited table description.', evidence: 'Diff: +148 / -24 chars. Reviewer: Customer Stewards.', sev: 'info' },
  { id: 'AE-78388', ts: '2026-04-26 22:04:00Z', actor: 'compliance-bot', actorType: 'service', kind: 'Access review', target: 'hr_secure.*', summary: 'Quarterly access review completed.', evidence: '12 grants reviewed · 2 revoked · 0 escalations.', sev: 'good' },
];

// --- AI assistant — canned answer with citations ---
const AI_THREADS = [
  { role: 'user', text: "What's powering the CFO Quarterly Dashboard, and is anything at risk this week?" },
  { role: 'assistant',
    answer: "The CFO Quarterly Dashboard is powered by `finance_prod.curated.revenue_daily`, which is **Certified** and within its 15-minute freshness SLA. There is one item to be aware of this week: a **re-certification is due today** for revenue_daily (SI-2482, owner Marisol Reyes). Two upstream silver tables are healthy. No active lineage gaps or quality regressions affect this dashboard.",
    plan: [
      'Resolve dashboard → primary asset via Unity Catalog lineage.',
      'Pull certification + freshness from governance_state.kpi_snapshot.',
      'Filter open stewardship items where asset_path matches.',
    ],
    citations: [
      { kind: 'asset', label: 'finance_prod.curated.revenue_daily', meta: 'Certified · 14 min ago', target: 'fin_prod_revenue_daily' },
      { kind: 'lineage', label: 'CFO Quarterly Dashboard ← revenue_daily', meta: 'system.access.table_lineage' },
      { kind: 'work', label: 'SI-2482 · Re-certification due', meta: 'Today · Marisol Reyes' },
      { kind: 'audit', label: 'AE-78421 · Last certification', meta: '2026-04-27 09:14Z' },
    ],
    grounding: 'Answer is grounded in Unity Catalog metadata + governance Delta tables. No raw row values were read.',
  },
];

// --- Glossary terms (cross-referenced) ---
const GLOSSARY = [
  { term: 'Net Revenue', domain: 'Finance', steward: 'Finance Stewards', status: 'Approved', def: 'Gross revenue minus discounts and refunds; recognized per ASC 606. Source-of-record column: `finance_prod.curated.revenue_daily.net_revenue_usd`.', linkedAssets: 4 },
  { term: 'Active Customer', domain: 'Customer', steward: 'Customer Stewards', status: 'Approved', def: 'A customer with at least one billable order in the trailing 90 days. Computed in `customer_360.gold.customer_profile.lifecycle_stage`.', linkedAssets: 7 },
  { term: 'Churn Propensity', domain: 'Customer', steward: 'Customer Stewards', status: 'Approved', def: 'Modeled probability that a customer will churn in the next 30 days. Served via `customer_360.ml.churn_propensity_v3`.', linkedAssets: 3 },
  { term: 'Booking', domain: 'Revenue & Sales', steward: 'Revenue Stewards', status: 'In Review', def: 'A confirmed order, regardless of recognition status.', linkedAssets: 6 },
];

// --- CDE registry ---
const CDES = [
  { name: 'Net Revenue (USD)', column: 'finance_prod.curated.revenue_daily.net_revenue_usd', owner: 'Finance Stewards', sox: true, recert: '90d', status: 'Healthy' },
  { name: 'Customer ID', column: 'customer_360.gold.customer_profile.customer_id', owner: 'Customer Stewards', sox: false, recert: '180d', status: 'Healthy' },
  { name: 'Lifetime Value (USD)', column: 'customer_360.gold.customer_profile.lifetime_value_usd', owner: 'Customer Stewards', sox: false, recert: '90d', status: 'Recert due (8d)' },
  { name: 'Compensation Band', column: 'hr_secure.confidential.compensation_band.band_id', owner: 'People Stewards', sox: false, recert: '180d', status: 'Healthy' },
  { name: 'Order Total (USD)', column: 'sales_prod.silver.orders.gross_total_usd', owner: 'Revenue Stewards', sox: true, recert: '90d', status: 'Healthy' },
];

// Recent activity (executive feed)
const RECENT_ACTIVITY = [
  { ts: '12 min ago', who: 'svc-governance-sweeper', what: 'flagged 1 asset for missing owner', target: 'experimental.sandbox.pricing_experiment_2025q4', kind: 'flag', sev: 'crit' },
  { ts: '32 min ago', who: 'Marisol Reyes', what: 'certified', target: 'finance_prod.curated.revenue_daily', kind: 'cert', sev: 'good' },
  { ts: '54 min ago', who: 'svc-classifier', what: 'auto-tagged PII columns on', target: 'customer_360.silver.contact_events', kind: 'tag', sev: 'info' },
  { ts: '1 hr ago', who: 'Aaron Chen', what: 'approved access for `customer-success-leads` to', target: 'customer_360.gold.customer_profile', kind: 'grant', sev: 'info' },
  { ts: '2 hr ago', who: 'Priya Natarajan', what: 'acknowledged quality alert on', target: 'sales_prod.silver.orders', kind: 'alert', sev: 'warn' },
];

// Coverage by domain (for the donut + bar combo)
const COVERAGE_TIMESERIES = [
  { week: 'W14', value: 78.4 },
  { week: 'W15', value: 79.1 },
  { week: 'W16', value: 81.0 },
  { week: 'W17', value: 82.3 },
  { week: 'W18', value: 83.7 },
  { week: 'W19', value: 84.2 },
  { week: 'W20', value: 85.0 },
  { week: 'W21', value: 85.4 },
  { week: 'W22', value: 86.0 },
  { week: 'W23', value: 86.4 },
  { week: 'W24', value: 86.9 },
  { week: 'W25', value: 87.4 },
];

// Asset type icon map (Lucide)
const ASSET_ICON = { table: 'table-2', view: 'layers', model: 'brain', dashboard: 'layout-dashboard', source: 'cloud-download', job: 'workflow', restricted: 'lock', notebook: 'book-open', volume: 'hard-drive' };

window.GA = {
  KPIS, CATALOGS, DOMAINS, ASSETS, ASSET_COLUMNS, LINEAGE, STEW_ITEMS, AUDIT_EVENTS, AI_THREADS, GLOSSARY, CDES, RECENT_ACTIVITY, COVERAGE_TIMESERIES, ASSET_ICON,
};
