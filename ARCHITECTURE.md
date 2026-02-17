# Reservation Agent — Architecture & System Design

> A multi-user SaaS platform for automating NYC restaurant reservations across Resy, OpenTable, and Tock. Built with a Next.js frontend, Python/Playwright worker backend, and Supabase for auth, database, and realtime updates.

---

## Table of Contents

1. [System Overview](#system-overview)
2. [Directory Structure](#directory-structure)
3. [Frontend (Next.js)](#frontend-nextjs)
4. [Backend Worker (Python)](#backend-worker-python)
5. [Database Schema (Supabase)](#database-schema-supabase)
6. [Platform Authentication](#platform-authentication)
7. [Platform Integrations](#platform-integrations)
8. [Key Workflows](#key-workflows)
9. [Infrastructure & Deployment](#infrastructure--deployment)
10. [Technical Decisions & Fixes](#technical-decisions--fixes)

---

## System Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                          User Browser                           │
│                    (Next.js App on Railway)                      │
└────────────────────────────┬────────────────────────────────────┘
                             │ HTTPS
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Next.js 16 (App Router)                       │
│         Railway: <your-railway-domain>.up.railway.app            │
│                                                                  │
│  Pages: Landing, Auth (login/signup/forgot/reset), Dashboard,   │
│         New Reservation Wizard, Platform Management              │
│  API Routes: /api/reservations, /api/platforms, /api/restaurants │
│  Auth: Supabase Auth (email/password + Google OAuth)            │
│  UI: MUI v7 + MUI X Date Pickers                               │
└────────────────────────────┬────────────────────────────────────┘
                             │ Supabase SDK (anon key / service role)
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                     Supabase (Hosted)                            │
│              <your-supabase-ref>.supabase.co                    │
│                                                                  │
│  Auth: Email/password, Google OAuth, password reset              │
│  Database: Postgres with RLS policies                           │
│  Tables: profiles, platform_accounts, restaurants,              │
│          reservation_requests, booking_attempts, activity_log    │
│  Realtime: Postgres changes → Dashboard live updates            │
└────────────────────────────┬────────────────────────────────────┘
                             │ Supabase SDK (service role key)
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                   Python Worker (Railway)                        │
│               reservation-worker service                        │
│                                                                  │
│  Polls Supabase every 30s for active requests                   │
│  Loads browser sessions or decrypts credentials (AES-256-GCM)  │
│  Launches Playwright browsers (Chromium/Firefox)                │
│  Checks availability & books reservations                       │
│  Logs attempts and activities back to Supabase                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Directory Structure

```
reservation-agent/
├── config/                          # YAML configuration files
│   ├── config.yaml                  # Local dev config (credentials, restaurants)
│   └── worker.yaml                  # Minimal Railway worker config
├── data/                            # Local runtime data (gitignored)
│   ├── reservation_agent.db         # SQLite (local mode only)
│   ├── logs/                        # Structured JSON logs
│   └── sessions/                    # Playwright browser sessions
├── launchd/                         # macOS daemon management
│   └── com.reservationagent.daemon.plist
├── scripts/                         # Manual helpers
│   └── authenticate.py              # Manual platform login script
├── src/reservation_agent/           # Python backend
│   ├── __main__.py                  # CLI entry point (Click)
│   ├── api/                         # FastAPI server (legacy local mode)
│   ├── browser/                     # Playwright session management
│   │   ├── session_manager.py       # Browser lifecycle, stealth, sessions
│   │   └── stealth.py               # Request interception, anti-detection
│   ├── core/                        # Business logic
│   │   ├── config.py                # Pydantic config models, YAML loader
│   │   ├── orchestrator.py          # Single-user mode (local)
│   │   ├── multi_user_orchestrator.py  # Multi-user cloud worker
│   │   └── scheduler.py             # APScheduler setup, wake scheduling
│   ├── db/                          # Data access
│   │   ├── models.py                # SQLAlchemy models (local SQLite)
│   │   └── supabase_client.py       # Supabase SDK client (cloud worker)
│   ├── notifications/               # Alerts
│   │   └── email.py                 # SMTP email (booking success, auth failures)
│   ├── platforms/                    # Restaurant platform automations
│   │   ├── base.py                  # BasePlatform ABC, TimeSlot dataclass
│   │   ├── resy.py                  # Resy: Chromium, iframe booking flow
│   │   ├── opentable.py             # OpenTable: Firefox, multi-step booking
│   │   └── tock.py                  # Tock: Chromium, prepaid experiences
│   └── utils/                       # Shared utilities
│       ├── logging.py               # Structlog JSON logging
│       └── retry.py                 # Exponential backoff, circuit breaker
├── supabase/                        # Supabase project files
│   ├── config.toml                  # Supabase local dev config
│   └── migrations/                  # SQL migrations
│       ├── 20260215000001_initial_schema.sql
│       ├── 20260215000002_restaurant_release_schedules.sql
│       └── 20260216000002_nullable_credentials.sql
├── tests/                           # Test suite
│   ├── unit/
│   ├── integration/
│   └── e2e/
├── web/                             # Next.js frontend
│   ├── src/
│   │   ├── app/                     # App Router pages & API routes
│   │   │   ├── page.tsx             # Landing page
│   │   │   ├── layout.tsx           # Root layout (theme, auth provider)
│   │   │   ├── (auth)/              # Auth pages
│   │   │   │   ├── login/page.tsx
│   │   │   │   ├── signup/page.tsx
│   │   │   │   ├── forgot-password/page.tsx
│   │   │   │   ├── reset-password/page.tsx
│   │   │   │   └── auth/callback/route.ts
│   │   │   ├── dashboard/           # Protected dashboard
│   │   │   │   ├── page.tsx         # Stats, recent requests, activity feed
│   │   │   │   ├── layout.tsx       # Sidebar nav, auth guard
│   │   │   │   ├── platforms/page.tsx  # Connect Resy/OpenTable/Tock
│   │   │   │   ├── reservations/
│   │   │   │   │   ├── new/page.tsx    # 4-step reservation wizard
│   │   │   │   │   └── [id]/page.tsx   # Reservation detail + actions
│   │   │   │   ├── activity/page.tsx   # Full activity log
│   │   │   │   └── settings/page.tsx   # User preferences
│   │   │   └── api/                    # API routes (server-side)
│   │   │       ├── reservations/route.ts       # GET/POST reservations
│   │   │       ├── reservations/[id]/route.ts  # GET/DELETE single
│   │   │       ├── restaurants/route.ts        # GET restaurant catalog
│   │   │       └── platforms/[platform]/
│   │   │           ├── connect/route.ts          # POST: verify + encrypt + store (legacy)
│   │   │           ├── verify/route.ts           # GET: dual-mode verify (browser session or credentials)
│   │   │           └── browser-auth/
│   │   │               ├── start/route.ts        # POST: launch BrowserBase session
│   │   │               └── complete/route.ts     # POST: capture session, DELETE: cancel
│   │   ├── lib/                     # Shared libraries
│   │   │   ├── browserbase.ts       # BrowserBase session manager (CDP + Playwright)
│   │   │   ├── crypto.ts            # AES-256-GCM encrypt/decrypt
│   │   │   ├── theme.ts             # MUI dark theme (indigo primary, Inter font)
│   │   │   └── supabase/
│   │   │       ├── client.ts        # Browser Supabase client
│   │   │       └── server.ts        # Server Supabase client (cookies)
│   │   └── components/
│   │       └── ThemeProvider.tsx     # MUI theme configuration
│   ├── Dockerfile                   # Multi-stage Node.js build
│   ├── railway.toml                 # Railway deployment config
│   ├── next.config.ts               # standalone output, React compiler
│   ├── package.json                 # Dependencies
│   └── .dockerignore
├── Dockerfile                       # Python worker Docker build
├── railway.toml                     # Railway worker config
├── .dockerignore                    # Excludes web/, secrets, sessions
└── pyproject.toml                   # Python package config + CLI entry
```

---

## Frontend (Next.js)

### Tech Stack
- **Next.js 16** (App Router) with **React 19**
- **MUI v7** (Material-UI) for all components
- **MUI X Date Pickers v8** for calendar date selection
- **Supabase SSR** (`@supabase/ssr`) for auth + database
- **BrowserBase SDK** (`@browserbasehq/sdk`) + **Playwright Core** for cloud browser auth
- **date-fns** for date formatting

### Pages

| Route | Description |
|-------|-------------|
| `/` | Landing page — hero, features, CTA |
| `/login` | Email/password + Google OAuth login |
| `/signup` | Account creation + Google OAuth |
| `/forgot-password` | Send password reset email |
| `/reset-password` | Set new password (from email link) |
| `/dashboard` | Stats cards, recent requests table, activity feed |
| `/dashboard/reservations/new` | 4-step wizard: Restaurant → Dates/Times → Options → Review |
| `/dashboard/reservations/[id]` | Detail view with Pause/Resume/Cancel/Delete actions |
| `/dashboard/platforms` | Connect platforms via BrowserBase cloud browser auth |
| `/dashboard/activity` | Full activity log |
| `/dashboard/settings` | Notification preferences |

### New Reservation Wizard (4 Steps)

1. **Restaurant Selection**: Autocomplete search across 50+ NYC restaurants. Shows platform badge, cuisine, neighborhood, price range. Displays release schedule info (e.g., "Releases 30 days ahead at 10:00 AM"). Shows **snipe cutoff date** — the first date whose slots haven't been released yet (e.g., "Feb 23 onwards: slots not yet released — available via snipe").

2. **Date & Time**: MUI `DateCalendar` with click-to-select/deselect dates (highlighted in primary color). Time range chips: Morning, Lunch, Afternoon, Dinner, Late Night. **Platform connection check** — warns with alert + "Connect Now" button if the required platform (Resy/OpenTable/Tock) isn't connected yet. **Slot Release Schedule card** — shows which selected dates are already released (monitored for cancellations) vs. unreleased (sniped when they open). Uses `Intl.DateTimeFormat` with `America/New_York` timezone for accurate ET offset calculation (do NOT use `date-fns-tz` — it had timezone comparison bugs).

3. **Options**: Toggle cancellation monitoring and release snipe. **Auto-configured** based on date analysis — if all selected dates are unreleased, cancellation monitoring is disabled (no existing slots to monitor) and release snipe is enabled. If all dates are already released, the opposite. Mixed dates get both enabled. Party size selector.

4. **Review**: Summary of all selections with per-date monitoring strategy breakdown (which dates get cancellation monitoring vs. snipe).

### API Routes

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/restaurants` | GET | List all restaurants from catalog |
| `/api/reservations` | GET | User's reservation requests (with restaurant join) |
| `/api/reservations` | POST | Create new reservation request (auto-derives `release_snipe` and `monitor_cancellations` from release schedule) |
| `/api/reservations/[id]` | GET | Single request detail |
| `/api/reservations/[id]` | DELETE | Delete a request |
| `/api/platforms/[platform]/connect` | POST | Legacy: verify credentials with platform API, encrypt, store |
| `/api/platforms/[platform]/verify` | GET | Dual-mode: return browser session status or decrypted username |
| `/api/platforms/[platform]/browser-auth/start` | POST | Launch BrowserBase cloud browser, return live view URL |
| `/api/platforms/[platform]/browser-auth/complete` | POST | Capture browser session (cookies/localStorage), store in Supabase |
| `/api/platforms/[platform]/browser-auth/complete` | DELETE | Cancel and clean up BrowserBase session |

### Realtime Updates
The dashboard subscribes to Supabase Realtime (Postgres changes on `reservation_requests` table). When the worker updates a request status (e.g., `active` → `booked`), the dashboard updates live without refresh.

---

## Backend Worker (Python)

### CLI Commands (`reservation-agent`)

| Command | Mode | Description |
|---------|------|-------------|
| `run` | Local | Start single-user daemon with local config.yaml |
| `worker` | Cloud | Multi-user mode — polls Supabase for all users |
| `serve` | Local | FastAPI dashboard (legacy) |
| `check` | Manual | One-off availability check |
| `status` | Info | Show agent statistics |
| `init-db` | Setup | Initialize local SQLite database |

### Multi-User Orchestrator (Cloud Worker)

The `MultiUserOrchestrator` is the core of the Railway deployment:

1. **Polls** Supabase every 30s for `status='active'` reservation requests
2. **Caches** platform instances per `(user_id, platform)` tuple
3. **Auth**: Loads browser session data (cookies/localStorage) or decrypts credentials (AES-256-GCM) — supports both auth methods
4. **Processes** up to 3 requests concurrently (asyncio semaphore)
5. **Checks** availability using Playwright browser automation
6. **Books** slots when matches are found
7. **Logs** all attempts and activities back to Supabase

### Single-User Orchestrator (Local Mode)

For running on a personal machine (e.g., Mac with launchd):

- Loads restaurants + credentials from `config/config.yaml`
- Uses local SQLite for state
- **APScheduler** with:
  - Release snipe scheduling (fires 30s before release, rapid-polls at 0.5s for 90s)
  - Cancellation monitoring (polls every 120s)
  - macOS wake scheduling (`sudo pmset schedule wake`)
  - Missed snipe recovery on startup
  - Extended `misfire_grace_time` (7200s) for laptop sleep handling
- Circuit breakers per platform (5 failures → 60s cooldown)
- Email notifications via SMTP

### Browser Management

- **Playwright** with persistent sessions (cookies saved to disk)
- **Browser selection**:
  - Resy, Tock → Chromium
  - OpenTable → Firefox (Chromium is blocked by OpenTable)
- **Stealth features**: Custom user agents, hidden webdriver flag, NYC geolocation
- **`force_new=True` pages** for concurrent operations (prevents navigation conflicts)

---

## Database Schema (Supabase)

### Entity Relationship

```
auth.users (Supabase managed)
    │
    ├──1:1──► profiles (auto-created on signup via trigger)
    │
    ├──1:N──► platform_accounts (encrypted Resy/OpenTable/Tock creds)
    │
    ├──1:N──► reservation_requests
    │             │
    │             ├──1:N──► booking_attempts (snipe/cancel check logs)
    │             │
    │             └──FK────► restaurants (shared catalog)
    │
    └──1:N──► activity_log (user-facing event feed)
```

### Tables

#### `profiles`
| Column | Type | Notes |
|--------|------|-------|
| id | uuid (PK) | References `auth.users(id)` |
| email | text | |
| full_name | text | |
| avatar_url | text | |
| notification_email | boolean | Default true |
| notification_sms | boolean | Default false |
| phone | text | |
| created_at, updated_at | timestamptz | |

**RLS**: Users can view/update own profile only.
**Trigger**: `on_auth_user_created` auto-inserts profile row.

#### `platform_accounts`
| Column | Type | Notes |
|--------|------|-------|
| id | uuid (PK) | |
| user_id | uuid (FK) | References `auth.users(id)` |
| platform | text | `resy`, `opentable`, or `tock` |
| session_data | jsonb | BrowserBase-captured cookies/localStorage (primary auth method) |
| encrypted_username | text (nullable) | AES-256-GCM ciphertext (legacy credential auth) |
| encrypted_password | text (nullable) | AES-256-GCM ciphertext (legacy credential auth) |
| encryption_iv | text (nullable) | Pipe-separated: `username_iv\|password_iv` |
| encryption_tag | text (nullable) | Pipe-separated: `username_tag\|password_tag` |
| is_connected | boolean | |
| last_verified_at | timestamptz | |

**RLS**: Users can CRUD own accounts. Unique on `(user_id, platform)`.
**Dual auth**: Accounts can have either `session_data` (browser auth) or encrypted credentials (legacy). Credential columns are nullable since migration `20260216000002`.

#### `restaurants`
| Column | Type | Notes |
|--------|------|-------|
| id | uuid (PK) | |
| name | text | |
| platform | text | `resy`, `opentable`, `tock`, `yelp`, `phone`, `own_site` |
| venue_id | text | Platform-specific slug |
| city | text | Default 'New York' |
| cuisine, neighborhood | text | |
| price_range | smallint | 1–4 |
| release_time | time | When new slots drop (e.g., 10:00) |
| release_days_ahead | smallint | How far ahead slots release (e.g., 30) |
| release_schedule_notes | text | Special cases (e.g., "1st of prev. month") |

**RLS**: Publicly readable. Unique on `(platform, venue_id)`.
**Seed data**: 54 NYC restaurants (43 Resy, 8 OpenTable, 3 Tock) with release schedules sourced from nycrsvps.com.

#### `reservation_requests`
| Column | Type | Notes |
|--------|------|-------|
| id | uuid (PK) | |
| user_id | uuid (FK) | References `auth.users(id)` |
| restaurant_id | uuid (FK) | References `restaurants(id)` |
| party_size | smallint | 1–20, default 2 |
| target_dates | date[] | Array of dates to check |
| preferred_times | text[] | e.g., `['18:00-20:00', '20:00-22:00']` |
| status | enum | `active`, `paused`, `booked`, `cancelled`, `expired` |
| monitor_cancellations | boolean | Check for cancelled slots |
| release_snipe | boolean | Snipe at release time |
| release_time, release_days_ahead | | Override restaurant defaults |
| booked_date, booked_time | | Filled on successful booking |
| confirmation_number | text | |
| notes | text | |

**RLS**: Users can CRUD own requests.
**Index**: `idx_reservation_requests_active` on `status WHERE status = 'active'` (worker polling).

#### `booking_attempts`
| Column | Type | Notes |
|--------|------|-------|
| id | uuid (PK) | |
| request_id | uuid (FK) | References `reservation_requests(id)` |
| attempt_type | enum | `snipe`, `cancellation_check`, `manual` |
| result | enum | `success`, `no_availability`, `slot_taken`, `auth_failed`, `error` |
| slot_time | text | |
| error_message | text | |
| duration_ms | integer | |

**RLS**: Users can view via join on `reservation_requests`. Service role can insert.

#### `activity_log`
| Column | Type | Notes |
|--------|------|-------|
| id | uuid (PK) | |
| user_id | uuid (FK) | |
| request_id | uuid (FK, nullable) | |
| event_type | text | e.g., `platform_connected`, `booking_success` |
| title | text | Human-readable title |
| description | text | |
| metadata | jsonb | Extra data |

**RLS**: Users can view own. Service role can insert.

---

## Platform Authentication

Two auth methods are supported. BrowserBase browser auth is the primary method; credential-based auth is legacy but still functional.

### BrowserBase Browser Auth (Primary)

Users authenticate directly with Resy/OpenTable/Tock through a BrowserBase cloud browser. This supports any login method (email/password, Google OAuth, Apple ID, social login) without credentials ever passing through our UI.

#### Flow

```
1. User clicks "Connect Account" on platforms page
    ↓
2. POST /api/platforms/[platform]/browser-auth/start
    → Creates BrowserBase cloud browser session (viewport 1280x800)
    → Connects via Chrome DevTools Protocol (CDP)
    → Navigates to platform login page
    → Returns { authSessionId, liveViewUrl }
    ↓
3. Frontend opens liveViewUrl in popup window (1300x850)
    → User sees native platform login UI
    → Logs in with any method (Google, email, etc.)
    ↓
4. User clicks "I'm Logged In" back in the app
    ↓
5. POST /api/platforms/[platform]/browser-auth/complete
    → Extracts full storage state (cookies + localStorage) via CDP
    → Upserts to platform_accounts with session_data
    → Closes BrowserBase browser
    → Logs platform_connected activity
```

#### Session Manager (`web/src/lib/browserbase.ts`)

- In-memory session tracking with UUID-based session IDs
- 10-minute TTL per session with auto-cleanup every 60s
- Stores active Playwright browser + page connections
- `cancelBrowserAuth()` for cleanup when user closes dialog without completing

#### Login URLs by Platform

| Platform | Login URL |
|----------|-----------|
| Resy | `https://resy.com/login` |
| OpenTable | `https://www.opentable.com/sign-in` |
| Tock | `https://www.exploretock.com/login` |

#### Why Popup Instead of Iframe

BrowserBase's live view URL has X-Frame-Options restrictions that block embedding in iframes. Additionally, Google OAuth and other third-party login flows open their own popups, which are blocked when nested inside an iframe. The solution uses `window.open()` to launch a dedicated popup window.

### Credential-Based Auth (Legacy)

Still supported for backward compatibility. User platform credentials are encrypted at rest using **AES-256-GCM** with per-user key derivation.

#### Key Derivation
```
master_key = process.env.ENCRYPTION_KEY  (shared secret)

Step 1: salt = PBKDF2(user_id, master_key, iterations=1, keylen=32, digest=sha256)
Step 2: derived_key = PBKDF2(master_key, salt, iterations=100000, keylen=32, digest=sha256)
```

Each user gets a unique encryption key derived from the master key + their user ID.

#### Encrypt (Next.js API route → Supabase)
```
iv = random 16 bytes
cipher = AES-256-GCM(derived_key, iv)
encrypted = cipher.update(plaintext) + cipher.final()
tag = cipher.getAuthTag()

Stored: { encrypted (hex), iv (hex), tag (hex) }
```

Username and password are encrypted separately. The `encryption_iv` and `encryption_tag` columns store pipe-separated values: `username_iv|password_iv` and `username_tag|password_tag`.

#### Decrypt (Python worker → platform login)
The Python `supabase_client.py` implements the identical key derivation and AES-256-GCM decryption, ensuring the worker can read credentials stored by the frontend.

### Verify Route (Dual-Mode)

The `/api/platforms/[platform]/verify` route detects the auth method and responds accordingly:

- **Browser session auth** (has `session_data`, no `encrypted_username`): Returns `{ authMethod: "browser", username: "Browser session", verified: true }`
- **Credential auth** (has `encrypted_username`): Decrypts and returns `{ authMethod: "credentials", username: "user@example.com", verified: true }`

---

## Platform Integrations

### Common Interface (`BasePlatform`)

```python
class BasePlatform:
    async def login() → bool
    async def check_session_valid() → bool
    async def check_availability(date, party_size) → list[TimeSlot]
    async def book_slot(slot, date, party_size) → dict
    async def get_page(force_new=False) → Page

@dataclass
class TimeSlot:
    time: str          # "19:00" (24h format)
    slot_id: str       # Platform-specific identifier
    slot_type: str     # "Dining Room", "Bar", "Counter"
    deposit_required: float | None
```

### Resy (Chromium)

- **Login**: Email/password form with multiple fallback selectors
- **Availability**: Intercepts `api.resy.com/4/find` API responses via request interception
- **Booking flow**:
  1. Click `ReservationButton` → Opens `widgets.resy.com` iframe
  2. Find "Reserve Now" button inside iframe: `button.Button--primary.Button--lg`
  3. Click → Confirmation appears in same iframe ("Reservation Booked")
- **Session trust**: Reuses sessions up to 168 hours old

### OpenTable (Firefox — Chromium is blocked)

- **Login**: Standard email/password form
- **Availability**: Scrapes slot elements: `li[data-test^="time-slot-"] a[role="button"]`
- **Critical guard**: Checks for "no online availability" message before parsing DOM (page shows "Restaurants you may also like" with other restaurants' slots using identical selectors)
- **aria-label filter**: Validates slot's aria-label contains target restaurant name
- **Single-page `check_and_book` flow**: Availability checking and booking are consolidated into one Playwright page session to prevent Firefox crashes from redundant page navigations and stale browser contexts. The method:
  1. Opens the restaurant page and checks for available slots
  2. If a matching slot is found, clicks it on the same page
  3. Handles optional "seating-options" intermediate page (prefers non-outdoor seating)
  4. Handles optional "specials" page
  5. Clicks "Complete Reservation" and verifies confirmation
- **Helper methods**: `_to_display_time`, `_click_time_slot`, `_handle_seating_options`, `_handle_specials`, `_click_confirm_and_verify` — shared between snipe and cancellation-monitoring paths
- **Page management**: `force_new=True` pages, closed in `finally` block
- **Used by both paths**: `_opentable_snipe_attempt` (for release snipes) and `_opentable_poll_attempt` (for cancellation monitoring) in the orchestrator both call `check_and_book`

### Tock (Chromium)

- **Used for**: Prepaid/ticketed experiences (Eleven Madison Park, Atomix, Per Se)
- **Login**: `POST exploretock.com/api/consumer/login`

---

## Key Workflows

### 1. User Creates a Reservation Request

```
User fills 4-step wizard in frontend
    ↓
POST /api/reservations → inserts to reservation_requests (status='active')
    ↓
Python worker polls Supabase (every 30s) → finds new request
    ↓
Worker fetches user's platform_accounts
    ↓
If session_data: load cookies/localStorage into browser
If encrypted credentials: decrypt → log into platform
    ↓
Worker launches Playwright browser
    ↓
Worker calls check_availability(date, party_size)
    ↓
If slots found matching preferred_times:
    → book_slot() → update status to 'booked' → log activity
If no slots:
    → log attempt (no_availability) → retry next poll cycle
    ↓
Dashboard updates in realtime via Supabase subscription
```

### 2. Platform Connection (BrowserBase Auth)

```
User clicks "Connect Account" for Resy/OpenTable/Tock
    ↓
POST /api/platforms/[platform]/browser-auth/start
    → BrowserBase creates cloud Chromium browser
    → Playwright connects via CDP
    → Navigates to platform login page
    → Returns authSessionId + liveViewUrl
    ↓
Frontend opens liveViewUrl in popup window (1300x850)
    ↓
User logs in natively (Google OAuth, email/password, etc.)
    ↓
User clicks "I'm Logged In" in the app dialog
    ↓
POST /api/platforms/[platform]/browser-auth/complete
    → Captures cookies + localStorage from browser
    → Upserts platform_accounts with session_data (jsonb)
    → Closes BrowserBase session
    → Logs platform_connected to activity_log
    ↓
Dashboard shows "Authenticated via browser session"
```

### 3. Release Snipe (Local Mode)

```
Scheduler calculates: release_datetime - 30 seconds
    ↓
Schedules macOS wake: sudo pmset schedule wake <time>
    ↓
Job fires → RapidPoller starts (0.5s interval, 90s duration)
    ↓
check_availability() called rapidly
    ↓
First matching slot found → book_slot() → send email notification
    ↓
If missed (laptop was sleeping): misfire_grace_time=7200s catches it
On startup: if release time passed but status=PENDING → fire immediately
```

### 4. Cancellation Monitoring

```
Every 120s (configurable):
    ↓
For each active request with monitor_cancellations=true:
    ↓
Skip dates where _is_date_unreleased() is true (no slots exist yet)
    ↓
For OpenTable: platform.check_and_book() (single-page flow)
For Resy/Tock: check_availability() → book_slot() if match found
    ↓
Circuit breaker: 5 consecutive failures → 60s cooldown per platform
```

---

## Infrastructure & Deployment

### Railway Services

| Service | Type | URL/Status |
|---------|------|------------|
| **web** | Next.js (Dockerfile) | `https://<your-railway-domain>.up.railway.app` |
| **worker** | Python/Playwright (Dockerfile) | Running, polling Supabase |

**Railway Project**: `reservation-worker` (ID: `<your-railway-project-id>`)

### Environment Variables

#### Web Service (Next.js)
| Variable | Description |
|----------|-------------|
| `NEXT_PUBLIC_SUPABASE_URL` | `https://<your-supabase-ref>.supabase.co` |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Supabase anon/public key |
| `SUPABASE_SERVICE_ROLE_KEY` | Supabase service role key (server-side only) |
| `ENCRYPTION_KEY` | Master key for credential encryption (legacy auth) |
| `BROWSERBASE_API_KEY` | BrowserBase API key for cloud browser sessions |
| `BROWSERBASE_PROJECT_ID` | BrowserBase project identifier |

#### Worker Service (Python)
| Variable | Description |
|----------|-------------|
| `SUPABASE_URL` | Same Supabase URL |
| `SUPABASE_SERVICE_ROLE_KEY` | Same service role key |
| `ENCRYPTION_KEY` | Same master encryption key (must match frontend) |

### Docker Builds

**Python Worker** (`Dockerfile`):
- Base: `python:3.11-slim`
- Installs Playwright system deps + Chromium + Firefox
- Copies `config/worker.yaml` as config
- CMD: `reservation-agent -c config/config.yaml worker`

**Next.js Web** (`web/Dockerfile`):
- Base: `node:20-alpine`
- Multi-stage: deps → build (with `NEXT_PUBLIC_*` build args) → production runner
- Output: Next.js standalone `server.js`
- Runs as non-root `nextjs` user

### Local Development (macOS)

- **launchd plist** at `launchd/com.reservationagent.daemon.plist`
- Runs `reservation-agent run` on boot
- Python path: `/opt/anaconda3/bin/python`
- Logs to `data/logs/daemon.{stdout,stderr}.log`
- KeepAlive with Nice 10 (low priority)

### Supabase

- **Project ref**: `<your-supabase-ref>`
- **Region**: `aws-0-us-east-1`
- **Auth**: Email/password + Google OAuth
- **Site URL**: `https://<your-railway-domain>.up.railway.app`
- **Redirect URLs**: `https://<your-railway-domain>.up.railway.app/**`
- **Migrations**: Managed via `supabase db push` from `supabase/migrations/`

---

## Technical Decisions & Fixes

### Browser Concurrency
- `check_availability` and `book_slot` each use `force_new=True` pages to avoid concurrent navigation conflicts on shared browser contexts.

### APScheduler Tuning
- `max_instances`: 1 → 3 (prevents job skipping when previous instance is still running)
- `cancellation_poll_interval`: 60s → 120s (prevents job backlog)
- `misfire_grace_time`: 7200s (handles laptop sleep/wake delays)

### OpenTable "Also Like" Guard
- When a restaurant has no availability, OpenTable shows "Restaurants you may also like" with other restaurants' slots using **identical CSS selectors**. The code checks for "no online availability" text first and filters slots by restaurant name in `aria-label` to avoid booking the wrong venue.

### Resy Iframe Booking
- The "Reserve Now" button lives inside a `widgets.resy.com` iframe, not the main page DOM. The code iterates `page.frames` to find the widget iframe, with fallback to main page search.

### Firefox for OpenTable
- OpenTable actively blocks Chromium-based automation. Firefox with Playwright bypasses this detection.

### Session Reuse
- Playwright sessions (cookies/localStorage) are persisted to disk and reused for up to 168 hours, avoiding repeated logins and reducing detection risk.

### BrowserBase Over Credential Forms
- Users authenticate directly with platform login pages through a BrowserBase cloud browser rather than entering credentials into our UI. This supports OAuth/social login, avoids credential handling liability, and provides a trusted native login experience. Session data (cookies/localStorage) is captured server-side via CDP after the user completes login.

### Popup Window for BrowserBase Live View
- BrowserBase's live view URL cannot be embedded in an iframe (X-Frame-Options restrictions). Google OAuth and other third-party login flows also open popups that are blocked when nested inside iframes. The solution uses `window.open()` to launch BrowserBase in a dedicated popup window (1300x850, centered).

### In-Memory Session TTL
- BrowserBase sessions are tracked in-memory with a 10-minute TTL and auto-cleanup every 60s. This prevents stale sessions from consuming BrowserBase resources if users abandon the auth flow.

### Credential Verification Before Storage (Legacy)
- Platform credentials are verified against the actual platform API before being encrypted and stored. This prevents users from entering wrong passwords and wondering why bookings fail.

### OpenTable Single-Page Booking (`check_and_book`)
- Opening separate pages for checking availability and then booking caused Firefox to crash from stale browser contexts and redundant page navigations. The fix consolidates both operations into a single Playwright page session — the same page that loads availability also clicks the slot and completes the booking. This eliminated crashes and improved reliability for both snipe and cancellation-monitoring flows.

### Stale Browser Context Detection
- The `SessionManager` detects dead Playwright browser contexts by catching errors on `context.new_page()`. When a stale context is detected, it explicitly closes the old context and browser, then creates fresh ones. This prevents memory leaks and cascading failures.

### Release Schedule Auto-Configuration
- The frontend and API both analyze target dates against the restaurant's release schedule (`release_days_ahead`, `release_time`) to auto-derive `release_snipe` and `monitor_cancellations` flags. Dates whose slots haven't been released yet get release snipe; dates with already-released slots get cancellation monitoring. The worker's `_is_date_unreleased()` helper also skips cancellation polling for unreleased dates (there are no existing slots to monitor for cancellations).

### ET Timezone Calculations (Frontend)
- Use `Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York' })` to determine the current ET offset, then perform all comparisons in UTC. Do NOT use `date-fns-tz` — its `toZonedTime()` function caused incorrect date comparisons that made the auto-configuration logic fail silently.

### Railway Web Service Deployment
- The web service and worker service share the same Railway project. Without `--path-as-root`, `railway up` uploads the entire repo root and picks up the root Python `Dockerfile` instead of `web/Dockerfile`, causing the web service to run the Python worker and crash with `KeyError: 'SUPABASE_URL'`. Always deploy with `railway up web/ --path-as-root`.

### Dark Theme Design
- The frontend uses a centralized dark theme (`web/src/lib/theme.ts`) with indigo primary (#6366f1), amber secondary (#f59e0b), deep black backgrounds (#0a0a0a/#141414), 12px border radius, Inter font, and no-transform buttons. This creates a cohesive modern aesthetic across all pages.
