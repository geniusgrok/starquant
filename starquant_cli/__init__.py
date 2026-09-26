"""``starquant`` command line: data sync | research backtest/validate/report | live run/status/flatten | report daily."""

from __future__ import annotations

import click

from starquant_cli._version import VERSION


@click.group()
@click.version_option(VERSION, prog_name="starquant")
def main() -> None:
    """StarQuant — Alpha-First trading system."""


@main.group()
def data() -> None:
    """Historical and live market data."""


@main.group()
def research() -> None:
    """Backtests, validation and research reports."""


@main.group()
def live() -> None:
    """Live trading loop on the configured venue profile."""


@main.group()
def report() -> None:
    """Daily attribution reports."""


from starquant_cli import data_cmd, governance_cmd, live_cmd, research_cmd  # noqa: E402  (importing registers them)

COMMAND_MODULES = (data_cmd, research_cmd, live_cmd, governance_cmd)

__all__ = ["COMMAND_MODULES", "main"]
