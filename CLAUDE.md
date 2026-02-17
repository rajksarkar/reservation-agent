# Reservation Agent — Claude Code Instructions

## Deployment Pipeline

After ANY code changes, always run this full deploy sequence automatically:

### 1. Git — Commit & Push
```bash
git add <changed files>
git commit -m "<descriptive message>"
git push origin <current-branch>
```

### 2. Supabase — Apply Migrations
If any files changed in `supabase/migrations/`:
```bash
supabase db push
```
Requires `SUPABASE_ACCESS_TOKEN` env var or `supabase login` first.
Project ref: `<your-supabase-project-ref>`

### 3. Railway — Redeploy Worker & Web

Both services live in the **same Railway project** (`<your-railway-project-id>`).
Deploy them separately:

```bash
# Deploy the worker (from repo root — uses root Dockerfile)
railway link --project <your-railway-project-id> --environment production --service reservation-worker
railway up

# Deploy the web frontend — MUST use --path-as-root to scope build context to web/
railway link --project <your-railway-project-id> --environment production --service web
railway up web/ --path-as-root
```

**CRITICAL:** The web service **must** be deployed with `railway up web/ --path-as-root` (from repo root).
Without `--path-as-root`, Railway uploads the entire repo and picks up the root Python Dockerfile instead of `web/Dockerfile`.

- Worker service name: `reservation-worker`
- Web service name: `web`
- After deploying web, re-link to worker: `railway link --project <your-railway-project-id> --environment production --service reservation-worker`

### Prerequisites
These CLI tools and auth tokens must be available:
- `git` (configured with GitHub access)
- `supabase` CLI with `SUPABASE_ACCESS_TOKEN` set
- `railway` CLI with `RAILWAY_TOKEN` set (install: `npm i -g @railway/cli`)

## Key Architecture Notes
- See `ARCHITECTURE.md` for full system design
- Python worker on Railway polls Supabase for active reservation requests
- Next.js frontend on Railway serves the web dashboard
- Browser sessions can be captured locally via `reservation-agent login-browser` and uploaded to Supabase
