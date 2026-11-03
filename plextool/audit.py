"""audit: find metadata and file problems across libraries."""

from __future__ import annotations

import argparse
import json

from .common import (
    FILE_LEVEL,
    PlexToolError,
    add_command,
    add_connection_args,
    add_library_arg,
    connect,
    describe,
    paint,
    pick_sections,
    plural,
    scan,
    working,
)
from .scan import wait_for_scans

LOW_RES = {"sd", "480", "576", "360", "240"}
MISSING_LIMIT = 25   # percent of a library; more than this missing usually means a drive is not mounted
UNMATCHED_PREFIXES = ("local://", "com.plexapp.agents.none")


# Each check takes (item, lang) and returns a short reason string, or None if the item is fine.

def check_unmatched(item, lang):
    if str(item.guid).startswith(UNMATCHED_PREFIXES):
        return "not matched to an online source"


def check_no_poster(item, lang):
    if not item.thumb:
        return "no poster"


def check_no_summary(item, lang):
    if not item.summary:
        return "no summary"


def check_missing_files(item, lang):
    bad = [part.file for media in item.media for part in media.parts if part.exists is False]
    if bad:
        return f"file missing on disk: {bad[0]}" + (f" (+{len(bad) - 1} more)" if len(bad) > 1 else "")


def check_low_res(item, lang):
    resolutions = {m.videoResolution for m in item.media if m.videoResolution}
    if resolutions and resolutions <= LOW_RES:
        return f"low resolution ({', '.join(sorted(resolutions))})"


def _streams(item, kind):
    return [s for media in item.media for part in media.parts for s in getattr(part, kind)()]


def check_no_subs(item, lang):
    if not any(s.languageCode == lang for s in _streams(item, "subtitleStreams")):
        return f"no '{lang}' subtitles"


def check_no_audio(item, lang):
    if not any(s.languageCode == lang for s in _streams(item, "audioStreams")):
        return f"no '{lang}' audio"


# name -> (function, works on files (movie/episode) rather than the library's top level, needs --lang,
#          needs the full item loaded to see its streams)
CHECKS = {
    "unmatched": (check_unmatched, False, False, False),
    "no-poster": (check_no_poster, False, False, False),
    "no-summary": (check_no_summary, False, False, False),
    "missing-files": (check_missing_files, True, False, False),
    "low-res": (check_low_res, True, False, False),
    "no-subs": (check_no_subs, True, True, True),
    "no-audio": (check_no_audio, True, True, True),
}


def run_check(name: str, items: list, lang: str | None) -> list[dict]:
    """Apply one check to items; returns [{'item': description, 'reason': ...}]."""
    func, _, _, needs_full = CHECKS[name]
    found = []
    with working(f"checking {name}") as progress:
        for number, item in enumerate(items, start=1):
            progress.detail = f"{number} of {len(items)} items"
            if needs_full:
                item.reload()
            reason = func(item, lang)
            if reason:
                found.append({"item": describe(item), "reason": reason})
    return found


def add_parser(subparsers) -> None:
    parser = add_command(
        subparsers, 'audit',
        'find unmatched items, missing files, missing subtitles and more',
        "Report problems in your libraries. Read-only. Checks: unmatched, no-poster, no-summary, missing-files, low-res, no-subs, no-audio. With no --check, every check that doesn't need --lang runs. no-subs and no-audio read every item's tracks and are slow on large libraries.",
        ['plextool audit',
        'plextool audit -c missing-files -c unmatched',
        "plextool audit -c no-subs --lang eng -l 'TV Shows'"])
    add_connection_args(parser)
    add_library_arg(parser)
    parser.add_argument("-c", "--check", action="append", choices=list(CHECKS), metavar="CHECK",
                        help="check to run; repeat for several (default: all that don't need --lang)")
    parser.add_argument("--lang", help="3-letter language code, as Plex shows it, for no-subs / no-audio, eg eng")
    parser.add_argument("-n", "--limit", type=int, metavar="N", help="show at most N problems per check")
    parser.add_argument("--json", action="store_true", help="print JSON instead of text")
    parser.add_argument("--clean-missing", action="store_true",
                        help="remove items whose files are gone: scan the library so Plex trashes them, then empty "
                             "the trash (a dry run unless --commit)")
    parser.add_argument("--commit", action="store_true", help="with --clean-missing, actually do it")
    parser.add_argument("--force", action="store_true",
                        help=f"with --clean-missing, go ahead even if over {MISSING_LIMIT}%% of a library is missing")
    parser.set_defaults(run=run)


def clean_missing(plex, args: argparse.Namespace) -> int:
    """Remove items whose files are gone, the way Plex does it: scan so they are trashed, then empty the trash."""
    todo = []
    for section in pick_sections(plex, args.library):
        items = scan(section, libtype=FILE_LEVEL[section.TYPE])
        missing = run_check("missing-files", items, None)
        percent = 100 * len(missing) / len(items) if items else 0
        print(paint(f"\n{section.title}: {plural(len(missing), 'file item')} missing of {len(items)} "
                    f"({percent:.0f}%)", "cyan"))
        for problem in missing[:args.limit or 15]:
            print(f"  {problem['item']}: {problem['reason']}")
        if not missing:
            continue
        if percent > MISSING_LIMIT and not args.force:
            raise PlexToolError(
                f"{percent:.0f}% of '{section.title}' is missing, which usually means a drive or share is not mounted "
                f"and not that the files were deleted. Nothing was changed. Check the storage, or pass --force "
                f"(the limit is {MISSING_LIMIT}%).")
        todo.append(section)
    if not todo:
        print("\nNothing to clean.")
        return 0
    names = ", ".join(s.title for s in todo)
    print(f"\nTo clean: scan {names}, then empty the trash of each. Emptying the trash also removes anything "
          "already in it. Watch history for the removed items is lost.")
    if not args.commit:
        print(paint("Dry run. Pass --commit to do it.", "yellow"))
        return 0
    for section in todo:
        section.update()
    wait_for_scans(plex, [s.title for s in todo])
    for section in todo:
        section.emptyTrash()
        print(f"Emptied trash: {section.title}")
    print("Run 'plextool audit -c missing-files' again to check.")
    return 0


def run(args: argparse.Namespace) -> int:
    if args.clean_missing:
        return clean_missing(connect(args), args)
    names = args.check or [n for n, (_, _, needs_lang, _) in CHECKS.items() if not needs_lang]
    for name in names:
        if CHECKS[name][2] and not args.lang:
            raise PlexToolError(f"Check '{name}' needs --lang, eg --lang eng")
    if args.limit is not None and args.limit < 1:
        raise PlexToolError("--limit must be at least 1")

    plex = connect(args)
    report: dict = {}
    for section in pick_sections(plex, args.library):
        cache: dict[str, list] = {}
        for name in names:
            level = FILE_LEVEL[section.TYPE] if CHECKS[name][1] else section.TYPE
            if level not in cache:
                cache[level] = scan(section, libtype=level)
            report.setdefault(name, {})[section.title] = run_check(name, cache[level], args.lang)

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0

    total = 0
    for name, libs in report.items():
        for title, problems in libs.items():
            print(paint(f"\n== {name} in {title}: {plural(len(problems), 'problem')} ==", "cyan"))
            for problem in problems[:args.limit]:
                print(f"  {problem['item']}: {problem['reason']}")
            total += len(problems)
    print(f"\n{plural(total, 'problem')} found.")
    return 0
