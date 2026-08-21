# Issue #356 validation results

Run date: 2026-08-21 (Asia/Shanghai)

The reproducible harness is in
`tests/benchmarks/issue_356_turn_run.py`; the tool commit is `e18774f`.
Results below are sanitized aggregates. No utterance, prompt, Keeper view,
model response, token, or credential is included. Percentiles use nearest-rank;
latencies start after the action submit has been sent and stop at
`turn.completed`.

## Fake before/after

The comparison uses the same harness and 5 samples per scenario in isolated
worktrees:

- Before: `f6ff264`, the production revision immediately before #356.
- After: `c280b21`, the #356 implementation merge commit.
- Both runs: 30 samples, 0 failures, fake provider.

| Scenario | Before P50/P95 ms | After P50/P95 ms | Before calls (Planner/Adj/Narrator/Submit) | After calls (Planner/Adj/Narrator/Submit) | After PlanRun writes (create/CAS) |
| --- | ---: | ---: | ---: | ---: | ---: |
| Single no-check | 52.181 / 84.856 | 80.853 / 116.078 | 1 / 0 / 1 / 1 | 1 / 0 / 1 / 1 | 1 / 3 |
| Single pending + cancel | 87.462 / 123.372 | 124.503 / 166.287 | 1 / 0 / 1 / 1 | 1 / 0 / 1 / 1 | 1 / 3 |
| Single validation repair | 73.869 / 114.497 | 101.841 / 131.647 | 1 / 1 / 1 / 2 | 1 / 1 / 1 / 2 | 1 / 6 |
| Single narrator retry | 99.638 / 141.480 | 105.801 / 142.826 | 2 / 0 / 2 / 2 | 1 / 0 / 2 / 1 | 1 / 3 |
| Commit response loss | 54.922 / 57.179 | 87.127 / 87.311 | 1 / 0 / 1 / 1 | 1 / 0 / 1 / 1 | 1 / 3 |
| Multi-step (2) | 115.325 / 150.143 | 127.238 / 166.535 | 1 / 2 / 1 / 2 | 1 / 2 / 1 / 2 | 1 / 8 |

Overall fake end-to-end latency changed from P50/P95
`86.027/141.480 ms` to `105.801/166.287 ms`. This is the measured cost of
creating and checkpointing the unified Run; it is not hidden as a zero-cost
architectural change. The important call-count invariants held: normal
single-action planner/adjudicator/narrator/submit calls stayed at `1/0/1/1`,
and a narrator retry did not re-run Planner or Engine submit. The response-loss
scenario reconciled exactly once through Engine status in both revisions.

## Real-model smoke

Run against current `origin/main` revision `2cf7528`, with
`deepseek/deepseek-chat`, 2 samples for each of three fixed scenario labels
(6 samples total). The action text is not retained in the report. All 6
samples completed with failure rate `0.0`; no transport retry was observed.

| Scenario classification | Samples | Step count | Planner / Adj / Narrator / Submit | PlanRun create/CAS | P50/P95 ms |
| --- | ---: | ---: | ---: | ---: | ---: |
| Observation | 2 | 1 | 1 / 0 / 1 / 1 | 1 / 3 | 4486.788 / 5119.781 |
| Investigation | 2 | 1 | 1 / 0 / 1 / 1 | 1 / 3 | 3735.646 / 4450.393 |
| Two-clause action | 2 | 2 | 1 / 2 / 1 / 2 | 1 / 8 | 8177.417 / 8226.400 |

Real-model results are a smoke sample, not a provider SLA or a statistically
representative performance claim. They demonstrate that the current provider
can execute both one-step and two-step paths through the same WebSocket TurnRun
chain with the expected high-level call shape.

## Reproduction

Fake comparison:

```bash
ISSUE_356_BENCHMARK_MODE=fake \
ISSUE_356_BENCHMARK_REPEATS=5 \
ISSUE_356_SUBJECT_REVISION=f6ff264 \
ISSUE_356_BENCHMARK_OUTPUT=/tmp/issue-356-pre.json \
uv run pytest -s tests/benchmarks/issue_356_turn_run.py
```

Run the same command at `c280b21` with
`ISSUE_356_SUBJECT_REVISION=c280b21`. Real smoke on the current checkout:

```bash
ISSUE_356_BENCHMARK_MODE=real \
ISSUE_356_BENCHMARK_REPEATS=2 \
ISSUE_356_BENCHMARK_OUTPUT=/tmp/issue-356-real.json \
uv run pytest -s tests/benchmarks/issue_356_turn_run.py
```

Raw JSON reports are intentionally kept outside Git. The checked-in table is
the review artifact for #356 and should be linked from the Issue/validation PR.
