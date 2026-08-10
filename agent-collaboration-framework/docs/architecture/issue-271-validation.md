# Issue #271: Internal Authority Classification

Issue #271 adds a deterministic, B-owned validation result for
ActionAdjudication. The Agent supplies an intent and candidate effects; it
never supplies an authority level.

## Boundary

AuthorityLevel (L0 through L5) is an internal diagnostic classification. It is
not a player action tier and it is not an execution gate. A valid L4 effect may
execute, while an invalid L2 effect may be rejected by the ordinary domain
rules.

The full ValidationResult is available only to B and trusted Host code. Its
authority level, target evidence, and internal reason must not enter
AdjudicationExecution, AdjudicationStatusView, PlayerView, Narrator context,
public progress events, or player SDK DTOs. A/Host receives only
ValidationFeedback, which contains a stable safe code and reason.

TARGET_NOT_FOUND and CANON_SHADOW are intentionally projected as the same
TARGET_UNAVAILABLE feedback so that hidden-object existence cannot be probed.

## Persistence

Accepted commands use the existing adjudication_command_executions.result_json
column with result_schema_version=2:

~~~json
{
  "execution": {},
  "validation": {},
  "committed_authority_level": "L2",
  "classification_coverage": "complete"
}
~~~

Rejected validation never writes a command row or authoritative state. Legacy
v1 rows, whose JSON is a bare AdjudicationExecution, remain readable and are
loaded with validation=None, committed_authority_level=None, and
classification_coverage="legacy_unknown". No table, column, or Alembic
migration is required.

## v1 scope

Agent-owned effects are classified by their concrete type and target namespace.
Rule-owned effects are not fully classified in v1; the rule match scope is
still revalidated, and results involving Rule effects carry
classification_coverage="rule_effects_excluded". Automatic repair loops,
retry budgets, and replanning belong to Issue #272.
