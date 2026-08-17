// Housing Simulator frontend.
//
// Layout:
//   Controls tab     — presets, all structural sliders, built-in tax sliders, run button.
//   Policies tab     — formula editor for built-in taxes + add custom formula policies.
//   Sim settings tab — N, M, years, seed (persistent across preset changes).
//   Parameters tab   — cheatsheet of variables available to formulas.
//
// Custom formula policies are kept entirely in JS state and sent to the API on each run.

const API_BASE = "";

// Built-in formula policies that ALSO have a slider on the Controls tab.
// These appear in the Policies tab too so the user can inspect/edit their formulas.
const BUILTIN_FORMULA_POLICIES = [
  {
    id: "tax",
    name: "Progressive multi-home tax",
    formula: "-p.value * (slider/1000) * (p.property_index - 1) if p.property_index > 1 else 0",
    perProp: true,
    help: "Tax on each property beyond the first, escalating with how many you already own.",
    slider_dom_id: "tax",
  },
  {
    id: "vac",
    name: "Vacancy tax",
    formula: "-p.value * (slider/1000) if (p.is_vacant and not p.is_residence) else 0",
    perProp: true,
    help: "Penalizes empty units. Discourages speculative holds.",
    slider_dom_id: "vac",
  },
];

// --- State ---
let PRESETS = {};
let TEMPLATES = {};
let customPolicies = [];   // [{name, formula, sliderVal, perProp, enabled, error}]
let customCounter = 0;
let baselineHist = null;
let baselineFinal = null;
let baselineLabel = "Baseline";
let charts = {};

// --- Bootstrap ---
async function boot() {
  try {
    const [pr, tp] = await Promise.all([
      fetch(API_BASE + "/api/presets").then(r => r.json()),
      fetch(API_BASE + "/api/templates").then(r => r.json()),
    ]);
    PRESETS = pr; TEMPLATES = tp;
  } catch (e) {
    setStatus("API unreachable. Is the backend running?");
    return;
  }
  initPresetButtons();
  initExampleLinks();
  initTabs();
  initSliders();
  initSimSettings();
  initDemographics();
  renderPolicies();
  // Apply baseline silently for first run, no diff display
  applyPreset(PRESETS.baseline, /*showDiff=*/false);
  setTimeout(run, 100);
}

function initPresetButtons() {
  const wrap = document.getElementById("preset-buttons");
  wrap.innerHTML = "";
  for (const name of Object.keys(PRESETS)) {
    const btn = document.createElement("button");
    btn.textContent = name.charAt(0).toUpperCase() + name.slice(1);
    btn.dataset.preset = name;
    btn.addEventListener("click", () => {
      applyPreset(PRESETS[name], /*showDiff=*/true, name);
      run();
    });
    wrap.appendChild(btn);
  }
}

function initExampleLinks() {
  const row = document.getElementById("examples-row");
  row.innerHTML = "Templates: ";
  for (const key of Object.keys(TEMPLATES)) {
    const a = document.createElement("a");
    a.textContent = TEMPLATES[key].name;
    a.addEventListener("click", () => addCustom(TEMPLATES[key]));
    row.appendChild(a);
  }
}

function initTabs() {
  document.querySelectorAll(".tab").forEach(t => {
    t.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach(x => x.classList.remove("active"));
      document.querySelectorAll(".tab-body").forEach(x => x.classList.remove("active"));
      t.classList.add("active");
      document.getElementById("t-" + t.dataset.tab).classList.add("active");
    });
  });
  document.getElementById("run").addEventListener("click", run);
  document.getElementById("add-custom").addEventListener("click", () => addCustom());
}

// All Controls-tab sliders: id -> {labelEl, format function}
const SLIDER_CONFIG = {
  loan:  { fmt: v => v + " yr" },
  ltv:   { fmt: v => v + "%" },
  mrate: { fmt: v => (v/10).toFixed(1) + "%" },
  build: { fmt: v => (v/10).toFixed(1) + "%" },
  pub:   { fmt: v => v + "%" },
  tax:   { fmt: v => (v/10).toFixed(1) + "%" },
  vac:   { fmt: v => (v/10).toFixed(1) + "%" },
  picky: { fmt: v => (v/100).toFixed(2) },
};

function initSliders() {
  for (const id of Object.keys(SLIDER_CONFIG)) {
    const inp = document.getElementById(id);
    const lbl = document.getElementById("v-" + id);
    const update = () => { lbl.textContent = SLIDER_CONFIG[id].fmt(parseFloat(inp.value)); };
    inp.addEventListener("input", update);
    update();
  }
}

function initSimSettings() {
  const update = () => {
    document.getElementById("v-N").textContent = parseInt(document.getElementById("N").value).toLocaleString();
    document.getElementById("v-M").textContent = parseInt(document.getElementById("M").value).toLocaleString();
    document.getElementById("v-yrs").textContent = document.getElementById("yrs").value;
    document.getElementById("v-seed").textContent = document.getElementById("seed").value;
  };
  ["N","M","yrs","seed"].forEach(id => document.getElementById(id).addEventListener("input", update));
  update();
}

// Demographics sliders with their format functions
const DEMO_CONFIG = {
  incmu:   { fmt: v => "€" + Math.round(Math.exp(parseFloat(v))).toLocaleString() },
  incsig:  { fmt: v => parseFloat(v).toFixed(2) },
  agemu:   { fmt: v => v + " yr" },
  agesig:  { fmt: v => v + " yr" },
  bprice:  { fmt: v => "€" + parseInt(v).toLocaleString() },
  iown:    { fmt: v => v + "%" },
  qspread: { fmt: v => (v/100).toFixed(2) },
};

const DEMO_DEFAULTS = {
  incmu: 10.6, incsig: 0.40, agemu: 45, agesig: 15,
  bprice: 180000, iown: 60, qspread: 25,
};

function initDemographics() {
  for (const id of Object.keys(DEMO_CONFIG)) {
    const inp = document.getElementById(id);
    const lbl = document.getElementById("v-" + id);
    const update = () => { lbl.textContent = DEMO_CONFIG[id].fmt(inp.value); };
    inp.addEventListener("input", update);
    update();
  }
  document.getElementById("reset-demo").addEventListener("click", () => {
    for (const [id, val] of Object.entries(DEMO_DEFAULTS)) {
      const inp = document.getElementById(id);
      inp.value = val;
      inp.dispatchEvent(new Event("input"));
    }
  });
}

// --- Preset application & diff display ---

function captureCurrentSliderValues() {
  return {
    loan: parseInt(document.getElementById("loan").value),
    mrate: parseInt(document.getElementById("mrate").value),
    ltv: parseInt(document.getElementById("ltv").value),
    build: parseInt(document.getElementById("build").value),
    pub: parseInt(document.getElementById("pub").value),
    tax: parseInt(document.getElementById("tax").value),
    vac: parseInt(document.getElementById("vac").value),
    dep: document.getElementById("dep").checked,
  };
}

function applyPreset(p, showDiff = false, presetName = null) {
  const before = captureCurrentSliderValues();

  // Set all Controls-tab inputs from the preset config.
  // Sim settings (N, M, years, seed) intentionally NOT changed.
  document.getElementById("loan").value = p.max_loan_years;
  document.getElementById("ltv").value = Math.round(p.max_ltv * 100);
  // Mortgage rate isn't in presets currently; keep current value
  document.getElementById("build").value = Math.round(p.construction_rate * 1000);
  document.getElementById("pub").value = Math.round(p.public_share * 100);
  document.getElementById("dep").checked = p.depreciation;
  document.getElementById("tax").value = p.multi_home_tax || 0;
  document.getElementById("vac").value = p.vacancy_tax || 0;

  // Refresh slider labels
  initSliders();

  if (showDiff) {
    renderPresetDiff(before, captureCurrentSliderValues(), presetName);
  }
}

const SLIDER_LABEL = {
  loan: { label: "Loan term", suffix: "yr" },
  mrate:{ label: "Mortgage rate", suffix: "% (×0.1)" },
  ltv:  { label: "Max LTV", suffix: "%" },
  build:{ label: "Construction rate", suffix: "% (×0.1)" },
  pub:  { label: "Public housing", suffix: "%" },
  tax:  { label: "Multi-home tax", suffix: "% (×0.1)" },
  vac:  { label: "Vacancy tax", suffix: "% (×0.1)" },
};

function renderPresetDiff(before, after, presetName) {
  const wrap = document.getElementById("preset-diff");
  const changes = [];
  for (const k of Object.keys(SLIDER_LABEL)) {
    if (before[k] !== after[k]) {
      const wasZero = before[k] === 0, isZero = after[k] === 0;
      let cls = "pd-change", marker = "";
      if (wasZero && !isZero) { cls = "pd-on"; marker = "+ "; }
      else if (!wasZero && isZero) { cls = "pd-off"; marker = "− "; }
      const fmt = SLIDER_CONFIG[k].fmt;
      changes.push(`<span class="${cls}">${marker}${SLIDER_LABEL[k].label}: ${fmt(before[k])} → ${fmt(after[k])}</span>`);
    }
  }
  if (before.dep !== after.dep) {
    const cls = after.dep ? "pd-on" : "pd-off";
    const marker = after.dep ? "+ " : "− ";
    changes.push(`<span class="${cls}">${marker}Tokyo depreciation: ${after.dep ? "ON" : "OFF"}</span>`);
  }
  if (changes.length === 0) {
    wrap.classList.remove("show");
    wrap.innerHTML = "";
    return;
  }
  wrap.classList.add("show");
  wrap.innerHTML = `<strong>${presetName.charAt(0).toUpperCase() + presetName.slice(1)} applied:</strong><br>${changes.join("<br>")}`;
}

// --- Policies tab rendering ---

function renderPolicies() {
  const list = document.getElementById("policy-list");
  list.innerHTML = "";

  // Built-in formula policies first (read-only formulas, slider value mirrored from Controls tab)
  for (const def of BUILTIN_FORMULA_POLICIES) {
    list.appendChild(makeBuiltinPolicyCard(def));
  }
  // Then custom ones
  for (let i = 0; i < customPolicies.length; i++) {
    list.appendChild(makeCustomPolicyCard(customPolicies[i], i));
  }
}

function makeBuiltinPolicyCard(def) {
  const card = document.createElement("div");
  card.className = "policy-card builtin";

  const head = document.createElement("div");
  head.className = "pc-head";
  // Active state mirrors the slider in Controls tab (zero = inactive)
  const sliderVal = parseInt(document.getElementById(def.slider_dom_id).value);
  const active = sliderVal > 0;
  const dot = document.createElement("span");
  dot.className = "pc-dot " + (active ? "on" : "off");
  dot.textContent = active ? "●" : "○";
  head.appendChild(dot);

  const name = document.createElement("div");
  name.className = "pc-name"; name.textContent = def.name;
  head.appendChild(name);

  const sliderInfo = document.createElement("span");
  sliderInfo.className = "pc-badge";
  sliderInfo.textContent = "slider: Controls tab";
  head.appendChild(sliderInfo);

  card.appendChild(head);

  const help = document.createElement("div");
  help.className = "pc-help"; help.textContent = def.help;
  card.appendChild(help);

  const toggle = document.createElement("div");
  toggle.className = "pc-toggle"; toggle.textContent = "Show formula ▾";
  const body = document.createElement("div"); body.className = "pc-body";

  const ppRow = document.createElement("div");
  ppRow.className = "pc-perprop-row";
  ppRow.textContent = "Runs per property (built-in, not editable)";
  body.appendChild(ppRow);

  const ta = document.createElement("textarea");
  ta.className = "pc-formula"; ta.value = def.formula; ta.disabled = true;
  body.appendChild(ta);

  toggle.addEventListener("click", () => {
    body.classList.toggle("show");
    toggle.textContent = body.classList.contains("show") ? "Hide formula ▴" : "Show formula ▾";
  });
  card.appendChild(toggle);
  card.appendChild(body);
  return card;
}

function makeCustomPolicyCard(c, idx) {
  const card = document.createElement("div");
  card.className = "policy-card";

  const head = document.createElement("div");
  head.className = "pc-head";
  const cb = document.createElement("input");
  cb.type = "checkbox"; cb.className = "pc-en"; cb.checked = c.enabled;
  cb.addEventListener("change", e => { c.enabled = e.target.checked; });
  head.appendChild(cb);

  const inp = document.createElement("input");
  inp.type = "text"; inp.value = c.name;
  inp.addEventListener("input", e => { c.name = e.target.value; });
  head.appendChild(inp);

  const del = document.createElement("button");
  del.className = "pc-del"; del.textContent = "Remove";
  del.addEventListener("click", () => {
    customPolicies.splice(idx, 1);
    renderPolicies();
  });
  head.appendChild(del);
  card.appendChild(head);

  // Slider
  const sr = document.createElement("div");
  sr.className = "pc-slider-row";
  const sl = document.createElement("input");
  sl.type = "range"; sl.min = "0"; sl.max = "200"; sl.step = "1"; sl.value = c.sliderVal;
  const vEl = document.createElement("span");
  vEl.className = "pc-val"; vEl.textContent = c.sliderVal;
  sl.addEventListener("input", e => {
    c.sliderVal = parseFloat(e.target.value);
    vEl.textContent = c.sliderVal;
  });
  sr.appendChild(sl); sr.appendChild(vEl);
  card.appendChild(sr);

  if (c.hint) {
    const help = document.createElement("div");
    help.className = "pc-help"; help.textContent = c.hint;
    card.appendChild(help);
  }

  const toggle = document.createElement("div");
  toggle.className = "pc-toggle"; toggle.textContent = "Edit formula ▾";
  const body = document.createElement("div"); body.className = "pc-body show";

  const ppRow = document.createElement("label");
  ppRow.className = "pc-perprop-row";
  const pp = document.createElement("input");
  pp.type = "checkbox"; pp.checked = c.perProp;
  pp.addEventListener("change", e => { c.perProp = e.target.checked; });
  ppRow.appendChild(pp);
  ppRow.appendChild(document.createTextNode(" Run per property"));
  body.appendChild(ppRow);

  const ta = document.createElement("textarea");
  ta.className = "pc-formula"; ta.value = c.formula;
  ta.addEventListener("input", e => { c.formula = e.target.value; });
  body.appendChild(ta);

  const err = document.createElement("div");
  err.className = "pc-err"; err.textContent = c.error || "";
  body.appendChild(err);

  toggle.addEventListener("click", () => {
    body.classList.toggle("show");
    toggle.textContent = body.classList.contains("show") ? "Hide editor ▴" : "Edit formula ▾";
  });
  card.appendChild(toggle);
  card.appendChild(body);
  return card;
}

function addCustom(template) {
  customPolicies.push({
    name: template?.name || "New policy",
    formula: template?.formula || "p.value * 0.001 * slider/100",
    sliderVal: template?.slider_value ?? 50,
    perProp: template?.per_prop ?? true,
    enabled: true,
    hint: template?.hint || "",
    error: "",
  });
  renderPolicies();
  // Switch to Policies tab so the user sees what they just added
  document.querySelector('.tab[data-tab="policies"]').click();
}

// --- Run simulation ---

function buildRequest() {
  const customs = customPolicies.map(c => ({
    name: c.name,
    formula: c.formula,
    slider_value: c.sliderVal,
    per_prop: c.perProp,
    enabled: c.enabled,
  }));
  return {
    max_loan_years: parseInt(document.getElementById("loan").value),
    max_ltv: parseInt(document.getElementById("ltv").value) / 100,
    mortgage_rate: parseInt(document.getElementById("mrate").value) / 1000,
    construction_rate: parseInt(document.getElementById("build").value) / 1000,
    public_share: parseInt(document.getElementById("pub").value) / 100,
    depreciation: document.getElementById("dep").checked,
    match_pickiness: parseInt(document.getElementById("picky").value) / 100,
    years: parseInt(document.getElementById("yrs").value),
    n_households: parseInt(document.getElementById("N").value),
    n_properties: parseInt(document.getElementById("M").value),
    seed: parseInt(document.getElementById("seed").value),
    multi_home_tax: parseInt(document.getElementById("tax").value),
    vacancy_tax: parseInt(document.getElementById("vac").value),
    custom_policies: customs,
    demographics: {
      income_log_mu: parseFloat(document.getElementById("incmu").value),
      income_log_sigma: parseFloat(document.getElementById("incsig").value),
      age_mean: parseFloat(document.getElementById("agemu").value),
      age_sd: parseFloat(document.getElementById("agesig").value),
      base_price: parseFloat(document.getElementById("bprice").value),
      initial_owner_share: parseInt(document.getElementById("iown").value) / 100,
      quality_pref_spread: parseInt(document.getElementById("qspread").value) / 100,
    },
  };
}

async function run() {
  setStatus("Running...");
  const req = buildRequest();
  let data;
  try {
    const r = await fetch(API_BASE + "/api/simulate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(req),
    });
    if (!r.ok) { setStatus("Server error " + r.status); return; }
    data = await r.json();
  } catch (e) {
    setStatus("Error: " + e.message);
    return;
  }

  // Surface compile errors on the matching custom policy
  for (const c of customPolicies) c.error = "";
  if (data.compile_errors?.length) {
    for (const ce of data.compile_errors) {
      const target = customPolicies.find(c => c.name === ce.policy_name);
      if (target) target.error = ce.error;
    }
    renderPolicies();
  }

  ensureCharts();
  if (!baselineHist) {
    baselineHist = data.history;
    baselineFinal = data.history[data.history.length - 1];
  }
  paint(data.history);
  updateCards(data.history[data.history.length - 1]);
  // Refresh policy cards so built-in tax indicators reflect current slider state
  renderPolicies();
  setStatus(`Done (${data.history.length - 1} years simulated).`);
}

// --- Charts ---
function ensureCharts() {
  if (charts.c1) return;
  const opts = {
    responsive: true, maintainAspectRatio: false,
    plugins: { legend: { display: false }, tooltip: { enabled: false } },
    scales: {
      x: { display: true, ticks: { font: { size: 9 } }, grid: { display: false } },
      y: { display: true, ticks: { font: { size: 9 } }, grid: { color: "rgba(127,127,127,0.1)" } }
    },
    elements: { point: { radius: 0 }, line: { borderWidth: 2, tension: 0.2 } }
  };
  const mk = (id, color) => new Chart(document.getElementById(id), {
    type: "line",
    data: { labels: [], datasets: [
      { label: "Baseline", data: [], borderColor: "#aaa", borderDash: [4,4] },
      { label: "Current", data: [], borderColor: color },
    ]},
    options: opts,
  });
  charts.c1 = mk("c1", "#854F0B");
  charts.c2 = mk("c2", "#A32D2D");
  charts.c3 = mk("c3", "#185FA5");
  charts.c4 = mk("c4", "#993C1D");
  charts.c5 = mk("c5", "#3B6D11");
  charts.c6 = mk("c6", "#993556");
}

function paint(history) {
  const labels = history.map(h => h.year);
  const set = (chart, key) => {
    chart.data.labels = labels;
    chart.data.datasets[0].data = baselineHist ? baselineHist.map(h => h[key]) : [];
    chart.data.datasets[1].data = history.map(h => h[key]);
    chart.update("none");
  };
  set(charts.c1, "housing_burden_median");
  set(charts.c2, "overburdened_pct");
  set(charts.c3, "homeownership_rate");
  set(charts.c4, "price_to_income");
  set(charts.c5, "disposable_share_median");
  set(charts.c6, "multi_owner_pct");
}

const fmtPct = x => (x * 100).toFixed(1) + "%";
const fmtNum = x => x.toFixed(2);

function updateCards(final) {
  const fmtEur = x => "€" + Math.round(x).toLocaleString();
  const setM = (vid, did, val, baseVal, fmt, lowGood) => {
    document.getElementById(vid).textContent = fmt(val);
    if (baselineFinal && final !== baselineFinal) {
      const diff = val - baseVal;
      const dd = document.getElementById(did);
      const threshold = fmt === fmtEur ? 100 : 0.005;
      if (Math.abs(diff) < threshold) {
        dd.textContent = "≈ baseline";
        dd.style.color = "var(--color-text-tertiary)";
      } else {
        const good = lowGood ? diff < 0 : diff > 0;
        dd.textContent = (diff > 0 ? "▲" : "▼") + " " + fmt(Math.abs(diff));
        dd.style.color = good ? "var(--color-text-success)" : "var(--color-text-danger)";
      }
    } else {
      document.getElementById(did).textContent = "";
    }
  };
  setM("m-bur","d-bur", final.housing_burden_median, baselineFinal?.housing_burden_median, fmtPct, true);
  setM("m-ovr","d-ovr", final.overburdened_pct, baselineFinal?.overburdened_pct, fmtPct, true);
  setM("m-own","d-own", final.homeownership_rate, baselineFinal?.homeownership_rate, fmtPct, false);
  setM("m-hou","d-hou", final.pct_housed, baselineFinal?.pct_housed, fmtPct, false);
  setM("m-pti","d-pti", final.price_to_income, baselineFinal?.price_to_income, fmtNum, true);
  setM("m-mul","d-mul", final.multi_owner_pct, baselineFinal?.multi_owner_pct, fmtPct, true);
  setM("m-dbt","d-dbt", final.median_mortgage_debt, baselineFinal?.median_mortgage_debt, fmtEur, true);
  setM("m-gin","d-gin", final.wealth_gini, baselineFinal?.wealth_gini, fmtNum, true);
}

function setStatus(msg) { document.getElementById("status").textContent = msg; }

boot();
