// Demo-mode mock backend for the static GitHub Pages build.
//
// The real app needs the FastAPI backend in backend/ (see HOSTING.md). GitHub
// Pages serves static files only, so this shim lets the published page still
// DO something: it wraps fetch(), and for /api/* calls it FIRST tries the real
// network — so when a live backend is present (local dev, or a Pages build
// pointed at a hosted API) this file does nothing at all. Only when no backend
// answers does it serve the precomputed fixtures in ./mock/, generated offline
// by scripts/gen_mock_fixtures.py from the genuine simulator.
//
// What demo mode can and cannot do:
//   • Built-in presets (Baseline, Loan10, Tokyo, Vienna, Combined) → real,
//     precomputed simulator output.
//   • Finance preset groups and the historical-series forecasts → real,
//     precomputed output.
//   • Custom sliders, custom formula policies, changed world size, and
//     arbitrary finance scenarios → cannot be computed statically; the mock
//     returns the nearest preset and flags it. Run the backend for those.
(function () {
  "use strict";

  // Where the fixtures live, relative to the page (works under a project subpath).
  const MOCK_BASE = new URL("mock/", document.baseURI).href;

  // Structural fields that identify a preset. Matched numerically so JS/Python
  // number formatting never matters.
  const SIG = ["max_loan_years", "max_ltv", "construction_rate",
               "public_share", "depreciation", "multi_home_tax", "vacancy_tax"];
  const DEFAULTS = { years: 50, n_households: 2000, n_properties: 1800, seed: 42 };

  let PRESETS = null;              // loaded lazily from mock/presets.json
  let bannerShown = false;
  let demoMode = false;            // set once a real backend is confirmed absent

  const realFetch = window.fetch.bind(window);

  const jsonResponse = (obj) =>
    new Response(JSON.stringify(obj), {
      status: 200,
      headers: { "Content-Type": "application/json", "X-Demo-Mock": "1" },
    });

  async function loadFixture(name) {
    const r = await realFetch(MOCK_BASE + name, { cache: "no-store" });
    if (!r.ok) throw new Error("fixture missing: " + name);
    return r.json();
  }

  function showBanner(msg) {
    if (bannerShown) return;
    bannerShown = true;
    const bar = document.createElement("div");
    bar.setAttribute("role", "status");
    bar.style.cssText =
      "position:sticky;top:0;z-index:9999;background:#8a5a00;color:#fff;" +
      "font:13px/1.4 system-ui,sans-serif;padding:8px 40px 8px 12px;" +
      "text-align:center;box-shadow:0 1px 4px rgba(0,0,0,.3)";
    bar.innerHTML =
      '<strong>Demo mode</strong> — precomputed results. Presets and the ' +
      'historical forecasts are real simulator output; custom sliders, ' +
      'policies and finance scenarios need the live backend ' +
      '(<a href="https://github.com/Gelato1337/housing-policy-simulator#run-it-for-real" ' +
      'style="color:#ffe;text-decoration:underline">how to run it</a>).';
    const x = document.createElement("button");
    x.textContent = "×";
    x.setAttribute("aria-label", "Dismiss");
    x.style.cssText =
      "position:absolute;right:8px;top:50%;transform:translateY(-50%);" +
      "background:none;border:none;color:#fff;font-size:18px;cursor:pointer;line-height:1";
    x.onclick = () => bar.remove();
    bar.appendChild(x);
    (document.body || document.documentElement).prepend(bar);
  }

  const approx = (a, b) => Math.abs(Number(a) - Number(b)) < 1e-9;

  function matchPreset(req) {
    if (!PRESETS) return null;
    for (const [name, p] of Object.entries(PRESETS)) {
      let ok = true;
      for (const k of SIG) {
        const rv = k === "depreciation" ? !!req[k] : Number(req[k] || 0);
        const pv = k === "depreciation" ? !!p[k] : Number(p[k] || 0);
        if (k === "depreciation" ? rv !== pv : !approx(rv, pv)) { ok = false; break; }
      }
      if (ok) return name;
    }
    return null;
  }

  function sizeChanged(req) {
    return ["years", "n_households", "n_properties", "seed"].some(
      (k) => req[k] !== undefined && Number(req[k]) !== DEFAULTS[k]);
  }

  async function handleSimulate(req) {
    if (!PRESETS) PRESETS = await loadFixture("presets.json");
    const custom = (req.custom_policies && req.custom_policies.length > 0);
    const preset = matchPreset(req);
    const name = preset || "baseline";
    const data = await loadFixture(`simulate-${name}.json`);
    const notes = [];
    if (!preset) notes.push("custom policy settings");
    if (custom) notes.push("custom formula policies");
    if (sizeChanged(req)) notes.push("non-default world size/seed");
    if (notes.length) {
      data.demo_note =
        "Demo mode cannot compute " + notes.join(", ") +
        `. Showing the precomputed "${name}" preset. Run the backend for live results.`;
    }
    // Custom policies still "compile" client-side? No — report none; the real
    // backend validates. Keep the shape the frontend expects.
    data.compile_errors = data.compile_errors || [];
    return jsonResponse(data);
  }

  async function handleFinance() {
    const groups = await loadFixture("finance-groups.json");
    const key = Object.keys(groups)[0];
    const out = groups[key];
    return jsonResponse(out);
  }

  async function handlePricePath() {
    // Derive the median-price growth path from the baseline simulate fixture —
    // same underlying data the real endpoint would use.
    const base = await loadFixture("simulate-baseline.json");
    const prices = base.history.map((h) => h.median_price);
    const growth = [];
    for (let i = 1; i < prices.length; i++) {
      const prev = prices[i - 1] > 0 ? prices[i - 1] : 1;
      growth.push(Math.round(((prices[i] - prev) / prev) * 1e5) / 1e5);
    }
    return jsonResponse({
      median_price: prices.map((p) => Math.round(p * 100) / 100),
      appreciation_path: growth,
      note: "Demo mode: baseline simulated median-price path (precomputed).",
    });
  }

  async function handleForecastHistorical(req) {
    const fc = await loadFixture("forecast-historical.json");
    const r = fc[req.key];
    if (!r) return new Response(JSON.stringify({ detail: "Unknown series" }), { status: 404 });
    return jsonResponse(r);
  }

  async function handleForecast() {
    // No arbitrary Bayesian fit statically; show the Finland series fit as a
    // representative example and say so.
    const fc = await loadFixture("forecast-historical.json");
    const r = Object.assign({}, fc.finland);
    r.demo_note = "Demo mode: showing a representative precomputed forecast. " +
      "Run the backend to fit your own price history.";
    return jsonResponse(r);
  }

  async function route(pathname, method, body) {
    if (method === "GET" && pathname.endsWith("/api/presets"))
      return jsonResponse((PRESETS = await loadFixture("presets.json")));
    if (method === "GET" && pathname.endsWith("/api/templates"))
      return jsonResponse(await loadFixture("templates.json"));
    if (method === "GET" && pathname.endsWith("/api/historical-series"))
      return jsonResponse(await loadFixture("historical-series.json"));
    if (method === "GET" && pathname.endsWith("/api/health"))
      return jsonResponse({ status: "demo" });
    if (method === "POST" && pathname.endsWith("/api/simulate"))
      return handleSimulate(body || {});
    if (method === "POST" && pathname.endsWith("/api/finance"))
      return handleFinance();
    if (method === "POST" && pathname.endsWith("/api/price-path"))
      return handlePricePath();
    if (method === "POST" && pathname.endsWith("/api/forecast-historical"))
      return handleForecastHistorical(body || {});
    if (method === "POST" && pathname.endsWith("/api/forecast"))
      return handleForecast();
    return new Response(JSON.stringify({ detail: "Not found in demo mode" }), { status: 404 });
  }

  window.fetch = async function (input, init) {
    const url = typeof input === "string" ? input : (input && input.url) || "";
    let pathname = url;
    try { pathname = new URL(url, document.baseURI).pathname; } catch (e) {}

    if (!/\/api\//.test(pathname)) return realFetch(input, init);

    // Try the real backend first — but only until one call confirms there is
    // none. After that, route straight to fixtures (no repeated 404 probes).
    if (!demoMode) {
      try {
        const resp = await realFetch(input, init);
        if (resp.ok) return resp;
      } catch (e) { /* no backend — fall through to fixtures */ }
      demoMode = true;
    }

    // Fall back to demo fixtures.
    const method = ((init && init.method) ||
      (typeof input === "object" && input.method) || "GET").toUpperCase();
    let body = null;
    const rawBody = (init && init.body) || (typeof input === "object" && input.body);
    if (rawBody) { try { body = JSON.parse(rawBody); } catch (e) {} }

    try {
      const out = await route(pathname, method, body);
      showBanner();
      return out;
    } catch (e) {
      return new Response(JSON.stringify({ detail: "Demo fixture error: " + e.message }),
        { status: 500, headers: { "Content-Type": "application/json" } });
    }
  };
})();
