import asyncio
import sys
import json
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
from rich import box
from config import config
from agp.client import AGPMCPClient

console = Console()

# ─── Color Palette (shared with app.py) ─────────────────────────────────────
C_GOLD   = "gold1"
C_RED    = "red1"
C_GREEN  = "green1"
C_CYAN   = "cyan1"
C_BLUE   = "dodger_blue1"
C_PURPLE = "medium_purple1"
C_ORANGE = "dark_orange"
C_DIM    = "grey50"
C_WHITE  = "bright_white"


def print_usage():
    """Prints premium help instructions for the CLI."""
    usage_text = (
        f"[bold {C_GOLD}]  ████  R-DEX  AGP  CLI  UTILITY  ████[/bold {C_GOLD}]\n"
        f"  [{C_DIM}]Execute AGP MCP tools directly from your shell[/{C_DIM}]\n\n"
        f"  [bold {C_ORANGE}]USAGE[/bold {C_ORANGE}]\n"
        f"    python cli.py [bold {C_WHITE}]<command>[/bold {C_WHITE}] [args]\n\n"
        f"  [bold {C_ORANGE}]COMMANDS[/bold {C_ORANGE}]\n"
        f"    [bold {C_GREEN}]list_tracks[/bold {C_GREEN}]         List all tracks with pricing info\n"
        f"    [bold {C_GREEN}]sigil_balance[/bold {C_GREEN}]       Check Sigil wallet balance & credit\n"
        f"    [bold {C_GREEN}]my_race[/bold {C_GREEN}]             Show active race state details\n"
        f"    [bold {C_GREEN}]track_state[/bold {C_GREEN}]         Check active track progress\n"
        f"    [bold {C_CYAN}]start_track[/bold {C_CYAN}] <id>    Register and join a specific track\n"
        f"    [bold {C_CYAN}]ask[/bold {C_CYAN}] <question>      Ask Oracle a YES/NO question ($ USDC)\n"
        f"    [bold {C_CYAN}]guess[/bold {C_CYAN}] <answer>      Submit a guess for current checkpoint\n"
        f"    [bold {C_PURPLE}]practice_ask[/bold {C_PURPLE}] <q>   Ask YES/NO on practice verification point\n"
        f"    [bold {C_PURPLE}]practice_guess[/bold {C_PURPLE}] <a> Submit answer for practice verification"
    )
    console.print(Panel(
        usage_text,
        border_style=f"bold {C_RED}",
        title=f"[bold {C_GOLD}]🏁 HELP 🏁[/bold {C_GOLD}]",
        title_align="center",
        expand=False,
        padding=(1, 3),
    ))


async def run_command(command: str, args: list):
    """Initializes connection and runs the requested command."""
    try:
        config.validate()
    except Exception as e:
        console.print(f"[bold {C_RED}][X] Configuration Error:[/bold {C_RED}] {e}")
        return

    client = AGPMCPClient(config.agp_server_url, config.agp_token)
    await client.start()

    try:
        if command == "list_tracks":
            tracks = await client.list_tracks()
            table = Table(
                title=f"[bold {C_GOLD}]🏁 AVAILABLE RACE TRACKS 🏁[/bold {C_GOLD}]",
                header_style=f"bold {C_WHITE} on grey23",
                border_style=C_PURPLE,
                box=box.DOUBLE_EDGE,
                show_lines=True,
                padding=(0, 1),
            )
            table.add_column("#", style=f"bold {C_DIM}", justify="center", width=3)
            table.add_column("Track Name", style=f"bold {C_WHITE}", min_width=12)
            table.add_column("Track ID", style=C_BLUE, no_wrap=True, min_width=36)
            table.add_column("CP", justify="center", style=C_CYAN)
            table.add_column("Ask $", justify="right", style=C_GREEN)
            table.add_column("Guess $", justify="right", style=C_ORANGE)
            table.add_column("Status", justify="center")

            for idx, t in enumerate(tracks):
                points = len(t.get("points", [])) if isinstance(t.get("points"), list) else t.get("pointCount", 0)
                is_over = t.get("over", False)
                raw_status = str(t.get("status", "")).upper()
                phase = str(t.get("phase", "")).lower()

                if is_over or raw_status == "OVER" or phase == "over":
                    status_badge = f"[white on grey30] 🏁 FINISHED [/white on grey30]"
                elif phase == "registration":
                    status_badge = f"[bold white on blue] 📝 REGISTRATION [/bold white on blue]"
                elif phase == "betting":
                    status_badge = f"[bold white on dark_magenta] 🎲 PREDICT MARKET [/bold white on dark_magenta]"
                elif t.get("started") or raw_status == "ACTIVE" or phase in ("racing", "active"):
                    status_badge = f"[white on green4] 🚦 RACING [/white on green4]"
                else:
                    status_badge = f"[white on dark_orange] ⏳ UPCOMING [/white on dark_orange]"

                table.add_row(
                    f"P{idx+1}",
                    t.get("name", "Unnamed"),
                    t.get("id", "N/A"),
                    str(points),
                    f"${float(t.get('questionCostUsd', 0.001)):.4f}",
                    f"${float(t.get('guessCostUsd', 0.000)):.4f}",
                    status_badge,
                )
            console.print(table)

        elif command == "sigil_balance":
            balance = await client.sigil_balance()
            sigil = balance.get("sigilBalance", balance) if isinstance(balance, dict) else {}

            bal_usd = float(sigil.get("balanceUsd", 0))
            credit = float(sigil.get("creditRemainingUsd", 0))
            total = bal_usd + credit

            table = Table(
                title=f"[bold {C_GOLD}]🪙 SIGIL WALLET PROFILE 🪙[/bold {C_GOLD}]",
                header_style=f"bold {C_WHITE} on grey23",
                border_style=C_GREEN,
                box=box.DOUBLE_EDGE,
                show_lines=True,
                padding=(0, 2),
            )
            table.add_column("Property", style=f"bold {C_ORANGE}", min_width=24)
            table.add_column("Value", style=f"bold {C_WHITE}", min_width=18)
            table.add_row("👤 Login Username", balance.get("login", "Unknown"))
            table.add_row("💵 USDC Wallet Balance", f"${bal_usd:.4f}")
            table.add_row("🪙 Remaining Free Credit", f"${credit:.4f}")
            table.add_row("💰 Total Available Funds", f"[bold {C_GREEN}]${total:.4f}[/bold {C_GREEN}]")
            table.add_row("🏛️ Treasury Status", sigil.get("creditStatus", "Unknown"))
            table.add_row("📊 Est. Ask Queries Left", f"~{int(total / 0.001):,}" if total > 0 else "0")
            console.print(table)

        elif command == "my_race":
            race = await client.my_race()
            console.print(Panel(
                f"[bold {C_WHITE}]{json.dumps(race, indent=2)}[/bold {C_WHITE}]",
                title=f"[bold {C_GOLD}]🏎️ MY RACE STATE[/bold {C_GOLD}]",
                border_style=C_CYAN,
                expand=False,
                padding=(1, 2),
            ))

        elif command == "track_state":
            state = await client.track_state()
            console.print(Panel(
                f"[bold {C_WHITE}]{json.dumps(state, indent=2)}[/bold {C_WHITE}]",
                title=f"[bold {C_GOLD}]🏁 TRACK PROGRESS[/bold {C_GOLD}]",
                border_style=C_CYAN,
                expand=False,
                padding=(1, 2),
            ))

        elif command == "start_track":
            if not args:
                console.print(f"[bold {C_RED}][X] Error: start_track requires a <track_id> argument.[/bold {C_RED}]")
                return
            track_id = args[0]
            console.print(f"[bold {C_CYAN}]🏁 Registering on track:[/bold {C_CYAN}] [dim]{track_id}[/dim]...")
            res = await client.start_track(track_id)
            console.print(Panel(
                f"[bold {C_WHITE}]{json.dumps(res, indent=2)}[/bold {C_WHITE}]",
                title=f"[bold {C_GREEN}][OK] REGISTRATION RESULT[/bold {C_GREEN}]",
                border_style=C_GREEN,
                expand=False,
            ))

        elif command == "ask":
            if not args:
                console.print(f"[bold {C_RED}][X] Error: ask requires a <question> string argument.[/bold {C_RED}]")
                return
            question = " ".join(args)
            console.print(f"[bold {C_ORANGE}]💬 Asking Oracle:[/bold {C_ORANGE}] '{question}'...")
            res = await client.ask(question)
            console.print(Panel(
                f"[bold {C_WHITE}]{json.dumps(res, indent=2)}[/bold {C_WHITE}]",
                title=f"[bold {C_GOLD}]🧠 ORACLE RESPONSE[/bold {C_GOLD}]",
                border_style=C_GOLD,
                expand=False,
            ))

        elif command == "guess":
            if not args:
                console.print(f"[bold {C_RED}][X] Error: guess requires an <answer> string argument.[/bold {C_RED}]")
                return
            answer = " ".join(args)
            console.print(f"[bold {C_CYAN}]🎯 Submitting guess:[/bold {C_CYAN}] '{answer}'...")
            res = await client.guess(answer)
            is_correct = res.get("correct") or res.get("status") == "correct" if isinstance(res, dict) else False
            if is_correct:
                console.print(Panel(
                    f"[bold {C_GREEN}]🏆🏆🏆  CORRECT!  🏆🏆🏆[/bold {C_GREEN}]",
                    border_style=f"bold {C_GREEN}",
                    expand=False,
                ))
            else:
                console.print(Panel(
                    f"[bold {C_RED}][X] Wrong guess.[/bold {C_RED}]\n"
                    f"[{C_DIM}]{json.dumps(res, indent=2)}[/{C_DIM}]",
                    border_style=C_RED,
                    expand=False,
                ))

        elif command == "practice_ask":
            if not args:
                console.print(f"[bold {C_RED}][X] Error: practice_ask requires a <question> string argument.[/bold {C_RED}]")
                return
            question = " ".join(args)
            console.print(f"[bold {C_PURPLE}]💬 Asking Practice Oracle:[/bold {C_PURPLE}] '{question}'...")
            res = await client.practice_ask(question)
            console.print(Panel(
                f"[bold {C_WHITE}]{json.dumps(res, indent=2)}[/bold {C_WHITE}]",
                title=f"[bold {C_GOLD}]🎯 PRACTICE RESPONSE[/bold {C_GOLD}]",
                border_style=C_PURPLE,
                expand=False,
            ))

        elif command == "practice_guess":
            if not args:
                console.print(f"[bold {C_RED}][X] Error: practice_guess requires an <answer> string argument.[/bold {C_RED}]")
                return
            answer = " ".join(args)
            console.print(f"[bold {C_PURPLE}]🎯 Submitting practice guess:[/bold {C_PURPLE}] '{answer}'...")
            res = await client.practice_guess(answer)
            console.print(Panel(
                f"[bold {C_WHITE}]{json.dumps(res, indent=2)}[/bold {C_WHITE}]",
                title=f"[bold {C_GREEN}]🏁 PRACTICE GUESS RESULT[/bold {C_GREEN}]",
                border_style=C_GREEN if res.get("verified") else C_ORANGE,
                expand=False,
            ))

        else:
            print_usage()

    except Exception as err:
        console.print(f"[bold {C_RED}][X] Command Failed:[/bold {C_RED}] {err}")
    finally:
        await client.shutdown()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print_usage()
        sys.exit(0)

    cmd = sys.argv[1].lower()
    cmd_args = sys.argv[2:]

    asyncio.run(run_command(cmd, cmd_args))
