#!/bin/bash
# Installation script for the Reservation Agent daemon

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PLIST_NAME="com.reservationagent.daemon.plist"
PLIST_SRC="$SCRIPT_DIR/$PLIST_NAME"
PLIST_DEST="$HOME/Library/LaunchAgents/$PLIST_NAME"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo "Reservation Agent Daemon Installer"
echo "==================================="
echo

# Check if plist source exists
if [ ! -f "$PLIST_SRC" ]; then
    echo -e "${RED}Error: plist file not found at $PLIST_SRC${NC}"
    exit 1
fi

# Update plist with correct paths
echo "Configuring plist with correct paths..."

# Get Python path - MUST use conda/python that has reservation_agent deps
PYTHON_PATH=$(which python 2>/dev/null || which python3 2>/dev/null)
# Prefer conda Python over system Python (system often lacks pip packages)
if [[ "$PYTHON_PATH" == *"CommandLineTools"* ]] || [[ "$PYTHON_PATH" == *"/usr/bin"* ]]; then
    for conda_python in \
        "$HOME/anaconda3/bin/python" \
        "$HOME/miniconda3/bin/python" \
        "/opt/anaconda3/bin/python" \
        "/opt/homebrew/anaconda3/bin/python"; do
        if [ -x "$conda_python" ]; then
            PYTHON_PATH="$conda_python"
            echo "Using conda Python (system Python lacks deps): $PYTHON_PATH"
            break
        fi
    done
fi
if [ -z "$PYTHON_PATH" ]; then
    echo -e "${RED}Error: python not found${NC}"
    echo "Activate conda first: conda activate base"
    echo "Then run this script again"
    exit 1
fi
echo "Using Python: $PYTHON_PATH"

# Add Python's bin to PATH for subprocesses (playwright, etc.)
PYTHON_BIN=$(dirname "$PYTHON_PATH")
EXTRA_PATH="$PYTHON_BIN:/usr/local/bin:/usr/bin:/bin"

# Create a temporary plist with updated paths
TEMP_PLIST=$(mktemp)
sed -e "s|/usr/local/bin/python3|$PYTHON_PATH|g" \
    -e "s|/Users/rsarkar/reservation-agent|$PROJECT_DIR|g" \
    -e "s|/usr/local/bin:/usr/bin:/bin|$EXTRA_PATH|g" \
    "$PLIST_SRC" > "$TEMP_PLIST"

# Create LaunchAgents directory if needed
mkdir -p "$HOME/Library/LaunchAgents"

# Stop existing daemon if running
if launchctl list | grep -q "com.reservationagent.daemon"; then
    echo "Stopping existing daemon..."
    launchctl unload "$PLIST_DEST" 2>/dev/null || true
fi

# Copy plist to LaunchAgents
echo "Installing plist to $PLIST_DEST..."
cp "$TEMP_PLIST" "$PLIST_DEST"
rm "$TEMP_PLIST"

# Create required directories
echo "Creating required directories..."
mkdir -p "$PROJECT_DIR/data/logs"
mkdir -p "$PROJECT_DIR/data/sessions"

# Check for config file
if [ ! -f "$PROJECT_DIR/config/config.yaml" ]; then
    echo -e "${YELLOW}Warning: config/config.yaml not found${NC}"
    echo "Copy config/config.example.yaml to config/config.yaml and configure it."
fi

# Install Python dependencies (use same Python as will run the daemon)
echo "Checking Python dependencies..."
if [ -f "$PROJECT_DIR/pyproject.toml" ]; then
    cd "$PROJECT_DIR"
    if $PYTHON_PATH -m pip install -e . --quiet 2>/dev/null; then
        echo "Package installed (editable mode)"
    elif $PYTHON_PATH -m pip install . --quiet 2>/dev/null; then
        echo "Package installed"
    else
        echo -e "${YELLOW}Warning: Could not install package. If you already have it installed, continue.${NC}"
        echo "Otherwise run manually: $PYTHON_PATH -m pip install -e \"$PROJECT_DIR\""
    fi
fi

# Install Playwright browsers (Chromium + Firefox for OpenTable)
echo "Installing Playwright browsers..."
$PYTHON_PATH -m playwright install chromium --quiet 2>/dev/null || true
$PYTHON_PATH -m playwright install firefox --quiet 2>/dev/null || true

echo
echo -e "${GREEN}Installation complete!${NC}"
echo
echo "Commands:"
echo "  Start daemon:   launchctl load $PLIST_DEST"
echo "  Stop daemon:    launchctl unload $PLIST_DEST"
echo "  Check status:   launchctl list | grep reservationagent"
echo "  View logs:      tail -f $PROJECT_DIR/data/logs/daemon.stdout.log"
echo
echo "Next steps:"
echo "  1. Configure config/config.yaml with your credentials"
echo "  2. Run manual auth: python scripts/manual_auth.py --platform resy"
echo "     (for OpenTable: python scripts/manual_auth.py --platform opentable)"
echo "  3. Start the daemon: launchctl load $PLIST_DEST"
echo
