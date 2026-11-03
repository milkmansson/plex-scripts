"""Command line entry point: `plextool <command> ...`."""

from __future__ import annotations

import argparse
import sys
import time

from . import (
    __version__,
    audit,
    auth,
    devices,
    dupes,
    info,
    playlists,
    recent,
    resume,
    scan,
    server,
    stale,
    status,
    subs,
    tokens,
    users,
    watched,
)
from .common import PlexToolError, enable_verbose, format_duration

# Seconds a command must take before its total time is printed (always printed with --verbose).
SHOW_TIME_AFTER = 5


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
    for module in (auth, tokens, devices, users, server, status, scan, recent, dupes, stale, info, audit, watched, resume, playlists, subs):
        module.add_parser(subparsers)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 0
    verbose = args.verbose_first or getattr(args, "verbose", False)
    if verbose:
        enable_verbose()
    started = time.monotonic()
    try:
        status = args.run(args)
        elapsed = time.monotonic() - started
        if verbose or elapsed >= SHOW_TIME_AFTER:
            print(f"Finished in {format_duration(elapsed)}", file=sys.stderr)
        return status
    except PlexToolError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130
