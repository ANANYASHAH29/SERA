# SERA — Suspect Extraction & Regression Attribution

SERA determines whether an accuracy regression in a CV image-classification
pipeline was caused by a specific Git commit or by genuine data
distribution shift — **without re-evaluating every candidate commit**.

It does this by building one ranked hypothesis space that contains every
commit in a time window *plus* an explicit "no commit responsible — this
is genuine drift" candidate, scoring each with cheap, zero-re-execution
evidence (does the diff touch a risk-category file? does the observed
confidence/entropy-shift shape match what that failure mode looks like?),
and only ever running a full, expensive isolated re-evaluation on the
single top-ranked candidate.

No LLM calls anywhere in the diagnostic logic. No Docker. No vector
database. No online retraining.

## Architecture

```
sera/
  config.py                  # PipelineConfig — every knob a commit could change
  model.py                   # CIFAR-adapted ResNet-18 + checkpoint I/O
  pipeline/
    ingestion.py              # stage 1: load + validate the 200-image canary set
    preprocessing.py          # stage 2: resize + normalize
    input_prep.py              # stage 3: channel order + tensor conversion
    inference.py                 # stage 4: model forward pass
    evaluation.py                 # stage 5: accuracy, confidence, entropy
    runner.py                       # wires stages 1-5 together
  conditions/
    inject_f1_resize.py .. inject_f5_checkpoint.py   # F1-F5: commit-level bugs
    inject_d1_covariate_shift.py                      # D1: genuine drift (no commit)
    registry.py                                        # risk-file patterns + shape templates
  github_integration/
    fetch_commits.py            # real commit/PR history via PyGithub (rate-limit retry, force-push tolerant)
    diff_analyzer.py             # classifies changed files into risk categories (.sera.yml or built-in patterns)
    synthetic_history.py          # fake commit history generator for testing
    pr_commenter.py                 # posts attribution result to a PR
  repo_config.py                # loads a repo's own .sera.yml (risk patterns + canary entrypoint)
  canary_interface.py           # pluggable canary-eval contract (subprocess JSON or in-process callable)
  method/
    evidence_signals.py           # observed confidence/entropy "shape" fingerprint
    ranker.py                       # joint ranking: commits + drift hypothesis
    validator.py                     # cost-bounded targeted validation
    memory.py                         # SQLite case store
  baselines/
    full_bisection.py             # classic bisection (expensive)
    naive_latest_commit.py          # "blame the most recent commit"
    confidence_only.py                # shape-only ranking, no provenance
  api/                              # FastAPI app (Swagger UI at /docs)
  db/                               # SQLAlchemy models + session
experiments/
  scenario.py                     # shared scenario builder used by trials + tests
  run_trials.py                     # multi-seed, multi-condition, multi-method sweep
  build_confusion_matrix.py           # 6x6 confusion matrix + top-1/top-2 CIs
  cost_comparison.py                    # accuracy vs # of expensive re-evaluations
scripts/
  train_baseline_model.py         # trains the two CIFAR-10 checkpoints SERA needs
  calibrate_templates.py            # prints observed shape vectors per condition
  demo_end_to_end.py                  # scripted single-scenario walkthrough
  canary_eval_entrypoint.py             # reference subprocess canary-eval implementation
  pr_check.py                             # PR bot: base-vs-head eval, rank, comment-or-stay-silent
  run_scheduled_canary.py                   # cron-friendly canary run, independent of any PR
  smoke_test_real_repo.py                     # read-only dry-run against a real repo
.github/workflows/
  sera_pr_check.yml               # runs pr_check.py on every PR
  sera_scheduled_canary.yml         # runs run_scheduled_canary.py on a cron schedule
.sera.yml                         # SERA's own risk-pattern config (also the reference example)
frontend/                         # React + Vite + Tailwind dashboard (optional; see below)
tests/
results/
```

## The six injectable conditions

| ID | Name | Layer | Ties to a commit? |
|----|------|-------|--------------------|
| F1 | Resize dimension changed | preprocessing config | yes |
| F2 | RGB/BGR channel order swapped | input-prep config | yes |
| F3 | Normalization mean/std drifted | preprocessing config | yes |
| F4 | Corrupted/noisy images leak past a broken data-quality filter | ingestion config | yes |
| F5 | Wrong model checkpoint loaded | inference config | yes |
| D1 | Genuine covariate shift (fog / motion blur / sensor noise) | raw canary images | **no — by design** |

D1 is implemented outside `PipelineConfig` entirely — it mutates the raw
canary images directly and has an empty `RISK_FILE_PATTERNS` list, so no
commit diff can ever be classified as its cause. This is the mechanism the
null-hypothesis test in `tests/test_null_hypothesis.py` and step 2 below
exercise directly.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate        # or .venv\Scripts\activate on Windows
pip install -r requirements.txt

# Train the two CIFAR-10 checkpoints SERA's pipeline depends on
# (resnet18_cifar10: converged model; resnet18_cifar10_stale: 1-epoch
# snapshot used to simulate F5's "wrong checkpoint loaded")
python scripts/train_baseline_model.py --epochs 12
```

This downloads CIFAR-10 via torchvision (~170MB, cached under `data/`) and
writes `checkpoints/resnet18_cifar10.pt` + `checkpoints/resnet18_cifar10_stale.pt`.
Training on CPU takes roughly 1-3 minutes/epoch depending on hardware.

The 200-image canary set is deterministically sampled from the CIFAR-10
test split (fixed seed) and cached to `canary/` on first use.

## Running the API

```bash
uvicorn sera.api.main:app --reload
```

Open http://127.0.0.1:8000/docs for the Swagger UI. Typical flow:

1. `POST /runs/baseline` — a healthy run against the canary set.
2. `POST /runs/inject` — `{"condition": "F3", "severity": 0.6}` — a regressed run.
3. `POST /incidents/detect?baseline_run_id=..&regressed_run_id=..` — opens an incident if the drop exceeds threshold.
4. `POST /incidents/{id}/history/synthetic` or `POST /incidents/{id}/history/github` — attach commit evidence.
5. `POST /incidents/{id}/rank` — SERA's joint ranking.
6. `POST /incidents/{id}/validate` — isolated re-evaluation of the top candidate only.

Run context (configs/canary images per run) is kept in-process, so steps
1-6 must happen against the same running API process — this is a research
prototype, not a durable service.

## Running the frontend

A minimal React + Vite + Tailwind dashboard lives in `frontend/` — the
same 6-step flow as above, plus a view of the `results/` experiment
sweep (accuracy summary, cost comparison, confusion matrices). With the
API already running:

```bash
cd frontend
npm install
npm run dev
```

Open http://127.0.0.1:5173. See `frontend/README.md` for details. This
is optional polish, not required for anything else in this repo — the
API + Swagger UI is the full system either way.

## Synthetic mode vs a real GitHub repo

**Synthetic mode** (`/incidents/{id}/history/synthetic`, or
`sera.github_integration.synthetic_history.generate_synthetic_history`)
fabricates a chronologically-ordered commit list: N harmless commits
touching unrelated files (`README.md`, `utils/logging.py`, ...), optionally
one "guilty" commit whose changed file matches a chosen F1-F5 risk
category, and optionally a concurrent unrelated commit clustered near it.
This is what the experiment runner and most of the test suite use, since
it needs no network access and no populated repository.

**Real GitHub mode** (`/incidents/{id}/history/github`, or
`sera.github_integration.fetch_commits.fetch_commit_history`) hits the
GitHub REST API v3 through PyGithub for an actual `owner/repo` and time
window, pulling each commit's changed files and (best-effort) associated
PR. Set a `GITHUB_TOKEN` environment variable (or pass `token=`) to avoid
the unauthenticated rate limit:

```bash
export GITHUB_TOKEN=ghp_xxx
python scripts/demo_end_to_end.py --github your-org/your-repo --since 2026-08-01 --until 2026-08-23
```

Point this at even a small toy repo with a handful of real commits
touching your pipeline's config files to sanity-check the fetch/classify
path against real merge commits, squashed PRs, and unrelated file changes.

## Deploying against a real repo

Everything above (the CIFAR-10 demo, synthetic history, the FastAPI app)
still works exactly as before and needs nothing below this point. The
rest of this section is for pointing SERA at an arbitrary repo instead of
its own demo pipeline.

### (a) The CIFAR-10 demo, unchanged

`scripts/demo_end_to_end.py`, `experiments/run_trials.py`, the FastAPI
app, and the whole pytest suite still run exactly as documented above —
this phase is purely additive. If no `.sera.yml` is present, every risk
classification and canary evaluation falls back to SERA's original
hardcoded CIFAR-10 patterns and reference pipeline.

### (b) Setting up `.sera.yml` for a new repo

Drop a `.sera.yml` in your repo's root (see the one at this project's own
root for a real, working example — SERA uses it on itself):

```yaml
risk_categories:
  F1_resize:
    - "config/preprocessing.yaml"
    - "**/resize_params.py"
  F3_normalization:
    - "config/normalize_constants.py"
  F5_checkpoint:
    - "models/*.checkpoint_ref"
canary:
  entrypoint: "canary_eval.py"
```

Notes:
- Category keys are matched by their leading `F1`-`F5`/`D1` token, so
  `F1_resize`, `F1-resize`, or bare `F1` all work — use whatever suffix
  reads clearest in your own config. Unrecognized keys are ignored, not
  fatal.
- Patterns are plain `fnmatch` globs, **not** gitignore-style implicit
  "match anywhere" — `"models/*.ckpt"` only matches a file directly under
  `models/`. Prefix with `**/` (e.g. `"**/*.ckpt"`) to match at any depth.
- `canary.entrypoint` points at your own script implementing the
  subprocess contract in `sera/canary_interface.py`: run it, and expect
  the LAST line of its stdout to be one JSON object:
  `{"accuracy": ..., "mean_confidence": ..., "mean_entropy": ..., "per_sample_confidence": [...], "per_sample_correct": [...]}`.
  `per_sample_correct` is required, not optional — without it SERA can't
  tell which images flipped from correct to wrong, which is exactly the
  signal genuine-drift detection depends on. See
  `scripts/canary_eval_entrypoint.py` for a real, working reference
  implementation (it's what SERA runs on its own CIFAR-10 pipeline).
- No `.sera.yml`? Everything falls back to the built-in demo patterns —
  nothing breaks, you just don't get repo-specific classification yet.

### (c) Running the scheduled Action

`.github/workflows/sera_scheduled_canary.yml` runs
`scripts/run_scheduled_canary.py` on a cron schedule (every 6 hours by
default) — independent of any PR, which is required for genuine drift
(D1) to ever be caught, since nothing about drift triggers a PR. It:

1. Runs your `canary.entrypoint` (or the CIFAR-10 reference pipeline).
2. Compares against a small `.sera/baseline_metrics.json` snapshot
   persisted across runs via `actions/cache` (restore-keys prefix match,
   since cache entries are immutable per exact key — see the workflow's
   comments). First run bootstraps this file.
3. On a regression, fetches recent commit history, ranks it against the
   drift hypothesis, and writes the result to the job's step summary.

Scheduled mode intentionally stops at ranking, not full validation: the
in-process validator (`sera/method/validator.py`) reverts a
`PipelineConfig` field, which only makes sense for SERA's own reference
pipeline — an arbitrary repo's canary is an opaque subprocess with no such
config to revert. Full before/after validation for an arbitrary repo is
exactly what the PR bot provides instead (next section), via git checkout
rather than config reversion.

To trigger it manually (e.g. to test it once, per the testing checklist
below): open the repo on GitHub → Actions → "SERA scheduled canary" →
"Run workflow". Or run it locally:

```bash
python scripts/run_scheduled_canary.py --repo-root . --baseline-file .sera/baseline_metrics.json
```

### (d) The PR-comment bot

`.github/workflows/sera_pr_check.yml` runs `scripts/pr_check.py` on every
PR open/update. It checks out the PR's base commit, runs the canary eval
there, checks out the head commit, runs it again, and only if a
regression is found AND the top-ranked suspect is one of *this PR's own
commits* does it post a comment (via `pr_commenter.py`) with the evidence
used. If the top suspect is drift, or a commit outside this PR, it stays
completely silent — a bot that comments "just in case" trains people to
ignore it.

The base-vs-head comparison is a git-native equivalent of SERA's
in-process "revert and re-run" validator: checking out the base commit
*is* reverting this PR's changes, code and canary script both, without
SERA needing to understand the target repo's own config format.

Runs automatically in CI with the standard `GITHUB_TOKEN` (needs
`pull-requests: write`, already set in the workflow). To test locally
against an open PR:

```bash
export GITHUB_TOKEN=ghp_xxx
python scripts/pr_check.py --repo owner/name --pr 42 --dry-run   # ranks + prints, never posts
python scripts/pr_check.py --repo owner/name --pr 42             # posts for real if implicated
```

### Real-world commit-history robustness

`fetch_commits.py` retries on `RateLimitExceededException` with backoff
derived from GitHub's `x-ratelimit-reset` header (capped at 15 minutes),
and degrades to "no evidence for this commit" rather than crashing when a
SHA stops resolving mid-fetch (a force-push happened underneath it) or a
commit's file list is too large for the API to return in full. Squashed
merge commits (one commit, dozens of files, one of them risky) are
classified correctly — touching a risk file is still real provenance
evidence — but `tests/test_commit_history_robustness.py` confirms that
provenance alone doesn't let an incidental risk-file touch outrank a
genuinely better-fitting candidate; shape match still has to pull its
weight. See that test file's comments for why a single-candidate
"provenance vs. drift" framing isn't actually the fair version of this
claim, and what is.

## Deploying the backend publicly (Render / Railway)

The multi-tenant dashboard's GitHub Actions integration (`/report/{repo_id}/scan`,
the CI reporter in `scripts/report_scan.py`) needs a backend GitHub's own
runners can actually reach — `127.0.0.1` on your laptop isn't reachable
from GitHub Actions, and tunneling your local machine means exposing a
process holding your GitHub App's private key to the public internet,
which is a real, not cosmetic, risk. Deploying to a small always-on host
avoids both problems.

**Required environment variables** (set these in the host's dashboard,
never commit them):

| Variable | Required for |
|---|---|
| `GITHUB_APP_ID` | multi-tenant App auth |
| `GITHUB_APP_PRIVATE_KEY` | multi-tenant App auth (paste the full multi-line PEM directly — Render/Railway's env var UI handles multi-line values natively, no special parsing needed) |
| `GITHUB_APP_SLUG` | `/tenant/install-url` |
| `GITHUB_WEBHOOK_SECRET` | webhook signature verification |
| `GITHUB_TOKEN` | optional — only the single-tenant scripts use it, not the dashboard |

All of these are read via plain `os.environ.get(...)` (see
`sera/github_integration/github_app.py`) — nothing in the codebase
hardcodes a secret anywhere; `scripts/register_github_app.py` writes
discovered credentials to a local, gitignored `.env.github_app` for your
own dev machine only, which the deployed host never sees or needs.

**Steps (Render, free tier — Railway is nearly identical):**

1. Push this repo to its own GitHub repo if it isn't already (a private
   repo is fine — Render/Railway both support connecting private repos).
2. On Render: **New → Web Service** → connect that repo.
3. Runtime: Python 3. Build command: `pip install -r requirements.txt`.
   Start command: leave blank — Render auto-detects the `Procfile` at the
   repo root (`web: uvicorn sera.api.main:app --host 0.0.0.0 --port $PORT`).
4. Under **Environment**, add the five variables from the table above.
5. Deploy. You'll get a URL like `https://sera-demo.onrender.com` — verify
   with `curl https://sera-demo.onrender.com/health` before wiring
   anything else to it.
6. Point `demo-fraud-model`'s `SERA_DASHBOARD_URL` GitHub Actions secret
   at this URL instead of `http://127.0.0.1:8000`, and update the
   frontend's backend origin (`frontend/src/api.ts`'s `BACKEND_ORIGIN`,
   and `frontend/vite.config.ts`'s proxy target) if you want the local
   dashboard UI to read from the deployed backend instead of a local one.

**Known limitations of the free tier, stated honestly:**
- **SQLite (`sera_state.db`) is not guaranteed to persist across
  redeploys or restarts** on free-tier ephemeral disks — fine for a demo
  session, not for long-term storage. A real deployment would point
  `sera.config.DB_PATH` at a persistent disk or swap to a hosted Postgres.
- **First build installs `torch`/`torchvision`** (needed by the CIFAR-10
  reference pipeline elsewhere in the app, even though the sklearn/tabular
  CI-reporting path in this demo never calls them) — expect a slower first
  build, not a failure.
- **The CIFAR-10 reference-pipeline routes will error on a fresh deploy**
  (`/tenant/repos/{id}/scan`, the dark-mode `/demo` Live Diagnosis flow)
  unless you also run `scripts/train_baseline_model.py` in that
  environment — a large download + CPU training job, not something to do
  on a free-tier demo deploy. The multi-tenant `/report` and
  `/ingest-scan-result` paths this demo actually uses don't need it.

## Running experiments

```bash
python experiments/run_trials.py --seeds 0 1 2 3 4 --out results/trials.csv
python experiments/build_confusion_matrix.py --in results/trials.csv --out-dir results/
python experiments/cost_comparison.py --in results/trials.csv --out results/cost_comparison.csv
```

`run_trials.py` sweeps all 6 conditions x all 4 methods (SERA + the 3
baselines) across the given seeds, recording each method's top-ranked
guess vs. ground truth and the number of expensive re-evaluations it
needed, as `results/trials.csv` / `results/trials.json`.

`build_confusion_matrix.py` produces, per method: a 6x6 (true condition x
predicted category) confusion matrix (`results/confusion_matrix_<method>.csv`
+ `.png`) and `results/accuracy_summary.csv` with top-1/top-2 accuracy and
Wilson 95% confidence intervals across seeds.

`cost_comparison.py` produces `results/cost_comparison.csv`: mean/total
expensive re-evaluations per method alongside accuracy — the key result
differentiating SERA from brute-force bisection (both reach an answer,
but bisection pays O(log N) expensive re-evaluations per incident while
SERA and the other baselines pay exactly 1).

## Tests

```bash
pytest tests/ -v
```

Most tests require the trained checkpoints (`scripts/train_baseline_model.py`)
and are skipped otherwise via `tests/conftest.py`'s `requires_checkpoint`
marker. The ranking-logic tests in `tests/test_ranker.py` are model-free
(they construct observed shapes directly) and always run.

## How to test it, end to end

Work through these in order — each validates a different layer.

**1. Unit-level.** `pytest tests/ -v`. `tests/test_conditions.py` confirms
each of F1-F5/D1 individually produces a clear accuracy drop and a
distinguishable shape signature when injected alone.

**2. The null-hypothesis sanity check (the most important test in the
repo).** `tests/test_null_hypothesis.py::test_drift_plus_harmless_commit_ranks_drift_first`
injects D1 with one harmless commit in the window and asserts SERA ranks
drift above it. A fast, model-free version of the same logic lives in
`tests/test_ranker.py::test_null_hypothesis_wins_against_a_harmless_commit`.

**3. Clean single-culprit cases.** `tests/test_conditions.py` +
`tests/test_ranker.py::test_guilty_commit_beats_drift_hypothesis_and_harmless_commits`
cover F1-F5 each ranking correctly against harmless commits.

**4. The hard case — concurrent confounds.**
`tests/test_hard_confound.py` injects F3 alongside a harmless commit *and*
a mild concurrent drift event, and asserts SERA still ranks the F3 commit
first — proof the evidence fusion weighs provenance and shape jointly
rather than treating either signal alone as decisive.

**5. Cost comparison.** `python experiments/run_trials.py && python
experiments/cost_comparison.py`. Check that SERA's mean re-evaluations
stay at 1 while `full_bisection`'s scale with `log2(commits per window)`.

Actual numbers from a 5-seed x 6-condition sweep (`results/cost_comparison.csv`):

| method | top-1 accuracy | mean re-evaluations | max re-evaluations |
|---|---|---|---|
| **sera** | **1.000** | **1.0** | 1 |
| confidence_only | 1.000 | 1.0 | 1 |
| full_bisection | 0.833 | 2.67 | 3 |
| naive_latest | 0.167 | 1.0 | 1 |

`full_bisection` pays 2.7x SERA's re-evaluation cost *and* is still less
accurate, because it has no null hypothesis: on every D1 (genuine drift)
trial it converges to blaming whichever harmless commit happens to sit
first in the window (see `results/confusion_matrix_full_bisection.csv` —
its F1-F5 diagonal is perfect, its D1 row is 100% wrong). That gap is the
whole cost-comparison story in one sentence.

**6. Confusion matrix.** `python experiments/build_confusion_matrix.py`.
On this clean single-condition-at-a-time sweep, SERA's confusion matrix
is a perfect 6x6 diagonal (`results/confusion_matrix_sera.csv`) — every
condition, including D1, is disambiguated correctly every time. Note that
`confidence_only` *also* scores 100% here: shape alone is enough to tell
the six conditions apart when nothing else is confounding the picture.
SERA's edge over confidence-only only shows up under a *concurrent*
confound (step 4 above, `tests/test_hard_confound.py`) — that's the
scenario where having both provenance and shape evidence, not just one,
actually matters. The clean sweep alone doesn't demonstrate that; say so
if reporting these numbers rather than implying the confusion matrix is
where SERA's advantage over confidence-only lives.

**7. Real-world smoke test.** `python scripts/smoke_test_real_repo.py
--repo owner/name --since 2026-08-01 --until 2026-08-23` (or `--local-path
/path/to/clone` for no-token offline testing) fetches real commits,
classifies each one's diff, and confirms the fetch/classify path doesn't
choke on merge commits, squashed PRs, or unrelated files — read-only, no
regression required. Add `--simulate-condition F3` to also print an
illustrative (clearly-labeled, not real) ranking.

**8. End-to-end demo.** `python scripts/demo_end_to_end.py` scripts the
full walkthrough — baseline → inject F3 → detection → history → ranking →
validation → recovery → case memory — for a live presentation. Pass
`--github owner/repo --since ... --until ...` to use a real repo instead
of the synthetic fallback; the synthetic path needs no network and is the
safer default for a live demo.

## Rolling out against a real repo: Stage 1 → Stage 2

Work through these in order — each one only makes sense once the previous
one is clean, and each requires actions only a repo owner can take (opening
a real PR, adding a real token) that this system can't do on its own.

**Stage 1 — a self-created demo repo you control:**

1. **Dry-run smoke test first.** `python scripts/smoke_test_real_repo.py
   --repo you/your-demo-repo --since ... --until ...` — confirm commit
   fetching and diff classification work against real API calls before
   anything else. This is the messiest layer (real merge commits, real
   API pagination) and the one most likely to surprise you.
2. **Manually trigger the scheduled canary run once** (Actions → "SERA
   scheduled canary" → "Run workflow") and confirm it runs and completes
   independent of any PR being open.
3. **Open a real test PR containing one known-risky change** (e.g. a
   commit touching a path your `.sera.yml` maps to a risk category) and
   confirm the bot comments, with evidence that actually matches what you
   changed.
4. **Open a second test PR containing only harmless changes** and confirm
   the bot stays completely silent — this is as important a pass/fail
   signal as step 3; a bot that comments on everything is worse than one
   that comments on nothing.

**Stage 2 — a real external repo,** only once all four Stage-1 steps pass
cleanly: repeat the dry-run smoke test (step 1) against it first, since
external repos have commit-history shapes (bots, squash-merge policies,
huge contributor lists) your own demo repo won't have exercised.

## Known limitations (worth stating honestly, not hiding)

- **F4 and D1 have structurally similar shape signatures** (both produce
  a "subset of images went bad" signal: F4 = 0.11 broadness / 0.91
  concentration, D1 = 0.22 / 0.77 -- see `scripts/calibrate_templates.py`
  output). On the clean, single-condition-at-a-time sweep this doesn't
  cause any actual confusion (SERA's confusion matrix is a perfect 6x6
  diagonal, `results/confusion_matrix_sera.csv`), because provenance
  breaks the tie cleanly when there's no ambiguity about which commits
  exist. The real risk is a *concurrent* F4-like event with no nearby
  commit touching an ingestion/data-quality-filter file -- shape evidence
  alone can't fully distinguish "a commit broke the filter" from "the
  world got noisier" in that specific situation. `confidence_only`
  (shape, no provenance) also scored 100% on the clean sweep for the same
  reason the F4/D1 pair didn't bite: nothing was confounding the signal.
  The provenance term's actual value only shows up under a concurrent
  confound (`tests/test_hard_confound.py`), not in the basic 6x6 sweep --
  don't cite the clean confusion matrix alone as evidence that provenance
  matters; cite the hard-confound test for that claim instead.
- **D1's corruptions are simplified reimplementations** of the classic
  "common corruptions" (fog, motion blur, Gaussian noise), not the exact
  ImageNet-C/CIFAR-10-C benchmark implementations — close enough to
  produce the right *shape* of degradation, not bit-for-bit identical.
- **Shape templates in `evidence_signals.CONDITION_SHAPE_TEMPLATES` are
  calibrated against one specific model/canary set/severity setting.**
  Re-run `scripts/calibrate_templates.py` after changing any of those and
  update the templates if the observed vectors drift.
- **The API keeps run context (configs + canary images) in-process, not in
  SQLite.** Restarting the API server between `/runs/*` and
  `/incidents/*/validate` calls loses that context — fine for a research
  prototype and a single demo session, not for a durable service.
- **Scheduled canary runs rank but don't validate.** The in-process
  validator reverts a `PipelineConfig` field, which doesn't generalize to
  an arbitrary repo's opaque subprocess canary. Full validation for a real
  repo comes from the PR bot's base-vs-head git checkout instead — a
  scheduled run that finds an incident with no open PR near it (e.g. pure
  drift between merges) gets ranked and logged, not auto-confirmed.
- **The scheduled-run baseline persistence (`actions/cache` + a JSON
  snapshot) is a pragmatic pattern, not a real database.** Good enough to
  diff "now" against "last scheduled run", not a substitute for the
  SQLite case memory the in-process demo uses. A concurrent workflow run
  or a cache eviction can lose the snapshot; the script bootstraps a fresh
  one automatically rather than crashing when that happens.
- **`.sera.yml` glob patterns are plain `fnmatch`, not gitignore
  semantics.** A pattern with no `**/` prefix is root-anchored, not
  "matches anywhere" — see "Setting up `.sera.yml` for a new repo" above.
  Easy to get a silent false-negative (a real risk file that just doesn't
  match your pattern) if you forget this.

## Explicitly out of scope

No LLM calls anywhere in the diagnostic logic, no Docker/Kubernetes, no
vector database, no online retraining loop, no black-box ML classifier for
ranking (the ranker is plain, auditable Python).

