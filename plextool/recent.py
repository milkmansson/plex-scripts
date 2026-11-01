"""recent: rewrite 'added at' dates to reorder Plex's Recently Added lists."""

from __future__ import annotations

import argparse
import re
from datetime import datetime, timedelta

from .common import (
    SECTION_LEVELS,
    PlexToolError,
    add_command,
    add_connection_args,
    connect,
    describe,
    paint,
    pick_sections,
    plural,
)

_SHIFT_RE = re.compile(r"^([+-]?)(\d+)(min|h|d|w)$")
_SHIFT_UNITS = {"min": "minutes", "h": "hours", "d": "days", "w": "weeks"}


def parse_date(text: str) -> datetime:
    """Parse 'YYYY-MM-DD' or 'YYYY-MM-DD HH:MM:SS'."""
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"'{text}' is not a date; use YYYY-MM-DD or 'YYYY-MM-DD HH:MM:SS'") from None


def parse_shift(text: str) -> timedelta:
    """Parse a relative offset such as '+30d', '-2w', '6h' or '90min' (sign optional)."""
    match = _SHIFT_RE.match(text.strip())
    if not match:
        raise argparse.ArgumentTypeError(
            f"'{text}' is not a shift; use a number and a unit (min, h, d, w), eg -30d")
    sign, amount, unit = match.groups()
    delta = timedelta(**{_SHIFT_UNITS[unit]: int(amount)})
    return -delta if sign == "-" else delta


def new_date(item, args: argparse.Namespace, now: datetime) -> datetime | None:
    """The date this item should get, or None if it can't be worked out."""
    if args.date:
        return args.date
    if args.now:
        return now
    if args.release:
        return item.originallyAvailableAt
    if item.addedAt is None:
        return None
    return item.addedAt + args.shift


def find_by_guid(section, level: str, guid: str) -> list:
    """Find items by Plex GUID (plex://...) or an agent GUID (imdb://, tmdb://, tvdb://)."""
    if guid.startswith("plex://"):
        return section.search(guid=guid, libtype=level)
    return [item for item in section.search(libtype=level)
            if any(g.id == guid for g in getattr(item, "guids", []))]


def find_items(section, level: str, args: argparse.Namespace) -> list:
    if args.title:
        return section.search(title=args.title, libtype=level)
    if args.guid:
        return find_by_guid(section, level, args.guid)
    return section.recentlyAdded(maxresults=args.recent, libtype=level)


def expand(item, cascade: bool) -> list:
    """The item itself, plus its seasons and episodes if cascading from a show or season."""
    targets = [item]
    if cascade:
        if item.type == "show":
            targets += item.seasons() + item.episodes()
        elif item.type == "season":
            targets += item.episodes()
    return targets


def show_item(index: int, item) -> None:
    released = getattr(item, "originallyAvailableAt", None)
    print(f"{paint(str(index).rjust(6), 'cyan')}: {paint(describe(item), 'bold')}")
    print(f"        Released: {released}")
    print(f"           Added: {item.addedAt}")
    print(f"         Plex ID: {item.guid}")
    for k, guid in enumerate(getattr(item, "guids", []), start=1):
        print(f"        GUID[{k:02d}]: {guid.id}")


def apply_dates(item, args: argparse.Namespace, now: datetime) -> dict:
    """Set (or preview) the new date on item and, if cascading, its children.

    Returns counts of 'changed' (which means 'would change' on a dry run),
    'unchanged' and 'skipped' (no date available, eg no release date).
    """
    counts = {"changed": 0, "unchanged": 0, "skipped": 0}
    children = {"changed": 0, "unchanged": 0, "skipped": 0}
    for target in expand(item, args.cascade):
        tally = counts if target is item else children
        date = new_date(target, args, now)
        if date is None:
            tally["skipped"] += 1
            continue
        if target.addedAt == date:
            tally["unchanged"] += 1
            continue
        previous = target.addedAt
        if args.commit:
            target.editAddedAt(date, locked=not args.no_lock)
            target.reload()
        tally["changed"] += 1
        if target is item:
            if args.commit:
                print(paint(f"      ! Date changed from {previous} to {target.addedAt}", "yellow"))
            else:
                print(paint(f"      ! Date would change from {previous} to {date}", "red"))
    if counts["skipped"]:
        print(paint("      ! No date available for this item (no release date?); skipped", "red"))
    if args.cascade:
        verb = "changed" if args.commit else "would change"
        print(f"      + children: {children['changed']} {verb}, "
              f"{children['unchanged']} already correct, {children['skipped']} skipped")
    return {k: counts[k] + children[k] for k in counts}


def add_parser(subparsers) -> None:
    parser = add_command(
        subparsers, 'recent',
        "change 'added at' dates to reorder Recently Added",
        "Change the 'added at' date of movies, shows, seasons or episodes, which moves them in Plex's Recently Added lists. Pick what to change (--title, --guid or --recent) and the new date (--date, --release, --now or --shift). Nothing is written unless --commit is given.\n\nPlex builds the TV Recently Added list from episodes. To reorder a series, use --cascade or --level episode.",
        ['plextool recent -l Movies -n 3 --release                  # preview the last 3 movies',
        'plextool recent -g plex://movie/abc123 --release --commit',
        "plextool recent -l 'TV Shows' -t 'Some Show' --cascade --release --commit",
        "plextool recent -l 'TV Shows' --level episode -n 20 --shift=-7d --commit"])
    add_connection_args(parser)
    parser.add_argument("-l", "--library", action="append", metavar="NAME",
                        help="library name; repeat for several (default: all movie and TV libraries)")
    parser.add_argument("--level", choices=sorted({lv for lvs in SECTION_LEVELS.values() for lv in lvs}),
                        help="what to change: movie, show, season or episode "
                             "(default: movie for movie libraries, show for TV libraries)")
    parser.add_argument("--cascade", action="store_true",
                        help="when changing a show or season, change its seasons and episodes too")

    select = parser.add_mutually_exclusive_group(required=True)
    select.add_argument("-t", "--title", help="select by title (substring match)")
    select.add_argument("-g", "--guid", "-p", "--plex-id", dest="guid", metavar="GUID",
                        help="select by Plex ID (plex://movie/...) or agent ID (imdb://tt..., tmdb://..., tvdb://...)")
    select.add_argument("-n", "--recent", type=int, metavar="N",
                        help="select the N most recently added items (per library)")

    when = parser.add_mutually_exclusive_group(required=True)
    when.add_argument("-d", "--date", type=parse_date, metavar="DATE",
                      help="set this date: YYYY-MM-DD or 'YYYY-MM-DD HH:MM:SS'")
    when.add_argument("-r", "--release", action="store_true",
                      help="set each item's date to its own original release/air date")
    when.add_argument("-N", "--now", action="store_true", help="set the date to right now")
    when.add_argument("-s", "--shift", type=parse_shift, metavar="OFFSET",
                      help="move each item's current date by an offset, eg +2w, 6h, 90min; write negatives with an = sign: --shift=-30d")

    parser.add_argument("--no-lock", action="store_true",
                        help="don't lock the date; by default it is locked so a rescan or "
                             "metadata refresh can't reset it")
    parser.add_argument("-y", "--commit", "--confirm", dest="commit", action="store_true",
                        help="write the changes (default is a dry run)")
    parser.set_defaults(run=run)


def run(args: argparse.Namespace) -> int:
    if args.recent is not None and args.recent < 1:
        raise PlexToolError("--recent must be at least 1")
    plex = connect(args)
    sections = pick_sections(plex, args.library)
    now = datetime.now().replace(microsecond=0)
    totals = {"changed": 0, "unchanged": 0, "skipped": 0}

    for section in sections:
        level = args.level or section.TYPE
        if level not in SECTION_LEVELS[section.TYPE]:
            if args.library:
                raise PlexToolError(
                    f"--level {level} doesn't apply to the {section.TYPE} library '{section.title}'")
            continue
        if args.cascade and level == "movie":
            raise PlexToolError("--cascade only applies to shows and seasons")
        items = find_items(section, level, args)
        print(paint(f" * {section.title}: found {plural(len(items), level)}", "cyan"))
        for index, item in enumerate(items, start=1):
            show_item(index, item)
            for key, value in apply_dates(item, args, now).items():
                totals[key] += value
            print()

    verb = "Changed" if args.commit else "Would change"
    print(f"{verb} {totals['changed']} item(s); {totals['unchanged']} already correct; "
          f"{totals['skipped']} skipped.")
    if not args.commit and totals["changed"]:
        print("Dry run only. Re-run with --commit to apply.")
    return 0
