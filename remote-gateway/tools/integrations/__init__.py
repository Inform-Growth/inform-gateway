"""Per-deployment integration tools.

Modules in this package wrap upstream business APIs (Apollo, Attio, Wiza, etc.)
or implement deployment-specific helpers (email body normalization, etc.).

Files here are intentionally **excluded** from the cross-repo `distribute.yml`
sync — every gateway deployment owns its own integration set. See
`docs/template-and-distribution.md` for the boundary.
"""
