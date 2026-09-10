import asyncio
import sys
import os

# Force UTF-8 output on Windows terminals
if sys.platform == "win32":
    os.system("")  # Enable ANSI escape sequences on Windows
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.prompt import Prompt
from rich.columns import Columns
from rich.text import Text
from rich import box
from config import config
from logger import logger
from agp.client import AGPMCPClient
from agp.planner import RacePlanner
from agp.benchmark import OfflineBenchmark
from agp.reasoning_provider import ReasoningProvider

console = Console()

# ─── Color Palette ───────────────────────────────────────────────────────────
C_GOLD    = "gold1"
C_RED     = "red1"
C_GREEN   = "green1"
C_CYAN    = "cyan1"
C_BLUE    = "dodger_blue1"
C_PURPLE  = "medium_purple1"
C_ORANGE  = "dark_orange"
C_DIM     = "grey50"
C_WHITE   = "bright_white"

def print_welcome_banner():
    """Prints a premium grand-prix dashboard banner with race aesthetics."""

    # ── ASCII art header ──
    header_art = (
        f"[bold {C_RED}]"
        "     +======================================================+\n"
        "     |                                                      |\n"
        f"     |  [bold {C_GOLD}]    🏁  R - D E X   A G P   R A C E R  🏁    [/bold {C_GOLD}]  |\n"
        "     |                                                      |\n"
        "     +======================================================+"
        f"[/bold {C_RED}]"
    )

    # ── System info card ──
    sys_info = (
        f"\n{header_art}\n\n"
        f"  [bold {C_GOLD}]► AGENT IDENTITY[/bold {C_GOLD}]\n"
        f"    [bold {C_WHITE}]• Agent Name:[/bold {C_WHITE}]  AIRA Race Agent\n"
        f"    [bold {C_WHITE}]• Owner:[/bold {C_WHITE}]       Halim\n"
        f"    [bold {C_WHITE}]• Website:[/bold {C_WHITE}]     [cyan]app.rialodex.xyz[/cyan]\n"
        f"    [bold {C_WHITE}]• X (Twitter):[/bold {C_WHITE}] [cyan]@feelanzr[/cyan]\n\n"
        f"  [bold {C_GOLD}]► TELEMETRY SETTINGS[/bold {C_GOLD}]\n"
        f"    [bold {C_WHITE}]• Engine:[/bold {C_WHITE}]      {config.llm_provider} [dim]({config.llm_model})[/dim]\n"
        f"    [bold {C_WHITE}]• Strategy:[/bold {C_WHITE}]    {config.race_profile.upper()}\n"
        f"    [bold {C_WHITE}]• Server:[/bold {C_WHITE}]      [dim]{config.agp_server_url}[/dim]\n"
    )

    console.print(Panel(
        sys_info,
        border_style=f"bold {C_RED}",
        title=f"[bold {C_GOLD}]🏎️ RACE CONTROL CENTER 🏎️[/bold {C_GOLD}]",
        subtitle=f"[dim {C_DIM}]Powered by Shannon Entropy Engine x EV Cost Optimizer[/dim {C_DIM}]",
        title_align="center",
        subtitle_align="center",
        expand=False,
        padding=(1, 3),
    ))


def print_mode_selector():
    """Prints a styled execution mode selector."""

    card1 = Panel(
        f"[bold {C_GREEN}]🏎️ LIVE RACE[/bold {C_GREEN}]\n"
        f"[{C_DIM}]Compete on Rialo/Latch\nserver using AGP tokens[/{C_DIM}]\n"
        f"[bold {C_WHITE}]Press [bold {C_GREEN}]1[/bold {C_GREEN}] to select[/bold {C_WHITE}]",
        border_style=C_GREEN,
        width=28,
        padding=(1, 2),
    )
    card2 = Panel(
        f"[bold {C_CYAN}]📊 BENCHMARK[/bold {C_CYAN}]\n"
        f"[{C_DIM}]Simulate races locally\nwithout spending AGP[/{C_DIM}]\n"
        f"[bold {C_WHITE}]Press [bold {C_CYAN}]2[/bold {C_CYAN}] to select[/bold {C_WHITE}]",
        border_style=C_CYAN,
        width=28,
        padding=(1, 2),
    )
    card3 = Panel(
        f"[bold {C_ORANGE}]❌ EXIT[/bold {C_ORANGE}]\n"
        f"[{C_DIM}]Shut down the agent\nand return to shell[/{C_DIM}]\n"
        f"[bold {C_WHITE}]Press [bold {C_ORANGE}]3[/bold {C_ORANGE}] to select[/bold {C_WHITE}]",
        border_style=C_ORANGE,
        width=28,
        padding=(1, 2),
    )
    mode_cards = [card1, card2, card3]
    console.print()
    console.print(Columns(mode_cards, padding=(0, 1), expand=False))


def build_tracks_table(tracks: list) -> Table:
    """Builds a premium-styled tracks table with status indicators."""
    table = Table(
        title=f"[bold {C_GOLD}]🏁 AVAILABLE RACE TRACKS 🏁[/bold {C_GOLD}]",
        header_style=f"bold {C_WHITE} on grey23",
        border_style=C_PURPLE,
        box=box.DOUBLE_EDGE,
        show_lines=True,
        padding=(0, 1),
        title_style=f"bold {C_GOLD}",
    )
    table.add_column("#", style=f"bold {C_DIM}", justify="center", width=3)
    table.add_column("Track Name", style=f"bold {C_WHITE}", min_width=14)
    table.add_column("Track ID", style=C_BLUE, no_wrap=True, min_width=36)
    table.add_column("CP", justify="center", style=C_CYAN)
    table.add_column("Ask $", justify="right", style=C_GREEN)
    table.add_column("Guess $", justify="right", style=C_ORANGE)
    table.add_column("Starts In", justify="center", style=C_GOLD)
    table.add_column("Status", justify="center")

    for idx, t in enumerate(tracks):
        points = t.get("points", [])
        point_count = len(points) if isinstance(points, list) else t.get("pointCount", 0)

        starts_in_sec = t.get("startsInSeconds", 0)
        if starts_in_sec and starts_in_sec > 0:
            mins, secs = divmod(int(starts_in_sec), 60)
            starts_in = f"{mins}m {secs}s" if mins > 0 else f"{secs}s"
        else:
            starts_in = "-"

        # Determine status with colored badge
        is_over = t.get("over", False)
        is_started = t.get("started", False)
        raw_status = str(t.get("status", "")).upper()
        phase = str(t.get("phase", "")).lower()

        if is_over or raw_status == "OVER" or phase == "over":
            status_badge = f"[bold white on grey30] 🏁 FINISHED [/bold white on grey30]"
        elif phase == "registration":
            status_badge = f"[bold white on blue] 📝 REGISTRATION [/bold white on blue]"
        elif phase == "betting":
            status_badge = f"[bold white on dark_magenta] 🎲 PREDICT MARKET [/bold white on dark_magenta]"
        elif is_started or raw_status == "ACTIVE" or phase in ("racing", "active"):
            status_badge = f"[bold white on green4] 🚦 RACING [/bold white on green4]"
        else:
            status_badge = f"[bold white on dark_orange] ⏳ UPCOMING [/bold white on dark_orange]"

        ask_cost = f"${float(t.get('questionCostUsd') or 0.001):.4f}"
        guess_cost = f"${float(t.get('guessCostUsd') or 0.000):.4f}"

        table.add_row(
            f"P{idx + 1}",
            t.get("name", "Unnamed"),
            t.get("id", "N/A"),
            str(point_count),
            ask_cost,
            guess_cost,
            starts_in,
            status_badge,
        )

    return table


async def main():
    print_welcome_banner()

    # Check configurations first
    try:
        config.validate()
    except ValueError as val_err:
        console.print(f"\n[bold {C_RED}][X] Configuration Error:[/bold {C_RED}] {val_err}")
        console.print(f"[{C_GOLD}]Please check your .env configuration file before starting.[/{C_GOLD}]")
        sys.exit(1)

    # Parse command line arguments for automated headless deployments
    import argparse
    parser = argparse.ArgumentParser(description="AIRA Racer Agent")
    parser.add_argument("--track", type=str, default=os.getenv("TRACK_ID"), help="Target track ID for automated execution")
    parser.add_argument("--mode", type=str, choices=["1", "2", "3"], help="Execution mode")
    args = parser.parse_args()

    is_headless = (
        os.getenv("HEADLESS", "").lower() == "true"
        or args.track is not None
        or args.mode is not None
        or not sys.stdin.isatty()
    )

    # Determine mode choice (headless vs interactive)
    if is_headless or args.mode:
        choice = args.mode or "1"
    else:
        # Prompt user for execution mode
        print_mode_selector()
        choice = Prompt.ask(
            f"\n[bold {C_WHITE}]🏎️ Select mode[/bold {C_WHITE}]",
            choices=["1", "2", "3"],
            default="1"
        )

    if choice == "3":
        console.print(f"\n[bold {C_GOLD}]See you on the track, racer! Goodbye.[/bold {C_GOLD}]")
        return

    if choice == "2":
        # Run offline benchmark simulation
        console.print(Panel(
            f"[bold {C_CYAN}]📊 Starting Offline Benchmark Simulation...[/bold {C_CYAN}]",
            border_style=C_CYAN,
            expand=False,
        ))
        benchmark = OfflineBenchmark(ReasoningProvider())
        await benchmark.run_all()
        return

    # choice == "1": Run Live Race
    while True:
        console.print(Panel(
            f"[bold {C_GREEN}]🏎️ Initializing Live Race Agent...[/bold {C_GREEN}]\n"
            f"[{C_DIM}]Establishing secure SSE connection to Rialo server[/{C_DIM}]",
            border_style=C_GREEN,
            expand=False,
        ))

        # Initialize client and planner
        client = AGPMCPClient(config.agp_server_url, config.agp_token)
        planner = RacePlanner(client)

        try:
            # Connect with robust retry logic (up to 50 attempts to survive temporary internet dropouts)
            max_retries = 50
            for attempt in range(1, max_retries + 1):
                try:
                    console.print(f"[{C_DIM}]Connection attempt {attempt}/{max_retries}...[/{C_DIM}]")
                    await client.start()
                    break
                except (ConnectionError, Exception) as conn_err:
                    if attempt == max_retries:
                        raise
                    sleep_time = min(5.0, attempt * 2)
                    console.print(f"[bold {C_ORANGE}]Connection failed: {conn_err}. Retrying in {sleep_time}s...[/bold {C_ORANGE}]")
                    await client.shutdown()
                    client = AGPMCPClient(config.agp_server_url, config.agp_token)
                    planner = RacePlanner(client)
                    await asyncio.sleep(sleep_time)

            console.print(f"\n[bold {C_GOLD}]🌐 Retrieving available tracks from server...[/bold {C_GOLD}]")
            
            selected_track = args.track
            selected_name = "Unknown"
            
            if is_headless and not selected_track:
                # Autonomous polling loop for new tracks
                while True:
                    try:
                        tracks = await client.list_tracks()
                        best_track = planner.strategy.choose_best_track(tracks)
                        if best_track:
                            selected_track = best_track["id"]
                            selected_name = best_track.get("name", selected_track[:12])
                            console.print(f"\n[bold {C_GREEN}]🤖 [Headless] Automatically selected track: {selected_name} ({selected_track})[/bold {C_GREEN}]")
                            break
                        else:
                            console.print(f"[{C_DIM}][Headless] No active or upcoming tracks found. Polling again in 25s...[/{C_DIM}]")
                    except Exception as poll_err:
                        console.print(f"[orange3][Headless] Polling error: {poll_err}. Reconnecting client and retrying in 25s...[/orange3]")
                        try:
                            await client.shutdown()
                        except Exception:
                            pass
                        client = AGPMCPClient(config.agp_server_url, config.agp_token)
                        planner = RacePlanner(client)
                        try:
                            await client.start()
                        except Exception:
                            pass
                    await asyncio.sleep(25.0)
            else:
                tracks = await client.list_tracks()
                if not tracks:
                    console.print(f"[{C_RED}]No active or upcoming tracks found on the server.[/{C_RED}]")
                    await client.shutdown()
                    return

                # Display premium tracks table
                console.print()
                console.print(build_tracks_table(tracks))
                console.print()

                if args.track:
                    selected_track = args.track
                elif not sys.stdin.isatty():
                    best = planner.strategy.choose_best_track(tracks)
                    selected_track = best["id"] if best else tracks[0].get("id")
                else:
                    # Select track with styled prompt
                    track_choices = [t.get("id") for t in tracks]
                    selected_track = Prompt.ask(
                        f"[bold {C_WHITE}]🏁 Select Track ID[/bold {C_WHITE}] [dim](press Enter for default)[/dim]",
                        choices=track_choices,
                        default=track_choices[0]
                    )
                
                # Find selected track name for display
                for t in tracks:
                    if t.get("id") == selected_track:
                        selected_name = t.get("name", selected_track[:12])
                        break

            # Fetch username dynamically from server
            try:
                balance_info = await client.sigil_balance()
                racer_name = balance_info.get("login", "darma150")
            except Exception:
                racer_name = "darma150"

            console.print(Panel(
                f"[bold {C_GREEN}]🚦 RACE STARTED[/bold {C_GREEN}]\n\n"
                f"  [bold {C_WHITE}]Track:[/bold {C_WHITE}]  {selected_name}\n"
                f"  [bold {C_WHITE}]ID:[/bold {C_WHITE}]     [dim]{selected_track}[/dim]\n"
                f"  [bold {C_WHITE}]Racer:[/bold {C_WHITE}]  {racer_name}\n\n"
                f"  [{C_DIM}]Autonomous planner loop engaged.[/{C_DIM}]\n"
                f"  [{C_DIM}]Press Ctrl+C to abort race.[/{C_DIM}]",
                border_style=f"bold {C_GREEN}",
                title=f"[bold {C_GOLD}]🏁🏁 GO GO GO! 🏁🏁[/bold {C_GOLD}]",
                title_align="center",
                expand=False,
                padding=(1, 3),
            ))

            # Execute Planner Loop
            loop_task = asyncio.create_task(planner.execute_race_loop(selected_track))

            try:
                await loop_task
            except asyncio.CancelledError:
                logger.info("[yellow]Race loop task cancelled.[/yellow]")

        except KeyboardInterrupt:
            console.print(f"\n[bold {C_ORANGE}]>> Race aborted by user. Shutting down client...[/bold {C_ORANGE}]")
            break
        except Exception as e:
            console.print(f"\n[bold {C_RED}][X] Fatal Race Error:[/bold {C_RED}] {e}")
        finally:
            try:
                await client.shutdown()
            except Exception:
                pass
            console.print(Panel(
                f"[bold {C_GOLD}]Race session concluded.[/bold {C_GOLD}]",
                border_style=C_DIM,
                expand=False,
            ))

        # Exit if not in continuous headless mode or if a specific track was targeted
        if not is_headless or args.track:
            break

        console.print("\n[bold cyan][Zeabur Autopilot][/bold cyan] [dim]Standing by. Scanning for next race grid in 20s...[/dim]")
        await asyncio.sleep(20.0)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        console.print(f"\n[bold {C_GOLD}]Exiting...[/bold {C_GOLD}]")
