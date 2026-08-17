# Housing Policy Simulator

Agent-based simulation of housing market dynamics under different policy regimes. Python backend with a FastAPI server and an HTML/JS frontend.

## Live demo

**[▶ Open the demo](https://gelato1337.github.io/housing-policy-simulator/)** — a static GitHub Pages build.

The simulator is a Python backend, and GitHub Pages only serves static files, so the demo runs in **demo mode**: a small client-side shim ([`frontend/mock-api.js`](frontend/mock-api.js)) serves *precomputed* simulator output. The five presets and the historical-series forecasts are **real, saved runs**; custom sliders, custom policies, and arbitrary finance scenarios need the live backend and are flagged in the demo. A banner explains this on the page.

## Run it for real

The demo is a shop window. To get the fully interactive app — every slider live — run the backend:

```bash
pip install -r requirements.txt   # Python 3.10+
python run.py                     # → http://localhost:8000
```

That's the whole app, no demo mode. To host a public backend (and the **security fix you must apply first**), see **[HOSTING.md](HOSTING.md)**.

## What's in it

- **5,000-household agent model** by default (configurable up to 20,000). Each household has age, income, savings, and a portfolio of properties.
- **Structural policies**: max loan term, LTV cap, construction rate, public housing share, Tokyo-style depreciation.
- **Formula policies**: write a Python expression that adjusts savings each year. Built-ins for progressive multi-home tax and vacancy tax. Custom policies authored at runtime.
- **Five presets**: Baseline, 10-year loan cap, Tokyo (heavy build + depreciation), Vienna (large public housing), Combined.
- **Eight metrics tracked per year**: homeownership rate, % housed, multi-owner %, price-to-income, housing burden, % overburdened, wealth Gini, average property condition.

## Quick start

You need Python 3.10+ and pip.

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Run the server
python run.py

# 3. Open http://localhost:8000 in your browser
```

That's it. The HTML frontend talks to the FastAPI backend over HTTP — both are served by the same process.

## UI organization

The app has five tabs in the left panel:

**Controls** holds everything you need for a single run: preset buttons, all structural sliders, the two built-in tax sliders, a **Buyer pickiness** slider for match acceptance friction, and the Run button. Clicking a preset updates these sliders and shows a diff summary.

**Policies** is the formula editor for built-in taxes (read-only formulas) and custom formula policies.

**Sim settings** holds the world parameters: number of households, properties, years to simulate, random seed. Persist across preset changes.

**Demographics** lets you reshape the initial population — median income, income inequality, age distribution, starting homeownership rate, baseline property price, and how heterogeneous buyer tastes are. Use this to model different cities or eras.

**Parameters** is a cheatsheet for the variables available inside formulas.

## Two tools in one app

This package contains **two separate models** that answer different questions:
1. **Policy simulator** (`/`) — the agent-based model. Population-level, stochastic, emergent. Answers "what happens to society under policy X." This is what most of this README describes.

2. **Decision comparator** (`/finance`) — a deterministic personal-finance projector. Single-agent, no randomness. Answers "what happens to *my* money if I take a 10 vs 40 year loan, or rent and invest vs buy now, or buy a fixer-upper vs move-in-ready." Side-by-side net worth, total interest, and housing cost over a chosen horizon. Tune expected stock return, house appreciation, and rent inflation. **Fair-comparison model:** the "starting capital" field (shown per scenario) is the same liquid wealth every scenario begins with — buying spends it as the down payment with any remainder invested, renting keeps it all invested, so every scenario starts at an identical net worth and the comparison is genuinely apples-to-apples. (An earlier version let "buy now" silently forfeit that capital, making buying look artificially poor; that is fixed and pinned by `test_finance_comparator.py`.)

They're deliberately separate because they need different math. The ABM is the wrong tool for individual decisions (too noisy, too aggregate); the deterministic comparator is the wrong tool for policy (no emergent dynamics). Cross-links between them are in the page headers.

### Variable-rate mortgages

The comparator supports both fixed and variable-rate loans. Variable loans follow a **Euribor path** you specify (a comma-separated list of annual benchmark rates in the sidebar). The borrower's effective rate is `benchmark + margin`, recomputed each year; when it changes, the monthly payment is re-amortized over the *remaining* term — exactly how Finnish annuity mortgages behave. This makes the 2022–2023 squeeze directly visible: lock 2% fixed before a spike vs. ride a variable loan that jumps to 5.5%, and the lifetime net-worth gap on the identical house is roughly €250k. A "Mortgage rate in force" chart shows each scenario's rate over time so the shock is obvious.

### Bull / bear variance

Each comparison can be run as three explicit branches instead of one. **Bull** is the owner-optimistic world: mortgage rates fall, house prices appreciate faster, stock returns are stronger. **Bear** is the mirror image. **Base** is your stated assumptions. The four swing magnitudes are sliders (rate ±, appreciation ±, stock-bull +, stock-bear −) with defaults matching realistic ranges (rates ±1.5pp, appreciation ±3pp, stocks +8 / −12pp around base). These are *deterministic alternate assumptions*, not a probability cloud — chosen deliberately so you can see exactly which lever drives the swing rather than getting an opaque confidence band. The net-worth chart renders a shaded bear→bull band per scenario with a solid base line; the summary table gains bear/base/bull columns plus the spread. The point it makes is uncomfortable and honest: for something like "buy now at a high fixed rate," the bear-to-bull spread can be larger than the entire base net worth — i.e. the decision is dominated by macro variables you do not control, and is closer to a bet than a calculation. Back-compatible: with variance off, the API and UI behave exactly as before.

### Metric glossary (policy simulator)

The Controls tab ends with a "What the metrics mean" glossary defining every dashboard measure (housing burden, % overburdened, homeownership, % housed, price/income, multi-owners, median mortgage debt, wealth Gini), each tagged with its direction (lower-is-better / higher-is-better, with caveats where "better" is genuinely ambiguous — e.g. low homeownership is good in the Vienna/Swiss models). It also explains the >40%-of-disposable-income overburden threshold (Eurostat convention) and how the wealth Gini is computed.

### Bridge: ABM prices → personal decision

The "Pull price path from policy sim" button runs the agent-based model with a baseline policy, extracts its emergent median-price growth path, and feeds it into the comparator as the house-appreciation assumption (replacing the flat slider). This connects the two tools: your buy-vs-wait decision can use simulated market dynamics instead of a guessed appreciation rate. **Caveat, stated in the UI:** this is the path of the *median* simulated home in a synthetic population — your specific house is not the median house, so treat it as a broad-market approximation, not a forecast.

### Swiss interest-only mode and model benchmarks

The comparator has a `swiss_interest_only` scenario kind. You put down a deposit and pay interest *forever* — the principal is never amortized (in Switzerland it transfers on sale or death). Housing cost is just interest plus upkeep, freeing the rest of your budget to invest. The model shows the honest tradeoff: equity never grows from paydown (only appreciation), you pay roughly 2x lifetime interest, but if stock returns beat the mortgage rate the higher invested balance wins on net worth — and if they don't, it loses. It is a leveraged bet on markets, and the tool makes both sides explicit.

Preset comparisons grounded in real housing-system mechanics: "Model: Finland vs Swiss vs rent" (variable-rate amortizing vs Swiss interest-only vs lifetime renting + investing), and "Model: Tokyo vs Vienna logic" (Tokyo's depreciating-building short-amortization logic vs Vienna's lifetime-subsidized-rent logic). These are illustrative parameterizations of each system's incentives, not claims about specific cities' current numbers.

### Bayesian price forecaster (honesty tool)

A structural time-series model (local linear trend + mean-reversion toward an income-based fundamental + AR noise, fit with a particle/ensemble method, numpy+scipy only) takes a historical price series and produces a fan chart. **Its purpose is the opposite of a crystal ball.** House prices are empirically close to a random walk with drift; turning points are not reliably predictable. The model exists to show *how wide the uncertainty genuinely is* — typically the 90% band 15 years out spans 60–70% of today's price. That width is the actionable result: it tells you that betting a life decision on any single price forecast is unwise. The endpoint refuses to run on fewer than 4 data points rather than fabricate a confident-looking line from nothing.

### Vetted real historical series

`backend/finance/historical.py` contains four hand-transcribed real annual *real* (inflation-adjusted) house-price series from authoritative public sources, selectable in the forecast UI and via `/api/forecast-historical`:

- **Japan** ("Tokyo-style") — the textbook bubble: ~9%/yr to the 1991 peak, then ~ −3.2%/yr for almost two decades. Source: OECD Analytical HPD via CEIC; Mumtaz & Šusták (2023).
- **Switzerland** ("Swiss-style") — lowest long-run real growth of 12 advanced economies (~1.1%/yr), defined by recurrent cycles (−27% 1973–77, −36% 1989–97), not trend. Source: Mumtaz & Šusták (2023), OECD.
- **Finland** — worst OECD real performance of the last decade (−13% since 2015 vs OECD +37%), sharp post-2022 slump from Euribor-linked variable mortgages. Source: Statistics Finland, BIS, IMF 2024.
- **Austria** ("Vienna-style" *caveat*) — strong national real growth, but for ~60% of Vienna residents the relevant series is a regulated *rent*, not this owner-price index; this is stated in the series note rather than faked into the numbers. Source: OECD Analytical HPD.

These are transcribed at ~5-year resolution with key turning-point years added, accurate to within a few index points — enough to show each market's *character* when fed to the forecaster. They are not a substitute for the full quarterly OECD series; the code sandbox cannot reach the OECD API directly, so the figures were sourced via web lookup of the published statistics and documented inline with their provenance. Feeding them to the forecaster is itself illuminating: Japan and Switzerland produce ~2.4–2.5× uncertainty bands (their histories contain crashes, so the honest model refuses to be confident), while Austria's smoother history yields the tightest band — still wide. The lesson the tool delivers is that for the boom-bust markets, no point forecast is meaningful at all.

## Price feedback (important fix)

Earlier versions had a correctness bug: property prices only responded to headcount supply/demand pressure and ignored credit conditions. They now anchor to **median purchasing power** — what the median qualified buyer can borrow (given rate, term, LTV) plus their down payment. When mortgage rates rise, max purchase price falls for everyone and prices are pulled down toward the new clearing level, with a sticky ±15%/year adjustment cap (housing reprices slowly, especially downward).

Consequence: the model now demonstrates the core thesis from housing economics. Longer loan terms don't make housing more affordable — they let buyers bid more, which gets capitalized into higher prices. In the simulation, 35-year loans produce a price-to-income ratio roughly 2x that of 10-year loans, holding everything else equal. Raising the mortgage rate from 1% to 10% roughly halves median prices.

## What gets measured

The headline metric is **housing burden as percentage of disposable income**. The simulation:

1. Computes disposable income as ~70% of gross income (rough Finnish tax+SSI average)
2. Tracks real mortgages with declining balances — owner-occupiers pay actual amortizing payments, not a flat 1.5%
3. Counts upkeep + property tax for owner-occupiers (~2% of value if paid off, ~0.8% if mortgaged)
4. Renters pay 5% yield on their unit's value as rent (3% if it's public housing)

Burden is **housing_cost / disposable_income** for each household, then the median is reported. The threshold for "overburdened" follows the Eurostat convention: >40% of disposable income going to housing. Baseline Finnish reality is around 20-25% for the median owner-occupier with mortgage; the simulation now produces numbers in this range.

The interesting consequence: with mortgages active, you can now see the real cost of long loans. 35-year loans roughly double the rate of severely-overburdened households compared to 10-year loans, because they let more marginal borrowers in at the price of a heavier ongoing burden for everyone in the system.



## Performance

A 2,000-household 50-year run takes ~0.7s on the API. The simulation engine uses a sorted-and-marked matching loop in the marketplace phase (O(N+M) per year instead of O(N*M)) and caches initial world states by (N, M, seed) so repeated runs with the same world size start from a memoized initial state. Larger worlds (5,000+) take ~2-3s. The browser UI shows "Running..." status while waiting.

## Architecture

```
housing_sim_py/
├── backend/
│   ├── simulator/          ← pure-Python simulation engine
│   │   ├── agents.py       ← Household, Property, World dataclasses
│   │   ├── world.py        ← init_world() — sets up initial state
│   │   ├── step.py         ← one-year simulation step in named phases
│   │   ├── policies.py     ← PolicyConfig + FormulaPolicy + templates
│   │   ├── metrics.py      ← compute_metrics() returns per-year stats
│   │   └── runner.py       ← run_simulation() — top-level loop
│   └── api/
│       └── main.py         ← FastAPI app: /api/simulate, /api/presets, /api/templates
├── frontend/
│   ├── index.html          ← single-page UI
│   ├── styles.css
│   └── app.js              ← talks to /api/simulate
├── notebooks/
│   └── explore.py          ← batch sweeps + plotting (Jupytext format)
├── tests/
│   └── test_simulator.py   ← unit tests
└── run.py                  ← single command to start the server
```

## Run options

### Web app (default)
```bash
python run.py
```
Serves the frontend at `http://localhost:8000` and the API at `http://localhost:8000/api/*`.

### API only
```bash
uvicorn backend.api.main:app --reload --port 8000
```

### Notebook / Python
```python
import sys
sys.path.append("backend")
from simulator import PolicyConfig, run_simulation, FormulaPolicy

cfg = PolicyConfig(
    max_loan_years=10,
    construction_rate=0.03,
    formula_policies=[
        FormulaPolicy("LVT", "-p.land_value * 0.01", per_prop=True),
    ],
)
history = run_simulation(cfg, years=50)
print(history[-1])
```

### Tests

The suite lives in `tests/` and has three files (54 tests total). Run everything:

```bash
cd housing_sim_py
python -m pytest tests/
```

Run one file, or one test, verbosely:

```bash
python -m pytest tests/test_benchmarks.py -v          # Tokyo/Vienna/Swiss validation
python -m pytest tests/test_finance_comparator.py -v  # personal comparator
python -m pytest tests/test_simulator.py -v           # ABM engine + API
python -m pytest tests/test_finance_comparator.py::test_swiss_wins_iff_stocks_beat_mortgage -v
```

If `pytest` isn't found, install the dev deps first: `pip install pytest fastapi uvicorn pydantic numpy scipy` (or `pip install -r requirements.txt`).

What each file covers:

- **`tests/test_simulator.py`** (30 tests) — the agent-based engine and the API: world init, formula policies, the price-feedback fix, mortgage tracking, variable rates, the bull/bear variance branches, the Bayesian forecaster, and the historical-series endpoints.
- **`tests/test_benchmarks.py`** (10 tests) — quantified validation that the Tokyo and Vienna presets reproduce their archetypes' *affordability character*, plus honesty guards that pin the known deviations (Tokyo has no bubble; Vienna's tenure mix isn't reproduced; there is deliberately no Swiss ABM preset) so they can't silently change.
- **`tests/test_finance_comparator.py`** (24 tests) — the personal comparator: the fair-comparison invariant (all scenarios start from identical net worth), rent-then-buy actually deploying its pot, rent-forever genuinely charging rent, Swiss economics, variable-rate transmission, real-terms deflation, and determinism.

### Benchmark report

For a plain-language, numbers-first assessment of how closely each preset matches its real-world archetype (and exactly where the analogy breaks):

```bash
python tests/report_benchmarks.py
```

This prints a comparison table plus a per-archetype verdict and the honest gap for each.

## How to extend

### Add a new metric

Edit `backend/simulator/metrics.py`. Add a key to the dict returned by `compute_metrics()`. The frontend's `app.js` reads metrics by key, so add a new metric card and chart there if you want it surfaced.

### Add a new formula policy template

Edit `backend/simulator/policies.py`. Add an entry to `POLICY_TEMPLATES`. It will automatically appear in the UI's template links.

### Add a new structural policy

This is the most involved kind of change because structural policies shape the marketplace mechanism, not just savings.

1. Add a field to `PolicyConfig` in `backend/simulator/policies.py`.
2. Add a phase function in `backend/simulator/step.py` (or modify an existing one) that reads your config field.
3. Call your phase from `step()` at the right point.
4. Expose a slider in `BUILT_IN` in `frontend/app.js`.
5. Add a corresponding field to `SimulationRequest` in `backend/api/main.py`.
6. Map it into `PolicyConfig` in the `simulate` endpoint.

### Calibrate against real data

The income distribution, property prices, and demographic parameters in `world.py` are illustrative defaults. To map this to a real city:

- Replace the lognormal income distribution with real household income data (e.g. from Statistics Finland / Tilastokeskus' `kotitalouksien_tulot` table).
- Adjust `base_price` and `land_fraction` to match observed average home prices and land-value ratios for the target city.
- Adjust `initial_owner_share` to match the city's actual homeownership rate.

## Caveats

The model is intentionally simplified. Things it does **not** do well, or at all:

- No geographic differentiation between regions, cities, or neighbourhoods, and no migration. This is the single biggest realism gap (a national average hides that Helsinki and depopulating Kainuu behave oppositely).
- No bank-side risk management — banks always lend up to their stress-test cap; in reality credit standards tighten in downturns.
- No construction-cost feedback — new builds are always base price × quality.
- Rental contracts reset every year (no leases, no rent control mechanics beyond the public-housing yield).
- No political-economy feedback (the "homevoter" dynamic is discussed as design rationale but homeowners don't actually vote against construction in the model).
- The ABM's absolute price-to-income level is sensitive to the income-drift parameter; treat ABM cross-scenario *comparisons* as robust and absolute levels as indicative only.
- The finance comparator's fixed-rate scenarios assume one rate for the loan's life; only the explicitly "variable" scenarios respond to the Euribor path.
- The historical series are ~5-year-resolution transcriptions, not full quarterly data (see references below for why, and exactly what was used).

These are honest limitations, not hidden ones — each is surfaced in the relevant part of the UI or docs.

## References, data sources, and provenance

This project mixes (a) real data I retrieved this session, (b) standard housing-economics logic the model is designed to be *consistent with*, and (c) software libraries. I have tried to be exact about which is which. In particular: where a canonical paper is cited for a *mechanism*, that means the model's design rationale follows the well-established idea from that literature — it does **not** mean the code is a faithful numerical reimplementation of that paper.

### A. Empirical data actually retrieved and used

These figures were obtained via web search this session (the code sandbox cannot reach statistical-agency APIs directly) and hand-transcribed into `backend/finance/historical.py`, which also documents provenance inline. Used by: the Bayesian forecaster's "real-world series" feature and the `/api/forecast-historical` endpoint.

- **Japan — national real house price index.** Anchor points (1991 peak ≈ 165.8, 2024 ≈ 116.4, 1960 ≈ 30.1, 2015=100): OECD Analytical House Price Database, accessed via CEIC's republication of the OECD series ("Japan — House Price Index: Seasonally Adjusted: OECD Member: Annual", ceicdata.com). Long-run shape (≈9%/yr to 1991, then ≈ −3.2%/yr to 2009): Mumtaz & Šusták, "Global house prices since 1950" (CFM Discussion Paper CFMDP2023-07 / Keio IES working paper, 2023).
- **Switzerland — national real house price index.** Defining facts (lowest long-run real growth of 12 advanced economies ≈1.1%/yr; 2019 ≈ 1989 level; peak-to-trough −27% in 1973–77 and −36% in 1989–97): Mumtaz & Šusták (2023), corroborated by the OECD Analytical House Price Database.
- **Finland — national real house price index.** Recent trajectory (real prices ≈ −13% since 2015 vs OECD +37%; sharpest fall since mid-2022; Euribor-linked variable-mortgage mechanism; ≈ −20%+ in some depopulating regions): IMF analysis as reported by Helsingin Sanomat / Helsinki Times (Dec 2024); Statistics Finland real house price index (2010=100, ≈92 in 2022) via Statista's republication; BIS Residential Property Price statistics (nominal, Finland, peak Q2 2022 ≈121.2, ≈108 by Q3 2024) via CEIC.
- **Austria — national real house price index.** Post-2005 real growth shape: OECD Analytical House Price Database. The "Vienna-style" label is explicitly *not* a Vienna price series — the note in the data file flags that ~60% of Vienna residents are in municipal/limited-profit regulated housing, so the relevant series for them is a regulated rent, not this owner-price index.
- **Current Finnish market context** used in conversation and to sanity-check defaults (≈2.8% average new-mortgage rate, 12-month Euribor the dominant reference rate, ECB on hold with the deposit facility rate at 2.00% as of mid-2025, ~36% of households renting in 2024): Global Property Guide "Finland Residential Property Market Analysis 2026"; the IMF/HS coverage above.

General reference databases consulted for cross-country context (not transcribed point-by-point): OECD Affordable Housing Database (indicator HM1.2, "Housing prices"); OECD House Price Tracker; OECD Analytical House Price Database (data-explorer.oecd.org); BIS Residential Property Price statistics.

### B. Economic logic and the literature it follows

The model implements standard housing-economics mechanisms. The code is original; the *ideas* are from this well-established literature:

- **Cheap/long credit gets capitalised into prices rather than improving affordability** (the central thesis behind the price-feedback fix and the long-loan-inflates-prices result). Standard references: Knoll, Schularick & Steger, "No Price Like Home: Global House Prices, 1870–2012" (American Economic Review, 2017) for the long-run land-scarcity "hockey stick"; Jordà, Schularick & Taylor, "Betting the House" (Journal of International Economics, 2015) and their broader Macrofinancial History work for the credit↔house-price link. Implemented in `simulator/step.py::phase_price_drift` as a purchasing-power anchor.
- **Search-and-matching frictions in housing** (the `match_pickiness` mechanism: finite viewings, probabilistic acceptance, price-stretch and taste-fit penalties). Design rationale follows the Diamond–Mortensen–Pissarides search framework as adapted to housing by Wheaton (1990, "Vacancy, Search, and Prices in a Housing Market Matching Model", JPE) and Genesove & Han (2012, "Search and matching in the housing market", JUE). Implemented in `simulator/step.py::phase_marketplace`.
- **Hedonic heterogeneity of preferences** (each household's `quality_preference`). Follows Rosen (1974, "Hedonic Prices and Implicit Markets", JPE).
- **Asymmetric/sticky downward price adjustment** (the ±15%/yr clamp and slow transmission of rate shocks). Consistent with Genesove & Mayer (2001, "Loss Aversion and Seller Behavior: Evidence from the Housing Market", QJE) and the broad downward-stickiness literature.
- **Price-to-income mean reversion as the fundamental anchor** in the Bayesian forecaster. Follows the long-standing finding that real house prices revert toward income-based fundamentals over long horizons (e.g. Gallin 2006, "The Long-Run Relationship Between House Prices and Income", Real Estate Economics) and the random-walk-with-drift characterisation that motivates the model's deliberately wide bands (Case & Shiller's work on housing predictability; Mumtaz & Šusták 2023 for the expectations-driven volatility view).
- **The "homevoter" political-economy intuition** (discussed as design rationale for why supply is politically constrained, not coded as a feedback): Fischel, *The Homevoter Hypothesis* (2001).
- **System-level stylised models** referenced in conversation as the inspiration for the named presets: the Tokyo supply-liberalisation / building-depreciation account, the Vienna social-housing model, and the Swiss interest-only/rent-dominant model. These presets are illustrative parameterisations of each system's *incentive structure*, grounded in the OECD/Mumtaz–Šusták data above, not claims about any city's current point values.

### C. Software and libraries

- **Python 3**, standard library.
- **NumPy** and **SciPy** — numerics; the Bayesian forecaster's particle/ensemble filter in `backend/finance/forecast.py` is built on these only (no PPL dependency).
- **FastAPI** + **Uvicorn** — the API/server in `backend/api/main.py`.
- **Pydantic** — request/response schemas.
- **pytest** — the 27-test suite in `tests/`.
- **Chart.js** (via CDN) — all frontend charts.
- The agent-based model, the deterministic finance comparator, the formula-policy DSL, and the Bayesian forecaster are original implementations written for this project.

### D. Honest statement on AI authorship

This codebase was written collaboratively with an AI assistant (Claude) over an iterative session. The economic mechanisms were chosen to be consistent with the literature in section B, but the assistant did not read those papers during this session — they are cited because they are the canonical sources for ideas that are standard knowledge in housing economics, and a reader should go to them rather than treat this tool as authoritative. The only sources actually read this session are the web-retrieved data sources in section A.

## License

This is a personal exploration tool. Use it however you want.
