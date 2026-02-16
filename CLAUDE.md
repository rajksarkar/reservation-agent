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
Project ref: `wibcyyhqpyutxikfnqsn`

### 3. Railway — Redeploy Worker & Web
```bash
railway up
```
Or if Railway is connected to the git branch, the push in step 1 triggers auto-deploy.

Railway project ID: `b596e976-3dab-4c69-b40e-dbea6b633597`

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
