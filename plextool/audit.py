"""audit: find metadata and file problems across libraries."""

from __future__ import annotations

import argparse
import json

from .common import (
    FILE_LEVEL,
    PlexToolError,
    add_connection_args,
    add_library_arg,
    connect,
    describe,
    paint,
    pick_sections,
    plural,
)

LOW_RES = {"sd", "480", "576", "360", "240"}
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
    for item in items:
        if needs_full:
            item.reload()
        reason = func(item, lang)
        if reason:
            found.append({"item": describe(item), "reason": reason})
    return found


def add_parser(subparsers) -> None:
    parser = subparsers.add_parser(
        "audit", help="find unmatched items, missing files, missing subtitles and more",
        description="Report problems in your libraries. Read-only. Available checks: "
                    + ", ".join(CHECKS) + ".")
    add_connection_args(parser)
    add_library_arg(parser)
    parser.add_argument("-c", "--check", action="append", choices=list(CHECKS), metavar="CHECK",
                        help="check to run; repeat for several (default: all that don't need --lang)")
    parser.add_argument("--lang", help="3-letter language code, as Plex shows it, for no-subs / no-audio, eg eng")
    parser.add_argument("-n", "--limit", type=int, metavar="N", help="show at most N problems per check")
    parser.add_argument("--json", action="store_true", help="print JSON instead of text")
    parser.set_defaults(run=run)


def run(args: argparse.Namespace) -> int:
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
                cache[level] = section.search(libtype=level)
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
