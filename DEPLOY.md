# Deploying: Neon + Render + Vercel + GitHub

```
Browser → Vercel (frontend, proxies /api/v1) → Render (API) → Neon (Postgres)
```

| Piece | Role | Free tier |
|---|---|---|
| **Neon** | PostgreSQL 16, **EU region**, use the *direct* connection string (no `-pooler`) | ~0.5 GB, suspends when idle, does not expire |
| **Render** | The API, built from `backend/Dockerfile.prod` (`render.yaml`) | sleeps after 15 min idle (~1 min to wake) |
| **Vercel** | The static frontend; `frontend/vercel.json` forwards `/api/v1` to Render, so same origin and no CORS | non-commercial use only |
| **GitHub** | CI on every push, and the `Deploy` workflow | free |

**Current setup: registration closed, no email.** `REGISTRATION_MODE=closed` and no SMTP
settings, so nobody can sign up and nothing is mailed (free Render services can't use the
usual SMTP ports anyway). Accounts are made with `make create-user`. The login page hides
"Crea account" and "Password dimenticata?" by itself, from `GET /auth/config`.

Deploys run from `.github/workflows/deploy.yml`: after CI is green on `main` it migrates the
database, **then** triggers Render for that exact commit (schema first, code second). So a
migration must stay compatible with the version still running: add columns and tables in
one release, drop things in a later one. Render's own auto-deploy is off. Until the two
secrets below exist the workflow skips itself with a notice instead of failing.

## First deploy, in this order

1. **Neon.** Create a project in an EU region (Frankfurt). Copy the **direct** connection
   string (the one without `-pooler`).
2. **Render.** New → Blueprint, pick the repo, apply `render.yaml`. It asks for two
   values: `DATABASE_URL` (the Neon string) and `TRUSTED_PROXY_COUNT` (enter `1`). Once the
   service exists, open its Settings and copy the **Deploy Hook** URL (the service's, not the
   Blueprint's sync hook). The service starts by itself on creation; the schema is created by
   the first Deploy run in step 5.
3. **GitHub.** Settings → Environments → `production`, add the secrets
   `PRODUCTION_DATABASE_URL` (the same Neon string) and `RENDER_DEPLOY_HOOK_URL`. Set them
   from a terminal so they stay out of your history, pasting the value at the prompt
   rather than in the command (zsh chokes on the `?` in the hook URL):
   `gh secret set RENDER_DEPLOY_HOOK_URL --env production`
4. **Vercel.** Import the repo with Root Directory `frontend`. Variables:
   `VITE_API_BASE_URL=/api/v1`, `VITE_LEGAL_CONTROLLER` (your name), `VITE_LEGAL_EMAIL` (a
   **public** privacy contact), `VITE_LEGAL_HOSTING` (e.g. `Render (Francoforte), Neon
   (Francoforte), Vercel`), optionally `VITE_LEGAL_ADDRESS`. They are baked in at build
   time: change one and redeploy. If Render's URL is not
   `https://finance-tracker-api.onrender.com`, edit the rewrite in `frontend/vercel.json`.
5. **Deploy.** Actions → Deploy → *Run workflow* (or push to `main`). Both the migration
   step and the Render step must be green.
6. **Bring your account over** (registration is closed, so there is no sign-up). The Neon
   database is empty until step 5 has migrated it, so do this after step 5. Two ways, from
   your machine, keeping the Neon string in a variable that never touches your shell history
   or the command line:
   - **Copy your existing account and data** from the local database (same password, same
     data; sessions are not copied, you log in again). Preview first with `--dry-run`:
     ```
     read -s NEON_URL
     docker compose exec -e TARGET_DATABASE_URL="$NEON_URL" backend python -m app.transfer_user you@example.com --dry-run
     docker compose exec -e TARGET_DATABASE_URL="$NEON_URL" backend python -m app.transfer_user you@example.com
     ```
     It copies only that one user (not the test users), everything in one transaction, and
     refuses to overwrite a user that already exists. Cached market prices are not copied:
     they are fetched again the first time you open the portfolio.
   - **Or start empty** with a brand-new account:
     ```
     docker compose exec -e DATABASE_URL="$NEON_URL" backend python -m app.create_user you@example.com
     ```
     It asks for the password twice.

## Check after the first deploy

- `https://<api>/health` returns 200 and `https://<api>/docs` returns 404 (the first call
  after a sleep takes about a minute). The site loads, has no "Crea account", and
  `/privacy` shows your name.
- Log in with the account you created.
- **Rate limiter.** `TRUSTED_PROXY_COUNT` is how many entries, counted from the right of
  `X-Forwarded-For`, belong to proxies we trust. **Use `1`.** What we measured on this setup:
  - Render appends the address of its own edge; it does not document the chain, and what it
    appends is one of a few edge addresses, not the visitor's. So the limiter's key is that
    address: attempts are counted per Render edge address, shared by many visitors.
  - A caller-supplied `X-Forwarded-For` is ignored, which is what matters: inventing an
    address no longer buys fresh attempts. (Trusting the header wholesale, or a count that
    reaches into it, lets anyone do exactly that.)
  - Through Vercel the real client address does not reach the app at all (Vercel's proxy
    stands in between), so there too the limit is shared.
  To re-check after changing anything proxy-related, send 25 wrong logins to the **API
  address**, each with a different `X-Forwarded-For`, right after a restart (a restart
  empties the counters):
  `for i in $(seq 1 25); do curl -s -o /dev/null -w '%{http_code} ' -X POST https://<api>/api/v1/auth/login -H "X-Forwarded-For: 6.6.6.$i" -H 'content-type: application/json' -d '{"email":"x@example.com","password":"wrong-password"}'; done`
  Expect at most about 20 `401`s (10 per edge address) and then `429`s. All 25 `401` means
  the header is being trusted: lower the count.
  The practical effect is a login limit shared by everyone. Fine for one user and closed
  registration; before opening registration move to calling the API directly from the
  browser (CORS), or limit per account, so one bad actor can't lock the others out.
- Unsafe settings (debug on, short JWT secret…) make the API refuse to start: read the
  deploy log if it won't come up.

## Turning email and registration on (later)

1. Pick a mail provider with an SMTP port other than 25/465/587 (Brevo, Mailgun and
   SendGrid offer 2525, Resend 2587: confirm in its docs) and verify a sender address.
2. On Render add `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM`,
   `FRONTEND_BASE_URL` (the Vercel domain) and, for approval mode, `ADMIN_EMAIL` (private).
   The login page then shows "Password dimenticata?" by itself.
3. Set `REGISTRATION_MODE` to `approval` (you approve each account from an email) or
   `open`. Before `open`, do the two things still pending: a consent screen for existing
   users and the confirmed change of email (see CLAUDE.md).
4. Without SMTP the API never writes email bodies in its production log (they hold links
   that act as credentials), so a missing setting leaks nothing but also sends nothing.

## Limits and what they mean

- **Render free:** sleeps when idle, and every restart empties the in-memory rate limiter
  and any pending CSV import preview. **One instance only**: scaling out needs Redis for
  both first (see CLAUDE.md).
- **Neon free:** small storage, and a sleeping database wakes on the first query (the
  engine uses `pool_pre_ping`, so stale connections after a pause are handled). Check its
  point-in-time history window in the console; it is short on the free plan.
- **No nightly purge:** Render cron jobs have no free plan. Run it by hand against
  production when you want it (same `read -s` trick: `... backend python -m app.purge
  --dry-run` first), or on a paid plan add the cron job sketched in `render.yaml`.
- **Vercel Hobby is non-commercial.** Fine for a free personal project; revisit if this
  ever earns money.
- **Privacy:** all API traffic, personal data included, passes through Vercel's network
  on its way to Render. Keep `VITE_LEGAL_HOSTING` and the processors listed in the privacy
  text accurate (Render, Neon, Vercel), and keep Neon and Render in the EU.

## Operating it

- Protect `main` (Settings → Rules) by requiring the CI jobs `backend` and `frontend`.
  Keep the bypass list empty, or the rule won't stop you either.
- Dependencies are audited by CI (`pip-audit`, `npm audit`).
