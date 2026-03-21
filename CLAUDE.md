# Reservation Agent — Claude Code Instructions

## Running Locally

### Prerequisites
- Python 3.11+
- Playwright browsers installed: `playwright install chromium firefox`

### Setup
```bash
pip install -e .
```

### Commands
```bash
# Start the agent (monitors restaurants from config.yaml)
reservation-agent run

# With custom config path
reservation-agent -c config/config.yaml run

# Dry run (no actual bookings)
reservation-agent --dry-run run

# One-off availability check
reservation-agent check -r "Carbone" -d 2026-03-20

# Log in to a platform and save browser session
reservation-agent login-browser -p resy
reservation-agent login-browser -p opentable

# Show status
reservation-agent status
```

### Configuration
All config lives in `config/config.yaml`:
- Platform credentials (resy, opentable, tock)
- Restaurant list with target dates, times, party size
- Scheduler settings (poll interval, snipe timing)
- Browser settings (headless, timeout, sessions dir)

### Key Architecture Notes
- See `ARCHITECTURE.md` for full system design
- Single-user local app — reads config.yaml, runs Playwright browsers
- Sessions persisted at `data/sessions/` (reused across restarts)
- Logs at `data/logs/`
- Platforms: Resy (Chromium), OpenTable (Firefox — blocks Chromium), Tock (Chromium)
