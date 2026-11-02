"""Command line entry point: `plextool <command> ...`."""

from __future__ import annotations

import argparse
import sys

from . import __version__, audit, auth, dupes, playlists, recent, resume, scan, stale, status, subs, watched
from .common import PlexToolError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="plextool", description="Maintenance helpers for a Plex Media Server.",
        epilog="Run 'plextool COMMAND --help' for a command's options and examples.\n"
               "Run 'plextool auth login' once to sign in; set PLEX_URL if the server isn't on localhost.\n"
               "Anything that changes your server is a dry run unless you pass --commit.",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", metavar="command")
    for module in (auth, status, scan, recent, dupes, stale, audit, watched, resume, playlists, subs):
        module.add_parser(subparsers)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 0
    try:
        return args.run(args)
    except PlexToolError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130
