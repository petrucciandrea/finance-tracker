# Deploying on Render

`render.yaml` describes everything: the API (Docker), Postgres 16, a nightly retention
job and the static frontend, all in Frankfurt. Backend and database must stay in the EU
(the privacy text says so).

## First deploy

1. Push the repo to GitHub. In Render: **New → Blueprint**, pick the repo. Render reads
   `render.yaml` and asks for every variable marked `sync: false`.
2. Fill them in. Backend: `ADMIN_EMAIL` (private, where approval requests arrive),
   `SMTP_HOST/USERNAME/PASSWORD/FROM`, `FRONTEND_BASE_URL`, `CORS_ALLOWED_ORIGINS`
   (a JSON list: `["https://<frontend>"]`). Frontend: `VITE_API_BASE_URL`
   (`https://<api>/api/v1`), `VITE_LEGAL_CONTROLLER`, `VITE_LEGAL_EMAIL` (a **public**
   privacy contact, not `ADMIN_EMAIL`), optionally `VITE_LEGAL_ADDRESS`.
   The frontend values are baked in at build time: change one and you must redeploy it.
3. The Blueprint names the services `finance-tracker-api` and `finance-tracker-web`. If
   Render gives them different URLs (names are global), fix **both** the CSP
   `connect-src` in `render.yaml` and the env vars above, or the browser will block every
   API call.
4. The API starts with `alembic upgrade head` (`preDeployCommand`), so the schema is
   created/updated before traffic arrives.

## Check after the first deploy

- `https://<api>/health` returns 200, `https://<api>/docs` returns 404.
- Register with a real address: the admin mail arrives; approve; the user gets **one**
  mail with the confirmation link; log in.
- **Rate limiter and proxies.** `TRUSTED_PROXY_COUNT=1` is a starting value, not a fact:
  it must equal how many proxies sit in front of the app. From your own machine send 11
  wrong logins, each with a different `X-Forwarded-For`:
  `curl -s -o /dev/null -w '%{http_code} ' -X POST https://<api>/api/v1/auth/login -H "X-Forwarded-For: 9.9.9.$i" -H 'content-type: application/json' -d '{"email":"x@example.com","password":"wrong-password"}'`
  The 11th must be `429`. If it stays `401`, the count is too high (the app is reading a
  value you control). If different people on different networks get throttled together,
  it is too low (everyone looks like the proxy): raise it by one and repeat.
- Settings that are unsafe in production (debug, short JWT secret, approval mode without
  SMTP…) make the API refuse to start: read the deploy log if it won't come up.

## Operating it

- **Retention** runs from the `finance-tracker-purge` cron job at 03:17 UTC
  (`python -m app.purge`). Locally: `make purge-dry`, then `make purge`.
- **Backups**: use a paid Postgres plan and confirm in the dashboard that daily backups
  are on and for how long they are kept. Rows deleted by a user or by the purge survive in
  a backup until it rotates out; the privacy text says so. Do a test restore once.
- **One instance only.** The rate limiter and the CSV import preview live in process
  memory; scaling out needs Redis for both first (see CLAUDE.md).
- **Opening registration**: set `REGISTRATION_MODE=open` on the API. Nothing else changes.
- Dependencies: `pip-audit` / `npm audit` run in CI (`.github/workflows/ci.yml`).
