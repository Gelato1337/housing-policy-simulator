"""
FastAPI server exposing the simulator.

Endpoints:
  GET  /api/health                  — liveness
  GET  /api/presets                 — preset configurations
  GET  /api/templates               — custom-policy templates
  POST /api/simulate                — run a simulation, return per-year metrics

The frontend posts a SimulationRequest and gets back a SimulationResponse
with the full history. Tiny payload, no streaming needed at our scale.
"""
from __future__ import annotations

import sys
import os
from typing import Any, Dict, List, Optional

# Make the simulator package importable when running this from the api/ dir.
THIS_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.dirname(THIS_DIR)
sys.path.insert(0, BACKEND_DIR)

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from simulator import (
    Demographics,
    FormulaPolicy,
    POLICY_TEMPLATES,
    PRESETS,
    PolicyConfig,
    progressive_multi_home_tax,
    run_simulation,
    vacancy_tax,
)


# ---------------------------------------------------------------------------
# Request/response schemas
# ---------------------------------------------------------------------------

class FormulaPolicySpec(BaseModel):
    """Spec for a single formula policy in a simulation request."""
    name: str
    formula: str
    slider_value: float = 100.0
    per_prop: bool = True
    enabled: bool = True


class DemographicsSpec(BaseModel):
    """Distribution parameters for the initial population."""
    income_log_mu: float = Field(10.6, ge=9.0, le=12.0)
    income_log_sigma: float = Field(0.4, ge=0.1, le=1.0)
    age_mean: float = Field(45.0, ge=25.0, le=65.0)
    age_sd: float = Field(15.0, ge=5.0, le=25.0)
    base_price: float = Field(180_000.0, ge=50_000.0, le=500_000.0)
    initial_owner_share: float = Field(0.60, ge=0.1, le=0.95)
    quality_pref_spread: float = Field(0.25, ge=0.0, le=0.6)


class SimulationRequest(BaseModel):
    # Structural policies
    max_loan_years: int = Field(25, ge=1, le=50)
    max_ltv: float = Field(0.90, ge=0.5, le=1.0)
    mortgage_rate: float = Field(0.030, ge=0.0, le=0.15)
    construction_rate: float = Field(0.005, ge=0, le=0.1)
    public_share: float = Field(0.0, ge=0, le=1.0)
    depreciation: bool = False

    # Match-acceptance friction
    match_pickiness: float = Field(0.0, ge=0.0, le=1.0)

    # World size
    years: int = Field(50, ge=1, le=200)
    n_households: int = Field(2000, ge=100, le=20000)
    n_properties: int = Field(1800, ge=100, le=20000)
    seed: int = Field(42, ge=1, le=10000)

    # Built-in formula policies via sliders
    multi_home_tax: float = 0.0
    vacancy_tax: float = 0.0

    # Custom formula policies
    custom_policies: List[FormulaPolicySpec] = Field(default_factory=list)

    # Demographics (optional; defaults applied if omitted)
    demographics: Optional[DemographicsSpec] = None


class CompileError(BaseModel):
    policy_name: str
    error: str


class SimulationResponse(BaseModel):
    history: List[Dict[str, float]]
    compile_errors: List[CompileError] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="Housing Policy Simulator API", version="1.0.0")

# CORS is open by default so the frontend can be served from anywhere
# (file://, a different port, etc.). Tighten in production.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.get("/api/presets")
def get_presets() -> Dict[str, Dict]:
    return PRESETS


@app.get("/api/templates")
def get_templates() -> Dict[str, Dict]:
    return POLICY_TEMPLATES


@app.post("/api/simulate", response_model=SimulationResponse)
def simulate(req: SimulationRequest) -> SimulationResponse:
    # Build the formula policies list
    formulas = []
    compile_errors: List[CompileError] = []

    # Built-in tax policies
    if req.multi_home_tax > 0:
        formulas.append(progressive_multi_home_tax(req.multi_home_tax))
    if req.vacancy_tax > 0:
        formulas.append(vacancy_tax(req.vacancy_tax))

    # Custom policies — compile each and capture errors
    for spec in req.custom_policies:
        pol = FormulaPolicy(
            name=spec.name,
            formula=spec.formula,
            slider_value=spec.slider_value,
            per_prop=spec.per_prop,
            enabled=spec.enabled,
        )
        if pol.error:
            compile_errors.append(CompileError(policy_name=spec.name, error=pol.error))
        formulas.append(pol)

    cfg = PolicyConfig(
        max_loan_years=req.max_loan_years,
        max_ltv=req.max_ltv,
        mortgage_rate=req.mortgage_rate,
        construction_rate=req.construction_rate,
        public_share=req.public_share,
        depreciation=req.depreciation,
        match_pickiness=req.match_pickiness,
        formula_policies=formulas,
    )

    # Optional demographics override
    demographics = None
    if req.demographics is not None:
        d = req.demographics
        demographics = Demographics(
            income_log_mu=d.income_log_mu,
            income_log_sigma=d.income_log_sigma,
            age_mean=d.age_mean,
            age_sd=d.age_sd,
            base_price=d.base_price,
            initial_owner_share=d.initial_owner_share,
            quality_pref_spread=d.quality_pref_spread,
        )

    try:
        history = run_simulation(
            cfg,
            years=req.years,
            n_households=req.n_households,
            n_properties=req.n_properties,
            seed=req.seed,
            demographics=demographics,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Simulation failed: {e}")

    return SimulationResponse(history=history, compile_errors=compile_errors)


# ---------------------------------------------------------------------------
# Personal-finance scenario comparator (separate deterministic tool)
# ---------------------------------------------------------------------------

from finance import (Assumptions, Scenario, VarianceConfig,
                     compare as finance_compare)


class AssumptionsSpec(BaseModel):
    horizon_years: int = Field(30, ge=1, le=60)
    stock_return: float = Field(0.07, ge=-0.05, le=0.20)
    house_appreciation: float = Field(0.02, ge=-0.05, le=0.15)
    rent_inflation: float = Field(0.02, ge=0.0, le=0.10)
    general_inflation: float = Field(0.02, ge=0.0, le=0.10)
    income: float = Field(45_000.0, ge=10_000, le=500_000)
    monthly_budget: float = Field(1_800.0, ge=200, le=20_000)
    real_terms: bool = False
    # Benchmark (Euribor) path: one rate per year. Empty = flat 2.5%.
    benchmark_path: List[float] = Field(default_factory=list)
    # Optional per-year house appreciation path (e.g. from /api/price-path).
    appreciation_path: List[float] = Field(default_factory=list)


class VarianceSpec(BaseModel):
    enabled: bool = False
    rate_delta: float = Field(0.015, ge=0.0, le=0.08)
    appreciation_delta: float = Field(0.03, ge=0.0, le=0.10)
    stock_delta_bull: float = Field(0.08, ge=0.0, le=0.20)
    stock_delta_bear: float = Field(0.12, ge=0.0, le=0.25)


class ScenarioSpec(BaseModel):
    name: str
    kind: str = Field("buy_now")  # buy_now | rent_then_buy | rent_forever
    home_price: float = Field(250_000.0, ge=10_000, le=5_000_000)
    down_payment: float = Field(50_000.0, ge=0, le=5_000_000)
    loan_years: int = Field(25, ge=1, le=50)
    rate_type: str = Field("fixed")  # fixed | variable
    mortgage_rate: float = Field(0.030, ge=0.0, le=0.20)
    margin: float = Field(0.010, ge=0.0, le=0.10)
    wait_years: int = Field(0, ge=0, le=30)
    monthly_rent: float = Field(0.0, ge=0, le=20_000)
    reno_total: float = Field(0.0, ge=0, le=2_000_000)
    reno_years: int = Field(0, ge=0, le=30)
    upkeep_rate: float = Field(0.015, ge=0.0, le=0.10)


class FinanceRequest(BaseModel):
    assumptions: AssumptionsSpec
    scenarios: List[ScenarioSpec]
    variance: Optional[VarianceSpec] = None


@app.post("/api/finance")
def finance(req: FinanceRequest) -> Dict:
    a = Assumptions(
        horizon_years=req.assumptions.horizon_years,
        stock_return=req.assumptions.stock_return,
        house_appreciation=req.assumptions.house_appreciation,
        rent_inflation=req.assumptions.rent_inflation,
        general_inflation=req.assumptions.general_inflation,
        income=req.assumptions.income,
        monthly_budget=req.assumptions.monthly_budget,
        real_terms=req.assumptions.real_terms,
        benchmark_path=list(req.assumptions.benchmark_path),
        appreciation_path=list(req.assumptions.appreciation_path),
    )
    scenarios = [
        Scenario(
            name=s.name, kind=s.kind, home_price=s.home_price,
            down_payment=s.down_payment, loan_years=s.loan_years,
            rate_type=s.rate_type, mortgage_rate=s.mortgage_rate,
            margin=s.margin, wait_years=s.wait_years,
            monthly_rent=s.monthly_rent, reno_total=s.reno_total,
            reno_years=s.reno_years, upkeep_rate=s.upkeep_rate,
        )
        for s in req.scenarios
    ]
    variance = None
    if req.variance is not None:
        variance = VarianceConfig(
            enabled=req.variance.enabled,
            rate_delta=req.variance.rate_delta,
            appreciation_delta=req.variance.appreciation_delta,
            stock_delta_bull=req.variance.stock_delta_bull,
            stock_delta_bear=req.variance.stock_delta_bear,
        )
    try:
        return finance_compare(scenarios, a, variance)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Finance projection failed: {e}")


class PricePathRequest(BaseModel):
    """Run the ABM with given policy and return its median price growth path.

    This bridges the two tools: the agent-based simulator produces an
    emergent market price trajectory, which can be fed into the personal
    comparator as a house_appreciation path instead of a flat assumption.

    IMPORTANT: this is the path of the *median* simulated home in a synthetic
    population. An individual property is not the median property, so treat
    this as "what if prices broadly follow the simulated market" — an
    informed approximation, not a forecast for one specific house.
    """
    max_loan_years: int = 25
    max_ltv: float = 0.90
    mortgage_rate: float = 0.030
    construction_rate: float = 0.005
    public_share: float = 0.0
    depreciation: bool = False
    years: int = Field(30, ge=2, le=80)
    seed: int = 42


@app.post("/api/price-path")
def price_path(req: PricePathRequest) -> Dict:
    cfg = PolicyConfig(
        max_loan_years=req.max_loan_years,
        max_ltv=req.max_ltv,
        mortgage_rate=req.mortgage_rate,
        construction_rate=req.construction_rate,
        public_share=req.public_share,
        depreciation=req.depreciation,
        formula_policies=[],
    )
    try:
        history = run_simulation(
            cfg, years=req.years,
            n_households=1500, n_properties=1350, seed=req.seed,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Simulation failed: {e}")

    prices = [h["median_price"] for h in history]
    # Year-over-year growth rates (one per year, from year 1 onward)
    growth = []
    for i in range(1, len(prices)):
        prev = prices[i - 1] if prices[i - 1] > 0 else 1.0
        growth.append(round((prices[i] - prev) / prev, 5))

    return {
        "median_price": [round(p, 2) for p in prices],
        "appreciation_path": growth,
        "note": ("Median simulated home price growth. An individual home is "
                 "not the median home; treat as a broad-market approximation."),
    }


class ForecastRequest(BaseModel):
    """Bayesian structural time-series forecast from a price history.

    The point is NOT a precise prediction — it's an honest uncertainty band.
    """
    history: List[float]
    income_history: Optional[List[float]] = None
    horizon: int = Field(15, ge=1, le=40)
    pti_anchor: float = Field(5.0, ge=1.0, le=15.0)
    seed: int = 0


@app.post("/api/forecast")
def forecast(req: ForecastRequest) -> Dict:
    from finance import forecast_prices
    try:
        return forecast_prices(
            history=req.history,
            income_history=req.income_history,
            horizon=req.horizon,
            pti_anchor=req.pti_anchor,
            seed=req.seed,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Forecast failed: {e}")


@app.get("/api/historical-series")
def historical_series() -> Dict:
    """Catalogue of vetted real-world price series available for forecasting."""
    from finance import list_series
    return {"series": list_series()}


class HistoricalForecastRequest(BaseModel):
    key: str                       # japan | switzerland | finland | austria
    horizon: int = Field(10, ge=1, le=40)
    pti_anchor: float = Field(5.0, ge=1.0, le=15.0)
    seed: int = 0


@app.post("/api/forecast-historical")
def forecast_historical(req: HistoricalForecastRequest) -> Dict:
    """Run the Bayesian forecaster on a vetted real historical series."""
    from finance import forecast_prices, get_series
    try:
        s = get_series(req.key)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    try:
        result = forecast_prices(
            history=[float(x) for x in s["index"]],
            income_history=None,
            horizon=req.horizon,
            pti_anchor=req.pti_anchor,
            seed=req.seed,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Forecast failed: {e}")
    # Attach provenance so the UI can show the user what they're looking at
    result["series_label"] = s["label"]
    result["series_years"] = s["years"]
    result["series_note"] = s["note"]
    result["series_source"] = s["source"]
    return result


# ---------------------------------------------------------------------------
# Static frontend (optional, served alongside the API)
# ---------------------------------------------------------------------------
# Project layout:
#   <root>/backend/api/main.py   <-- this file
#   <root>/frontend/index.html
#   <root>/frontend/app.js
#   <root>/frontend/styles.css
#
# We serve index.html at "/" and the JS/CSS assets at "/static/<file>".
PROJECT_ROOT = os.path.dirname(BACKEND_DIR)
FRONTEND_DIR = os.path.join(PROJECT_ROOT, "frontend")

if os.path.isdir(FRONTEND_DIR):
    from fastapi.responses import HTMLResponse, Response as _Resp
    import mimetypes as _mime

    _NOSTORE = {
        "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
        "Pragma": "no-cache",
        "Expires": "0",
    }

    # Defeat conditional requests entirely. FileResponse/StaticFiles emit an
    # ETag + Last-Modified, so a browser revalidates with If-None-Match and
    # the server answers "304 Not Modified" — the browser then keeps its
    # STALE copy and you never see code changes. We strip those request
    # headers on the way in and never emit validators on the way out, so a
    # full 200 with fresh bytes is returned every time. These files are a
    # few KB; there is no cost to never caching them.
    @app.middleware("http")
    async def _no_store(request, call_next):
        # Strip conditional-request headers at the ASGI scope level so no
        # handler can answer "304 Not Modified" and let the browser keep a
        # stale copy. scope["headers"] is a list of (bytes, bytes) tuples.
        try:
            drop = (b"if-none-match", b"if-modified-since")
            request.scope["headers"] = [
                (k, v) for (k, v) in request.scope["headers"]
                if k.lower() not in drop
            ]
        except Exception:
            pass
        response = await call_next(request)
        path = request.url.path
        if path.startswith("/static") or path in ("/", "/finance"):
            for k, v in _NOSTORE.items():
                response.headers[k] = v
            if "etag" in response.headers:
                del response.headers["etag"]
            if "last-modified" in response.headers:
                del response.headers["last-modified"]
        return response

    def _serve(filename: str):
        full = os.path.join(FRONTEND_DIR, filename)
        with open(full, "rb") as fh:
            data = fh.read()
        ctype = _mime.guess_type(full)[0] or "application/octet-stream"
        return _Resp(content=data, media_type=ctype, headers=dict(_NOSTORE))

    @app.get("/")
    def root():
        return _serve("index.html")

    @app.get("/finance")
    def finance_page():
        return _serve("finance.html")

    # Serve static assets ourselves (no ETag/Last-Modified, always 200).
    @app.get("/static/{asset:path}")
    def static_asset(asset: str):
        # Prevent path traversal; only serve files that exist in FRONTEND_DIR.
        safe = os.path.normpath(asset).lstrip("/\\")
        if safe.startswith("..") or os.path.isabs(safe):
            raise HTTPException(status_code=404, detail="Not found")
        full = os.path.join(FRONTEND_DIR, safe)
        if not os.path.isfile(full):
            raise HTTPException(status_code=404, detail="Not found")
        with open(full, "rb") as fh:
            data = fh.read()
        ctype = _mime.guess_type(full)[0] or "application/octet-stream"
        return _Resp(content=data, media_type=ctype, headers=dict(_NOSTORE))
