"""resume: tidy the Continue Watching list."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta

from .common import PlexToolError, add_connection_args, connect, describe


def percent(item) -> int:
    if item.viewOffset and item.duration:
        return min(100, round(100 * item.viewOffset / item.duration))
    return 0


def select(items: list, now: datetime, idle_days: int | None = None) -> list:
    """Partly watched items, optionally only those untouched for idle_days."""
    chosen = [i for i in items if i.viewOffset]
    if idle_days is not None:
        cutoff = now - timedelta(days=idle_days)
        chosen = [i for i in chosen if i.lastViewedAt is None or i.lastViewedAt < cutoff]
    return chosen


def add_parser(subparsers) -> None:
    parser = subparsers.add_parser(
        "resume", help="list or clear Continue Watching entries",
        description="List partly-watched items in the token owner's Continue Watching. "
                    "With --clear, remove them by marking them watched or unwatched.")
    add_connection_args(parser)
    parser.add_argument("--idle", type=int, metavar="DAYS", help="only items not played in the last DAYS days")
    parser.add_argument("--clear", choices=("watched", "unwatched"),
                        help="mark the listed items watched, or unwatched. Unwatched also "
                             "resets any earlier view count on that item.")
    parser.add_argument("-y", "--commit", action="store_true", help="write the changes (default is a dry run)")
    parser.set_defaults(run=run)


def run(args: argparse.Namespace) -> int:
    if args.commit and not args.clear:
        raise PlexToolError("--commit needs --clear watched|unwatched")
    plex = connect(args)
    items = select(plex.continueWatching(), datetime.now(), args.idle)
    if not items:
        print("Nothing in progress.")
        return 0
    for number, item in enumerate(items, start=1):
        seen = item.lastViewedAt.strftime("%Y-%m-%d") if item.lastViewedAt else "?"
        print(f"{number:>4}  {percent(item):>3}%  last played {seen}  {describe(item)}")
        if args.clear and args.commit:
            item.markPlayed() if args.clear == "watched" else item.markUnplayed()
    if args.clear:
        verb = "Marked" if args.commit else "Would mark"
        print(f"\n{verb} {len(items)} item(s) {args.clear}.")
        if not args.commit:
            print("Dry run only. Re-run with --commit to apply.")
    return 0
