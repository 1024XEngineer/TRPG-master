"""Registry tables for the rule engine's publish-once, reuse-forever split.

Each module in this package is a small, closed lookup table shipped with the
Engine itself — never loaded from module content. A v3 Rule may only
*reference* an entry that already exists here (by predicate name, effect
type, rule step kind, or ruleset action id); module content can never define
a new one. Supporting a genuinely new kind of any of these is an Engine
release, not a module publish. See GitHub issue #347 §4.1/§4.2 for the full
rationale, and §4.3/§4.4 for the linker-style two-pass reference resolution
and ECS-style read/write declarations these tables are modelled on.

**This package is a leaf.** It sits alongside `contracts/` rather than inside
`engine/` because both `engine` (execution time) and `module` (publish-time
validation) read from it, and `docs/architecture.md` §6 forbids
`module -> engine`. At runtime these tables import only from `contracts`;
where an evaluator needs an engine state model it is imported under
`TYPE_CHECKING` for annotations only, so importing a table never drags the
engine in behind it.
"""

from __future__ import annotations
