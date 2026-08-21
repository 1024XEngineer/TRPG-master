# Issue #356 validation protocol

This document defines the reproducible evidence pass for the 1..N TurnRun
unification. It does not change the production execution path. The benchmark is
an explicitly invoked WebSocket test and is excluded from normal pytest
collection so that CI never calls a paid model accidentally.

## What is measured

The report contains only the subject/tool Git revisions, provider/model identifiers, scenario
classification, step count, failure code, call counts, retry/repair counts, and
monotonic durations. It never contains player text, prompts, Keeper capability
data, model output, narration text, tokens, or API keys. A recursive report
validator rejects sensitive field names before a JSON result can be written.

The fake-mode scenarios are deterministic:

- `single_no_check`
- `single_pending_cancel`
- `single_validation_repair`
- `single_narrator_retry`
- `commit_response_loss`
- `multi_step`

`end_to_end_ms` runs from WebSocket action submission to `turn.completed` (or a
terminal failure). `first_narration_completion_ms` contains the same boundary
for successful turns only. `first_pending_ms` runs to the first
`adjudication.pending`. P50 and P95 use the nearest-rank method. Setup time for
accounts, rooms, characters, game start, and WebSocket join is excluded.

## Deterministic comparison

Run current code from `trpg-backend`:

```bash
ISSUE_356_BENCHMARK_MODE=fake \
ISSUE_356_BENCHMARK_REPEATS=10 \
ISSUE_356_SUBJECT_REVISION=$(git rev-parse HEAD) \
ISSUE_356_BENCHMARK_OUTPUT=/tmp/issue-356-current.json \
uv run pytest -s tests/benchmarks/issue_356_turn_run.py
```

For the historical comparison, create an isolated worktree at `f6ff264`, copy
the two benchmark modules into that worktree without committing them, and run
the same command there. Do not switch the working branch or rewrite historical
dependencies. The pre-change single-action path is expected to report zero
PlanRun create/CAS writes; current one-step turns must report PlanRun writes
without increasing Planner, Step Adjudicator, Narrator, or Engine submit calls.

## Real-model smoke

Real mode uses the provider configured by the backend `.env`. It must be run on
the current implementation only:

```bash
ISSUE_356_BENCHMARK_MODE=real \
ISSUE_356_BENCHMARK_REPEATS=2 \
ISSUE_356_BENCHMARK_OUTPUT=/tmp/issue-356-real.json \
uv run pytest -s tests/benchmarks/issue_356_turn_run.py
```

The three real scenarios submit an observation, an investigation, and a
two-clause action. Scenario names are labels rather than assumed model output:
the resulting `step_counts`, pending latency, failures, and actual model call
counts show how the provider classified and executed them. Do not rerun failed
samples selectively. Increase repeats only as an explicit cost/latency choice.

Raw JSON remains outside the repository. A reviewed, aggregate Markdown table
may be committed as release evidence, with the exact revisions, command,
machine/runtime context, sample count, and any limitations stated plainly.
