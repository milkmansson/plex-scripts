"""stale: find what is taking up space and not being watched."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta

from .common import (
    FILE_LEVEL,
    PlexToolError,
    add_command,
    add_connection_args,
    add_library_arg,
    connect,
    describe,
    item_size,
    paint,
    pick_sections,
    plural,
    pretty_size,
)


def build_rows(items: list, section_type: str) -> list[dict]:
    """One row per movie, or per show (summing its episodes), from movie/episode items."""
    rows: dict[str, dict] = {}
    for item in items:
        name = describe(item) if section_type == "movie" else item.grandparentTitle
        row = rows.setdefault(name, {"name": name, "size": 0, "added": None, "last_viewed": None,
                                     "views": 0, "count": 0})
        row["size"] += item_size(item)
        row["count"] += 1
        row["views"] += item.viewCount or 0
        if item.addedAt and (row["added"] is None or item.addedAt < row["added"]):
            row["added"] = item.addedAt
        if item.lastViewedAt and (row["last_viewed"] is None or item.lastViewedAt > row["last_viewed"]):
            row["last_viewed"] = item.lastViewedAt
    return list(rows.values())


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
        "List movies and shows by disk use, filtered by how long they have gone unwatched. Conditions combine with AND. Watch history is the token owner's only. Read-only.",
        ['plextool stale --unwatched --age 365 --min-size 5GB',
        'plextool stale -l Movies --idle 730 -n 20'])
    add_connection_args(parser)
    add_library_arg(parser)
    parser.add_argument("--unwatched", action="store_true", help="only things never watched")
    parser.add_argument("--idle", type=int, metavar="DAYS", help="only things not watched in the last DAYS days")
    parser.add_argument("--age", type=int, metavar="DAYS", help="only things added more than DAYS days ago")
    parser.add_argument("--min-size", type=parse_size, default=0, metavar="SIZE", help="ignore anything smaller, eg 1GB")
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
    report = {}
    for section in pick_sections(plex, args.library):
        items = section.search(libtype=FILE_LEVEL[section.TYPE])
        rows = filter_rows(build_rows(items, section.TYPE), now, args.unwatched,
                           args.idle, args.age, args.min_size)
        rows.sort(key=lambda r: r["size"], reverse=True)
        report[section.title] = rows

    if args.json:
        out = {lib: [{**r, "added": _iso(r["added"]), "last_viewed": _iso(r["last_viewed"])}
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
            print(f"{'':>17}added {added}, last watched {seen}")
    return 0
