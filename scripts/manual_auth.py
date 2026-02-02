#!/usr/bin/env python3
"""Manual authentication helper script.

Opens a visible browser window for manual login to reservation platforms.
This is useful when:
- Initial setup to capture session cookies
- Session expired and needs re-authentication
- Platform requires CAPTCHA or 2FA

Usage:
    python scripts/manual_auth.py --platform resy
    python scripts/manual_auth.py --platform opentable
    python scripts/manual_auth.py --platform tock
"""

import asyncio
import sys
from pathlib import Path

import click
from rich.console import Console

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from reservation_agent.browser.session_manager import SessionManager
from reservation_agent.core.config import BrowserConfig, load_config

console = Console()

PLATFORM_URLS = {
    "resy": "https://resy.com",
    "opentable": "https://www.opentable.com/login",
    "tock": "https://www.exploretock.com/login",
}


async def manual_auth(platform: str, config_path: str | None = None):
    """Open browser for manual authentication."""
    if platform not in PLATFORM_URLS:
        console.print(f"[red]Unknown platform: {platform}[/]")
        console.print(f"Available: {', '.join(PLATFORM_URLS.keys())}")
        return

    # Load config or use defaults
    try:
        config = load_config(config_path)
        browser_config = config.browser
    except Exception:
        browser_config = BrowserConfig(headless=False)

    # Force non-headless for manual auth
    browser_config.headless = False

    console.print(f"\n[bold]Manual Authentication: {platform.title()}[/]\n")
    console.print("A browser window will open. Please log in manually.")
    console.print("Once logged in, press Enter to save the session.\n")

    session_manager = SessionManager(browser_config)

    try:
        await session_manager.start()

        # Get a page and navigate to login
        page = await session_manager.get_page(platform)
        await page.goto(PLATFORM_URLS[platform])

        console.print(f"[cyan]Browser opened to {PLATFORM_URLS[platform]}[/]")
        console.print("[yellow]Log in to your account...[/]\n")

        # Wait for user to complete login
        input("Press Enter after you've logged in successfully...")

        # Save the session
        await session_manager.save_session(platform)

        console.print(f"\n[green]✓ Session saved for {platform}![/]")
        console.print(f"Session file: data/sessions/{platform}_session.json\n")

    except Exception as e:
        console.print(f"[red]Error: {e}[/]")
    finally:
        await session_manager.stop()


@click.command()
@click.option(
    "--platform",
    "-p",
    required=True,
    type=click.Choice(["resy", "opentable", "tock"]),
    help="Platform to authenticate with",
)
@click.option(
    "--config",
    "-c",
    type=click.Path(exists=True),
    help="Path to configuration file",
)
def main(platform: str, config: str | None):
    """Manual authentication helper for reservation platforms."""
    asyncio.run(manual_auth(platform, config))


if __name__ == "__main__":
    main()
