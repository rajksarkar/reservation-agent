"""CLI entry point for the reservation agent."""

import asyncio
import json
from pathlib import Path

import click
from rich.console import Console

console = Console()


@click.group()
@click.option(
    "--config",
    "-c",
    type=click.Path(exists=True),
    help="Path to configuration file",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Run without making actual bookings",
)
@click.pass_context
def cli(ctx, config, dry_run):
    """Autonomous restaurant reservation agent."""
    ctx.ensure_object(dict)
    ctx.obj["config_path"] = config
    ctx.obj["dry_run"] = dry_run


@cli.command()
@click.pass_context
def run(ctx):
    """Start the reservation agent (polls config.yaml for restaurants to monitor)."""
    from reservation_agent.core.config import load_config
    from reservation_agent.core.orchestrator import Orchestrator
    from reservation_agent.utils.logging import setup_logging

    config_path = ctx.obj.get("config_path")
    dry_run = ctx.obj.get("dry_run", False)

    try:
        config = load_config(config_path)
        if dry_run:
            config.dry_run = True

        setup_logging(config.log_level, config.log_dir)

        enabled = [r for r in config.restaurants if r.enabled]
        console.print("[bold green]Starting Reservation Agent...[/]")
        console.print(f"[dim]Monitoring {len(enabled)} restaurant(s)[/]")
        if config.dry_run:
            console.print("[yellow]Running in dry-run mode[/]")

        for r in enabled:
            console.print(f"  [cyan]{r.name}[/] ({r.platform}) — {len(r.target_dates)} date(s)")

        async def main():
            orchestrator = Orchestrator(config)
            await orchestrator.start()

            try:
                await orchestrator.run_forever()
            except KeyboardInterrupt:
                pass
            finally:
                await orchestrator.stop()

        asyncio.run(main())

    except Exception as e:
        console.print(f"[red]Error: {e}[/]")
        raise


@cli.command()
@click.option("--platform", "-p", default="resy", help="Platform to check (resy, opentable, tock)")
@click.option("--restaurant", "-r", required=True, help="Restaurant name from config")
@click.option("--date", "-d", required=True, help="Date to check (YYYY-MM-DD)")
@click.option("--party-size", "-s", default=2, help="Party size")
@click.pass_context
def check(ctx, platform, restaurant, date, party_size):
    """One-off availability check for a restaurant."""
    from reservation_agent.core.config import load_config
    from reservation_agent.utils.logging import setup_logging

    config_path = ctx.obj.get("config_path")

    try:
        config = load_config(config_path)
        setup_logging(config.log_level, config.log_dir)

        # Find the restaurant in config
        restaurant_config = None
        for r in config.restaurants:
            if r.name.lower() == restaurant.lower():
                restaurant_config = r
                break

        if not restaurant_config:
            console.print(f"[red]Restaurant '{restaurant}' not found in config[/]")
            return

        async def main():
            from reservation_agent.browser.session_manager import SessionManager
            from reservation_agent.platforms.resy import ResyPlatform
            from reservation_agent.platforms.opentable import OpenTablePlatform
            from reservation_agent.platforms.tock import TockPlatform

            platform_classes = {
                "resy": ResyPlatform,
                "opentable": OpenTablePlatform,
                "tock": TockPlatform,
            }

            session_manager = SessionManager(config.browser)
            await session_manager.start()

            try:
                credential = config.get_credential(restaurant_config.platform)
                if not credential:
                    console.print(f"[red]No credentials for {restaurant_config.platform}[/]")
                    return

                credentials = {
                    "platform": restaurant_config.platform,
                    "username": credential.username,
                    "password": credential.password,
                }

                platform_cls = platform_classes.get(restaurant_config.platform)
                if not platform_cls:
                    console.print(f"[red]Unknown platform: {restaurant_config.platform}[/]")
                    return

                plat = platform_cls(session_manager, credentials)

                console.print(f"[dim]Logging in to {restaurant_config.platform}...[/]")
                if not await plat.ensure_logged_in():
                    console.print("[red]Login failed[/]")
                    return

                console.print(f"[dim]Checking {restaurant_config.name} for {date}...[/]")
                result = await plat.check_availability(restaurant_config, date, party_size)

                if result.available_slots:
                    console.print(f"[green]Found {len(result.available_slots)} slot(s):[/]")
                    for slot in result.available_slots:
                        slot_type = f" ({slot.slot_type})" if slot.slot_type else ""
                        console.print(f"  [cyan]{slot.time}[/]{slot_type}")
                else:
                    console.print("[yellow]No availability[/]")
            finally:
                await session_manager.stop()

        asyncio.run(main())

    except Exception as e:
        console.print(f"[red]Error: {e}[/]")
        raise


@cli.command(name="login-browser")
@click.option("--platform", "-p", default="resy", help="Platform to log in to (resy, opentable, tock)")
@click.pass_context
def login_browser(ctx, platform):
    """Open a real browser to log in manually and save the session locally."""
    async def main():
        from playwright.async_api import async_playwright

        console.print(f"[bold green]Launching browser for {platform} login...[/]")

        pw = await async_playwright().start()

        if platform == "opentable":
            browser = await pw.firefox.launch(headless=False)
        else:
            browser = await pw.chromium.launch(headless=False)

        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            locale="en-US",
            timezone_id="America/New_York",
        )
        page = await context.new_page()

        urls = {
            "resy": "https://resy.com",
            "opentable": "https://www.opentable.com",
            "tock": "https://www.exploretock.com",
        }
        url = urls.get(platform, urls["resy"])
        await page.goto(url, wait_until="domcontentloaded")

        console.print(f"\n[yellow]Log in to {platform} in the browser window.[/]")
        input("Press Enter here when you're logged in...")

        storage_state = await context.storage_state()

        sessions_dir = Path("data/sessions")
        sessions_dir.mkdir(parents=True, exist_ok=True)
        session_file = sessions_dir / f"{platform}_session.json"
        session_file.write_text(json.dumps(storage_state, indent=2))
        console.print(f"[green]Session saved to {session_file}[/]")

        await browser.close()
        await pw.stop()
        console.print("[bold green]Done![/]")

    asyncio.run(main())


@cli.command()
@click.pass_context
def status(ctx):
    """Show agent status and configuration summary."""
    from reservation_agent.core.config import load_config

    config_path = ctx.obj.get("config_path")

    try:
        config = load_config(config_path)
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/]")
        return

    console.print("[bold]Reservation Agent Status[/]\n")

    # Credentials
    console.print("[bold cyan]Platform Credentials:[/]")
    for cred in config.credentials:
        console.print(f"  {cred.platform}: {cred.username}")

    # Restaurants
    enabled = [r for r in config.restaurants if r.enabled]
    disabled = [r for r in config.restaurants if not r.enabled]
    console.print(f"\n[bold cyan]Restaurants: {len(enabled)} active, {len(disabled)} disabled[/]")
    for r in enabled:
        console.print(
            f"  [green]●[/] {r.name} ({r.platform}) — "
            f"{len(r.target_dates)} date(s), party of {r.party_size}"
        )
    for r in disabled:
        console.print(f"  [dim]○ {r.name} ({r.platform})[/]")

    # Sessions
    sessions_dir = Path(config.browser.sessions_dir)
    console.print(f"\n[bold cyan]Sessions ({sessions_dir}):[/]")
    if sessions_dir.exists():
        for f in sorted(sessions_dir.glob("*_session.json")):
            import time
            age_hours = (time.time() - f.stat().st_mtime) / 3600
            color = "green" if age_hours < 48 else "yellow" if age_hours < 168 else "red"
            console.print(f"  [{color}]{f.name}[/] — {age_hours:.1f}h old")
    else:
        console.print("  [dim]No sessions directory[/]")

    # Config
    console.print(f"\n[bold cyan]Settings:[/]")
    console.print(f"  Poll interval: {config.scheduler.cancellation_poll_interval}s")
    console.print(f"  Snipe duration: {config.scheduler.snipe_duration}s")
    console.print(f"  Headless: {config.browser.headless}")
    console.print(f"  Dry run: {config.dry_run}")


def main():
    """Main entry point."""
    cli(obj={})


if __name__ == "__main__":
    main()
