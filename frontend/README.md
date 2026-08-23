# SERA frontend

A minimal React + Vite + Tailwind dashboard for SERA. Two views:

- **Live diagnosis** — walks the same 6-step flow as the API (baseline
  run → inject a condition → detect → attach commit history → rank →
  validate the top candidate only), showing the ranked candidate table
  and validation outcome as they happen.
- **Experiment results** — reads the pre-computed `results/` sweep
  (accuracy summary, cost comparison, confusion matrices) via the
  backend's `/experiments/summary` endpoint.

This is a research-prototype control panel, not a production app: no
auth, no routing, all state lives in the page and resets on reload.

## Running it

The backend must already be running (from the repo root):

```bash
uvicorn sera.api.main:app --reload
```

Then, in this directory:

```bash
npm install
npm run dev
```

Open http://127.0.0.1:5173. The Vite dev server proxies `/api/*` to
`http://127.0.0.1:8000` (see `vite.config.ts`) and loads confusion-matrix
images directly from the backend's `/results-static` mount.

`npm run build` produces a static `dist/` you could serve some other way,
but there's no bundled production server here — this is meant to run
against a local `uvicorn --reload` backend during development/demos, not
be deployed standalone.
