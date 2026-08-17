"""
Bayesian structural time-series forecaster for house prices.

PURPOSE AND HONEST CAVEAT
-------------------------
House price forecasting is genuinely hard. The empirical consensus is that
real house prices behave like a random walk with drift plus slow reversion
to an income-based fundamental; turning points are essentially unpredictable.
This module does NOT pretend to predict the future. Its value is the
opposite: it shows how WIDE the uncertainty must honestly be. A point
forecast of house prices 10 years out is close to meaningless; a fan chart
that says "somewhere between -30% and +70% with 80% probability" is honest
and is itself useful information for a decision-maker.

MODEL
-----
We model log-price with a local-linear-trend + mean-reversion-to-fundamental
+ AR(1) noise structure:

    fundamental_t = log(income_t * pti_anchor)              # what income supports
    level_t       = level_{t-1} + trend_{t-1}
                    + kappa * (fundamental_t - level_{t-1})  # reversion pull
                    + eps_level
    trend_t       = phi * trend_{t-1} + eps_trend
    observed_t    = level_t + eps_obs

Parameters (kappa, phi, the three noise scales) are given priors and the
posterior is approximated with a simple ensemble/particle method (no heavy
PPL dependency). We then draw posterior-predictive future paths and report
quantiles.

INPUTS
------
- history: list of observed prices (any length >= 4), oldest first
- income_history: optional matching incomes; if absent, a flat income is
  assumed and the fundamental anchor degrades to a constant (pure trend+AR)
- horizon: years to forecast
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np


@dataclass
class ForecastConfig:
    horizon: int = 15
    n_particles: int = 4000
    pti_anchor: float = 5.0          # price-to-income level prices revert to
    seed: int = 0
    # Priors (means) — kept deliberately broad to reflect genuine ignorance
    kappa_prior_mean: float = 0.10   # reversion speed toward fundamental/yr
    kappa_prior_sd: float = 0.08
    phi_prior_mean: float = 0.70     # trend persistence
    phi_prior_sd: float = 0.20


def _fit_and_forecast(
    prices: np.ndarray,
    incomes: Optional[np.ndarray],
    cfg: ForecastConfig,
) -> Dict:
    rng = np.random.default_rng(cfg.seed)
    n = len(prices)
    log_p = np.log(prices)

    # Fundamental (log) anchor. If we have incomes, anchor = log(income*pti).
    # Otherwise anchor is a constant = mean of observed log price (so the
    # model degrades gracefully to trend + AR with mild reversion to mean).
    if incomes is not None and len(incomes) == n:
        log_fund = np.log(np.maximum(incomes, 1.0) * cfg.pti_anchor)
        # Extend the fundamental into the future by extrapolating income
        # growth (geometric mean of historical income growth).
        if n >= 2:
            inc_growth = (incomes[-1] / max(incomes[0], 1.0)) ** (1.0 / (n - 1))
        else:
            inc_growth = 1.0
        future_income = [incomes[-1] * (inc_growth ** k)
                         for k in range(1, cfg.horizon + 1)]
        future_fund = np.log(np.array(future_income) * cfg.pti_anchor)
    else:
        const = float(np.mean(log_p))
        log_fund = np.full(n, const)
        future_fund = np.full(cfg.horizon, const)

    # Rough empirical scales for the noise priors from the data itself.
    diffs = np.diff(log_p)
    base_sigma = float(np.std(diffs)) if len(diffs) > 1 else 0.05
    base_sigma = max(base_sigma, 0.01)

    P = cfg.n_particles

    # Sample parameters from priors (truncated to sane ranges).
    kappa = np.clip(rng.normal(cfg.kappa_prior_mean, cfg.kappa_prior_sd, P),
                    0.0, 0.6)
    phi = np.clip(rng.normal(cfg.phi_prior_mean, cfg.phi_prior_sd, P),
                  -0.2, 0.98)
    sig_level = np.abs(rng.normal(base_sigma, base_sigma * 0.5, P)) + 1e-4
    sig_trend = np.abs(rng.normal(base_sigma * 0.5, base_sigma * 0.3, P)) + 1e-4
    sig_obs = np.abs(rng.normal(base_sigma * 0.5, base_sigma * 0.3, P)) + 1e-4

    # Run each particle's state filter over the observed history to get a
    # likelihood weight (how well these params explain the data), plus the
    # end-state (level, trend) to seed forecasting.
    level = np.full(P, log_p[0])
    trend = np.zeros(P)
    loglik = np.zeros(P)

    for t in range(1, n):
        pull = kappa * (log_fund[t] - level)
        level_pred = level + trend + pull
        trend_pred = phi * trend
        # Observation likelihood under Gaussian obs noise + level noise
        pred_var = sig_level ** 2 + sig_obs ** 2
        resid = log_p[t] - level_pred
        loglik += -0.5 * (resid ** 2 / pred_var) - 0.5 * np.log(2 * np.pi * pred_var)
        # Update state toward the observation (simple Kalman-ish gain)
        gain = sig_level ** 2 / pred_var
        level = level_pred + gain * resid
        trend = trend_pred + 0.5 * gain * (resid)  # let trend absorb some signal

    # Convert log-likelihood to normalized weights (stabilised).
    loglik -= loglik.max()
    w = np.exp(loglik)
    w_sum = w.sum()
    if not np.isfinite(w_sum) or w_sum <= 0:
        w = np.ones(P) / P
    else:
        w = w / w_sum

    # Resample particles by weight to get the posterior ensemble.
    idx = rng.choice(P, size=P, replace=True, p=w)
    level_e = level[idx]
    trend_e = trend[idx]
    kappa_e = kappa[idx]
    phi_e = phi[idx]
    sl_e = sig_level[idx]
    st_e = sig_trend[idx]
    so_e = sig_obs[idx]

    # Forecast forward: propagate each particle with its own noise draws.
    paths = np.zeros((P, cfg.horizon))
    lvl = level_e.copy()
    trd = trend_e.copy()
    for h in range(cfg.horizon):
        pull = kappa_e * (future_fund[h] - lvl)
        lvl = (lvl + trd + pull
               + rng.normal(0.0, 1.0, P) * sl_e)
        trd = phi_e * trd + rng.normal(0.0, 1.0, P) * st_e
        obs = lvl + rng.normal(0.0, 1.0, P) * so_e
        paths[:, h] = np.exp(obs)

    # Quantiles for the fan chart.
    qs = [5, 20, 50, 80, 95]
    quant = {q: np.percentile(paths, q, axis=0).tolist() for q in qs}

    # Posterior parameter summaries (for an honesty panel).
    param_summary = {
        "reversion_kappa": {
            "median": float(np.median(kappa_e)),
            "p05": float(np.percentile(kappa_e, 5)),
            "p95": float(np.percentile(kappa_e, 95)),
        },
        "trend_persistence_phi": {
            "median": float(np.median(phi_e)),
            "p05": float(np.percentile(phi_e, 5)),
            "p95": float(np.percentile(phi_e, 95)),
        },
    }

    # A blunt honesty metric: width of the 90% band at the final horizon,
    # expressed as a multiple of the last observed price.
    last_price = float(prices[-1])
    final_lo = quant[5][-1]
    final_hi = quant[95][-1]
    band_width_ratio = (final_hi - final_lo) / last_price if last_price > 0 else 0.0

    return {
        "history": [float(p) for p in prices.tolist()],
        "forecast_quantiles": {str(q): quant[q] for q in qs},
        "param_summary": param_summary,
        "uncertainty": {
            "final_year_90pct_low": round(final_lo, 2),
            "final_year_90pct_high": round(final_hi, 2),
            "band_width_as_multiple_of_today": round(band_width_ratio, 3),
        },
        "caveat": (
            "House prices are close to a random-walk-with-drift; this is a "
            "statistical extrapolation, not a forecast. The wide band IS the "
            "result: treat the median line with deep skepticism and the band "
            "as the honest range of ignorance."
        ),
    }


def forecast_prices(
    history: List[float],
    income_history: Optional[List[float]] = None,
    horizon: int = 15,
    pti_anchor: float = 5.0,
    seed: int = 0,
) -> Dict:
    """
    Public entry point. `history` is oldest-first observed prices.
    Returns a dict with the fan-chart quantiles and an honesty summary.
    """
    if history is None or len(history) < 4:
        raise ValueError("Need at least 4 historical price points to fit.")
    cfg = ForecastConfig(horizon=horizon, pti_anchor=pti_anchor, seed=seed)
    prices = np.asarray(history, dtype=float)
    incomes = (np.asarray(income_history, dtype=float)
               if income_history is not None and len(income_history) == len(history)
               else None)
    return _fit_and_forecast(prices, incomes, cfg)
