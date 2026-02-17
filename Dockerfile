FROM python:3.11-slim

# Install system deps for Playwright browsers
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Shared browser deps
    libglib2.0-0 libnss3 libnspr4 libdbus-1-3 libatk1.0-0 \
    libatk-bridge2.0-0 libcups2 libdrm2 libxkbcommon0 libatspi2.0-0 \
    libxcomposite1 libxdamage1 libxfixes3 libxrandr2 libgbm1 libpango-1.0-0 \
    libcairo2 libasound2 libwayland-client0 libx11-6 libx11-xcb1 libxcb1 \
    libxext6 libxshmfence1 fonts-noto-color-emoji fonts-freefont-ttf \
    # Firefox-specific deps (GTK3, GDK, PangoCairo, etc.)
    libgtk-3-0 libgdk-pixbuf-2.0-0 libpangocairo-1.0-0 \
    libcairo-gobject2 libxcursor1 libxi6 libxtst6 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy and install Python package
COPY pyproject.toml README.md ./
COPY src/ ./src/
COPY config/worker.yaml ./config/config.yaml

RUN pip install --no-cache-dir -e .

# Install Playwright browsers (Chromium for Resy/Tock, Firefox for OpenTable)
RUN playwright install chromium firefox

# Create writable dirs for sessions and logs
RUN mkdir -p /tmp/sessions /tmp/logs

# Default: run the multi-user web worker with the worker config
CMD ["reservation-agent", "-c", "config/config.yaml", "worker"]
