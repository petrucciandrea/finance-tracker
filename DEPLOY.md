# Deploying: Neon + Render + Vercel + GitHub

```
Browser → Vercel (frontend, proxies /api/v1) → Render (API) → Neon (Postgres)
```

| Piece | Role | Free tier |
|---|---|---|
| **Neon** | PostgreSQL 16, **EU region**, use the *direct* connection string (no `-pooler`) | ~0.5 GB, suspends when idle, does not expire |
| **Render** | The API, built from `backend/Dockerfile.prod` (`render.yaml`) | sleeps after 15 min idle (~1 min to wake); **no outbound SMTP on ports 25/465/587** |
| **Vercel** | The static frontend; `frontend/vercel.json` forwards `/api/v1` to Render, so same origin and no CORS | non-commercial use only |
| **GitHub** | CI on every push, and the `Deploy` workflow | free |

Deploys are driven by `.github/workflows/deploy.yml`: after CI is green on `main` it
migrates the database, **then** triggers Render for that exact commit (schema first, code
second). So a migration must stay compatible with the version still running: add columns
and tables in one release, drop things in a later one. Render's own auto-deploy is off.

## First deploy, in this order

1. **Neon.** Create a project in an EU region (Frankfurt). Copy the direct connection
   string.
2. **Mail.** Free Render services can't use ports 25/465/587, so Gmail's SMTP won't work.
   Use a provider with another port (Brevo, Mailgun and SendGrid offer 2525, Resend 2587:
   confirm in its docs) and a sender address/domain it has verified.
3. **Render.** New → Blueprint, pick the repo, apply `render.yaml`. Fill the prompts:
   `DATABASE_URL` (the Neon string), `ADMIN_EMAIL` (private), `SMTP_HOST/PORT/USERNAME/
   PASSWORD/FROM`, `FRONTEND_BASE_URL` and `CORS_ALLOWED_ORIGINS` (the Vercel domain,
   the latter as a JSON list), `TRUSTED_PROXY_COUNT` (start at `2`). Then, in the service's
   Settings, copy the **Deploy Hook** URL: the service's one, not the Blueprint's sync hook.
4. **GitHub.** Settings → Environments → create `production`, add the secrets
   `PRODUCTION_DATABASE_URL` (the same Neon string) and `RENDER_DEPLOY_HOOK_URL`. Set them
   from a terminal so they stay out of your history, and paste the value at the prompt
   rather than in the command (zsh chokes on the `?` in the hook URL):
   `gh secret set RENDER_DEPLOY_HOOK_URL --env production`
5. **Vercel.** Import the repo with Root Directory `frontend`. Variables:
   `VITE_API_BASE_URL=/api/v1`, `VITE_LEGAL_CONTROLLER`, `VITE_LEGAL_EMAIL` (a **public**
   contact, not `ADMIN_EMAIL`), `VITE_LEGAL_HOSTING` (e.g. `Render (Francoforte), Neon
   (Francoforte), Vercel`), optionally `VITE_LEGAL_ADDRESS`. They are baked in at build
   time: change one and redeploy. If Render's URL is not
   `https://finance-tracker-api.onrender.com`, edit the rewrite in `frontend/vercel.json`.
6. **Deploy.** Push to `main`, or Actions → Deploy → *Run workflow*. Check that the
   migration step and the Render hook step are both green.

## Check after the first deploy

- `https://<api>/health` returns 200 and `https://<api>/docs` returns 404 (the first call
  after a sleep takes about a minute). The site loads and `/privacy` has your name on it.
- Register with a real address: the admin mail arrives; approve; the user gets **one** mail
  with the confirmation link; log in. If no mail arrives, read the API log: it says
  `Email sent to …` or `Failed to send email …` with the SMTP error.
- **Rate limiter and proxies.** `TRUSTED_PROXY_COUNT` must equal how many proxies sit in
  front of the app (here Vercel's rewrite and Render's, probably 2). From your machine,
  through the **Vercel** domain, send 11 wrong logins, each with a different
  `X-Forwarded-For`:
  `for i in $(seq 1 11); do curl -s -o /dev/null -w '%{http_code} ' -X POST https://<vercel domain>/api/v1/auth/login -H "X-Forwarded-For: 9.9.9.$i" -H 'content-type: application/json' -d '{"email":"x@example.com","password":"wrong-password"}'; done`
  The 11th must be `429`. If it stays `401` the count is too high (the app reads a value
  you control): lower it. If different people on different networks get throttled
  together, it is too low (everyone looks like a proxy): raise it. Change it in Render's
  dashboard and repeat.
- Unsafe settings (debug on, short JWT secret, approval mode without SMTP…) make the API
  refuse to start: read the deploy log if it won't come up.

## Limits and what they mean

- **Render free:** sleeps when idle, and every restart empties the in-memory rate limiter
  and any pending CSV import preview. **One instance only**: scaling out needs Redis for
  both first (see CLAUDE.md).
- **Neon free:** small storage, and a sleeping database wakes on the first query (the
  engine uses `pool_pre_ping`, so stale connections after a pause are handled). Check its
  point-in-time history window in the console; it is short on the free plan.
- **No nightly purge:** Render cron jobs have no free plan. Run `make purge` by hand
  (against the dev DB) or, on a paid plan, add the cron job sketched in `render.yaml`.
- **Vercel Hobby is non-commercial.** Fine for a free personal project; revisit if this
  ever earns money.
- **Privacy:** all API traffic, personal data included, passes through Vercel's network
  on its way to Render. Keep `VITE_LEGAL_HOSTING` and the processors listed in the privacy
  text accurate (Render, Neon, Vercel), and keep Neon and Render in the EU.

## Operating it

- **Opening registration:** set `REGISTRATION_MODE=open` on the API. Nothing else changes.
- Protect `main` (Settings → Rules) by requiring the CI jobs `backend` and `frontend`.
  Keep the bypass list empty, or the rule won't stop you either.
- Dependencies are audited by CI (`pip-audit`, `npm audit`).
