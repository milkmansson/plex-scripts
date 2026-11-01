"""dupes: list items that Plex holds more than one file/version for."""

from __future__ import annotations

import argparse
import json

from plexapi.exceptions import BadRequest, NotFound

from .common import (
    FILE_LEVEL,
    PlexToolError,
    add_command,
    add_connection_args,
    add_library_arg,
    confirm_typed,
    connect,
    describe,
    paint,
    pick_sections,
    plural,
    pretty_size,
)


def find_duplicates(section) -> list:
    """Items in a section with more than one media version."""
    level = FILE_LEVEL[section.TYPE]
    try:
        return section.search(libtype=level, duplicate=True)
    except (BadRequest, NotFound):
        # The server didn't accept the duplicate filter; check every item instead.
        return [item for item in section.search(libtype=level) if len(item.media) > 1]


def summarise(item) -> dict:
    """A plain-data description of an item and each of its versions."""
    versions = []
    for index, media in enumerate(item.media):
        parts = [{"file": p.file, "size": p.size or 0} for p in media.parts]
        versions.append({
            "index": index,
            "resolution": media.videoResolution,
            "codec": media.videoCodec,
            "size": sum(p["size"] for p in parts),
            "height": media.height or 0,
            "parts": parts,
        })
    sizes = [v["size"] for v in versions]
    return {
        "title": describe(item),
        "plex_id": item.guid,
        "versions": versions,
        # Space freed by keeping only the largest version.
        "reclaimable": sum(sizes) - max(sizes, default=0),
    }


KEEP_KEYS = {
    "largest": lambda v: v["size"],
    "smallest": lambda v: -v["size"],
    "best-resolution": lambda v: (v["height"], v["size"]),
}


def choose_deletions(entry: dict, keep: str) -> tuple[list[int], str | None]:
    """Pick which versions of an item to delete, keeping one.

    Returns (indices to delete, reason the item was skipped or None). Items with a
    multi-part version are skipped, because deleting one part would break it.
    """
    versions = entry["versions"]
    if any(len(v["parts"]) > 1 for v in versions):
        return [], "has a multi-part version"
    best = max(versions, key=KEEP_KEYS[keep])
    return [v["index"] for v in versions if v is not best], None


def print_summary(number: int, entry: dict) -> None:
    print(f"{paint(str(number).rjust(5), 'cyan')} {paint(entry['title'], 'bold')}")
    for version in entry["versions"]:
        quality = " ".join(filter(None, (version["resolution"], version["codec"])))
        label = f"  [{quality}]" if quality else ""
        parts = version["parts"]
        if len(parts) == 1:
            print(f"     - [{version['index']}] {parts[0]['file']}  {pretty_size(version['size'])}{label}")
        else:
            print(f"     - [{version['index']}] {plural(len(parts), 'part')}, "
                  f"{pretty_size(version['size'])} total{label}")
            for part in parts:
                print(f"         {part['file']}  {pretty_size(part['size'])}")
            print(paint("         (multi-part version: these files play as one item; "
                        "deleting one part breaks it)", "yellow"))


def add_parser(subparsers) -> None:
    parser = add_command(
        subparsers, 'dupes',
        'list items with more than one file (and optionally delete extras)',
        'Report movies and episodes that Plex has more than one version of. Read-only unless --keep is given. Duplicates are whatever Plex has matched together, right or wrong.\n\n--keep deletes the other versions of every duplicate from disk. It is a preview unless you add --commit, and then you must type DELETE to confirm.',
        ['plextool dupes',
        'plextool dupes -l Movies --sort size -n 20',
        'plextool dupes -l Movies --keep best-resolution            # preview deletions',
        'plextool dupes -l Movies --keep best-resolution --commit   # really delete'])
    add_connection_args(parser)
    add_library_arg(parser)
    parser.add_argument("-n", "--limit", type=int, metavar="N", help="show at most N items per library")
    parser.add_argument("--sort", choices=("title", "size"), default="title",
                        help="order by title, or by reclaimable space (largest first)")
    parser.add_argument("--json", action="store_true", help="print JSON instead of text")
    parser.add_argument("--keep", choices=list(KEEP_KEYS),
                        help="DELETES the other versions of every duplicate, keeping the largest, "
                             "smallest or highest-resolution one. Dry run unless --commit.")
    parser.add_argument("-y", "--commit", action="store_true", help="with --keep: really delete files")
    parser.add_argument("--assume-yes", action="store_true", help="with --commit: skip the typed confirmation")
    parser.set_defaults(run=run)


def delete_extras(found: list, keep: str, commit: bool, assume_yes: bool) -> int:
    """Delete (or preview deleting) all but one version of each (item, entry) pair."""
    plan = []
    for item, entry in found:
        indices, skipped = choose_deletions(entry, keep)
        if skipped:
            print(paint(f"  skip {entry['title']}: {skipped}", "yellow"))
            continue
        plan.append((item, entry, indices))

    freed = 0
    print(paint(f"\nKeeping the {keep} version of each item:", "cyan"))
    for item, entry, indices in plan:
        print(f"  {entry['title']}")
        for v in entry["versions"]:
            action = paint("DELETE", "red") if v["index"] in indices else paint("keep  ", "green")
            print(f"    {action} {v['parts'][0]['file']}  {pretty_size(v['size'])}")
            if v["index"] in indices:
                freed += v["size"]
    count = sum(len(i) for _, _, i in plan)
    print(f"\n{plural(count, 'file')} would be deleted, freeing {pretty_size(freed)}.")
    if not commit or not count:
        if count:
            print("Dry run only. Re-run with --commit to delete.")
        return 0

    confirm_typed("DELETE", f"This permanently deletes {plural(count, 'file')} from disk.", assume_yes)
    for item, entry, indices in plan:
        victims = [item.media[i] for i in indices]
        for media in victims:
            try:
                media.delete()
            except BadRequest:
                raise PlexToolError(
                    "The server refused to delete. Enable Settings > Library > "
                    "'Allow media deletion' and try again.") from None
            print(f"  deleted {media.parts[0].file}")
    return 0


def run(args: argparse.Namespace) -> int:
    if args.limit is not None and args.limit < 1:
        raise PlexToolError("--limit must be at least 1")
    if args.commit and not args.keep:
        raise PlexToolError("--commit needs --keep")
    plex = connect(args)
    report = {}
    pairs = []
    for section in pick_sections(plex, args.library):
        found = [(item, summarise(item)) for item in find_duplicates(section)]
        if args.sort == "size":
            found.sort(key=lambda p: p[1]["reclaimable"], reverse=True)
        found = found[:args.limit] if args.limit else found
        pairs += found
        report[section.title] = [entry for _, entry in found]

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0 if not args.keep else delete_extras(pairs, args.keep, args.commit, args.assume_yes)

    total = reclaimable = 0
    for title, entries in report.items():
        print(paint(f"\n== {title}: {plural(len(entries), 'item')} with duplicates ==", "cyan"))
        for number, entry in enumerate(entries, start=1):
            print_summary(number, entry)
        total += len(entries)
        reclaimable += sum(e["reclaimable"] for e in entries)
    print(f"\n{plural(total, 'item')} with duplicates; "
          f"{pretty_size(reclaimable)} could be freed by keeping only the largest version of each.")
    if args.keep:
        return delete_extras(pairs, args.keep, args.commit, args.assume_yes)
    return 0
