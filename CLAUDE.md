# Manual Dispatch Request (dispatch_request) — Project Instructions

This project follows the global `AGENTS.md` and `SECURITY_BASELINE.md`.
The notes below cover only what's specific to this repository.

This app reuses the same auth and theming approach as the sibling
`dispatch` app.

## Version identifiers

Three places, in sync at `v1.0.3`:

- `package.json` — the `version` field
- `public/index.html` — the `<title>`
- `api/index.py` — the `APP_VERSION` constant

`README.md`'s "Current Version" section still reads `v1.0.0` — stale
documentation, flagged during governance migration, not corrected.

## Local development

`server.js` has **no `/api` proxy**, same as the sibling `dispatch`
app — it only serves static files from `public/` and a catch-all to
`index.html`. Use `vercel dev` for local development that includes
working API calls; `node server.js` alone serves the UI but every
`/api/*` call will fail.
