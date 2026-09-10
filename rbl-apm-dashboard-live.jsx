import React, { useState, useMemo, useCallback } from "react";

const COLORS = {
  ink: "#1C2A3A", inkSecondary: "#5B6B7A", paper: "#F6F4EF", card: "#FFFFFF",
  border: "#DDD9CE", accent: "#5B6E4F", accentMuted: "#8FA283",
  risk: "#9B3A2E", riskMuted: "#C98F84",
  quadInvest: "#E4E9DE", quadTolerate: "#EDEAE1", quadMigrate: "#F2E2DE", quadEliminate: "#EAD3CC",
};

const DISPOSITION_INFO = {
  Retain: { color: "#5B6E4F", desc: "Healthy and valuable — leave as is." },
  Rehost: { color: "#6E8A8F", desc: "Healthy and valuable — just needs to move off legacy infrastructure." },
  Replatform: { color: "#B08A3E", desc: "Valuable but ageing, on legacy infrastructure — modernise while migrating." },
  Replace: { color: "#9B3A2E", desc: "Valuable but poor technical health — lift-and-shift won't fix this." },
  Retire: { color: "#7A6A73", desc: "Low value, or already being decommissioned." },
  Refactor: { color: "#6C7A99", desc: "Doesn't fit a clean pattern — needs architect judgement." },
};

const NODE_TYPE_COLOR = {
  Application: "#1C2A3A", SoftwareTechnology: "#5B6E4F",
  HardwareTechnology: "#8FA283", Data: "#B08A3E",
};

const DEPENDENCY_TYPES = new Set(["RUNS_ON", "DEPENDS_ON", "INTEGRATES_WITH"]);

const EDGE_STYLES = {
  RUNS_ON: { color: "#1C2A3A", dash: null, label: "runs on" },
  DEPENDS_ON: { color: "#9B3A2E", dash: null, label: "depends on" },
  INTEGRATES_WITH: { color: "#5B6E4F", dash: null, label: "integrates with" },
  STORES: { color: "#B08A3E", dash: "6,3", label: "stores" },
  PROVIDES: { color: "#4A7A8C", dash: "2,2", label: "provides" },
  STORED_BY: { color: "#8B5E83", dash: "9,3", label: "stored by" },
  DUPLICATES: { color: "#6B6B6B", dash: "1,3", label: "duplicates" },
  REPLACES: { color: "#C9752E", dash: "5,2,1,2", label: "replaces" },
  GOVERNED_BY: { color: "#6C7A99", dash: "3,4", label: "governed by" },
};
function edgeStyle(relType) {
  return EDGE_STYLES[relType] || { color: "#5B6B7A", dash: null, label: relType.toLowerCase().replace(/_/g, " ") };
}

const healthLabel = { 1: "Poor", 2: "Adequate", 3: "Good", 4: "Good" };
const valueLabel = { 1: "Low", 2: "Medium", 3: "High" };
const fmtGBP = (n) => n == null ? "—" : `£${Number(n).toLocaleString("en-GB", { maximumFractionDigits: 0 })}`;

function deriveQueryApiUrl(uri) {
  const host = uri.trim().replace(/^neo4j\+s:\/\//, "").replace(/^neo4j:\/\//, "")
    .replace(/^bolt\+s:\/\//, "").replace(/^bolt:\/\//, "").replace(/\/$/, "");
  return `https://${host}/db/neo4j/query/v2`;
}

async function runCypher(apiUrl, authHeader, statement, parameters = {}) {
  const res = await fetch(apiUrl, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json", Authorization: authHeader },
    body: JSON.stringify({ statement, parameters }),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`Query API returned ${res.status}: ${text || res.statusText}`);
  }
  const json = await res.json();
  const fields = json.data.fields;
  const values = json.data.values;
  return values.map((row) => Object.fromEntries(fields.map((f, i) => [f, row[i]])));
}

function computeDisposition(app) {
  if (app.status === "Retiring") return { code: "Retire", reason: "Already flagged for retirement" };
  if (!app.businessValue || !app.techHealth) return { code: "Refactor", reason: "Insufficient data to classify" };
  const onPrem = app.hosting === "On-Prem";
  if (app.businessValue <= 1) return { code: "Retire", reason: "Low business value" };
  if (app.businessValue >= 2 && app.techHealth <= 2) {
    return onPrem
      ? { code: "Replatform", reason: "Valuable but ageing, on legacy infrastructure" }
      : { code: "Replace", reason: "Valuable but poor technical health, already off-prem" };
  }
  if (app.businessValue >= 2 && app.techHealth >= 3) {
    return onPrem
      ? { code: "Rehost", reason: "Healthy and valuable, just needs to leave legacy infrastructure" }
      : { code: "Retain", reason: "Healthy, valuable, and already modern" };
  }
  return { code: "Refactor", reason: "Doesn't fit a clean pattern" };
}

// simple force-directed layout, no external library — fine for small graphs
function layoutGraph(nodes, links, width, height) {
  const pos = {};
  nodes.forEach((n, i) => {
    const angle = (i / nodes.length) * 2 * Math.PI;
    pos[n.id] = { x: width / 2 + Math.cos(angle) * 150, y: height / 2 + Math.sin(angle) * 150, vx: 0, vy: 0 };
  });
  for (let iter = 0; iter < 300; iter++) {
    for (let i = 0; i < nodes.length; i++) {
      for (let j = i + 1; j < nodes.length; j++) {
        const a = pos[nodes[i].id], b = pos[nodes[j].id];
        let dx = a.x - b.x, dy = a.y - b.y;
        let dist = Math.sqrt(dx * dx + dy * dy) || 0.1;
        const force = 1800 / (dist * dist);
        const fx = (dx / dist) * force, fy = (dy / dist) * force;
        a.vx += fx; a.vy += fy; b.vx -= fx; b.vy -= fy;
      }
    }
    links.forEach((l) => {
      const a = pos[l.sourceId], b = pos[l.targetId];
      if (!a || !b) return;
      let dx = b.x - a.x, dy = b.y - a.y;
      let dist = Math.sqrt(dx * dx + dy * dy) || 0.1;
      const force = (dist - 130) * 0.02;
      const fx = (dx / dist) * force, fy = (dy / dist) * force;
      a.vx += fx; a.vy += fy; b.vx -= fx; b.vy -= fy;
    });
    nodes.forEach((n) => {
      const p = pos[n.id];
      p.vx += (width / 2 - p.x) * 0.001;
      p.vy += (height / 2 - p.y) * 0.001;
      p.vx *= 0.85; p.vy *= 0.85;
      p.x += p.vx; p.y += p.vy;
      p.x = Math.max(40, Math.min(width - 40, p.x));
      p.y = Math.max(40, Math.min(height - 40, p.y));
    });
  }
  return pos;
}

function computeReachable(nodeId, links, direction) {
  // direction 'downstream' = things affected if nodeId fails (source depends on nodeId)
  // direction 'upstream' = things nodeId depends on
  const found = new Set();
  let frontier = [nodeId];
  while (frontier.length) {
    const next = [];
    frontier.forEach((cur) => {
      links.forEach((l) => {
        if (!DEPENDENCY_TYPES.has(l.relType)) return;
        if (direction === "downstream" && l.targetId === cur && !found.has(l.sourceId) && l.sourceId !== nodeId) {
          found.add(l.sourceId); next.push(l.sourceId);
        }
        if (direction === "upstream" && l.sourceId === cur && !found.has(l.targetId) && l.targetId !== nodeId) {
          found.add(l.targetId); next.push(l.targetId);
        }
      });
    });
    frontier = next;
  }
  return found;
}

export default function APMDashboardLive() {
  const [uri, setUri] = useState("");
  const [username, setUsername] = useState("neo4j");
  const [password, setPassword] = useState("");
  const [status, setStatus] = useState("idle");
  const [errorMsg, setErrorMsg] = useState("");
  const [apps, setApps] = useState([]);
  const [capCoverage, setCapCoverage] = useState([]);
  const [depNodes, setDepNodes] = useState([]);
  const [depLinks, setDepLinks] = useState([]);
  const [lastFetched, setLastFetched] = useState(null);
  const [hovered, setHovered] = useState(null);
  const [selectedNode, setSelectedNode] = useState(null);
  const [hoveredEdge, setHoveredEdge] = useState(null);
  const [view, setView] = useState("portfolio"); // portfolio | dependencies

  const [statusFilter, setStatusFilter] = useState(new Set());
  const [criticalityFilter, setCriticalityFilter] = useState(new Set());
  const [dispositionFilter, setDispositionFilter] = useState(new Set());
  const [search, setSearch] = useState("");

  const fetchData = useCallback(async (apiUrl, authHeader) => {
    setStatus("loading");
    setErrorMsg("");
    try {
      const appRows = await runCypher(apiUrl, authHeader,
        `MATCH (a:Instance:Application)
         OPTIONAL MATCH (r:Instance:Risk)-[:AFFECTS]->(a)
         RETURN properties(a) AS app, collect(DISTINCT r.name) AS risks
         ORDER BY app.name`
      );
      const capRows = await runCypher(apiUrl, authHeader,
        `MATCH (c:Instance:Capability)
         OPTIONAL MATCH (c)<-[:SUPPORTS]-(a:Instance:Application)
         RETURN c.name AS capability, count(a) AS count
         ORDER BY c.name`
      );
      const depRows = await runCypher(apiUrl, authHeader,
        `MATCH (a:Instance)-[r]->(b:Instance)
         WHERE (a:Application OR a:SoftwareTechnology OR a:HardwareTechnology OR a:Data)
           AND (b:Application OR b:SoftwareTechnology OR b:HardwareTechnology OR b:Data)
         RETURN a.id AS sourceId, a.name AS sourceName,
                [l IN labels(a) WHERE l <> 'Instance'][0] AS sourceType,
                type(r) AS relType,
                b.id AS targetId, b.name AS targetName,
                [l IN labels(b) WHERE l <> 'Instance'][0] AS targetType`
      );

      const normalised = appRows.map((row) => ({
        id: row.app.id, name: row.app.name, vendor: row.app.vendor || "—",
        status: row.app.status || "—", hosting: row.app.hosting_model || "—",
        businessValue: Number(row.app.business_value) || null,
        techHealth: Number(row.app.technical_health) || null,
        criticality: row.app.criticality || "—",
        tco: row.app.tco != null ? Number(row.app.tco) : null,
        risks: row.risks || [],
      }));

      const nodeMap = new Map();
      depRows.forEach((r) => {
        nodeMap.set(r.sourceId, { id: r.sourceId, name: r.sourceName, type: r.sourceType });
        nodeMap.set(r.targetId, { id: r.targetId, name: r.targetName, type: r.targetType });
      });

      setApps(normalised);
      setCapCoverage(capRows);
      setDepNodes([...nodeMap.values()]);
      setDepLinks(depRows.map((r) => ({ sourceId: r.sourceId, targetId: r.targetId, relType: r.relType })));
      setLastFetched(new Date());
      setStatus("connected");
    } catch (e) {
      setErrorMsg(e.message || String(e));
      setStatus("error");
    }
  }, []);

  const handleConnect = () => {
    if (!uri || !password) { setErrorMsg("Enter your Aura connection URI and password."); setStatus("error"); return; }
    fetchData(deriveQueryApiUrl(uri), "Basic " + btoa(`${username}:${password}`));
  };
  const handleRefresh = () => fetchData(deriveQueryApiUrl(uri), "Basic " + btoa(`${username}:${password}`));

  const appsWithDisposition = useMemo(
    () => apps.map((a) => ({ ...a, disposition: computeDisposition(a) })),
    [apps]
  );

  const allStatuses = useMemo(() => [...new Set(apps.map((a) => a.status))], [apps]);
  const allCriticalities = useMemo(() => [...new Set(apps.map((a) => a.criticality))], [apps]);
  const allDispositions = Object.keys(DISPOSITION_INFO);

  const filteredApps = useMemo(() => appsWithDisposition.filter((a) => {
    if (statusFilter.size && !statusFilter.has(a.status)) return false;
    if (criticalityFilter.size && !criticalityFilter.has(a.criticality)) return false;
    if (dispositionFilter.size && !dispositionFilter.has(a.disposition.code)) return false;
    if (search && !`${a.name} ${a.vendor}`.toLowerCase().includes(search.toLowerCase())) return false;
    return true;
  }), [appsWithDisposition, statusFilter, criticalityFilter, dispositionFilter, search]);

  const kpis = useMemo(() => ({
    total: filteredApps.length,
    production: filteredApps.filter((a) => a.status === "Production").length,
    atRisk: filteredApps.filter((a) => a.risks && a.risks.length > 0).length,
    totalTco: filteredApps.reduce((sum, a) => sum + (a.tco || 0), 0),
  }), [filteredApps]);

  const dispositionCounts = useMemo(() => {
    const counts = Object.fromEntries(allDispositions.map((d) => [d, 0]));
    appsWithDisposition.forEach((a) => { counts[a.disposition.code] = (counts[a.disposition.code] || 0) + 1; });
    return counts;
  }, [appsWithDisposition]);

  const toggleSetFilter = (setter, current, value) => {
    const next = new Set(current);
    next.has(value) ? next.delete(value) : next.add(value);
    setter(next);
  };

  // --- Dependency graph derived data ---
  const spofIds = useMemo(() => {
    const inDegree = {};
    depLinks.forEach((l) => {
      if (DEPENDENCY_TYPES.has(l.relType)) inDegree[l.targetId] = (inDegree[l.targetId] || 0) + 1;
    });
    return new Set(Object.entries(inDegree).filter(([, n]) => n >= 2).map(([id]) => id));
  }, [depLinks]);

  const graphW = 700, graphH = 460;
  const positions = useMemo(
    () => (depNodes.length ? layoutGraph(depNodes, depLinks, graphW, graphH) : {}),
    [depNodes, depLinks]
  );

  const downstream = selectedNode ? computeReachable(selectedNode, depLinks, "downstream") : new Set();
  const upstream = selectedNode ? computeReachable(selectedNode, depLinks, "upstream") : new Set();
  const relatedSet = selectedNode ? new Set([selectedNode, ...downstream, ...upstream]) : null;

  // --- Portfolio quadrant geometry ---
  const W = 640, H = 380, pad = 48;
  const maxTco = Math.max(1, ...apps.map((a) => a.tco || 0));
  const xScale = (v) => pad + ((v - 1) / 2) * (W - pad * 2);
  const yScale = (v) => H - pad - ((v - 1) / 3) * (H - pad * 2);
  const rScale = (tco) => 10 + ((tco || 0) / maxTco) * 22;
  const quadrantColor = (a) => {
    const v = (a.businessValue || 0) >= 3, h = (a.techHealth || 0) >= 3;
    if (v && h) return COLORS.accent;
    if (!v && h) return COLORS.accentMuted;
    if (v && !h) return COLORS.risk;
    return COLORS.riskMuted;
  };

  // Several apps often share identical integer scores (e.g. business value 3,
  // health 4), which would otherwise stack bubbles exactly on top of each
  // other. Group by score and fan tied apps out around their true point.
  const quadrantPositions = useMemo(() => {
    const groups = {};
    filteredApps.forEach((a) => {
      if (!a.businessValue || !a.techHealth) return;
      const key = `${a.businessValue}-${a.techHealth}`;
      (groups[key] = groups[key] || []).push(a);
    });
    const result = {};
    Object.values(groups).forEach((group) => {
      const baseX = xScale(group[0].businessValue);
      const baseY = yScale(group[0].techHealth);
      const n = group.length;
      group.forEach((a, i) => {
        if (n === 1) {
          result[a.id] = { x: baseX, y: baseY };
        } else {
          const angle = (i / n) * 2 * Math.PI;
          const spread = 24 + n * 3;
          result[a.id] = {
            x: Math.max(pad + 10, Math.min(W - pad - 10, baseX + Math.cos(angle) * spread)),
            y: Math.max(pad + 10, Math.min(H - pad - 10, baseY + Math.sin(angle) * spread)),
          };
        }
      });
    });
    return result;
  }, [filteredApps]);

  const chipStyle = (active) => ({
    display: "inline-block", padding: "4px 10px", fontSize: 12.5,
    border: `1px solid ${active ? COLORS.ink : COLORS.border}`,
    background: active ? COLORS.ink : COLORS.card, color: active ? COLORS.card : COLORS.ink,
    borderRadius: 3, marginRight: 6, marginBottom: 6, cursor: "pointer",
  });

  return (
    <div style={{ background: COLORS.paper, color: COLORS.ink,
      fontFamily: "'IBM Plex Sans', ui-sans-serif, system-ui, -apple-system, sans-serif",
      minHeight: "100%", padding: "32px 40px" }}>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&display=swap');
        * { box-sizing: border-box; }
        table { border-collapse: collapse; width: 100%; }
        th, td { text-align: left; padding: 10px 14px; font-size: 13.5px; }
        tbody tr { border-top: 1px solid ${COLORS.border}; }
        tbody tr:hover { background: #FBFAF6; }
        input { font-family: inherit; }
      `}</style>

      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end",
        borderBottom: `2px solid ${COLORS.ink}`, paddingBottom: 16, marginBottom: 24 }}>
        <div>
          <div style={{ fontSize: 13, color: COLORS.inkSecondary, marginBottom: 4 }}>
            Digital, Data & Technology Directorate
          </div>
          <h1 style={{ fontSize: 26, fontWeight: 600, margin: 0, letterSpacing: "-0.01em" }}>
            Application portfolio — The Royal British Legion
          </h1>
        </div>
        <div style={{ fontSize: 12.5, color: COLORS.inkSecondary, textAlign: "right" }}>
          {status === "connected" && lastFetched
            ? `Live from Neo4j · updated ${lastFetched.toLocaleTimeString()}`
            : "Not connected"}
        </div>
      </div>

      {status !== "connected" && (
        <div style={{ background: COLORS.card, border: `1px solid ${COLORS.border}`, borderRadius: 4,
          padding: 20, marginBottom: 28, maxWidth: 520 }}>
          <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 4 }}>Connect to your Aura instance</div>
          <div style={{ fontSize: 12.5, color: COLORS.inkSecondary, marginBottom: 14, lineHeight: 1.5 }}>
            Paste the same connection URI, username, and password you used in load_schema.py. Nothing is stored —
            these live only in this page while it's open.
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <input placeholder="neo4j+s://xxxxxxxx.databases.neo4j.io" value={uri} onChange={(e) => setUri(e.target.value)}
              style={{ padding: "8px 10px", border: `1px solid ${COLORS.border}`, borderRadius: 3, fontSize: 13.5 }} />
            <div style={{ display: "flex", gap: 10 }}>
              <input placeholder="username" value={username} onChange={(e) => setUsername(e.target.value)}
                style={{ flex: 1, padding: "8px 10px", border: `1px solid ${COLORS.border}`, borderRadius: 3, fontSize: 13.5 }} />
              <input placeholder="password" type="password" value={password} onChange={(e) => setPassword(e.target.value)}
                style={{ flex: 1, padding: "8px 10px", border: `1px solid ${COLORS.border}`, borderRadius: 3, fontSize: 13.5 }} />
            </div>
            <button onClick={handleConnect} disabled={status === "loading"}
              style={{ padding: "9px 16px", background: COLORS.ink, color: COLORS.card, border: "none",
                borderRadius: 3, fontSize: 13.5, fontWeight: 500, cursor: "pointer", width: "fit-content" }}>
              {status === "loading" ? "Connecting…" : "Connect and load"}
            </button>
            {status === "error" && (
              <div style={{ fontSize: 12.5, color: COLORS.risk, marginTop: 4, lineHeight: 1.5 }}>{errorMsg}</div>
            )}
          </div>
        </div>
      )}

      {status === "connected" && (
        <>
          {/* View toggle */}
          <div style={{ display: "flex", gap: 8, marginBottom: 18 }}>
            {[["portfolio", "Portfolio overview"], ["dependencies", "Dependencies & impact"]].map(([key, label]) => (
              <button key={key} onClick={() => { setView(key); setSelectedNode(null); }}
                style={{ padding: "8px 16px", fontSize: 13.5, fontWeight: 500, cursor: "pointer", borderRadius: 3,
                  border: `1px solid ${COLORS.ink}`,
                  background: view === key ? COLORS.ink : COLORS.card,
                  color: view === key ? COLORS.card : COLORS.ink }}>
                {label}
              </button>
            ))}
          </div>

          {view === "portfolio" && (
            <>
              <div style={{ marginBottom: 20 }}>
                <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 4, marginBottom: 8 }}>
                  <span style={{ fontSize: 12.5, color: COLORS.inkSecondary, marginRight: 8 }}>Status:</span>
                  {allStatuses.map((s) => (
                    <span key={s} style={chipStyle(statusFilter.has(s))}
                      onClick={() => toggleSetFilter(setStatusFilter, statusFilter, s)}>{s}</span>
                  ))}
                  <span style={{ fontSize: 12.5, color: COLORS.inkSecondary, margin: "0 8px" }}>Criticality:</span>
                  {allCriticalities.map((c) => (
                    <span key={c} style={chipStyle(criticalityFilter.has(c))}
                      onClick={() => toggleSetFilter(setCriticalityFilter, criticalityFilter, c)}>{c}</span>
                  ))}
                </div>
                <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 4, marginBottom: 8 }}>
                  <span style={{ fontSize: 12.5, color: COLORS.inkSecondary, marginRight: 8 }}>Disposition:</span>
                  {allDispositions.map((d) => (
                    <span key={d} style={chipStyle(dispositionFilter.has(d))}
                      onClick={() => toggleSetFilter(setDispositionFilter, dispositionFilter, d)}>{d}</span>
                  ))}
                </div>
                <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
                  <input placeholder="Search name or vendor…" value={search} onChange={(e) => setSearch(e.target.value)}
                    style={{ padding: "7px 10px", border: `1px solid ${COLORS.border}`, borderRadius: 3, fontSize: 13, width: 240 }} />
                  <button onClick={handleRefresh}
                    style={{ padding: "7px 14px", background: COLORS.card, color: COLORS.ink, border: `1px solid ${COLORS.border}`,
                      borderRadius: 3, fontSize: 13, cursor: "pointer" }}>Refresh from Neo4j</button>
                  {(statusFilter.size > 0 || criticalityFilter.size > 0 || dispositionFilter.size > 0 || search) && (
                    <button onClick={() => { setStatusFilter(new Set()); setCriticalityFilter(new Set()); setDispositionFilter(new Set()); setSearch(""); }}
                      style={{ padding: "7px 14px", background: "transparent", color: COLORS.inkSecondary, border: "none",
                        fontSize: 13, cursor: "pointer", textDecoration: "underline" }}>Clear filters</button>
                  )}
                </div>
              </div>

              <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 16, marginBottom: 28 }}>
                {[
                  { label: "Applications shown", value: kpis.total },
                  { label: "In production", value: kpis.production },
                  { label: "With an active risk", value: kpis.atRisk, tone: kpis.atRisk > 0 ? "risk" : null },
                  { label: "Estimated annual TCO", value: fmtGBP(kpis.totalTco) },
                ].map((kpi, i) => (
                  <div key={i} style={{ background: COLORS.card, border: `1px solid ${COLORS.border}`,
                    borderTop: `3px solid ${kpi.tone === "risk" ? COLORS.risk : COLORS.ink}`, padding: "16px 18px", borderRadius: 4 }}>
                    <div style={{ fontSize: 26, fontWeight: 600 }}>{kpi.value}</div>
                    <div style={{ fontSize: 13, color: COLORS.inkSecondary, marginTop: 4 }}>{kpi.label}</div>
                  </div>
                ))}
              </div>

              <div style={{ display: "grid", gridTemplateColumns: "1fr 280px", gap: 24, marginBottom: 28 }}>
                <div style={{ background: COLORS.card, border: `1px solid ${COLORS.border}`, borderRadius: 4, padding: 20 }}>
                  <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 2 }}>Business value vs. technical health</div>
                  <div style={{ fontSize: 13, color: COLORS.inkSecondary, marginBottom: 12 }}>
                    Bubble size reflects estimated annual TCO. Apps with identical scores are fanned out around
                    their true point for legibility — the fan-out itself carries no meaning.
                  </div>
                  <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H}>
                    <rect x={xScale(2)} y={pad} width={W - pad - xScale(2)} height={yScale(3) - pad} fill={COLORS.quadInvest} />
                    <rect x={pad} y={pad} width={xScale(2) - pad} height={yScale(3) - pad} fill={COLORS.quadTolerate} />
                    <rect x={xScale(2)} y={yScale(3)} width={W - pad - xScale(2)} height={H - pad - yScale(3)} fill={COLORS.quadMigrate} />
                    <rect x={pad} y={yScale(3)} width={xScale(2) - pad} height={H - pad - yScale(3)} fill={COLORS.quadEliminate} />
                    <text x={W - pad - 8} y={pad + 18} fontSize="12" fill={COLORS.ink} textAnchor="end" fontWeight="600">Invest</text>
                    <text x={pad + 8} y={pad + 18} fontSize="12" fill={COLORS.ink} textAnchor="start" fontWeight="600">Tolerate</text>
                    <text x={W - pad - 8} y={H - pad - 10} fontSize="12" fill={COLORS.ink} textAnchor="end" fontWeight="600">Migrate</text>
                    <text x={pad + 8} y={H - pad - 10} fontSize="12" fill={COLORS.ink} textAnchor="start" fontWeight="600">Eliminate</text>
                    <line x1={pad} y1={H - pad} x2={W - pad} y2={H - pad} stroke={COLORS.ink} strokeWidth="1" />
                    <line x1={pad} y1={pad} x2={pad} y2={H - pad} stroke={COLORS.ink} strokeWidth="1" />
                    <text x={W / 2} y={H - 12} fontSize="12" fill={COLORS.inkSecondary} textAnchor="middle">Business value →</text>
                    <text x={16} y={H / 2} fontSize="12" fill={COLORS.inkSecondary} textAnchor="middle" transform={`rotate(-90 16 ${H / 2})`}>Technical health →</text>
                    {filteredApps.filter((a) => a.businessValue && a.techHealth).map((a) => {
                      const pos = quadrantPositions[a.id];
                      if (!pos) return null;
                      const cx = pos.x, cy = pos.y, r = rScale(a.tco);
                      return (
                        <g key={a.id} onMouseEnter={() => setHovered(a.id)} onMouseLeave={() => setHovered(null)} style={{ cursor: "pointer" }}>
                          <circle cx={cx} cy={cy} r={r} fill={quadrantColor(a)} fillOpacity={hovered === a.id ? 0.95 : 0.75}
                            stroke={COLORS.ink} strokeWidth={hovered === a.id ? 1.5 : 0.5} />
                          <text x={cx} y={cy - r - 6} fontSize="11" fill={COLORS.ink} textAnchor="middle" fontWeight={hovered === a.id ? "600" : "400"}>
                            {a.name.length > 22 ? a.name.slice(0, 20) + "…" : a.name}
                          </text>
                        </g>
                      );
                    })}
                  </svg>
                </div>

                <div style={{ background: COLORS.card, border: `1px solid ${COLORS.border}`, borderRadius: 4, padding: 18 }}>
                  {hovered ? (() => {
                    const a = appsWithDisposition.find((x) => x.id === hovered);
                    if (!a) return null;
                    return (
                      <div>
                        <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 6 }}>{a.name}</div>
                        <div style={{ fontSize: 12.5, lineHeight: 1.9 }}>
                          <div><b>Vendor</b> — {a.vendor}</div>
                          <div><b>Status</b> — {a.status}</div>
                          <div><b>Business value</b> — {valueLabel[a.businessValue] || "—"}</div>
                          <div><b>Technical health</b> — {healthLabel[a.techHealth] || "—"}</div>
                          <div><b>Criticality</b> — {a.criticality}</div>
                          <div><b>Est. annual TCO</b> — {fmtGBP(a.tco)}</div>
                          <div style={{ marginTop: 8 }}>
                            <span style={{ background: DISPOSITION_INFO[a.disposition.code].color, color: "#fff",
                              padding: "2px 8px", borderRadius: 3, fontSize: 11.5, fontWeight: 600 }}>{a.disposition.code}</span>
                            <div style={{ marginTop: 4, color: COLORS.inkSecondary }}>{a.disposition.reason}</div>
                          </div>
                          {a.risks.length > 0 && (
                            <div style={{ marginTop: 8, color: COLORS.risk }}><b>Risk:</b> {a.risks.join(", ")}</div>
                          )}
                        </div>
                      </div>
                    );
                  })() : (
                    <div style={{ fontSize: 12.5, color: COLORS.inkSecondary, lineHeight: 1.6 }}>
                      Hover a bubble to see application detail, including its 6R disposition.
                    </div>
                  )}
                </div>
              </div>

              {/* 6R Disposition panel */}
              <div style={{ background: COLORS.card, border: `1px solid ${COLORS.border}`, borderRadius: 4, padding: 20, marginBottom: 28 }}>
                <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 2 }}>6R disposition</div>
                <div style={{ fontSize: 13, color: COLORS.inkSecondary, marginBottom: 14 }}>
                  A sharper lens than the quadrant alone — what to actually do about each application, based on
                  business value, technical health, and hosting model. Click a category to filter the inventory below.
                </div>
                {allDispositions.map((d) => (
                  <div key={d} style={{ display: "flex", alignItems: "center", marginBottom: 8, cursor: "pointer" }}
                    onClick={() => toggleSetFilter(setDispositionFilter, dispositionFilter, d)}>
                    <div style={{ width: 100, fontSize: 13, fontWeight: dispositionFilter.has(d) ? 700 : 400 }}>{d}</div>
                    <div style={{ flex: 1, background: "#EFEDE5", height: 18, borderRadius: 2, overflow: "hidden", marginRight: 10 }}>
                      <div style={{ width: `${(dispositionCounts[d] / Math.max(1, apps.length)) * 100}%`,
                        background: DISPOSITION_INFO[d].color, height: "100%" }} />
                    </div>
                    <div style={{ width: 200, fontSize: 12, color: COLORS.inkSecondary }}>{DISPOSITION_INFO[d].desc}</div>
                    <div style={{ width: 30, textAlign: "right", fontSize: 13 }}>{dispositionCounts[d]}</div>
                  </div>
                ))}
              </div>

              <div style={{ background: COLORS.card, border: `1px solid ${COLORS.border}`, borderRadius: 4, padding: 20, marginBottom: 28 }}>
                <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 2 }}>Capability coverage</div>
                <div style={{ fontSize: 13, color: COLORS.inkSecondary, marginBottom: 14 }}>
                  Live count of applications with a SUPPORTS relationship into each capability.
                </div>
                {capCoverage.map((c) => (
                  <div key={c.capability} style={{ display: "flex", alignItems: "center", marginBottom: 8 }}>
                    <div style={{ width: 260, fontSize: 13 }}>{c.capability}</div>
                    <div style={{ flex: 1, background: "#EFEDE5", height: 18, borderRadius: 2, overflow: "hidden" }}>
                      <div style={{ width: `${Math.min(100, (c.count / Math.max(1, apps.length)) * 100)}%`,
                        background: c.count === 0 ? COLORS.riskMuted : COLORS.accent, height: "100%" }} />
                    </div>
                    <div style={{ width: 90, textAlign: "right", fontSize: 13, color: COLORS.inkSecondary }}>
                      {c.count} application{c.count === 1 ? "" : "s"}
                    </div>
                  </div>
                ))}
              </div>

              <div style={{ background: COLORS.card, border: `1px solid ${COLORS.border}`, borderRadius: 4, overflow: "hidden" }}>
                <div style={{ padding: "16px 18px 4px", fontSize: 15, fontWeight: 600 }}>
                  Inventory ({filteredApps.length} of {apps.length})
                </div>
                <table>
                  <thead>
                    <tr style={{ borderTop: `1px solid ${COLORS.border}` }}>
                      <th>Application</th><th>Vendor</th><th>Status</th><th>Hosting</th>
                      <th>Criticality</th><th>Disposition</th><th>Est. annual TCO</th><th>Risk</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredApps.map((a) => (
                      <tr key={a.id}>
                        <td style={{ fontWeight: 500 }}>{a.name}</td>
                        <td>{a.vendor}</td>
                        <td>{a.status}</td>
                        <td>{a.hosting}</td>
                        <td>{a.criticality}</td>
                        <td>
                          <span style={{ background: DISPOSITION_INFO[a.disposition.code].color, color: "#fff",
                            padding: "2px 8px", borderRadius: 3, fontSize: 11 }}>{a.disposition.code}</span>
                        </td>
                        <td>{fmtGBP(a.tco)}</td>
                        <td>
                          {a.risks.length > 0
                            ? <span style={{ color: COLORS.risk, fontSize: 11.5, fontWeight: 600 }}>{a.risks.length} flagged</span>
                            : "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}

          {view === "dependencies" && (
            <div style={{ display: "grid", gridTemplateColumns: "1fr 300px", gap: 24 }}>
              <div style={{ background: COLORS.card, border: `1px solid ${COLORS.border}`, borderRadius: 4, padding: 20 }}>
                <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 2 }}>Technical dependency graph</div>
                <div style={{ fontSize: 13, color: COLORS.inkSecondary, marginBottom: 12 }}>
                  Applications, platforms, and data, connected by runs-on / depends-on / integrates-with / stores
                  relationships. Nodes with a red ring are shared dependencies. Hover an edge to see what it means,
                  click a node to see its blast radius.
                </div>
                <svg viewBox={`0 0 ${graphW} ${graphH}`} width="100%" height={graphH}>
                  {depLinks.map((l, i) => {
                    const a = positions[l.sourceId], b = positions[l.targetId];
                    if (!a || !b) return null;
                    const dim = relatedSet && !(relatedSet.has(l.sourceId) && relatedSet.has(l.targetId));
                    const style = edgeStyle(l.relType);
                    const isHovered = hoveredEdge === i;
                    // trim the line to stop at each node's edge, not its center,
                    // so the arrowhead lands outside the circle instead of under it
                    const NODE_R = 14;
                    const dx = b.x - a.x, dy = b.y - a.y;
                    const dist = Math.sqrt(dx * dx + dy * dy) || 1;
                    const ux = dx / dist, uy = dy / dist;
                    const x1 = a.x + ux * NODE_R, y1 = a.y + uy * NODE_R;
                    const x2 = b.x - ux * NODE_R, y2 = b.y - uy * NODE_R;
                    const midX = (x1 + x2) / 2, midY = (y1 + y2) / 2;
                    return (
                      <g key={i}>
                        <line x1={x1} y1={y1} x2={x2} y2={y2} stroke="transparent" strokeWidth={14}
                          pointerEvents="all"
                          onMouseEnter={() => setHoveredEdge(i)} onMouseLeave={() => setHoveredEdge(null)}
                          style={{ cursor: "pointer" }} />
                        <line x1={x1} y1={y1} x2={x2} y2={y2}
                          pointerEvents="none"
                          stroke={dim ? "#DDD9CE" : style.color} strokeWidth={dim ? 1 : (isHovered ? 2.5 : 1.5)}
                          strokeDasharray={style.dash || undefined}
                          opacity={dim ? 0.3 : 0.85} markerEnd="url(#arrow)" />
                        {isHovered && !dim && (
                          <g>
                            <rect x={midX - 62} y={midY - 11} width="124" height="20" fill="#fff"
                              stroke={COLORS.border} rx="3" />
                            <text x={midX} y={midY + 4} fontSize="11" fill={COLORS.ink} textAnchor="middle" fontWeight="500">
                              {style.label}
                            </text>
                          </g>
                        )}
                      </g>
                    );
                  })}
                  <defs>
                    <marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto">
                      <path d="M0,0 L0,6 L7,3 z" fill={COLORS.inkSecondary} />
                    </marker>
                  </defs>
                  {depNodes.map((n) => {
                    const p = positions[n.id];
                    if (!p) return null;
                    const isSpof = spofIds.has(n.id);
                    const dim = relatedSet && !relatedSet.has(n.id);
                    const isSelected = selectedNode === n.id;
                    return (
                      <g key={n.id} onClick={() => setSelectedNode(isSelected ? null : n.id)} style={{ cursor: "pointer" }}
                        opacity={dim ? 0.25 : 1}>
                        <circle cx={p.x} cy={p.y} r={isSelected ? 16 : 12} fill={NODE_TYPE_COLOR[n.type] || COLORS.inkSecondary}
                          stroke={isSpof ? COLORS.risk : "#fff"} strokeWidth={isSpof ? 3 : 1.5} />
                        <text x={p.x} y={p.y - 18} fontSize="10.5" fill={COLORS.ink} textAnchor="middle" fontWeight={isSelected ? "600" : "400"}>
                          {n.name.length > 20 ? n.name.slice(0, 18) + "…" : n.name}
                        </text>
                      </g>
                    );
                  })}
                </svg>
                <div style={{ display: "flex", gap: 16, marginTop: 8, fontSize: 11.5, color: COLORS.inkSecondary }}>
                  {Object.entries(NODE_TYPE_COLOR).map(([type, color]) => (
                    <div key={type} style={{ display: "flex", alignItems: "center", gap: 4 }}>
                      <span style={{ width: 9, height: 9, borderRadius: "50%", background: color, display: "inline-block" }} />
                      {type}
                    </div>
                  ))}
                </div>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 14, marginTop: 8, fontSize: 11.5, color: COLORS.inkSecondary }}>
                  {[...new Set(depLinks.map((l) => l.relType))].map((rt) => {
                    const style = edgeStyle(rt);
                    return (
                      <div key={rt} style={{ display: "flex", alignItems: "center", gap: 5 }}>
                        <svg width="28" height="8">
                          <line x1="0" y1="4" x2="28" y2="4" stroke={style.color} strokeWidth="2.5"
                            strokeDasharray={style.dash || undefined} />
                        </svg>
                        {style.label}
                      </div>
                    );
                  })}
                </div>
              </div>

              <div style={{ background: COLORS.card, border: `1px solid ${COLORS.border}`, borderRadius: 4, padding: 18 }}>
                {selectedNode ? (() => {
                  const n = depNodes.find((x) => x.id === selectedNode);
                  if (!n) return null;
                  return (
                    <div>
                      <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 4 }}>{n.name}</div>
                      <div style={{ fontSize: 11.5, color: COLORS.inkSecondary, marginBottom: 10 }}>{n.type}</div>
                      {spofIds.has(n.id) && (
                        <div style={{ background: "#F2E2DE", color: COLORS.risk, padding: "6px 10px", borderRadius: 3,
                          fontSize: 12, fontWeight: 600, marginBottom: 12 }}>
                          Shared dependency — {[...depLinks.filter(l => l.targetId === n.id && DEPENDENCY_TYPES.has(l.relType))].length} systems rely on this
                        </div>
                      )}
                      <div style={{ fontSize: 13, fontWeight: 600, color: COLORS.risk, marginBottom: 4 }}>
                        If this fails: {downstream.size} system{downstream.size === 1 ? "" : "s"} affected
                      </div>
                      {[...downstream].map((id) => {
                        const dn = depNodes.find((x) => x.id === id);
                        return dn ? <div key={id} style={{ fontSize: 12.5, marginLeft: 8, marginBottom: 2 }}>• {dn.name}</div> : null;
                      })}
                      <div style={{ fontSize: 13, fontWeight: 600, marginTop: 12, marginBottom: 4 }}>
                        Depends on: {upstream.size} system{upstream.size === 1 ? "" : "s"}
                      </div>
                      {[...upstream].map((id) => {
                        const dn = depNodes.find((x) => x.id === id);
                        return dn ? <div key={id} style={{ fontSize: 12.5, marginLeft: 8, marginBottom: 2 }}>• {dn.name}</div> : null;
                      })}
                    </div>
                  );
                })() : (
                  <div>
                    <div style={{ fontSize: 13, color: COLORS.inkSecondary, lineHeight: 1.6, marginBottom: 14 }}>
                      Click a node to see its blast radius — everything that would be affected if it failed.
                    </div>
                    {spofIds.size > 0 && (
                      <>
                        <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8 }}>Shared dependencies detected</div>
                        {[...spofIds].map((id) => {
                          const n = depNodes.find((x) => x.id === id);
                          return n ? (
                            <div key={id} style={{ fontSize: 12.5, marginBottom: 6, cursor: "pointer", color: COLORS.risk }}
                              onClick={() => setSelectedNode(id)}>
                              • {n.name}
                            </div>
                          ) : null;
                        })}
                      </>
                    )}
                  </div>
                )}
              </div>
            </div>
          )}
        </>
      )}

      <div style={{ fontSize: 11.5, color: COLORS.inkSecondary, marginTop: 20, lineHeight: 1.6 }}>
        Connects directly to Neo4j Aura's Query API over HTTPS. Credentials are held only in this page's memory.
        6R disposition is calculated from business value, technical health, and hosting model using simple rules
        shown in each application's detail — a real assessment would involve architect judgement, this is a starting point.
      </div>
    </div>
  );
}
