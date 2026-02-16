"""CLI entry point for the reservation agent."""

import asyncio
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

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
    """Start the reservation agent daemon."""
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

        console.print("[bold green]Starting Reservation Agent...[/]")
        if config.dry_run:
            console.print("[yellow]Running in dry-run mode[/]")

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

    except FileNotFoundError as e:
        console.print(f"[red]Error: {e}[/]")
        sys.exit(1)
    except Exception as e:
        console.print(f"[red]Error: {e}[/]")
        raise


@cli.command()
@click.option("--host", default="127.0.0.1", help="Host to bind to")
@click.option("--port", default=8000, help="Port to bind to")
@click.option("--api-only", is_flag=True, help="Run API without orchestrator")
@click.pass_context
def serve(ctx, host, port, api_only):
    """Start the web dashboard server."""
    import uvicorn

    from reservation_agent.api.app import create_app

    console.print(f"[bold green]Starting dashboard at http://{host}:{port}[/]")

    app = create_app(api_only=api_only)
    uvicorn.run(app, host=host, port=port)


@cli.command()
@click.argument("restaurant")
@click.argument("date")
@click.option("--party-size", "-p", default=2, help="Party size")
@click.pass_context
def check(ctx, restaurant, date, party_size):
    """Check availability for a restaurant."""
    from reservation_agent.core.config import load_config
    from reservation_agent.core.orchestrator import Orchestrator
    from reservation_agent.utils.logging import setup_logging

    config_path = ctx.obj.get("config_path")

    try:
        config = load_config(config_path)
        setup_logging("WARNING")  # Quiet logging for CLI

        async def main():
            console.print(
                f"[dim]Checking availability for {restaurant} on {date} "
                "(this may take 30-60 seconds)...[/]"
            )
            orchestrator = Orchestrator(config)
            # Skip scheduler/DB for check - avoids pickle errors with async callbacks
            await orchestrator.start(enable_scheduler=False, init_db=False)

            try:
                result = await orchestrator.manual_check(restaurant, date, party_size)

                if "error" in result:
                    console.print(f"[red]Error: {result['error']}[/]")
                    return

                table = Table(title=f"Availability: {restaurant} on {date}")
                table.add_column("Time")
                table.add_column("Type")
                table.add_column("Deposit")

                for slot in result.get("slots", []):
                    deposit = f"${slot['deposit']}" if slot.get("deposit") else "-"
                    table.add_row(slot["time"], slot.get("type") or "-", deposit)

                if not result.get("slots"):
                    console.print("[yellow]No slots available[/]")
                else:
                    console.print(table)

            finally:
                await orchestrator.stop()

        asyncio.run(main())

    except Exception as e:
        console.print(f"[red]Error: {e}[/]")
        raise


@cli.command()
@click.pass_context
def status(ctx):
    """Show agent status and upcoming jobs."""
    from reservation_agent.core.config import load_config
    from reservation_agent.db.models import init_database, get_session_factory
    from reservation_agent.db.repository import Repository

    config_path = ctx.obj.get("config_path")

    try:
        config = load_config(config_path)

        async def main():
            engine = await init_database(config.database_url)
            session_factory = get_session_factory(engine)
            repo = Repository(session_factory)

            stats = await repo.get_dashboard_stats()

            console.print("\n[bold]Agent Status[/]")
            console.print(f"Active Bookings: {stats['active_bookings']}")
            console.print(f"Completed Bookings: {stats['completed_bookings']}")

            if stats.get("recent_activity"):
                console.print("\n[bold]Recent Activity[/]")
                for item in stats["recent_activity"][:5]:
                    level_color = {
                        "info": "blue",
                        "warning": "yellow",
                        "error": "red",
                    }.get(item["level"], "white")
                    console.print(
                        f"  [{level_color}]{item['level'].upper()}[/] "
                        f"{item['message']}"
                    )

        asyncio.run(main())

    except Exception as e:
        console.print(f"[red]Error: {e}[/]")


@cli.command()
@click.pass_context
def worker(ctx):
    """Start the multi-user web worker (polls Supabase for requests)."""
    from reservation_agent.core.config import load_config
    from reservation_agent.core.multi_user_orchestrator import MultiUserOrchestrator
    from reservation_agent.utils.logging import setup_logging

    config_path = ctx.obj.get("config_path")
    dry_run = ctx.obj.get("dry_run", False)

    try:
        config = load_config(config_path, allow_minimal=True)
        if dry_run:
            config.dry_run = True

        setup_logging(config.log_level, config.log_dir)

        console.print("[bold green]Starting Multi-User Worker...[/]")
        console.print("[dim]Polling Supabase for active reservation requests[/]")
        if config.dry_run:
            console.print("[yellow]Running in dry-run mode[/]")

        async def main():
            orchestrator = MultiUserOrchestrator(config)
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


@cli.command(name="login-browser")
@click.option("--platform", "-p", default="resy", help="Platform to log in to (resy, opentable, tock)")
@click.option("--user-id", "-u", required=True, help="Supabase user ID to store session for")
@click.pass_context
def login_browser(ctx, platform, user_id):
    """Open a real browser to log in manually, then save the session."""
    import json

    async def main():
        from playwright.async_api import async_playwright

        console.print(f"[bold green]Launching browser for {platform} login...[/]")

        pw = await async_playwright().start()
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
        input("[dim]Press Enter here when you're logged in...[/dim]")

        # Capture session state
        storage_state = await context.storage_state()

        # Save locally
        sessions_dir = Path("data/sessions")
        sessions_dir.mkdir(parents=True, exist_ok=True)
        session_file = sessions_dir / f"{platform}_session.json"
        session_file.write_text(json.dumps(storage_state, indent=2))
        console.print(f"[green]Session saved to {session_file}[/]")

        # Upload to Supabase
        try:
            from reservation_agent.db.supabase_client import SupabaseRepository
            repo = SupabaseRepository()
            repo.update_session_data(user_id, platform, storage_state)
            console.print("[green]Session uploaded to Supabase[/]")
        except Exception as e:
            console.print(f"[yellow]Warning: Could not upload to Supabase: {e}[/]")
            console.print("[dim]Session is saved locally and can be uploaded later.[/]")

        await browser.close()
        await pw.stop()
        console.print("[bold green]Done![/]")

    asyncio.run(main())


@cli.command()
@click.pass_context
def init_db(ctx):
    """Initialize the database."""
    from reservation_agent.core.config import load_config
    from reservation_agent.db.models import init_database

    config_path = ctx.obj.get("config_path")

    try:
        config = load_config(config_path)

        async def main():
            await init_database(config.database_url)
            console.print("[green]Database initialized successfully[/]")

        asyncio.run(main())

    except Exception as e:
        console.print(f"[red]Error: {e}[/]")


def main():
    """Main entry point."""
    cli(obj={})


if __name__ == "__main__":
    main()
