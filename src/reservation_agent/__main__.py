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
    """Open a real browser to log in manually, then upload the session to Supabase."""
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

        storage_state = await context.storage_state()

        # Save locally as backup
        sessions_dir = Path("data/sessions")
        sessions_dir.mkdir(parents=True, exist_ok=True)
        session_file = sessions_dir / f"{platform}_session.json"
        session_file.write_text(json.dumps(storage_state, indent=2))
        console.print(f"[green]Session saved locally to {session_file}[/]")

        # Upload to Supabase
        try:
            from reservation_agent.db.supabase_client import SupabaseRepository
            repo = SupabaseRepository()
            repo.update_session_data(user_id, platform, storage_state)
            console.print("[green]Session uploaded to Supabase[/]")
        except Exception as e:
            console.print(f"[yellow]Warning: Could not upload to Supabase: {e}[/]")
            console.print("[dim]Session is saved locally — upload manually if needed.[/]")

        await browser.close()
        await pw.stop()
        console.print("[bold green]Done![/]")

    asyncio.run(main())


def main():
    """Main entry point."""
    cli(obj={})


if __name__ == "__main__":
    main()
