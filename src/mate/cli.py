"""Typer CLI for mate."""

from __future__ import annotations

import json
import platform

import typer

from mate.config import load_settings
from mate.logging import configure_logging
from mate.main import main as launch

app = typer.Typer(no_args_is_help=True)


@app.command()
def run() -> None:
    """Launch the GUI."""

    launch()


@app.command()
def doctor() -> None:
    """Print environment diagnostics."""

    settings = load_settings()
    configure_logging(settings)
    info = {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "paths": {
            "home": str(settings.paths.base_dir),
            "logs": str(settings.paths.logs_dir),
        },
    }
    typer.echo(json.dumps(info, indent=2))


@app.command()
def settings(key: str | None = typer.Argument(None)) -> None:
    """Display current settings or a specific section."""

    data = load_settings().model_dump()
    if key:
        data = data.get(key, {})
    typer.echo(json.dumps(data, indent=2, default=str))
