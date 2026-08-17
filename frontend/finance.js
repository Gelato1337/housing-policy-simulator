// Personal-finance comparator frontend.
// Talks to POST /api/finance. Deterministic, no randomness.

const PRESETS = {
  "10y vs 40y loan": [
    { name: "10-year loan", kind: "buy_now", home_price: 250000, down_payment: 50000, loan_years: 10, mortgage_rate: 0.035 },
    { name: "40-year loan", kind: "buy_now", home_price: 250000, down_payment: 50000, loan_years: 40, mortgage_rate: 0.035 },
  ],
  "Buy now vs wait 3y": [
    { name: "Buy now", kind: "buy_now", home_price: 250000, down_payment: 50000, loan_years: 25, mortgage_rate: 0.035 },
    { name: "Rent 3y then buy", kind: "rent_then_buy", home_price: 250000, down_payment: 50000, loan_years: 25, mortgage_rate: 0.035, wait_years: 3 },
  ],
  "Fixer vs move-in": [
    { name: "Fixer-upper", kind: "buy_now", home_price: 150000, down_payment: 30000, loan_years: 25, mortgage_rate: 0.035, reno_total: 60000, reno_years: 8 },
    { name: "Move-in ready", kind: "buy_now", home_price: 250000, down_payment: 50000, loan_years: 25, mortgage_rate: 0.035 },
  ],
  "Rent forever vs buy": [
    { name: "Buy", kind: "buy_now", home_price: 250000, down_payment: 50000, loan_years: 25, mortgage_rate: 0.035 },
    { name: "Rent forever + invest", kind: "rent_forever", home_price: 250000, down_payment: 50000, monthly_rent: 1000 },
  ],
  "Fixed vs variable (rate shock)": [
    { name: "Fixed 3.5%", kind: "buy_now", home_price: 250000, down_payment: 50000, loan_years: 25, rate_type: "fixed", mortgage_rate: 0.035 },
    { name: "Variable (Euribor+1%)", kind: "buy_now", home_price: 250000, down_payment: 50000, loan_years: 25, rate_type: "variable", margin: 0.01 },
  ],
  "Model: Finland vs Swiss vs rent": [
    { name: "Finnish amortizing 25y", kind: "buy_now", home_price: 250000, down_payment: 25000, loan_years: 25, rate_type: "variable", margin: 0.008 },
    { name: "Swiss interest-only", kind: "swiss_interest_only", home_price: 250000, down_payment: 50000, rate_type: "fixed", mortgage_rate: 0.02 },
    { name: "Rent forever + invest", kind: "rent_forever", home_price: 250000, down_payment: 50000, monthly_rent: 1000 },
  ],
  "Model: Tokyo vs Vienna logic": [
    // Tokyo: building depreciates, so model low appreciation + shorter amortization.
    { name: "Tokyo-style (depreciating)", kind: "buy_now", home_price: 200000, down_payment: 40000, loan_years: 20, rate_type: "fixed", mortgage_rate: 0.015 },
    // Vienna: most people rent cheap public-ish housing for life and invest.
    { name: "Vienna-style (lifetime rent)", kind: "rent_forever", home_price: 250000, down_payment: 50000, monthly_rent: 900 },
  ],
};

let scenarios = [];
let scenarioCounter = 0;
let charts = {};
const COLORS = ["#185FA5", "#993C1D", "#3B6D11", "#854F0B", "#534AB7", "#993556"];

function boot() {
  initAssumptionLabels();
  initPresetButtons();
  document.getElementById("run").addEventListener("click", run);
  document.getElementById("add-scenario").addEventListener("click", () => addScenario());
  document.getElementById("pull-abm").addEventListener("click", pullAbmPricePath);
  initForecastControls();
  initVarianceControls();
  // Load first preset by default
  loadPreset("10y vs 40y loan");
  setTimeout(run, 150);
}

function initVarianceControls() {
  const on = document.getElementById("var-on");
  const box = document.getElementById("var-controls");
  on.addEventListener("change", () => {
    box.style.display = on.checked ? "block" : "none";
  });
  const fmts = {
    "v-ratedelta": ["v-vrate", v => "±" + (v / 10).toFixed(1) + "%"],
    "v-apprdelta": ["v-vappr", v => "±" + (v / 10).toFixed(1) + "%"],
    "v-bulldelta": ["v-vbull", v => "+" + (v / 10).toFixed(0) + "%"],
    "v-beardelta": ["v-vbear", v => "−" + (v / 10).toFixed(0) + "%"],
  };
  for (const [id, [lbl, fmt]] of Object.entries(fmts)) {
    const el = document.getElementById(id);
    const up = () => { document.getElementById(lbl).textContent = fmt(el.value); };
    el.addEventListener("input", up);
    up();
  }
}

// Holds the most recent ABM median price series (absolute €), for the
// forecaster's "use ABM price path" button.
let abmMedianPrices = [];

function initForecastControls() {
  const hEl = document.getElementById("fc-horizon");
  const pEl = document.getElementById("fc-pti");
  const upd = () => {
    document.getElementById("v-fchorizon").textContent = hEl.value + " yr";
    document.getElementById("v-fcpti").textContent = (pEl.value / 10).toFixed(1);
  };
  hEl.addEventListener("input", upd);
  pEl.addEventListener("input", upd);
  upd();
  document.getElementById("fc-run").addEventListener("click", runForecast);
  document.getElementById("fc-loadhist").addEventListener("click", loadHistoricalSeries);
  document.getElementById("fc-frompath").addEventListener("click", () => {
    if (!abmMedianPrices.length) {
      document.getElementById("fc-note").textContent =
        "No ABM price path yet — click 'Pull price path from policy sim' first.";
      return;
    }
    document.getElementById("fc-history").value =
      abmMedianPrices.map(x => Math.round(x)).join(",");
    document.getElementById("fc-note").textContent =
      "Loaded " + abmMedianPrices.length + " simulated price points.";
  });
}

async function loadHistoricalSeries() {
  const key = document.getElementById("fc-series").value;
  const note = document.getElementById("fc-note");
  const prov = document.getElementById("fc-prov");
  if (!key) { note.textContent = "Pick a real-world series first."; return; }
  note.textContent = "Fitting Bayesian model to real " + key + " data...";
  try {
    const r = await fetch("/api/forecast-historical", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        key,
        horizon: parseInt(document.getElementById("fc-horizon").value),
        pti_anchor: parseInt(document.getElementById("fc-pti").value) / 10,
        seed: 1,
      }),
    });
    if (!r.ok) { note.textContent = "Failed (" + r.status + ")"; return; }
    const d = await r.json();
    // Reflect the loaded series into the textarea for transparency
    document.getElementById("fc-history").value = d.history.map(x => Math.round(x)).join(",");
    paintForecast(d.history, d);
    const u = d.uncertainty;
    note.textContent =
      `90% band at year +${d.forecast_quantiles["50"].length}: ` +
      `${Math.round(u.final_year_90pct_low)} to ${Math.round(u.final_year_90pct_high)} ` +
      `(index pts, = ${(u.band_width_as_multiple_of_today * 100).toFixed(0)}% of latest). ` +
      `The width IS the answer.`;
    prov.textContent = d.series_label + " — " + d.series_note +
      " [source: " + d.series_source + "]";
  } catch (e) {
    note.textContent = "Error: " + e.message;
  }
}

async function runForecast() {
  const note = document.getElementById("fc-note");
  note.textContent = "Fitting Bayesian model...";
  const raw = document.getElementById("fc-history").value.trim();
  const history = raw.split(",").map(x => parseFloat(x.trim())).filter(x => !isNaN(x));
  if (history.length < 4) {
    note.textContent = "Need at least 4 price points.";
    return;
  }
  try {
    const r = await fetch("/api/forecast", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        history,
        horizon: parseInt(document.getElementById("fc-horizon").value),
        pti_anchor: parseInt(document.getElementById("fc-pti").value) / 10,
        seed: 1,
      }),
    });
    if (!r.ok) { note.textContent = "Failed (" + r.status + ")"; return; }
    const d = await r.json();
    paintForecast(history, d);
    const u = d.uncertainty;
    note.textContent =
      `90% band at final year: €${Math.round(u.final_year_90pct_low).toLocaleString()} ` +
      `to €${Math.round(u.final_year_90pct_high).toLocaleString()} ` +
      `(= ${(u.band_width_as_multiple_of_today * 100).toFixed(0)}% of today's price). ` +
      `That width IS the answer.`;
  } catch (e) {
    note.textContent = "Error: " + e.message;
  }
}

let forecastChart = null;
function paintForecast(history, d) {
  const q = d.forecast_quantiles;
  const H = q["50"].length;
  // X axis: historical years (negative→0) then forecast years 1..H
  const histLabels = history.map((_, i) => -(history.length - 1 - i));
  const fcLabels = Array.from({ length: H }, (_, i) => i + 1);
  const labels = histLabels.concat(fcLabels);
  const pad = new Array(history.length).fill(null);

  const ds = [
    { label: "History", data: history.concat(new Array(H).fill(null)),
      borderColor: "#444", borderWidth: 2, pointRadius: 0 },
    { label: "Median forecast", data: pad.concat(q["50"]),
      borderColor: "#185FA5", borderWidth: 2, pointRadius: 0 },
    // 90% band (5–95) as a filled area between two lines
    { label: "95%", data: pad.concat(q["95"]),
      borderColor: "transparent", backgroundColor: "rgba(24,95,165,0.10)",
      pointRadius: 0, fill: "+1" },
    { label: "5%", data: pad.concat(q["5"]),
      borderColor: "transparent", backgroundColor: "rgba(24,95,165,0.10)",
      pointRadius: 0, fill: false },
    // 60% band (20–80) darker
    { label: "80%", data: pad.concat(q["80"]),
      borderColor: "transparent", backgroundColor: "rgba(24,95,165,0.20)",
      pointRadius: 0, fill: "+1" },
    { label: "20%", data: pad.concat(q["20"]),
      borderColor: "transparent", backgroundColor: "rgba(24,95,165,0.20)",
      pointRadius: 0, fill: false },
  ];

  if (forecastChart) forecastChart.destroy();
  forecastChart = new Chart(document.getElementById("c-forecast"), {
    type: "line",
    data: { labels, datasets: ds },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: { display: true, labels: { font: { size: 9 }, boxWidth: 10,
          filter: it => ["History", "Median forecast"].includes(it.text) } },
        tooltip: { enabled: true },
      },
      scales: {
        x: { ticks: { font: { size: 9 } }, grid: { display: false },
             title: { display: true, text: "years (0 = now)", font: { size: 9 } } },
        y: { ticks: { font: { size: 9 }, callback: v => "€" + (v / 1000).toFixed(0) + "k" },
             grid: { color: "rgba(127,127,127,0.1)" } },
      },
      elements: { line: { tension: 0.15 } },
    },
  });
}

async function pullAbmPricePath() {
  const note = document.getElementById("abm-note");
  note.textContent = "Running policy simulation...";
  // Use the horizon as the number of years to simulate.
  const horizon = parseInt(document.getElementById("horizon").value);
  try {
    const r = await fetch("/api/price-path", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        max_loan_years: 25, max_ltv: 0.90, mortgage_rate: 0.030,
        construction_rate: 0.005, public_share: 0.0, depreciation: false,
        years: Math.max(2, horizon), seed: 42,
      }),
    });
    if (!r.ok) { note.textContent = "Failed (" + r.status + ")"; return; }
    const d = await r.json();
    abmAppreciationPath = d.appreciation_path || [];
    abmMedianPrices = d.median_price || [];  // also keep absolute path for forecaster
    // Auto-select the ABM radio
    document.querySelector('input[name="apprsrc"][value="abm"]').checked = true;
    const avg = abmAppreciationPath.length
      ? (abmAppreciationPath.reduce((a, b) => a + b, 0) / abmAppreciationPath.length * 100)
      : 0;
    note.textContent = `Pulled ${abmAppreciationPath.length}y path (avg ${avg.toFixed(1)}%/yr). Approximation: median simulated home, not your specific one.`;
  } catch (e) {
    note.textContent = "Error: " + e.message;
  }
}

const ASSUMP = {
  horizon: { fmt: v => v + " yr" },
  stock:   { fmt: v => (v/10).toFixed(1) + "%" },
  appr:    { fmt: v => (v/10).toFixed(1) + "%" },
  rentinf: { fmt: v => (v/10).toFixed(1) + "%" },
  budget:  { fmt: v => "€" + parseInt(v).toLocaleString() },
};

function initAssumptionLabels() {
  for (const id of Object.keys(ASSUMP)) {
    const inp = document.getElementById(id);
    const lbl = document.getElementById("v-" + id);
    const upd = () => { lbl.textContent = ASSUMP[id].fmt(inp.value); };
    inp.addEventListener("input", upd);
    upd();
  }
}

function initPresetButtons() {
  const wrap = document.getElementById("preset-buttons");
  for (const name of Object.keys(PRESETS)) {
    const b = document.createElement("button");
    b.textContent = "+ " + name;
    b.title = "Add these scenarios to the comparison";
    b.style.fontSize = "11px";
    b.addEventListener("click", () => { appendPreset(name); run(); });
    wrap.appendChild(b);
  }
  // A clear-all control so the user can reset without reloading the page.
  const clr = document.createElement("button");
  clr.textContent = "Clear all";
  clr.style.cssText = "font-size:11px;opacity:0.75;";
  clr.addEventListener("click", () => {
    scenarios = [];
    renderScenarios();
    document.getElementById("summary-table").innerHTML = "";
  });
  wrap.appendChild(clr);
}

function appendPreset(name) {
  // ADD the preset's scenarios to whatever is already there (deduped names
  // get a numeric suffix so two "Buy" cards don't collide visually).
  const existing = new Set(scenarios.map(s => s.name));
  for (const tpl of PRESETS[name]) {
    let nm = tpl.name;
    let k = 2;
    while (existing.has(nm)) { nm = `${tpl.name} (${k++})`; }
    existing.add(nm);
    scenarios.push({ ...tpl, name: nm, id: ++scenarioCounter });
  }
  renderScenarios();
}

// Kept for the initial boot state only (replaces, used once on load).
function loadPreset(name) {
  scenarios = PRESETS[name].map(s => ({ ...s, id: ++scenarioCounter }));
  renderScenarios();
}

function addScenario() {
  scenarios.push({
    id: ++scenarioCounter,
    name: "Scenario " + (scenarios.length + 1),
    kind: "buy_now",
    home_price: 250000, down_payment: 50000,
    loan_years: 25, mortgage_rate: 0.035,
    wait_years: 0, monthly_rent: 0, reno_total: 0, reno_years: 0,
  });
  renderScenarios();
}

function renderScenarios() {
  const wrap = document.getElementById("scenario-cards");
  wrap.innerHTML = "";
  scenarios.forEach((s, idx) => wrap.appendChild(scenarioCard(s, idx)));
}

function field(label, value, onInput, type = "number", step = "1") {
  const d = document.createElement("div");
  d.style.cssText = "display:flex;justify-content:space-between;align-items:center;gap:10px;margin-bottom:6px;font-size:12px;";
  const l = document.createElement("span");
  l.textContent = label;
  l.style.color = "var(--color-text-secondary)";

  if (type !== "number") {
    const i = document.createElement("input");
    i.type = type;
    i.value = value;
    i.className = "fld-input";
    i.addEventListener("input", e => onInput(e.target.value));
    d.appendChild(l);
    d.appendChild(i);
    return d;
  }

  // Custom numeric stepper: rounded pill, [ − | value | + ], no native spinner
  const stepNum = parseFloat(step) || 1;
  const wrap = document.createElement("div");
  wrap.className = "num-stepper";

  const dec = document.createElement("button");
  dec.type = "button";
  dec.className = "num-step-btn";
  dec.textContent = "\u2212"; // minus sign
  dec.tabIndex = -1;

  const inp = document.createElement("input");
  inp.type = "text";
  inp.inputMode = "decimal";
  inp.className = "num-step-input";
  inp.value = value;

  const inc = document.createElement("button");
  inc.type = "button";
  inc.className = "num-step-btn";
  inc.textContent = "+";
  inc.tabIndex = -1;

  const clean = v => {
    const n = parseFloat(v);
    return isNaN(n) ? 0 : n;
  };
  const fmt = n => {
    // keep integers clean, otherwise trim trailing zeros sensibly
    return Number.isInteger(n) ? String(n) : String(parseFloat(n.toFixed(4)));
  };
  const commit = n => {
    inp.value = fmt(n);
    onInput(inp.value);
  };

  dec.addEventListener("click", () => commit(clean(inp.value) - stepNum));
  inc.addEventListener("click", () => commit(clean(inp.value) + stepNum));
  inp.addEventListener("input", e => onInput(e.target.value));
  inp.addEventListener("blur", () => { inp.value = fmt(clean(inp.value)); });

  wrap.appendChild(dec);
  wrap.appendChild(inp);
  wrap.appendChild(inc);
  d.appendChild(l);
  d.appendChild(wrap);
  return d;
}

function scenarioCard(s, idx) {
  const card = document.createElement("div");
  card.className = "policy-card";
  card.style.borderLeft = `3px solid ${COLORS[idx % COLORS.length]}`;

  const head = document.createElement("div");
  head.className = "pc-head";
  const nm = document.createElement("input");
  nm.type = "text"; nm.value = s.name;
  nm.className = "scenario-name";
  nm.addEventListener("input", e => { s.name = e.target.value; });
  head.appendChild(nm);

  const kindSel = document.createElement("select");
  kindSel.className = "scenario-select";
  [["buy_now","Buy now"],["rent_then_buy","Rent then buy"],["rent_forever","Rent forever"],["swiss_interest_only","Swiss (interest-only)"]].forEach(([v,t]) => {
    const o = document.createElement("option");
    o.value = v; o.textContent = t; if (s.kind === v) o.selected = true;
    kindSel.appendChild(o);
  });
  kindSel.addEventListener("change", e => { s.kind = e.target.value; renderScenarios(); });
  head.appendChild(kindSel);

  const del = document.createElement("button");
  del.className = "pc-del"; del.textContent = "Remove";
  del.addEventListener("click", () => {
    scenarios = scenarios.filter(x => x.id !== s.id);
    renderScenarios();
  });
  head.appendChild(del);
  card.appendChild(head);

  const body = document.createElement("div");
  body.style.cssText = "margin-top:6px;display:grid;grid-template-columns:1fr 1fr;gap:0 16px;";

  if (s.kind === "rent_forever") {
    body.appendChild(field("Starting savings €", s.down_payment, v => s.down_payment = +v, "number", "5000"));
    body.appendChild(field("Monthly rent €", s.monthly_rent || 0, v => { s.monthly_rent = +v; renderScenarios(); }, "number", "50"));
    body.appendChild(field("Reference home price € (for auto-rent)", s.home_price, v => { s.home_price = +v; renderScenarios(); }, "number", "5000"));
  } else {
    body.appendChild(field("Home price €", s.home_price, v => s.home_price = +v, "number", "5000"));
    body.appendChild(field("Starting capital €", s.down_payment, v => s.down_payment = +v, "number", "5000"));
    body.appendChild(field("Loan years", s.loan_years, v => s.loan_years = +v));

    // Rate type selector
    const rt = document.createElement("div");
    rt.style.cssText = "display:flex;justify-content:space-between;align-items:center;gap:8px;margin-bottom:4px;font-size:12px;";
    const rtl = document.createElement("span");
    rtl.textContent = "Rate type"; rtl.style.color = "var(--color-text-secondary)";
    const rtsel = document.createElement("select");
    rtsel.className = "scenario-select";
    [["fixed","Fixed"],["variable","Variable (Euribor+margin)"]].forEach(([v,t]) => {
      const o = document.createElement("option");
      o.value = v; o.textContent = t;
      if ((s.rate_type || "fixed") === v) o.selected = true;
      rtsel.appendChild(o);
    });
    rtsel.addEventListener("change", e => { s.rate_type = e.target.value; renderScenarios(); });
    rt.appendChild(rtl); rt.appendChild(rtsel);
    body.appendChild(rt);

    if ((s.rate_type || "fixed") === "variable") {
      body.appendChild(field("Bank margin %", ((s.margin ?? 0.01)*100).toFixed(2),
        v => s.margin = +v/100, "number", "0.05"));
    } else {
      body.appendChild(field("Mortgage rate %", ((s.mortgage_rate ?? 0.03)*100).toFixed(2),
        v => s.mortgage_rate = +v/100, "number", "0.1"));
    }
  }

  if (s.kind === "rent_then_buy") {
    body.appendChild(field("Wait years", s.wait_years, v => s.wait_years = +v));
    body.appendChild(field("Monthly rent while waiting € (0=auto)", s.monthly_rent || 0, v => s.monthly_rent = +v, "number", "50"));
  }
  if (s.kind === "buy_now") {
    body.appendChild(field("Renovation total €", s.reno_total || 0, v => s.reno_total = +v, "number", "5000"));
    body.appendChild(field("Reno spread (years)", s.reno_years || 0, v => s.reno_years = +v));
  }

  card.appendChild(body);

  // Explanatory footnote per scenario kind so the workflow isn't a mystery
  const note = document.createElement("p");
  note.style.cssText = "margin:8px 0 0;font-size:10px;color:var(--color-text-tertiary);line-height:1.5;";
  if (s.kind === "rent_then_buy") {
    note.textContent = "Starts with your starting capital invested. You rent for the wait years while it (plus monthly surplus) compounds, then automatically buy: the down payment is the larger of your stated starting capital or 20% of the by-then price, capped at the accumulated pot. The rest stays invested. You don't set the down payment manually — it's computed.";
  } else if (s.kind === "rent_forever") {
    const effRent = (s.monthly_rent && s.monthly_rent > 0)
      ? Math.round(s.monthly_rent)
      : Math.round((s.home_price || 250000) * 0.004);
    const src = (s.monthly_rent && s.monthly_rent > 0)
      ? "your entered rent"
      : "auto-estimated at 0.4%/mo of the reference home price";
    note.textContent = `Never buys. The whole starting savings stays invested for the full horizon. Rent starts at €${effRent.toLocaleString()}/month (${src}) and grows with rent inflation each year. That rent is a real cash outflow in the projection — it is not free.`;
  } else if (s.kind === "swiss_interest_only") {
    note.textContent = "Pays the deposit, then interest only — forever. The principal is never repaid (settled on sale/death). Frees cash to invest; net worth subtracts the constant debt every year. Wins only if investment returns beat the mortgage rate.";
  } else {
    note.textContent = "Spends the starting capital as the down payment on day 0; any excess stays invested. All scenarios begin from the same starting capital so the comparison is fair.";
  }
  card.appendChild(note);
  return card;
}

// Holds the appreciation path pulled from the ABM, if any.
let abmAppreciationPath = [];

function parseEuriborPath() {
  const raw = document.getElementById("euribor").value.trim();
  if (!raw) return [];
  return raw.split(",")
    .map(x => parseFloat(x.trim()))
    .filter(x => !isNaN(x))
    .map(x => x / 100);  // user enters percent, engine wants fraction
}

function buildRequest() {
  const apprMode = document.querySelector('input[name="apprsrc"]:checked').value;
  const apprPath = (apprMode === "abm") ? abmAppreciationPath : [];
  return {
    assumptions: {
      horizon_years: parseInt(document.getElementById("horizon").value),
      stock_return: parseInt(document.getElementById("stock").value) / 1000,
      house_appreciation: parseInt(document.getElementById("appr").value) / 1000,
      rent_inflation: parseInt(document.getElementById("rentinf").value) / 1000,
      general_inflation: 0.02,
      income: 45000,
      monthly_budget: parseInt(document.getElementById("budget").value),
      real_terms: document.getElementById("realterms").checked,
      benchmark_path: parseEuriborPath(),
      appreciation_path: apprPath,
    },
    scenarios: scenarios.map(s => ({
      name: s.name, kind: s.kind,
      home_price: s.home_price, down_payment: s.down_payment,
      loan_years: s.loan_years || 25,
      rate_type: s.rate_type || "fixed",
      mortgage_rate: s.mortgage_rate ?? 0.03,
      margin: s.margin ?? 0.01,
      wait_years: s.wait_years || 0, monthly_rent: s.monthly_rent || 0,
      reno_total: s.reno_total || 0, reno_years: s.reno_years || 0,
      upkeep_rate: 0.015,
    })),
    variance: {
      enabled: document.getElementById("var-on").checked,
      rate_delta: parseInt(document.getElementById("v-ratedelta").value) / 1000,
      appreciation_delta: parseInt(document.getElementById("v-apprdelta").value) / 1000,
      stock_delta_bull: parseInt(document.getElementById("v-bulldelta").value) / 1000,
      stock_delta_bear: parseInt(document.getElementById("v-beardelta").value) / 1000,
    },
  };
}

async function run() {
  setStatus("Running...");
  let data;
  try {
    const r = await fetch("/api/finance", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(buildRequest()),
    });
    if (!r.ok) { setStatus("Server error " + r.status); return; }
    data = await r.json();
  } catch (e) {
    setStatus("Error: " + e.message);
    return;
  }
  ensureCharts();
  paint(data);
  renderSummary(data);
  setStatus("Done.");
}

function ensureCharts() {
  if (charts.net) return;
  const opts = (eur = true) => ({
    responsive: true, maintainAspectRatio: false,
    plugins: { legend: { display: true, labels: { font: { size: 10 }, boxWidth: 12 } }, tooltip: { enabled: true } },
    scales: {
      x: { ticks: { font: { size: 9 } }, grid: { display: false } },
      y: { ticks: { font: { size: 9 }, callback: v => "€" + (v/1000).toFixed(0) + "k" }, grid: { color: "rgba(127,127,127,0.1)" } }
    },
    elements: { point: { radius: 0 }, line: { borderWidth: 2, tension: 0.15 } }
  });
  charts.net = new Chart(document.getElementById("c-net"), { type: "line", data: { labels: [], datasets: [] }, options: opts() });
  charts.int = new Chart(document.getElementById("c-int"), { type: "line", data: { labels: [], datasets: [] }, options: opts() });
  charts.inv = new Chart(document.getElementById("c-inv"), { type: "line", data: { labels: [], datasets: [] }, options: opts() });
  charts.hou = new Chart(document.getElementById("c-hou"), { type: "line", data: { labels: [], datasets: [] }, options: opts() });

  // Rate chart uses a percent axis instead of euros
  const rateOpts = {
    responsive: true, maintainAspectRatio: false,
    plugins: { legend: { display: true, labels: { font: { size: 10 }, boxWidth: 12 } }, tooltip: { enabled: true } },
    scales: {
      x: { ticks: { font: { size: 9 } }, grid: { display: false } },
      y: { ticks: { font: { size: 9 }, callback: v => (v * 100).toFixed(1) + "%" }, grid: { color: "rgba(127,127,127,0.1)" }, beginAtZero: true }
    },
    elements: { point: { radius: 0 }, line: { borderWidth: 2, tension: 0 } }
  };
  charts.rate = new Chart(document.getElementById("c-rate"), { type: "line", data: { labels: [], datasets: [] }, options: rateOpts });
}

function seriesOf(entry) {
  // Back-compat: entry always has .series (base). Branches optional.
  return entry.series;
}

function paint(data) {
  const names = Object.keys(data);
  const anyVar = names.some(n => data[n].variance && data[n].branches);
  const labels = seriesOf(data[names[0]]).map(p => p.year);

  const mk = (key) => names.map((n, i) => ({
    label: n,
    data: seriesOf(data[n]).map(p => p[key]),
    borderColor: COLORS[i % COLORS.length],
    backgroundColor: "transparent",
  }));

  // Net worth chart: if variance on, draw bear/bull as a shaded band with
  // a solid base line, per scenario. Otherwise the normal single line.
  if (anyVar) {
    const ds = [];
    names.forEach((n, i) => {
      const e = data[n];
      const col = COLORS[i % COLORS.length];
      if (e.variance && e.branches) {
        const bear = e.branches.bear.series.map(p => p.net_worth);
        const base = e.branches.base.series.map(p => p.net_worth);
        const bull = e.branches.bull.series.map(p => p.net_worth);
        // bull as upper bound, bear fills down to it -> shaded band
        ds.push({ label: n + " (bull)", data: bull, borderColor: "transparent",
                  backgroundColor: hexA(col, 0.13), pointRadius: 0, fill: "+2" });
        ds.push({ label: n + " (base)", data: base, borderColor: col,
                  borderWidth: 2, pointRadius: 0, fill: false });
        ds.push({ label: n + " (bear)", data: bear, borderColor: "transparent",
                  backgroundColor: hexA(col, 0.13), pointRadius: 0, fill: false });
      } else {
        ds.push({ label: n, data: seriesOf(e).map(p => p.net_worth),
                  borderColor: col, backgroundColor: "transparent",
                  borderWidth: 2, pointRadius: 0 });
      }
    });
    charts.net.data.labels = labels;
    charts.net.data.datasets = ds;
    charts.net.options.plugins.legend.labels.filter =
      it => it.text.endsWith("(base)") || !it.text.includes("(");
    charts.net.update("none");
  } else {
    charts.net.data.labels = labels;
    charts.net.data.datasets = mk("net_worth");
    charts.net.update("none");
  }

  charts.int.data.labels = labels; charts.int.data.datasets = mk("cumulative_interest"); charts.int.update("none");
  charts.inv.data.labels = labels; charts.inv.data.datasets = mk("investments"); charts.inv.update("none");
  charts.hou.data.labels = labels; charts.hou.data.datasets = mk("cumulative_housing_cost"); charts.hou.update("none");
  charts.rate.data.labels = labels; charts.rate.data.datasets = mk("effective_rate"); charts.rate.update("none");
}

function hexA(hex, a) {
  const h = hex.replace("#", "");
  const r = parseInt(h.substring(0, 2), 16);
  const g = parseInt(h.substring(2, 4), 16);
  const b = parseInt(h.substring(4, 6), 16);
  return `rgba(${r},${g},${b},${a})`;
}

function renderSummary(data) {
  const names = Object.keys(data);
  const eur = x => "€" + Math.round(x).toLocaleString();
  const anyVar = names.some(n => data[n].variance && data[n].branches);

  let html = '<table style="width:100%;border-collapse:collapse;font-size:12px;">';
  if (anyVar) {
    html += '<tr style="border-bottom:0.5px solid var(--color-border-tertiary);text-align:left;">' +
      '<th style="padding:6px;">Scenario</th>' +
      '<th style="padding:6px;text-align:right;color:var(--color-text-danger);">Bear net worth</th>' +
      '<th style="padding:6px;text-align:right;font-weight:600;">Base net worth</th>' +
      '<th style="padding:6px;text-align:right;color:var(--color-text-success);">Bull net worth</th>' +
      '<th style="padding:6px;text-align:right;">Base interest</th></tr>';
    // Best by base net worth
    let bestNet = -Infinity, bestName = "";
    for (const n of names) {
      const v = data[n].branches ? data[n].branches.base.final.net_worth
                                 : data[n].final.net_worth;
      if (v > bestNet) { bestNet = v; bestName = n; }
    }
    for (const n of names) {
      const e = data[n];
      const isBest = n === bestName;
      if (e.branches) {
        const bear = e.branches.bear.final, base = e.branches.base.final, bull = e.branches.bull.final;
        const spread = bull.net_worth - bear.net_worth;
        html += `<tr style="border-bottom:0.5px solid var(--color-border-tertiary);${isBest ? 'background:var(--color-background-secondary);' : ''}">` +
          `<td style="padding:6px;">${n}${isBest ? ' ★' : ''}` +
          `<div style="font-size:10px;color:var(--color-text-tertiary);">range ${eur(spread)}</div></td>` +
          `<td style="padding:6px;text-align:right;color:var(--color-text-danger);">${eur(bear.net_worth)}</td>` +
          `<td style="padding:6px;text-align:right;font-weight:600;">${eur(base.net_worth)}</td>` +
          `<td style="padding:6px;text-align:right;color:var(--color-text-success);">${eur(bull.net_worth)}</td>` +
          `<td style="padding:6px;text-align:right;">${eur(base.total_interest_paid)}</td></tr>`;
      } else {
        const f = e.final;
        html += `<tr style="border-bottom:0.5px solid var(--color-border-tertiary);">` +
          `<td style="padding:6px;">${n}</td>` +
          `<td style="padding:6px;text-align:right;">—</td>` +
          `<td style="padding:6px;text-align:right;font-weight:600;">${eur(f.net_worth)}</td>` +
          `<td style="padding:6px;text-align:right;">—</td>` +
          `<td style="padding:6px;text-align:right;">${eur(f.total_interest_paid)}</td></tr>`;
      }
    }
    html += '</table>';
    html += '<p style="font-size:11px;color:var(--color-text-tertiary);margin-top:6px;">★ = highest <em>base</em> net worth. The bear→bull range shows how much the outcome hinges on rates, prices and stock returns you don\'t control — a wide range means the decision is more a bet than a calculation. Net worth = home equity + investments − debt.</p>';
  } else {
    html += '<tr style="border-bottom:0.5px solid var(--color-border-tertiary);text-align:left;">' +
      '<th style="padding:6px;">Scenario</th><th style="padding:6px;text-align:right;">Final net worth</th>' +
      '<th style="padding:6px;text-align:right;">Total interest</th>' +
      '<th style="padding:6px;text-align:right;">Total housing cost</th>' +
      '<th style="padding:6px;text-align:right;">Final investments</th></tr>';
    let bestNet = -Infinity, bestName = "";
    for (const n of names) if (data[n].final.net_worth > bestNet) { bestNet = data[n].final.net_worth; bestName = n; }
    for (const n of names) {
      const f = data[n].final;
      const isBest = n === bestName;
      html += `<tr style="border-bottom:0.5px solid var(--color-border-tertiary);${isBest ? 'background:var(--color-background-secondary);' : ''}">` +
        `<td style="padding:6px;">${n}${isBest ? ' ★' : ''}</td>` +
        `<td style="padding:6px;text-align:right;font-weight:500;">${eur(f.net_worth)}</td>` +
        `<td style="padding:6px;text-align:right;color:var(--color-text-danger);">${eur(f.total_interest_paid)}</td>` +
        `<td style="padding:6px;text-align:right;">${eur(f.total_housing_cost)}</td>` +
        `<td style="padding:6px;text-align:right;">${eur(f.investments)}</td></tr>`;
    }
    html += '</table>';
    html += '<p style="font-size:11px;color:var(--color-text-tertiary);margin-top:6px;">★ = highest final net worth. Net worth = home equity + investments − debt. All figures nominal unless "real terms" is checked.</p>';
  }
  document.getElementById("summary-table").innerHTML = html;
}

function setStatus(m) { document.getElementById("status").textContent = m; }

boot();
