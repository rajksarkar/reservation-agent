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
