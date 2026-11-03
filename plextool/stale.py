"""stale: find what is taking up space and not being watched."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta

from plexapi.exceptions import NotFound

from .common import (
    FILE_LEVEL,
    PlexToolError,
    add_command,
    add_connection_args,
    add_library_arg,
    connect,
    describe,
    item_size,
    no_autoreload,
    paint,
    pick_sections,
    plural,
    pretty_size,
    scan,
    shared_users,
    user_server,
    working,
)

OWNER = "owner"


def row_name(item, section_type: str) -> str:
    return describe(item) if section_type == "movie" else item.grandparentTitle


def build_rows(items: list, section_type: str) -> list[dict]:
    """One row per movie, or per show (summing its episodes), from movie/episode items.

    The items are the owner's, so the viewing counted is the owner's. Each row's
    'watchers' maps who has watched it to when they last did (None if Plex has no date).
    """
    rows: dict[str, dict] = {}
    for item in items:
        name = row_name(item, section_type)
        row = rows.setdefault(name, {"name": name, "size": 0, "added": None, "last_viewed": None,
                                     "views": 0, "count": 0, "watchers": {}})
        row["size"] += item_size(item)
        row["count"] += 1
        row["views"] += item.viewCount or 0
        if item.viewCount:
            note_watcher(row, OWNER, item.lastViewedAt)
        if item.addedAt and (row["added"] is None or item.addedAt < row["added"]):
            row["added"] = item.addedAt
        if item.lastViewedAt and (row["last_viewed"] is None or item.lastViewedAt > row["last_viewed"]):
            row["last_viewed"] = item.lastViewedAt
    return list(rows.values())


def note_watcher(row: dict, who: str, when: datetime | None) -> None:
    """Record that `who` watched this row, keeping the latest date seen."""
    seen = row["watchers"].get(who)
    row["watchers"][who] = max((d for d in (seen, when) if d), default=None)


def add_user_views(rows: list[dict], items: list, section_type: str, who: str) -> None:
    """Add another user's watched items (from their view of the library) to the rows.

    Items that are not in `rows` (the owner cannot see them) are ignored.
    """
    by_name = {row["name"]: row for row in rows}
    for item in items:
        row = by_name.get(row_name(item, section_type))
        if row is None or not item.viewCount:
            continue
        row["views"] += item.viewCount
        note_watcher(row, who, item.lastViewedAt)
        if item.lastViewedAt and (row["last_viewed"] is None or item.lastViewedAt > row["last_viewed"]):
            row["last_viewed"] = item.lastViewedAt


def latest_watcher(row: dict) -> str | None:
    """Who watched this row most recently, or None if no one has a date."""
    dated = {who: when for who, when in row["watchers"].items() if when}
    return max(dated, key=dated.get) if dated else None


def filter_rows(rows: list[dict], now: datetime, unwatched: bool = False,
                idle_days: int | None = None, age_days: int | None = None,
                min_size: int = 0) -> list[dict]:
    """Keep rows matching every given condition."""
    kept = []
    for row in rows:
        if row["size"] < min_size:
            continue
        if unwatched and row["views"] > 0:
            continue
        if idle_days is not None and row["last_viewed"] and row["last_viewed"] > now - timedelta(days=idle_days):
            continue
        if age_days is not None and (row["added"] is None or row["added"] > now - timedelta(days=age_days)):
            continue
        kept.append(row)
    return kept


def parse_size(text: str) -> int:
    """'500MB', '2GB', '1.5TB' or plain bytes."""
    units = {"KB": 1024, "MB": 1024**2, "GB": 1024**3, "TB": 1024**4, "B": 1}
    cleaned = text.strip().upper()
    for suffix, factor in units.items():
        if cleaned.endswith(suffix):
            try:
                return int(float(cleaned[:-len(suffix)]) * factor)
            except ValueError:
                break
    else:
        if cleaned.isdigit():
            return int(cleaned)
    raise argparse.ArgumentTypeError(f"'{text}' is not a size; use eg 500MB or 2GB")


def add_parser(subparsers) -> None:
    parser = add_command(
        subparsers, 'stale',
        'find large, unwatched or idle content',
        "List movies and shows by disk use, filtered by how long they have gone unwatched. Conditions combine with AND. Watched means watched by the token owner, unless you add --all-users or --user to count other people too. Read-only.",
        ['plextool stale --unwatched --age 365 --min-size 5GB',
        'plextool stale -l Movies --idle 730 -n 20',
        'plextool stale --unwatched --all-users',
        'plextool stale --idle 365 --user alice --user bob'])
    add_connection_args(parser)
    add_library_arg(parser)
    parser.add_argument("--unwatched", action="store_true", help="only things never watched")
    parser.add_argument("--idle", type=int, metavar="DAYS", help="only things not watched in the last DAYS days")
    parser.add_argument("--age", type=int, metavar="DAYS", help="only things added more than DAYS days ago")
    parser.add_argument("--min-size", type=parse_size, default=0, metavar="SIZE", help="ignore anything smaller, eg 1GB")
    parser.add_argument("--all-users", action="store_true",
                        help="also count what every user the server is shared with has watched "
                             "(one library scan per user, so it is slow on large libraries)")
    parser.add_argument("--user", action="append", default=[], metavar="NAME",
                        help="also count what this user has watched; repeat for more than one")
    parser.add_argument("-n", "--limit", type=int, default=50, metavar="N", help="show the N biggest (default 50)")
    parser.add_argument("--json", action="store_true", help="print JSON instead of text")
    parser.set_defaults(run=run)


def _iso(value):
    return value.isoformat() if value else None


def run(args: argparse.Namespace) -> int:
    if args.limit < 1:
        raise PlexToolError("--limit must be at least 1")
    plex = connect(args)
    now = datetime.now()
    sections = pick_sections(plex, args.library)
    rows_by_section = {}
    for section in sections:
        items = scan(section, autoreload=False, libtype=FILE_LEVEL[section.TYPE])
        rows_by_section[section.title] = build_rows(items, section.TYPE)

    users = shared_users(args, plex) if args.all_users else []
    users += [name for name in args.user if name.lower() not in {u.lower() for u in users}]
    for number, name in enumerate(users, start=1):
        try:
            user_plex = user_server(args, plex, name)
        except PlexToolError as e:
            if args.all_users and name not in args.user:
                print(f"warning: skipping {name}: {e}", file=sys.stderr)
                continue
            raise
        if user_plex is plex:
            continue  # --user named the owner, who is already counted
        print(f"Reading what {name} has watched (user {number} of {len(users)})...", file=sys.stderr)
        for section in sections:
            try:
                theirs = user_plex.library.section(section.title)
            except NotFound:
                continue  # this library is not shared with them
            with working(f"reading what {name} has watched in {section.title}"):
                items = no_autoreload(theirs.search(libtype=FILE_LEVEL[section.TYPE], unwatched=False))
            add_user_views(rows_by_section[section.title], items, section.TYPE, name)

    report = {}
    for section in sections:
        rows = filter_rows(rows_by_section[section.title], now, args.unwatched,
                           args.idle, args.age, args.min_size)
        rows.sort(key=lambda r: r["size"], reverse=True)
        report[section.title] = rows

    if args.json:
        out = {lib: [{**r, "added": _iso(r["added"]), "last_viewed": _iso(r["last_viewed"]),
                      "watchers": {who: _iso(when) for who, when in r["watchers"].items()}}
                     for r in rows[:args.limit]] for lib, rows in report.items()}
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return 0

    for title, rows in report.items():
        total = sum(r["size"] for r in rows)
        print(paint(f"\n== {title}: {plural(len(rows), 'match')}, {pretty_size(total)} ==", "cyan"))
        for number, row in enumerate(rows[:args.limit], start=1):
            seen = row["last_viewed"].strftime("%Y-%m-%d") if row["last_viewed"] else "never"
            added = row["added"].strftime("%Y-%m-%d") if row["added"] else "?"
            files = f"  ({row['count']} files)" if row["count"] > 1 else ""
            print(f"{number:>5} {pretty_size(row['size']):>9}  {row['name']}{files}")
            by = ""
            if users and latest_watcher(row):
                others = sorted(set(row["watchers"]) - {latest_watcher(row)})
                by = f" by {latest_watcher(row)}" + (f" (also {', '.join(others)})" if others else "")
            print(f"{'':>17}added {added}, last watched {seen}{by}")
    return 0
