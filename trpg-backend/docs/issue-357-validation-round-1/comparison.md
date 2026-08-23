# Issue #357 Real-model Round 1

- Revision: `d6bd38aa68949cb5882d0ff09253ea12bc8309ae`
- Verdict: **NO-GO**
- Model calls: 752
- Transport calls: 752
- Input/output tokens: 5863233 / 87807

| Gate | Observed | Threshold | Result |
| --- | ---: | ---: | :---: |
| `complex_p95_absolute_increase` | 1320.257 | <= 1500.0 | PASS |
| `complex_p95_relative_increase` | 0.200625 | <= 0.25 | PASS |
| `semantic_one_action_p95` | 7577.76 | <= 6500.0 | FAIL |
| `planner_terminal_failure_rate` | 0.0 | <= 0.02 | PASS |
| `semantic_e2e_terminal_failure_rate` | 0.05 | <= 0.02 | FAIL |
| `multi_step_count_accuracy` | 1.0 | >= 0.95 | PASS |
| `multi_kind_sequence_accuracy` | 1.0 | >= 0.95 | PASS |
| `structured_success_after_retry` | 1.0 | >= 0.99 | PASS |
| `deterministic_rule_first_drop` | 0.1451 | <= 0.05 | FAIL |
| `transport_call_cap` | 849.0 | <= 2500.0 | PASS |
