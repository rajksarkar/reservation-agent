# Reservation Agent — Architecture & System Design

> A local tool for automating NYC restaurant reservations across Resy, OpenTable, and Tock. Built with Python, Playwright browser automation, and YAML-based configuration.

---

## System Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    config/config.yaml                         │
│  Credentials, restaurants, scheduler settings, browser opts  │
└────────────────────────────┬────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────┐
│                   Orchestrator (Python)                       │
│                                                              │
│  Reads config → launches Playwright browsers                 │
│  Cancellation monitoring: polls every 120s                   │
│  Release sniping: rapid-polls at 0.5s for 90s at release     │
│  Logs to data/logs/, sessions at data/sessions/              │
└────────────────────────────┬────────────────────────────────┘
                             │
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
         ┌────────┐    ┌──────────┐   ┌────────┐
         │  Resy  │    │ OpenTable│   │  Tock  │
         │Chromium│    │ Firefox  │   │Chromium│
         └────────┘    └──────────┘   └────────┘
```

---

## Directory Structure

```
reservation-agent/
├── config/
│   └── config.yaml                  # All configuration (credentials, restaurants, settings)
├── data/                            # Runtime data (gitignored)
│   ├── logs/                        # Structured JSON logs
│   └── sessions/                    # Playwright browser sessions
├── src/reservation_agent/           # Python source
│   ├── __main__.py                  # CLI entry point (Click)
│   ├── core/
│   │   ├── config.py                # Pydantic config models, YAML loader
│   │   ├── orchestrator.py          # Main orchestrator (polling + snipes)
│   │   ├── scheduler.py             # RapidPoller for release snipes
│   │   └── exceptions.py            # Custom exception hierarchy
│   ├── browser/
│   │   ├── session_manager.py       # Browser lifecycle, persistent sessions
│   │   └── stealth.py               # Anti-detection, request interception
│   ├── platforms/
│   │   ├── base.py                  # BasePlatform ABC, TimeSlot dataclass
│   │   ├── resy.py                  # Resy: Chromium, iframe booking flow
│   │   ├── opentable.py             # OpenTable: Firefox, multi-step booking
│   │   └── tock.py                  # Tock: Chromium, prepaid experiences
│   └── utils/
│       ├── logging.py               # Structlog JSON logging
│       └── retry.py                 # Exponential backoff, circuit breaker
├── tests/                           # Test suite
├── scripts/                         # Helper scripts
├── pyproject.toml                   # Python package config + CLI entry
└── .gitignore
```

---

## CLI Commands

| Command | Description |
|---------|-------------|
| `run` | Start the agent — monitors restaurants from config.yaml |
| `check` | One-off availability check for a restaurant |
| `login-browser` | Open browser to log in manually, saves session |
| `status` | Show configuration summary and session status |

---

## Orchestrator

The `Orchestrator` class is the core loop:

1. Reads enabled restaurants from `config/config.yaml`
2. For each restaurant, gets or creates a platform instance with credentials from config
3. **Cancellation monitoring**: Every `cancellation_poll_interval` seconds, checks availability for each target date and books if a matching slot is found
4. **Release sniping**: Schedules rapid-poll tasks for upcoming release windows (30s before release, polls at 0.5s for 90s)
5. Per-platform concurrency limits: OpenTable=1 (shared Firefox), Resy/Tock=2

---

## Platform Integrations

### Common Interface (`BasePlatform`)

```python
class BasePlatform:
    async def login() → bool
    async def check_session_valid() → bool
    async def check_availability(date, party_size) → AvailabilityResult
    async def book_slot(slot, date, party_size) → BookingResult
```

### Resy (Chromium)
- Availability: Intercepts `api.resy.com/4/find` API responses
- Booking: Click ReservationButton → find "Reserve Now" inside `widgets.resy.com` iframe → confirmation

### OpenTable (Firefox — Chromium blocked)
- Single-page `check_and_book` flow: checks availability and books on the same page
- Guards against "Restaurants you may also like" showing other restaurants' slots
- Filters slots by restaurant name in `aria-label`

### Tock (Chromium)
- Prepaid/ticketed experiences (Eleven Madison Park, Atomix, Per Se)

---

## Browser Management

- **Playwright** with persistent sessions (cookies saved to `data/sessions/`)
- **Browser selection**: Resy/Tock → Chromium, OpenTable → Firefox
- **Stealth**: Custom user agents, hidden webdriver flag, NYC geolocation
- **`force_new=True` pages** for concurrent operations
- Sessions reused across restarts (up to 48h by default)

---

## Key Workflows

### Cancellation Monitoring
```
Every 120s:
  For each enabled restaurant with monitor_cancellations=true:
    Skip unreleased dates (snipe handles those)
    OpenTable: check_and_book() single-page flow
    Resy/Tock: check_availability() → book_slot() if match
```

### Release Snipe
```
Orchestrator detects release window within 2 hours:
  Schedules async task to sleep until 30s before release
  Wakes up → rapid-polls at 0.5s for 90s
  First matching slot → book immediately
```

---

## Technical Decisions

- **Firefox for OpenTable**: OpenTable blocks Chromium-based automation
- **Single-page OpenTable booking**: Separate pages for check/book crashed Firefox; consolidated flow is reliable
- **Resy iframe booking**: "Reserve Now" button is inside a `widgets.resy.com` iframe, not main DOM
- **OpenTable "Also Like" guard**: When no availability, page shows other restaurants' slots with identical selectors; code checks for "no online availability" first
- **`force_new=True` pages**: Prevents concurrent navigation conflicts on shared browser contexts
