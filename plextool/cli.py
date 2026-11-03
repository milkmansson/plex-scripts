"""Command line entry point: `plextool <command> ...`."""

from __future__ import annotations

import argparse
import sys

from . import (
    __version__,
    audit,
    auth,
    dupes,
    playlists,
    recent,
    resume,
    scan,
    server,
    stale,
    status,
    subs,
    watched,
)
from .common import PlexToolError, enable_verbose


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="plextool", description="Maintenance helpers for a Plex Media Server.",
        epilog="Run 'plextool COMMAND --help' for a command's options and examples.\n"
               "Run 'plextool auth login' once to sign in, then 'plextool server find' if the server isn't on localhost.\n"
               "Anything that changes your server is a dry run unless you pass --commit.",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("-v", "--verbose", dest="verbose_first", action="store_true",
                        help="print each request sent to Plex, with its reply, on stderr (also accepted after the command)")
    subparsers = parser.add_subparsers(dest="command", metavar="command")
    for module in (auth, server, status, scan, recent, dupes, stale, audit, watched, resume, playlists, subs):
        module.add_parser(subparsers)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 0
    if args.verbose_first or getattr(args, "verbose", False):
        enable_verbose()
    try:
        return args.run(args)
    except PlexToolError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130
