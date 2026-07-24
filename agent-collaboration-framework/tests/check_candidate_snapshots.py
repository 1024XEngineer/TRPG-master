"""Small immutable Ruleset snapshots used only by deterministic tests.

This is not the authoritative CoC 7e catalog.  It intentionally contains only
the check candidates referenced by the Phase 1 demo fixture.  Production code
will receive the authoritative catalog from Ruleset / Reference Data later.
"""

from __future__ import annotations

# Aligned with trpg-backend coc7_content.py (2026-07-23):
#   Attributes: STR/CON/POW/DEX/APP/SIZ/INT/EDU/LUCK (uppercase)
#   Skills:     lowercase with hyphens (spot-hidden, fighting-brawl)
DEMO_CHECK_CANDIDATES: frozenset[str] = frozenset(
    {
        "spot-hidden",
        "STR",
    }
)
