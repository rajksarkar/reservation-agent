# Reservation Agent

An autonomous restaurant reservation agent that monitors Resy, OpenTable, and Tock for hard-to-get NYC restaurant reservations.

## Features

- **Release Sniping**: Automatically attempts to book reservations the moment they become available
- **Cancellation Monitoring**: Continuously monitors for cancellations and books when slots open
- **Multi-Platform Support**: Works with Resy, OpenTable, and Tock
- **Email Notifications**: Get notified when reservations are booked or when action is needed
- **Web Dashboard**: Monitor status and activity through a simple web interface
- **Persistent Sessions**: Browser sessions persist across restarts
- **macOS Daemon**: Runs as a background service using launchd

## Quick Start

### 1. Install Dependencies

```bash
cd ~/reservation-agent
pip install -e .
playwright install chromium
```

### 2. Configure

```bash
cp config/config.example.yaml config/config.yaml
```

Edit `config/config.yaml` with your credentials and restaurant preferences.

Set environment variables for passwords:
```bash
export SMTP_PASSWORD="your-gmail-app-password"
export RESY_PASSWORD="your-resy-password"
export OPENTABLE_PASSWORD="your-opentable-password"
export TOCK_PASSWORD="your-tock-password"
```

### 3. Initialize Database

```bash
python -m reservation_agent init-db
```

### 4. Authenticate with Platforms

Run the manual authentication script for each platform you want to use:

```bash
python scripts/manual_auth.py --platform resy
python scripts/manual_auth.py --platform opentable
python scripts/manual_auth.py --platform tock
```

This opens a browser window where you can log in manually. The session is saved for future use.

### 5. Run the Agent

**Development mode:**
```bash
python -m reservation_agent run
```

**With dry-run (no actual bookings):**
```bash
python -m reservation_agent --dry-run run
```

**As a background daemon:**
```bash
./launchd/install.sh
launchctl load ~/Library/LaunchAgents/com.reservationagent.daemon.plist
```

## CLI Commands

```bash
# Start the agent
python -m reservation_agent run

# Start web dashboard only
python -m reservation_agent serve

# Check availability
python -m reservation_agent check "Carbone" "2026-03-15" --party-size 2

# Show status
python -m reservation_agent status

# Initialize database
python -m reservation_agent init-db
```

## Web Dashboard

Start the dashboard:
```bash
python -m reservation_agent serve --port 8000
```

Access at http://localhost:8000

The dashboard shows:
- Active bookings and their status
- Scheduled jobs (release snipes, cancellation monitors)
- Recent activity log

## Configuration

### Restaurant Configuration

```yaml
restaurants:
  - name: "Carbone"
    platform: "resy"           # resy, opentable, or tock
    venue_id: "carbone-new-york"
    party_size: 2
    target_dates:
      - "2026-03-15"
      - "2026-03-16"
    preferred_times:
      - "19:00-20:00"          # Time ranges
      - "20:00-21:00"
    release_time: "09:00"      # When reservations open
    release_days_ahead: 30     # Days before target date
    monitor_cancellations: true
    enabled: true
```

### Finding Venue IDs

- **Resy**: The URL slug (e.g., `carbone-new-york` from `resy.com/cities/ny/carbone-new-york`)
- **OpenTable**: The restaurant ID from the URL (e.g., `restaurant-name-city-123`)
- **Tock**: The URL slug (e.g., `atomix` from `exploretock.com/atomix`)

### Email Notifications

For Gmail, use an App Password:
1. Go to Google Account → Security → 2-Step Verification → App passwords
2. Create a new app password for "Mail"
3. Use that password in your config

## How It Works

### Release Sniping

1. Agent calculates when reservations will be released (target date - release_days_ahead)
2. Wakes up 30 seconds before release time
3. Rapidly polls (every 500ms) for 10 seconds looking for available slots
4. Books the first slot matching your preferred times

### Cancellation Monitoring

1. Polls for availability every 60 seconds (configurable)
2. Uses exponential backoff on errors to avoid rate limiting
3. Circuit breaker opens after 5 consecutive failures
4. Books immediately when a matching slot appears

## Troubleshooting

### Session Expired

If you get authentication errors:
```bash
python scripts/manual_auth.py --platform resy
```

### No Slots Found

1. Check the browser is configured correctly (set `headless: false` temporarily)
2. Verify the venue_id is correct
3. Check the target date is within the booking window

### Rate Limited

The agent uses exponential backoff and circuit breakers to handle rate limiting. If you're consistently rate limited:
1. Increase `cancellation_poll_interval` in config
2. Reduce the number of restaurants being monitored

### Daemon Not Starting

Check the logs:
```bash
tail -f ~/reservation-agent/data/logs/daemon.stderr.log
```

## Project Structure

```
reservation-agent/
├── config/
│   └── config.yaml          # Your configuration
├── data/
│   ├── reservation_agent.db # SQLite database
│   ├── sessions/            # Browser sessions
│   └── logs/                # Log files
├── launchd/
│   └── install.sh           # Daemon installer
├── scripts/
│   └── manual_auth.py       # Manual login helper
└── src/reservation_agent/
    ├── api/                 # Web dashboard
    ├── browser/             # Browser automation
    ├── core/                # Core logic
    ├── db/                  # Database models
    ├── notifications/       # Email notifications
    ├── platforms/           # Resy, OpenTable, Tock
    └── utils/               # Utilities
```

## Security Notes

- Passwords can be stored as environment variables using `${VAR_NAME}` syntax
- Browser sessions are stored locally in `data/sessions/`
- Never commit `config.yaml` with real credentials

## License

MIT
