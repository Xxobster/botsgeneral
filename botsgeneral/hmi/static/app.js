const $ = (id) => document.getElementById(id);

function fmtNum(x, d = 2) {
  if (x === "inf") return "∞";
  if (x === "-inf") return "−∞";
  if (x == null || x === "" || Number.isNaN(Number(x))) return "—";
  const n = Number(x);
  return n.toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d });
}
function fmtPct01(x) {
  if (x == null || Number.isNaN(Number(x))) return "—";
  return (100 * Number(x)).toFixed(1) + "%";
}
function signedClass(x) {
  const n = Number(x);
  if (!Number.isFinite(n) || n === 0) return "";
  return n > 0 ? "up" : "dn";
}
function gateClass(x, gate = 1) {
  if (x === "inf") return "up";
  if (x === "-inf") return "dn";
  const n = Number(x);
  if (!Number.isFinite(n)) return "";
  return n > gate ? "up" : "dn";
}
function fmtPctVal(x, d = 2) {
  if (x == null || x === "" || Number.isNaN(Number(x))) return "—";
  return Number(x).toFixed(d) + "%";
}
// Bybit closed-pnl "side" is the CLOSING order side (a long is closed by a Sell).
// Show the position direction instead: closing Sell => Long, closing Buy => Short.
function tradeDir(closeSide) {
  const s = String(closeSide || "").toLowerCase();
  if (s === "sell") return "Long";
  if (s === "buy") return "Short";
  return closeSide || "—";
}

// Open position "side" is the position side itself (Buy = long).
function posDir(side) {
  const s = String(side || "").toLowerCase();
  if (s === "buy") return "Long";
  if (s === "sell") return "Short";
  return side || "—";
}

function riskPctOf(row) {
  if (row.display_risk_pct != null) return row.display_risk_pct;
  if (row.actual_risk_pct != null) return row.actual_risk_pct;
  return row.risk_pct;
}
function when(ms) {
  if (!ms) return "—";
  const d = new Date(Number(ms));
  return d.toISOString().replace("T", " ").slice(0, 16) + " UTC";
}
function barClass(pct) {
  if (pct == null) return "";
  if (pct >= 90) return "bad";
  if (pct >= 80) return "warn";
  return "";
}

let FLEET = null;
let selected = null;

function renderHosts(hosts) {
  const el = $("hosts");
  const hidden = new Set(["sm", "ln3"]);
  const hiddenIp = new Set(["212.73.150.149", "185.203.119.52"]);
  const shown = (hosts || []).filter((h) => {
    const alias = String(h.alias || h.agent_id || "").toLowerCase();
    const vps = String(h.vps || "");
    return !hidden.has(alias) && !hiddenIp.has(vps);
  });
  // Remember which bots are down (per host sitrep) so account cards can flag them.
  window.__botsDown = new Set();
  window.__botsSeen = new Set();
  (hosts || []).forEach((h) => (((h.sitrep || {}).bots) || []).forEach((b) => {
    window.__botsSeen.add(String(b.bot));
    if (!b.running) window.__botsDown.add(String(b.bot));
  }));
  el.innerHTML = shown.map((h) => {
    const cpu = (h.cpu || {}).cpu_pct;
    const mem = (h.memory || {}).used_pct;
    const disk = (h.disk || {}).used_pct;
    const load = h.load || {};
    const bots = ((h.sitrep || {}).bots || []);
    const up = bots.filter((b) => b.running).length;
    const down = bots.length - up;
    const botsLine = bots.length
      ? bots.map((b) => `<span class="${b.running ? "up" : "dn"}">${b.label || b.bot}</span>`).join(" · ")
      : (h.ok ? "no trading units on this host" : (h.error || "unreachable"));
    return `<article class="host ${h.ok ? "" : "down"}">
      <h3><span>${h.alias || h.vps || "host"}</span><span class="${h.ok ? "up" : "dn"}">${h.ok ? "UP" : "DOWN"}</span></h3>
      <div class="kv"><span>Central Processing Unit (CPU)</span><span>${fmtNum(cpu, 1)}%</span></div>
      <div class="bar ${barClass(cpu)}"><i style="width:${Math.max(0, Math.min(100, cpu || 0))}%"></i></div>
      <div class="kv"><span>Memory</span><span>${fmtNum(mem, 1)}%</span></div>
      <div class="bar ${barClass(mem)}"><i style="width:${Math.max(0, Math.min(100, mem || 0))}%"></i></div>
      <div class="kv"><span>Disk</span><span>${fmtNum(disk, 1)}% · ${fmtNum((h.disk || {}).free_gb, 1)} GB free</span></div>
      <div class="bar ${barClass(disk)}"><i style="width:${Math.max(0, Math.min(100, disk || 0))}%"></i></div>
      <div class="kv"><span>Load 1/5/15</span><span>${fmtNum(load.load1, 2)} / ${fmtNum(load.load5, 2)} / ${fmtNum(load.load15, 2)}</span></div>
      <div class="kv"><span>Uptime</span><span>${fmtNum((h.uptime || {}).uptime_days, 1)} days</span></div>
      <div class="bots-mini">${up} up / ${down} down · ${botsLine}</div>
    </article>`;
  }).join("");
}

function renderTotals(t) {
  $("totals").hidden = false;
  $("t-accounts").textContent = t.n_accounts;
  if ($("t-open")) $("t-open").textContent = t.n_open_positions ?? 0;
  $("t-trades").textContent = t.n_trades;
  $("t-real").textContent = fmtNum(t.realized_pnl, 2);
  $("t-real").className = signedClass(t.realized_pnl);
  $("t-upl").textContent = fmtNum(t.open_upl, 2);
  $("t-upl").className = signedClass(t.open_upl);
  $("t-comb").textContent = fmtNum(t.combined, 2);
  $("t-comb").className = signedClass(t.combined);
  $("t-eq").textContent = fmtNum(t.equity, 2);
}

function metricLine(m) {
  m = m || {};
  return `n=${m.n_trades ?? 0} · PnL ${fmtNum(m.realized_pnl, 2)} · WR ${fmtPct01(m.winrate)} · PF ${fmtNum(m.profit_factor, 2)} · RF ${fmtNum(m.recovery_factor, 2)}`;
}

function cardHtml(a) {
  const m = a.closed_all || {};
  const aliases = (a.alias_list || [a.vps_alias]).filter(Boolean).join(", ");
  const bots = (a.bots || a.bot_ids || []).join(", ") || "—";
  const coins = (a.live_symbols || []).join(" ") || "—";
  const nOpen = a.n_open_positions ?? (a.positions || []).filter((p) => Number(p.size || p.qty || 0) > 0).length;
  const botIds = (a.bot_ids || a.bots || []).map(String);
  const downBots = botIds.filter((b) => (window.__botsDown || new Set()).has(b));
  const downCls = downBots.length ? " bot-down" : "";
  const downTag = downBots.length ? `<span class="dn"> · ${downBots.length} bot${downBots.length > 1 ? "s" : ""} NOT RUNNING: ${downBots.join(", ")}</span>` : "";
  return `<button type="button" class="card${downCls}" data-acct="${a.account}">
    <div class="name">${a.account}${downTag}</div>
    <div class="meta">${aliases} · ${bots}<br/>pairs ${coins} · since ${a.since || "—"} · ${fmtNum(a.days_active, 1)} days active</div>
    <div class="metrics">
      <div><span>Equity</span><br/><b>${fmtNum(a.total_equity, 2)}</b></div>
      <div><span>Open positions</span><br/><b>${nOpen}</b></div>
      <div><span>Closed round-trips</span><br/><b>${m.n_trades ?? 0}</b></div>
      <div><span>Open unrealized</span><br/><b class="${signedClass(a.total_perp_upl)}">${fmtNum(a.total_perp_upl, 2)}</b></div>
      <div><span>Realized Profit and Loss (PnL)</span><br/><b class="${signedClass(m.realized_pnl)}">${fmtNum(m.realized_pnl, 2)}</b></div>
      <div><span>Win rate (WR)</span><br/><b>${fmtPct01(m.winrate)}</b></div>
      <div><span>Profit factor (PF)</span><br/><b class="${gateClass(m.profit_factor, 1)}">${fmtNum(m.profit_factor, 2)}</b></div>
      <div><span>Recovery factor (RF)</span><br/><b class="${gateClass(m.recovery_factor, 1)}">${fmtNum(m.recovery_factor, 2)}</b></div>
    </div>
  </button>`;
}

function renderCards() {
  const q = ($("filter-acct").value || "").trim().toLowerCase();
  const rows = (FLEET.accounts || []).filter((a) => {
    if (!q) return true;
    const blob = [a.account, ...(a.bots || []), ...(a.bot_ids || []), ...(a.live_symbols || [])].join(" ").toLowerCase();
    return blob.includes(q);
  });
  $("cards").innerHTML = rows.map(cardHtml).join("") || "<p class='err'>No accounts match.</p>";
  $("cards").querySelectorAll(".card").forEach((btn) => {
    btn.addEventListener("click", () => openDetail(btn.dataset.acct));
  });
}

function fmtMoneyAxis(v) {
  const n = Number(v);
  if (!Number.isFinite(n)) return "—";
  const abs = Math.abs(n);
  const sign = n < 0 ? "−" : "";
  if (abs >= 1e6) return sign + (abs / 1e6).toFixed(1) + "M";
  if (abs >= 1e3) return sign + (abs / 1e3).toFixed(abs >= 1e4 ? 0 : 1) + "k";
  return sign + abs.toFixed(abs >= 100 ? 0 : 2);
}

function fmtDateAxis(ms) {
  const d = new Date(Number(ms));
  if (Number.isNaN(d.getTime())) return "";
  const y = d.getUTCFullYear();
  const m = String(d.getUTCMonth() + 1).padStart(2, "0");
  const day = String(d.getUTCDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function niceTicks(minV, maxV, count) {
  if (!(maxV > minV)) return [minV];
  const span = maxV - minV;
  const step0 = span / Math.max(1, count - 1);
  const pow = Math.pow(10, Math.floor(Math.log10(step0)));
  const candidates = [1, 2, 2.5, 5, 10].map((m) => m * pow);
  let step = candidates[0];
  for (const c of candidates) {
    if (span / c <= count) { step = c; break; }
    step = c;
  }
  const start = Math.floor(minV / step) * step;
  const out = [];
  for (let v = start; v <= maxV + step * 0.5; v += step) {
    if (v >= minV - step * 1e-9 && v <= maxV + step * 1e-9) out.push(v);
  }
  return out.length ? out : [minV, maxV];
}

function drawCurve(canvas, points) {
  const dpr = devicePixelRatio || 1;
  const ctx = canvas.getContext("2d");
  const w = canvas.width = canvas.clientWidth * dpr;
  const h = canvas.height = 260 * dpr;
  ctx.clearRect(0, 0, w, h);
  if (!points || points.length < 1) {
    ctx.fillStyle = "#8b95a3";
    ctx.font = `${12 * dpr}px sans-serif`;
    ctx.fillText("No closed trades yet", 16 * dpr, h / 2);
    return;
  }
  const xs = points.map((p) => p.t);
  const ys = points.map((p) => p.cum);
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  let minY = Math.min(0, ...ys);
  let maxY = Math.max(0, ...ys);
  if (minY === maxY) {
    minY -= 1;
    maxY += 1;
  }
  const padL = 64 * dpr;
  const padR = 16 * dpr;
  const padT = 16 * dpr;
  const padB = 36 * dpr;
  const dx = Math.max(1, maxX - minX);
  const dy = Math.max(1e-9, maxY - minY);
  const X = (t) => padL + ((t - minX) / dx) * (w - padL - padR);
  const Y = (v) => padT + (1 - (v - minY) / dy) * (h - padT - padB);

  ctx.strokeStyle = "#2a3340";
  ctx.lineWidth = 1 * dpr;
  ctx.fillStyle = "#8b95a3";
  ctx.font = `${11 * dpr}px sans-serif`;
  ctx.textAlign = "right";
  ctx.textBaseline = "middle";
  const yTicks = niceTicks(minY, maxY, 5);
  yTicks.forEach((v) => {
    const y = Y(v);
    ctx.beginPath();
    ctx.moveTo(padL, y);
    ctx.lineTo(w - padR, y);
    ctx.stroke();
    ctx.fillText(fmtMoneyAxis(v), padL - 6 * dpr, y);
  });

  ctx.strokeStyle = "#3a4556";
  ctx.beginPath();
  ctx.moveTo(padL, Y(0));
  ctx.lineTo(w - padR, Y(0));
  ctx.stroke();

  const nX = Math.min(5, points.length);
  ctx.textAlign = "center";
  ctx.textBaseline = "top";
  for (let i = 0; i < nX; i++) {
    const idx = nX === 1 ? 0 : Math.round((i * (points.length - 1)) / (nX - 1));
    const t = points[idx].t;
    const x = X(t);
    ctx.beginPath();
    ctx.moveTo(x, padT);
    ctx.lineTo(x, h - padB);
    ctx.strokeStyle = "#2a3340";
    ctx.stroke();
    ctx.fillStyle = "#8b95a3";
    ctx.fillText(fmtDateAxis(t), x, h - padB + 6 * dpr);
  }

  const last = ys[ys.length - 1];
  ctx.strokeStyle = last >= 0 ? "#3dd68c" : "#f0616d";
  ctx.lineWidth = 2 * dpr;
  ctx.beginPath();
  points.forEach((p, i) => {
    const x = X(p.t);
    const y = Y(p.cum);
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();
}

function accountBots(a) {
  const bots = (a.bots || a.bot_ids || []).filter(Boolean);
  return bots.length ? bots.join(", ") : "—";
}

function renderWinners() {
  const body = $("pair-winners");
  if (!body) return;
  const rows = FLEET.pair_winners || [];
  if (!rows.length) {
    body.innerHTML = `<tr><td class="l empty" colspan="15">No closed pair stats yet.</td></tr>`;
    return;
  }
  body.innerHTML = rows.map((r) => `
    <tr>
      <td class="l">${r.vps_alias || r.vps || "—"}</td>
      <td class="l">${r.bot || "—"}</td>
      <td class="l">${r.pair || "—"}</td>
      <td class="l">${r.account || "—"}</td>
      <td>${r.n_trades ?? 0}</td>
      <td>${fmtNum(r.days_active, 1)}</td>
      <td>${fmtNum(r.trades_per_day, 2)}</td>
      <td class="${signedClass(r.realized_pnl)}">${fmtNum(r.realized_pnl, 2)}</td>
      <td>${fmtPct01(r.winrate)}</td>
      <td class="${gateClass(r.profit_factor, 1)}">${fmtNum(r.profit_factor, 2)}</td>
      <td class="${gateClass(r.recovery_factor, 1)}">${fmtNum(r.recovery_factor, 2)}</td>
      <td>${fmtNum(r.max_drawdown, 2)}</td>
      <td>${fmtNum(r.payoff, 2)}</td>
      <td class="${signedClass(r.avg_pnl)}">${fmtNum(r.avg_pnl, 2)}</td>
      <td>${fmtNum(r.total_equity, 2)}</td>
    </tr>`).join("");
}

function renderActiveTrades() {
  const rows = [];
  (FLEET.accounts || []).forEach((a) => {
    (a.positions || []).forEach((p) => {
      const size = Number(p.size);
      if (!Number.isFinite(size) || size === 0) return;
      rows.push({
        account: a.account,
        bot: p.bot_id || accountBots(a),
        symbol: p.symbol || "—",
        side: posDir(p.side),
        size: p.size,
        entry: p.avgPrice,
        mark: p.markPrice,
        upl: p.unrealisedPnl,
        lev: p.leverage,
        confidence_pct: p.confidence_pct,
        display_risk_pct: riskPctOf(p),
        nearer: p.closer_exit
          ? `${p.closer_exit} ${fmtNum(p.closer_pct, 2)}%`
          : "—",
      });
    });
  });
  rows.sort((x, y) => Math.abs(Number(y.upl) || 0) - Math.abs(Number(x.upl) || 0));
  const body = $("active-trades");
  if (!rows.length) {
    body.innerHTML = `<tr><td class="l empty" colspan="12">No active trades.</td></tr>`;
    return;
  }
  body.innerHTML = rows.map((r) => `
    <tr>
      <td class="l">${r.account}</td>
      <td class="l">${r.bot}</td>
      <td class="l">${r.symbol}</td>
      <td class="l">${r.side}</td>
      <td>${r.size}</td>
      <td>${r.entry}</td>
      <td>${r.mark}</td>
      <td class="${signedClass(r.upl)}">${fmtNum(r.upl, 4)}</td>
      <td>${fmtPctVal(r.confidence_pct)}</td>
      <td>${fmtPctVal(r.display_risk_pct)}</td>
      <td>${r.lev ?? "—"}</td>
      <td class="l">${r.nearer}</td>
    </tr>`).join("");
}

function renderRecentTrades() {
  const rows = [];
  (FLEET.accounts || []).forEach((a) => {
    (a.trades || []).forEach((t) => {
      rows.push({
        ms: Number(t.updated_ms) || 0,
        account: a.account,
        bot: t.bot_id || accountBots(a),
        symbol: t.symbol || "—",
        side: tradeDir(t.side),
        qty: t.qty,
        entry: t.entry,
        exit: t.exit,
        pnl: t.pnl,
        confidence_pct: t.confidence_pct,
        display_risk_pct: riskPctOf(t),
      });
    });
  });
  rows.sort((x, y) => y.ms - x.ms);
  const top = rows.slice(0, 10);
  const body = $("recent-trades");
  if (!top.length) {
    body.innerHTML = `<tr><td class="l empty" colspan="11">No closed trades yet.</td></tr>`;
    return;
  }
  body.innerHTML = top.map((t) => `
    <tr>
      <td class="l">${when(t.ms)}</td>
      <td class="l">${t.account}</td>
      <td class="l">${t.bot}</td>
      <td class="l">${t.symbol}</td>
      <td class="l">${t.side}</td>
      <td>${t.qty}</td>
      <td>${t.entry}</td>
      <td>${t.exit}</td>
      <td class="${signedClass(t.pnl)}">${fmtNum(t.pnl, 4)}</td>
      <td>${fmtPctVal(t.confidence_pct)}</td>
      <td>${fmtPctVal(t.display_risk_pct)}</td>
    </tr>`).join("");
}

function openDetail(name) {
  const a = (FLEET.accounts || []).find((x) => x.account === name);
  if (!a) return;
  selected = name;
  setDetailOpen(true);
  const m = a.closed_all || {};
  const strategies = (a.strategies || []).map((s) => `
    <div class="strat">
      <b>${s.title || s.bot}</b>
      <div class="meta">${s.family_title || ""} · ${s.timeframe || ""} · readiness ${s.readiness || ""}</div>
      <p>${s.summary || s.notes || ""}</p>
      ${(s.rules || []).length ? `<ul>${s.rules.map((r) => `<li>${r}</li>`).join("")}</ul>` : ""}
    </div>`).join("") || "<p class='meta'>No catalog entry for these units.</p>";
  const opens = (a.positions || []).map((p) => `
    <div class="open">
      OPEN ${p.symbol} ${posDir(p.side)} qty=${p.size} entry=${p.avgPrice} mark=${p.markPrice}
      upl=<span class="${signedClass(p.unrealisedPnl)}">${p.unrealisedPnl}</span> lev=${p.leverage}
      conf=${fmtPctVal(p.confidence_pct)} risk=${fmtPctVal(riskPctOf(p))}
      TP=${p.takeProfit || "—"} SL=${p.stopLoss || "—"}
      opened=${when(p.opened_at_ms)}
      ${p.closer_exit ? `to ${p.closer_exit} ${fmtNum(p.closer_pct, 2)}%` : ""}
    </div>`).join("") || "<p class='meta'>No open positions.</p>";
  const pairs = ["ALL", ...new Set([...(a.live_symbols || []), ...((a.trades || []).map((t) => t.symbol))])];
  $("detail-body").innerHTML = `
    <h2>${a.account}</h2>
    <p class="meta">${(a.alias_list || []).join(", ")} · bots ${(a.bots || []).join(", ")} ·
      started ${a.since} · ${fmtNum(a.days_active, 1)} days active ·
      equity ${fmtNum(a.total_equity, 2)} · wallet ${fmtNum(a.total_wallet_balance, 2)}</p>
    <p><b class="${signedClass(m.realized_pnl)}">${metricLine(m)}</b>
      · Max drawdown ${fmtNum(m.max_drawdown, 2)} (${fmtPct01(m.max_dd_pct)})
      · Payoff ${fmtNum(m.payoff, 2)}
      · PF <span class="${gateClass(m.profit_factor, 1)}">${fmtNum(m.profit_factor, 2)}</span>
      · RF <span class="${gateClass(m.recovery_factor, 1)}">${fmtNum(m.recovery_factor, 2)}</span></p>
    <h3>Strategy</h3>
    ${strategies}
    <h3>Profit and Loss (PnL) curve</h3>
    <div class="row-tools">
      <label>Pair <select id="pair-filter">${pairs.map((p) => `<option>${p}</option>`).join("")}</select></label>
    </div>
    <canvas class="chart" id="eq-chart"></canvas>
    <h3>Open positions</h3>
    ${opens}
    <h3>Closed trades</h3>
    <div class="table-wrap"><table>
      <thead><tr>
        <th class="l">Close (UTC)</th><th class="l">Pair</th><th class="l">Side</th>
        <th>Qty</th><th>Entry</th><th>Exit</th><th>PnL</th>
        <th>Conf %</th><th>Risk %</th>
        <th>Lev</th><th>Type</th><th>Fees</th>
      </tr></thead>
      <tbody id="trade-rows"></tbody>
    </table></div>
    <h3>Per pair</h3>
    <div class="table-wrap"><table>
      <thead><tr>
        <th class="l">Pair</th><th>n</th><th>PnL</th><th>WR</th><th>PF</th><th>RF</th><th>Since</th><th>Days</th>
      </tr></thead>
      <tbody>${(a.per_coin || []).map((c) => `
        <tr>
          <td class="l">${c.symbol}</td>
          <td>${c.n_trades}</td>
          <td class="${signedClass(c.realized_pnl)}">${fmtNum(c.realized_pnl, 2)}</td>
          <td>${fmtPct01(c.winrate)}</td>
          <td class="${gateClass(c.profit_factor, 1)}">${fmtNum(c.profit_factor, 2)}</td>
          <td class="${gateClass(c.recovery_factor, 1)}">${fmtNum(c.recovery_factor, 2)}</td>
          <td>${c.since || ""}</td>
          <td>${fmtNum(c.days_active, 1)}</td>
        </tr>`).join("")}</tbody>
    </table></div>
  `;
  const apply = () => {
    const pair = $("pair-filter").value;
    const trades = (a.trades || []).filter((t) => pair === "ALL" || t.symbol === pair);
    $("trade-rows").innerHTML = trades.map((t) => `
      <tr>
        <td class="l">${when(t.updated_ms)}</td>
        <td class="l">${t.symbol}</td>
        <td class="l">${tradeDir(t.side)}</td>
        <td>${t.qty}</td>
        <td>${t.entry}</td>
        <td>${t.exit}</td>
        <td class="${signedClass(t.pnl)}">${fmtNum(t.pnl, 4)}</td>
        <td>${fmtPctVal(t.confidence_pct)}</td>
        <td>${fmtPctVal(riskPctOf(t))}</td>
        <td>${t.leverage || "—"}</td>
        <td>${t.order_type || t.exec_type || "—"}</td>
        <td>${[t.open_fee, t.close_fee].filter(Boolean).join(" / ") || "—"}</td>
      </tr>`).join("") || `<tr><td class="l" colspan="12">No trades for this pair.</td></tr>`;
    let pts = (a.equity_curve || {}).points || [];
    if (pair !== "ALL") pts = ((a.equity_curve_by_symbol || {})[pair] || {}).points || [];
    drawCurve($("eq-chart"), pts);
  };
  $("pair-filter").addEventListener("change", apply);
  apply();
}

async function refresh() {
  $("status").textContent = "Refreshing every Virtual Private Server…";
  $("btn-refresh").disabled = true;
  try {
    const r = await fetch("api/fleet", { cache: "no-store" });
    if (!r.ok) throw new Error("HTTP " + r.status);
    FLEET = await r.json();
    renderHosts(FLEET.hosts || []);
    renderTotals(FLEET.totals || {});
    renderWinners();
    renderActiveTrades();
    renderRecentTrades();
    renderCards();
    const err = (FLEET.errors || []).filter((e) => e.error);
    $("status").textContent = `Updated ${when(FLEET.generated_ms)} · ${err.length ? err.map((e) => e.agent + ": " + e.error).join(" | ") : "all hosts answered"}`;
    if (selected && $("detail").classList.contains("is-open")) openDetail(selected);
  } catch (e) {
    $("status").textContent = "Refresh failed: " + e.message;
  } finally {
    $("btn-refresh").disabled = false;
  }
}

function setDetailOpen(open) {
  const el = $("detail");
  el.hidden = !open;
  el.classList.toggle("is-open", open);
  if (!open) selected = null;
}

$("btn-refresh").addEventListener("click", refresh);
$("btn-close").addEventListener("click", () => setDetailOpen(false));
$("detail").addEventListener("click", (ev) => {
  if (ev.target.id === "detail") setDetailOpen(false);
});
$("filter-acct").addEventListener("input", () => { if (FLEET) renderCards(); });
refresh();
