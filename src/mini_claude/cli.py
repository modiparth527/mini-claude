"""
CLI entry point — wires together config, the Anthropic client, rich Console,
and the agent loop into the interactive REPL.

Backend selection (highest priority wins):
  1. --mode flag on the command line
  2. MODE= in .env (or shell env var)
  3. auto-detect: Anthropic API if ANTHROPIC_API_KEY is set, else Bedrock
"""

import json
import logging
import sys
from typing import Annotated

import anthropic
import typer
from rich.console import Console
from rich.logging import RichHandler
from rich.panel import Panel

from mini_claude.agent import run_agent
from mini_claude.config import Settings, settings
from mini_claude.repo_tracer import open_repo_visualization

app = typer.Typer(help="Mini Claude Code — a minimal coding agent.")

console = Console()

_VALID_MODES = ("anthropic", "bedrock")


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(message)s",
        handlers=[RichHandler(console=console, show_path=False, markup=True)],
    )


def _make_client(cfg: Settings) -> anthropic.Anthropic | anthropic.AnthropicBedrock:
    """Create the right client for the active backend."""
    if cfg.active_mode == "anthropic":
        if not cfg.anthropic_api_key:
            raise ValueError(
                "ANTHROPIC_API_KEY is required for anthropic mode. "
                "Add it to .env or set the environment variable."
            )
        return anthropic.Anthropic(api_key=cfg.anthropic_api_key)

    # Bedrock — uses boto3 credential chain: SSO → env vars → ~/.aws/credentials
    return anthropic.AnthropicBedrock(
        aws_region=cfg.aws_region,
        **({"aws_profile": cfg.aws_profile} if cfg.aws_profile else {}),
    )


@app.command()
def main(
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Show debug logs")] = False,
    mode: Annotated[
        str | None,
        typer.Option("--mode", "-m", help="Backend: anthropic or bedrock (overrides .env MODE=)"),
    ] = None,
) -> None:
    _setup_logging(verbose)

    if mode and mode not in _VALID_MODES:
        console.print(f"[bold red]Unknown mode {mode!r}. Choose: anthropic, bedrock[/bold red]")
        raise typer.Exit(code=1)

    # CLI --mode flag overrides the MODE= from .env
    cfg = settings.model_copy(update={"mode": mode}) if mode else settings

    try:
        client = _make_client(cfg)
    except Exception as exc:
        console.print(f"[bold red]Config error:[/bold red] {exc}")
        raise typer.Exit(code=1) from exc

    mode_label = f"[dim]{cfg.active_mode}[/dim]  [dim]{cfg.effective_model}[/dim]"
    console.print(
        Panel.fit(
            f"[bold cyan]Mini Claude Code[/bold cyan]  {mode_label}\n"
            "[dim]Commands: /clear  /history  /trace [prompt]  /exit[/dim]",
            border_style="cyan",
        )
    )

    history: list[dict] = []

    while True:
        try:
            user_input = console.input("\n[bold green]you>[/bold green] ").strip()
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]bye[/dim]")
            sys.exit(0)

        if not user_input:
            continue

        match user_input:
            case "/exit" | "/quit":
                console.print("[dim]bye[/dim]")
                sys.exit(0)

            case "/clear":
                history = []
                console.print("[dim]history cleared[/dim]")

            case "/history":
                console.print_json(json.dumps(history, indent=2))

            case s if s == "/trace" or s.startswith("/trace "):
                prompt = user_input[len("/trace"):].strip()
                if prompt:
                    console.print(
                        f"[dim]Tracing live {cfg.active_mode} call: {prompt!r} — this may take a moment…[/dim]"
                    )
                    trace_client = client
                else:
                    console.print("[dim]Tracing mock dry-run (no API call) — building HTML…[/dim]")
                    trace_client = None
                try:
                    path = open_repo_visualization(prompt or "list the files here", client=trace_client)
                    console.print(f"[bold green]Opened:[/bold green] {path}")
                except Exception as exc:
                    console.print(f"[bold red]trace error:[/bold red] {exc}")
                    logging.exception("Unhandled exception in /trace")

            case _:
                try:
                    history = run_agent(
                        user_message=user_input,
                        history=history,
                        client=client,
                        settings=cfg,
                        console=console,
                    )
                except (anthropic.APIError, anthropic.APIConnectionError) as exc:
                    console.print(f"[bold red]API error:[/bold red] {exc}")
                except Exception as exc:
                    console.print(f"[bold red]error:[/bold red] {exc}")
                    logging.exception("Unhandled exception in agent loop")


if __name__ == "__main__":
    app()
