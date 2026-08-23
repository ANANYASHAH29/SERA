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
    fetch_commits.py            # real commit/PR history via PyGithub
    diff_analyzer.py             # classifies changed files into F1-F5 risk categories
    synthetic_history.py          # fake commit history generator for testing
    pr_commenter.py                 # optional: posts attribution result to a PR
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

**7. Real-world smoke test.** Point `fetch_commit_history` (or
`scripts/demo_end_to_end.py --github ...`) at a real small repo (even one
you set up yourself with a few commits touching pipeline config files) and
confirm it doesn't choke on merge commits, squashed PRs, or unrelated
files.

**8. End-to-end demo.** `python scripts/demo_end_to_end.py` scripts the
full walkthrough — baseline → inject F3 → detection → history → ranking →
validation → recovery → case memory — for a live presentation. Pass
`--github owner/repo --since ... --until ...` to use a real repo instead
of the synthetic fallback; the synthetic path needs no network and is the
safer default for a live demo.

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

## Explicitly out of scope

No LLM calls anywhere in the diagnostic logic, no Docker/Kubernetes, no
vector database, no online retraining loop, no black-box ML classifier for
ranking (the ranker is plain, auditable Python).
