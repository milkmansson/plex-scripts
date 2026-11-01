"""Command line entry point: `plextool <command> ...`."""

from __future__ import annotations

import argparse
import sys

from . import __version__, audit, dupes, playlists, recent, resume, scan, stale, status, watched
from .common import PlexToolError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="plextool", description="Maintenance helpers for a Plex Media Server.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True, metavar="command")
    for module in (status, scan, recent, dupes, stale, audit, watched, resume, playlists):
        module.add_parser(subparsers)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.run(args)
    except PlexToolError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130
