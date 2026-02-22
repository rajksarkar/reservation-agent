# Reservation Agent

A multi-user SaaS platform for automating NYC restaurant reservations across Resy, OpenTable, and Tock. Built with a Next.js frontend, Python/Playwright worker backend, and Supabase for auth, database, and realtime updates.

## Features

- **Release Sniping**: Automatically books reservations the moment they become available, with sub-second polling
- **Cancellation Monitoring**: Continuously monitors for cancellations and books when slots open
- **Multi-Platform Support**: Resy (Chromium), OpenTable (Firefox), and Tock (Chromium)
- **BrowserBase Cloud Auth**: Users authenticate with platforms via a cloud browser — supports Google OAuth, Apple ID, and any login method without credentials ever passing through our UI
- **4-Step Reservation Wizard**: Restaurant search (50+ NYC venues) with release schedule info, date/time selection, smart auto-configuration of snipe vs. monitor strategies, and review
- **Realtime Dashboard**: Live updates via Supabase Realtime subscriptions — no refresh needed
- **Smart Date Analysis**: Auto-detects which dates need release sniping vs. cancellation monitoring based on each restaurant's release schedule
- **Email Notifications**: Get notified on booking success or auth failures
- **Dual Deployment**: Cloud mode (Railway + Supabase, multi-user) or local mode (macOS daemon, single-user)

## Architecture

```
User Browser → Next.js 16 (Railway) → Supabase (Auth, Postgres, Realtime) → Python Worker (Railway)
```

- **Frontend**: Next.js 16 (App Router), React 19, MUI v7, deployed on Railway
- **Backend**: Python worker with Playwright browser automation, deployed on Railway
- **Database**: Supabase Postgres with RLS policies, realtime subscriptions
- **Auth**: Supabase Auth (email/password + Google OAuth) for the app; BrowserBase cloud browsers for platform authentication

See [ARCHITECTURE.md](ARCHITECTURE.md) for full system design, database schema, and detailed workflows.

## Quick Start (Cloud Deployment)

### Prerequisites

- Node.js 20+, Python 3.11+
- [Supabase](https://supabase.com) project
- [Railway](https://railway.app) project
- [BrowserBase](https://browserbase.com) account (for platform auth)
- CLI tools: `supabase`, `railway`

### 1. Set Up Supabase

Apply database migrations:
```bash
supabase db push
```

Configure Supabase Auth with email/password and Google OAuth. Set the site URL to your Railway web domain.

### 2. Deploy the Worker

```bash
railway link --environment production --service reservation-worker
railway up
```

Required env vars: `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `ENCRYPTION_KEY`

### 3. Deploy the Web Frontend

```bash
railway link --environment production --service web
railway up web/ --path-as-root
```

**Important**: `--path-as-root` is required so Railway uses `web/Dockerfile` instead of the root Python Dockerfile.

Required env vars: `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`, `ENCRYPTION_KEY`, `BROWSERBASE_API_KEY`, `BROWSERBASE_PROJECT_ID`

### 4. Connect Platforms

1. Sign up at the web dashboard
2. Go to Dashboard > Platforms
3. Click "Connect Account" for Resy, OpenTable, or Tock
4. Log in through the BrowserBase cloud browser popup (supports Google OAuth, email/password, etc.)
5. Session data is captured and stored securely

### 5. Create a Reservation Request

Use the 4-step wizard in Dashboard > New Reservation:
1. **Restaurant**: Search and select from 50+ NYC restaurants
2. **Dates & Times**: Pick dates and time ranges; see which dates are released vs. unreleased
3. **Options**: Auto-configured snipe/monitor strategy based on date analysis
4. **Review**: Confirm and submit

The worker automatically picks up active requests and begins monitoring.

## Quick Start (Local Mode)

For running as a single-user agent on macOS:

### 1. Install

```bash
pip install -e .
playwright install chromium firefox
```

### 2. Configure

```bash
cp config/config.example.yaml config/config.yaml
```

Edit `config/config.yaml` with your restaurant preferences.

### 3. Run

```bash
# Start the agent
reservation-agent run

# Or as a background daemon via launchd
launchctl load ~/Library/LaunchAgents/com.reservationagent.daemon.plist
```

## CLI Commands

| Command | Mode | Description |
|---------|------|-------------|
| `reservation-agent run` | Local | Start single-user daemon with local config |
| `reservation-agent worker` | Cloud | Multi-user mode — polls Supabase for all users |
| `reservation-agent serve` | Local | Legacy FastAPI dashboard |
| `reservation-agent check` | Manual | One-off availability check |
| `reservation-agent status` | Info | Show agent statistics |
| `reservation-agent init-db` | Setup | Initialize local SQLite database |

## How It Works

### Release Sniping

1. Agent calculates when reservations will be released (target date minus release_days_ahead)
2. Schedules a job 30 seconds before release time (local mode also schedules macOS wake via `pmset`)
3. Rapid-polls every 500ms for 90 seconds looking for available slots
4. Books the first slot matching preferred times
5. Handles missed snipes (laptop sleep) with 2-hour misfire grace time

### Cancellation Monitoring

1. Polls for availability every 120 seconds
2. Skips dates that haven't been released yet (no existing slots to monitor)
3. Circuit breaker: 5 consecutive failures trigger a 60-second cooldown per platform
4. Books immediately when a matching slot appears

### Platform-Specific Details

- **Resy**: Intercepts `api.resy.com` API responses for availability; books via iframe widget
- **OpenTable**: Single-page `check_and_book` flow — checks availability and books on the same Playwright page to prevent Firefox crashes; filters slots by restaurant name in aria-label to avoid booking wrong venues from "you may also like" suggestions
- **Tock**: Prepaid/ticketed experiences (Eleven Madison Park, Atomix, Per Se)

## Project Structure

```
reservation-agent/
├── config/                          # YAML configuration files
│   ├── config.yaml                  # Local dev config
│   └── worker.yaml                  # Railway worker config
├── src/reservation_agent/           # Python backend
│   ├── __main__.py                  # CLI entry point (Click)
│   ├── browser/                     # Playwright session management + stealth
│   ├── core/                        # Orchestrators, scheduler, config
│   ├── db/                          # SQLAlchemy models + Supabase client
│   ├── notifications/               # Email alerts (SMTP)
│   ├── platforms/                   # Resy, OpenTable, Tock automation
│   └── utils/                       # Logging, retry, circuit breaker
├── web/                             # Next.js frontend
│   ├── src/app/                     # App Router pages & API routes
│   │   ├── (auth)/                  # Login, signup, password reset
│   │   ├── dashboard/               # Protected dashboard pages
│   │   │   ├── reservations/new/    # 4-step reservation wizard
│   │   │   ├── platforms/           # Platform connection management
│   │   │   └── activity/            # Activity log
│   │   └── api/                     # Server-side API routes
│   ├── src/lib/                     # Supabase clients, crypto, theme, BrowserBase
│   └── Dockerfile                   # Multi-stage Node.js build
├── supabase/                        # Supabase project
│   └── migrations/                  # SQL migrations (schema, RLS, triggers)
├── Dockerfile                       # Python worker Docker build
├── launchd/                         # macOS daemon management
└── pyproject.toml                   # Python package config + CLI entry
```

## Security

- Platform credentials encrypted at rest with AES-256-GCM and per-user derived keys
- BrowserBase auth avoids credential handling — users log in directly with platforms
- Supabase Row Level Security (RLS) on all tables
- Credential verification before storage (legacy auth)
- Never commit `config.yaml` with real credentials

## License

MIT
