# Issue #357 Real-model Round 1

- Revision: `aca238b48441de688ced4d57545f61d57374e71e`
- Verdict: **NO-GO**
- Model calls: 670
- Transport calls: 670
- Input/output tokens: 4466690 / 74076
- Semantic step-count distributions: `{'real_investigation': {'1': 20}, 'real_multi_step': {'2': 20}, 'real_observation': {'1': 20}}`
- Semantic adjudicator paths: `{'real_investigation': {'deterministic': {'per_sample_max': 0, 'per_sample_mean': 0.0, 'per_sample_min': 0, 'total': 0}, 'model': {'per_sample_max': 1, 'per_sample_mean': 1.0, 'per_sample_min': 1, 'total': 20}, 'repair': {'per_sample_max': 1, 'per_sample_mean': 0.05, 'per_sample_min': 0, 'total': 1}, 'rule_first': {'per_sample_max': 0, 'per_sample_mean': 0.0, 'per_sample_min': 0, 'total': 0}}, 'real_multi_step': {'deterministic': {'per_sample_max': 2, 'per_sample_mean': 2.0, 'per_sample_min': 2, 'total': 40}, 'model': {'per_sample_max': 0, 'per_sample_mean': 0.0, 'per_sample_min': 0, 'total': 0}, 'repair': {'per_sample_max': 0, 'per_sample_mean': 0.0, 'per_sample_min': 0, 'total': 0}, 'rule_first': {'per_sample_max': 0, 'per_sample_mean': 0.0, 'per_sample_min': 0, 'total': 0}}, 'real_observation': {'deterministic': {'per_sample_max': 1, 'per_sample_mean': 1.0, 'per_sample_min': 1, 'total': 20}, 'model': {'per_sample_max': 0, 'per_sample_mean': 0.0, 'per_sample_min': 0, 'total': 0}, 'repair': {'per_sample_max': 0, 'per_sample_mean': 0.0, 'per_sample_min': 0, 'total': 0}, 'rule_first': {'per_sample_max': 0, 'per_sample_mean': 0.0, 'per_sample_min': 0, 'total': 0}}}`

| Gate | Observed | Threshold | Result |
| --- | ---: | ---: | :---: |
| `complex_p95_absolute_increase` | 2203.02 | <= 1500.0 | FAIL |
| `complex_p95_relative_increase` | 0.369821 | <= 0.25 | FAIL |
| `semantic_one_action_p95` | 7860.309 | <= 6500.0 | FAIL |
| `planner_terminal_failure_rate` | 0.0 | <= 0.02 | PASS |
| `semantic_e2e_terminal_failure_rate` | 0.0 | <= 0.02 | PASS |
| `multi_step_count_accuracy` | 1.0 | >= 0.95 | PASS |
| `multi_kind_sequence_accuracy` | 1.0 | >= 0.95 | PASS |
| `structured_success_after_retry` | 1.0 | >= 0.99 | PASS |
| `deterministic_rule_first_drop` | 0.0 | <= 0.05 | PASS |
| `transport_call_cap` | 1288.0 | <= 2500.0 | PASS |
