# Gateway Admin UI

React + Vite + TypeScript + Tailwind 4 + shadcn (base-ui) dashboard for the Remote Gateway.

## Develop

```bash
# From repo root:
./dev.sh
```

Then open http://localhost:5173/admin. Vite proxies `/admin/api/*` to the
Python gateway on :8000 and injects `VITE_ADMIN_TOKEN` automatically.

## Build

```bash
npm install
npm run build
# Output: dist/
```

The Python gateway serves `dist/` from `/admin/` in production.

## Test

```bash
npm test
```

## Configure

Copy `.env.example` to `.env.local` and adjust:

```
VITE_ADMIN_TOKEN=inform-admin-2026  # must match the Python ADMIN_TOKEN
```

## Stack

- Vite 5, React 19, TypeScript 6
- Tailwind 4 (via @tailwindcss/vite plugin, CSS-first config in `src/styles/globals.css`)
- shadcn/ui primitives backed by `@base-ui/react`
- TanStack Query 5 + Table 8, react-router-dom 6, react-hook-form 7, zod 3
- Vitest 4, Testing Library 16

## Spec & Plan

- Spec: `../../docs/superpowers/specs/2026-05-05-admin-ui-react-port-design.md`
- Phase 0 Plan: `../../docs/superpowers/plans/2026-05-05-admin-ui-phase-0-scaffolding.md`
