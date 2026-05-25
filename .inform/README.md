# .inform/

In-house tooling for Inform Growth. Lives at a dotted prefix so it's:

1. **Hidden by convention** — quiet in directory listings; tools that respect dotfiles will skip it.
2. **Excluded from client scaffolds** — `copier.yml`'s `_exclude` block keeps `.inform/` out of templated client repos.
3. **Excluded from CORE_FILES sync** — `.github/workflows/distribute.yml` does not enumerate any `.inform/` paths, so changes here never auto-push to client gateways.

The contents of this directory are *deliverable as a service* — when Inform Growth is engaged to maintain a client gateway, run the relevant installer (e.g. `.inform/qa/scripts/install_qa_tooling.sh <client-repo>`) to copy the tooling into that client's repo as a one-off.

## Current contents

- `qa/` — automated test/fix loop for use during development. See `qa/README.md`.

## Conventions for adding more

- Each sub-area gets its own folder under `.inform/` (`qa/`, future: `release/`, `audit/`, etc.).
- Each folder has a `README.md` explaining the surface and how to install it onto a client repo.
- Installers always go through a manual script, never via distribute.yml.
