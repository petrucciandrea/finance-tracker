# Deploying on Render

`render.yaml` describes the API (Docker), Postgres 16 and the static frontend, all in
Frankfurt. Backend and database must stay in the EU (the privacy text says so).

**It is currently set up for Render's free tier, as a trial.** Read "Free-tier limits"
before relying on it, and "Moving to paid" before the database expires.

## First deploy

1. Push the repo to GitHub. In Render: **New → Blueprint**, pick the repo. Render reads
   `render.yaml` and asks for every variable marked `sync: false`.
2. Fill them in.
   - API: `ADMIN_EMAIL` (private, where approval requests arrive), `SMTP_HOST`,
     `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM` (see the mail note below),
     `FRONTEND_BASE_URL`, `CORS_ALLOWED_ORIGINS` (a JSON list: `["https://<frontend>"]`).
   - Frontend: `VITE_API_BASE_URL` (`https://<api>/api/v1`), `VITE_LEGAL_CONTROLLER`,
     `VITE_LEGAL_EMAIL` (a **public** privacy contact, not `ADMIN_EMAIL`), optionally
     `VITE_LEGAL_ADDRESS`. These are baked in at build time: change one, redeploy the frontend.
3. The Blueprint names the services `finance-tracker-api` and `finance-tracker-web`. If
   Render gives them different URLs (names are global), fix **both** the CSP `connect-src`
   in `render.yaml` and the variables above, or the browser blocks every API call.
4. The API runs `alembic upgrade head` each time it starts, so the schema is created and
   updated by itself.

## Free-tier limits (checked against Render's docs)

- **No SMTP on ports 25, 465, 587.** Free web services can't connect out on them, so
  Gmail's SMTP does not work here. Use a provider that offers another port and put it in
  `SMTP_PORT`: Brevo, Mailgun and SendGrid offer 2525, Resend 2587 (confirm in the
  provider's docs). Nothing in the code changes. Send from an address or domain the
  provider has verified, or mail lands in spam.
- **Sleeps after 15 minutes idle**, about a minute to wake. A restart empties the
  in-memory rate limiter and any pending CSV import preview.
- **Free database: 1 GB, no backups, expires 30 days after creation, deleted 14 days later.**
  Put the date in your calendar.
- **750 free instance hours a month per workspace**; one always-on service fits just under.
- **No cron jobs on the free plan**: the nightly purge is commented out in `render.yaml`.
  Run `make purge` against the dev DB, or wait for the paid move.
- No pre-deploy command, hence migrations at start-up.

## Check after the first deploy

- `https://<api>/health` returns 200, `https://<api>/docs` returns 404 (the first call
  after a sleep takes about a minute).
- Register with a real address: the admin mail arrives; approve; the user gets **one**
  mail with the confirmation link; log in. If no mail arrives, read the API log: the line
  is `Email sent to …` or `Failed to send email …` with the SMTP error.
- **Rate limiter and proxies.** `TRUSTED_PROXY_COUNT=1` is a starting value, not a fact:
  it must equal how many proxies sit in front of the app. From your machine send 11 wrong
  logins, each with a different `X-Forwarded-For`:
  `for i in $(seq 1 11); do curl -s -o /dev/null -w '%{http_code} ' -X POST https://<api>/api/v1/auth/login -H "X-Forwarded-For: 9.9.9.$i" -H 'content-type: application/json' -d '{"email":"x@example.com","password":"wrong-password"}'; done`
  The 11th must be `429`. If it stays `401`, the count is too high (the app is reading a
  value you control). If different people on different networks get throttled together,
  it is too low (everyone looks like the proxy): raise it by one and repeat.
- Settings that are unsafe in production (debug, short JWT secret, approval mode without
  SMTP…) make the API refuse to start: read the deploy log if it won't come up.

## Moving to paid (before the database expires)

1. **Database:** in the Render dashboard upgrade the Postgres instance to a paid plan. The
   data is kept; do it before day 30 (day 44 at the very latest, after which it is deleted).
   Then set `plan:` in `render.yaml` to match, so the Blueprint doesn't fight the dashboard.
   If you want a safety copy first: `pg_dump` from the dashboard's external connection.
2. **API (optional):** `plan: starter`, remove `dockerCommand`, add
   `preDeployCommand: alembic upgrade head`. This stops the sleeping and the limiter reset.
3. **Purge:** uncomment the `finance-tracker-purge` cron job (it is a paid service type).
4. **Backups:** on a paid database confirm in the dashboard that automatic backups are on
   and for how long; do one test restore. Rows deleted by a user or by the purge survive in
   a backup until it rotates out; the privacy text says so.

## Operating it

- **One instance only.** The rate limiter and the CSV preview live in process memory;
  scaling out needs Redis for both first (see CLAUDE.md).
- **Opening registration**: set `REGISTRATION_MODE=open` on the API. Nothing else changes.
- Dependencies are audited by CI (`.github/workflows/ci.yml`).
