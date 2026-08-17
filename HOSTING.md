# Hosting

This project is a **Python simulator** (FastAPI + numpy) with a JS frontend.
There are two ways to run it, and they answer different needs.

| | Demo mode (GitHub Pages) | The real app |
|---|---|---|
| What runs | Static files + a JS shim serving **precomputed** results | The actual FastAPI backend |
| Presets | ✅ real simulator output (saved) | ✅ live |
| Custom sliders / policies / world size | ❌ shows nearest preset, flagged | ✅ live |
| Finance comparator (arbitrary scenarios) | ❌ shows a precomputed example | ✅ live |
| Cost / setup | Free, zero infra | A Python host |

The published Pages site is a **shop window** — enough to click around the
presets and see genuine curves without anyone running a server. Everything
interactive needs the backend below.

## Run it locally (the full app)

Needs Python 3.10+.

```bash
pip install -r requirements.txt
python run.py
# open http://localhost:8000
```

The frontend (`API_BASE = ""`) talks to the same-origin backend, so no config
is needed. The demo mock (`frontend/mock-api.js`) is **not** loaded in this
mode — it only exists in the Pages build — so local dev is always fully live.

## ⚠️ Security: do not expose a public backend as-is

The **custom formula policy** feature compiles and `eval()`s a user-supplied
Python expression on the server ([`backend/simulator/policies.py`](backend/simulator/policies.py)).
The builtins are whitelisted, but that sandbox is **escapable** — a crafted
expression can reach `object.__subclasses__()` and from there run arbitrary
code and read files on the host.

This is harmless on **localhost** (you are only ever executing your own input).
It is a **critical remote-code-execution hole the moment the backend is public**.
So, before hosting a backend that strangers can reach, do one of:

1. **Disable custom formulas on the hosted instance** — keep presets, the
   structural/tax sliders, and the built-in tax formulas (which are fixed
   strings, not user input). Simplest and safe.
2. **Replace the evaluator** with a real AST-walking interpreter that permits
   only arithmetic and the whitelisted names (no attribute access, no
   subscripting, no comprehensions). Keeps the feature, closes the hole.

The static Pages demo is unaffected — it has no server to attack.

## Host the real backend (optional, for a fully-live public site)

Any host that runs a Python web process works. Free-tier options:

- **Render** / **Fly.io** — `pip install -r requirements.txt`, start command
  `python run.py` (bind `0.0.0.0:$PORT`). Free instances sleep; the first
  request after idle takes 20–50s to wake.
- **Hugging Face Spaces** (Docker or FastAPI template) — no credit card,
  friendlier for an always-warm demo.

CORS is already open (`allow_origins=["*"]` in
[`backend/api/main.py`](backend/api/main.py)), so a browser on any origin can
call it. **Apply the security fix above first.**

### Point the Pages frontend at a hosted backend

The demo mock tries the real network **before** falling back to fixtures, so if
the page can reach a live backend it uses it automatically. To make the Pages
build call your hosted API, set `API_BASE` in `frontend/app.js` and
`frontend/finance.js` to the backend URL (e.g. `https://your-app.onrender.com`)
before the Pages workflow builds. With a reachable backend, `mock-api.js` stays
dormant and every control is live.

## Regenerate the demo fixtures

The precomputed fixtures in `frontend/mock/` are produced from the real
simulator, so they can never silently diverge from the code:

```bash
python scripts/gen_mock_fixtures.py --out frontend/mock
```

The Pages workflow ([`.github/workflows/pages.yml`](.github/workflows/pages.yml))
also regenerates them on every deploy. If you change the model, the presets, or
the historical series, re-run this (or just push — CI does it) so the demo
reflects the change.

## How the Pages build is assembled

`scripts/build_pages.sh` produces a self-contained `_site/` from `frontend/`
without modifying `frontend/` itself:

- assets are placed under `static/` so the existing `static/…` URLs resolve;
- the `/finance` and `/` cross-links are rewritten to real `.html` files;
- `mock-api.js` + `mock/*.json` are wired in.

The workflow runs that script and publishes `_site/` to Pages.
