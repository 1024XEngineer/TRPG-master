"""Composition roots.

`build_fake_application` used to live here: it wired the v2 Orchestrator to the
Checkpoint kernel for the offline CLI. Both are gone with #226; what remains are
the provider-specific Host Agent builders, imported from
`collaboration_framework.bootstrap.host_agent` directly.
"""

__all__: list[str] = []
