"""
Generate docs/cli.md, the complete `snodas` command reference, from the command line parser itself, so the reference
can't drift from the code. tests/test_cli_reference.py fails if docs/cli.md is out of date.

    python -m snodas_tools.cli_reference          # rewrite docs/cli.md

The tables are built from the parser's option definitions rather than its `--help` text, whose layout varies between
Python versions.
"""

import argparse
from pathlib import Path

from .cli import _parser

DOC_PATH = Path(__file__).resolve().parents[2] / "docs" / "cli.md"


def _subcommands(parser: argparse.ArgumentParser) -> dict[str, argparse.ArgumentParser]:
    for action in parser._actions:  # pylint: disable=protected-access
        if isinstance(action, argparse._SubParsersAction):  # pylint: disable=protected-access
            return dict(action.choices)
    return {}


def _summaries(parser: argparse.ArgumentParser) -> dict[str, str]:
    for action in parser._actions:  # pylint: disable=protected-access
        if isinstance(action, argparse._SubParsersAction):  # pylint: disable=protected-access
            return {a.dest: a.help or "" for a in action._choices_actions}  # pylint: disable=protected-access
    return {}


def _metavar(action: argparse.Action) -> str:
    if action.nargs == 0:
        return ""
    if action.choices:
        name = "{" + ",".join(str(c) for c in action.choices) + "}"
    else:
        name = action.metavar or (action.dest if not action.option_strings else action.dest.upper())
    if action.nargs in ("+", "*"):
        return f"{name} [{name} ...]"
    if action.nargs == "?":
        return f"[{name}]"
    return name


def _row(action: argparse.Action) -> str:
    metavar = _metavar(action)
    if action.option_strings:
        usage = ", ".join(action.option_strings) + (f" {metavar}" if metavar else "")
    else:
        usage = metavar
    help_text = (action.help or "").replace("|", "\\|")
    if action.required and action.option_strings:
        help_text = f"**Required.** {help_text}"
    return f"| `{usage}` | {help_text} |"


def _table(parser: argparse.ArgumentParser, include_help: bool = True) -> list[str]:
    actions = [
        a
        for a in parser._actions  # pylint: disable=protected-access
        if a.help != argparse.SUPPRESS
        and not isinstance(a, argparse._SubParsersAction)  # pylint: disable=protected-access
        and (include_help or not isinstance(a, argparse._HelpAction))  # pylint: disable=protected-access
    ]
    if not actions:
        return []
    return ["| Argument or option | Description |", "|---|---|", *(_row(a) for a in actions)]


def cli_reference() -> str:
    """The command reference as Markdown."""
    parser = _parser()
    commands = _subcommands(parser)
    summaries = _summaries(parser)
    lines = [
        "# Command reference",
        "",
        "Every `snodas` command and option. This page is generated from the program itself by",
        "`python -m snodas_tools.cli_reference`; don't edit it by hand. For examples, see the [README](../README.md).",
        "Run `snodas COMMAND --help` for the same information in a terminal.",
        "",
        "| Command | What it does |",
        "|---|---|",
        *(f"| [`snodas {name}`](#snodas-{name}) | {summaries.get(name, '')} |" for name in commands),
        "",
        "## Options for every command",
        "",
        "These go before the command name, e.g. `snodas --quiet run ...`.",
        "",
        *_table(parser),
        "",
    ]
    for name, sub in commands.items():
        summary = summaries.get(name, "")
        lines += [f"## snodas {name}", "", summary[:1].upper() + summary[1:] + ".", ""]
        lines += _table(sub, include_help=False) + [""]
    return "\n".join(lines)


def main() -> None:
    DOC_PATH.parent.mkdir(parents=True, exist_ok=True)
    DOC_PATH.write_text(cli_reference())
    print(f"Wrote {DOC_PATH}")


if __name__ == "__main__":
    main()
