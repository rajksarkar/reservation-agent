# Reservation Agent

A local tool for automating NYC restaurant reservations across Resy, OpenTable, and Tock. Built with Python and Playwright browser automation.

## Features

- **Release Sniping**: Automatically books reservations the moment they become available, with sub-second polling
- **Cancellation Monitoring**: Continuously monitors for cancellations and books when slots open
- **Multi-Platform Support**: Resy (Chromium), OpenTable (Firefox), and Tock (Chromium)
- **Smart Date Analysis**: Auto-detects which dates need release sniping vs. cancellation monitoring based on each restaurant's release schedule
- **Persistent Sessions**: Browser sessions saved to disk and reused across restarts

## Quick Start

### 1. Install

```bash
pip install -e .
playwright install chromium firefox
```

### 2. Configure

Edit `config/config.yaml` with your credentials and restaurants:

```yaml
credentials:
  - platform: "resy"
    username: "you@example.com"
    password: "your-password"

restaurants:
  - name: "Carbone"
    platform: "resy"
    venue_id: "carbone-new-york"
    party_size: 2
    target_dates:
      - "2026-04-01"
    preferred_times:
      - "19:00-20:00"
    release_time: "09:00"
    release_days_ahead: 30
    monitor_cancellations: true
    enabled: true
```

### 3. Log in to platforms

```bash
# Opens a real browser — log in manually, session is saved
reservation-agent login-browser -p resy
reservation-agent login-browser -p opentable
```

### 4. Run

```bash
# Start monitoring
reservation-agent run

# Dry run (no actual bookings)
reservation-agent --dry-run run

# One-off availability check
reservation-agent check -r "Carbone" -d 2026-04-01

# Show status
reservation-agent status
```

## How It Works

### Cancellation Monitoring
- Polls for availability every 120 seconds
- Skips dates that haven't been released yet
- Books immediately when a matching slot appears

### Release Sniping
- Detects upcoming release windows from restaurant config
- Starts rapid-polling (0.5s) 30 seconds before release time for 90 seconds
- Books the first slot matching preferred times

### Platform Details
- **Resy**: Intercepts API responses for availability; books via iframe widget
- **OpenTable**: Single-page check+book flow on Firefox (Chromium is blocked by OpenTable)
- **Tock**: Prepaid/ticketed experiences (Eleven Madison Park, Atomix, Per Se)

## Project Structure

```
reservation-agent/
├── config/config.yaml           # Credentials, restaurants, settings
├── data/
│   ├── logs/                    # Structured JSON logs
│   └── sessions/                # Playwright browser sessions
├── src/reservation_agent/
│   ├── __main__.py              # CLI (run, check, login-browser, status)
│   ├── core/
│   │   ├── config.py            # Pydantic config models
│   │   ├── orchestrator.py      # Main loop (polling + snipes)
│   │   └── scheduler.py         # RapidPoller for release snipes
│   ├── browser/
│   │   ├── session_manager.py   # Browser lifecycle, persistent sessions
│   │   └── stealth.py           # Anti-detection
│   ├── platforms/
│   │   ├── base.py              # BasePlatform ABC
│   │   ├── resy.py              # Resy automation
│   │   ├── opentable.py         # OpenTable automation
│   │   └── tock.py              # Tock automation
│   └── utils/
│       ├── logging.py           # Structlog logging
│       └── retry.py             # Backoff + circuit breaker
└── pyproject.toml               # Package config
```

See [ARCHITECTURE.md](ARCHITECTURE.md) for detailed system design.

## License

MIT
