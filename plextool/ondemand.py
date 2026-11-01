"""subs export / subs fetch: work with subtitles Plex downloads on demand."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import requests
from plexapi.exceptions import BadRequest, NotFound

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
)
from .recent import find_by_guid
from .subs import ISO3_TO_ISO1, lang_code, output_names

# Plex's search options: 0 = prefer not, 1 = prefer, 2 = only, 3 = exclude
PREFERENCE = {"prefer": 1, "only": 2, "exclude": 3}
EXT_ALIASES = {"subrip": "srt", "ass": "ass", "ssa": "ass", "webvtt": "vtt"}


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def short_lang(code: str | None) -> str:
    """Two-letter language code from a 2- or 3-letter one, eg 'eng' -> 'en'."""
    code = (code or "").lower()
    return ISO3_TO_ISO1.get(code, code) if len(code) == 3 else code


def stream_lang(stream) -> str:
    return short_lang(stream.languageTag or lang_code(None, stream.languageCode))


def stream_track(stream) -> dict:
    """The fields subs.output_names needs, from a plexapi SubtitleStream."""
    ext = (stream.format or stream.codec or "srt").lower()
    return {"lang": stream_lang(stream), "forced": bool(stream.forced),
            "sdh": bool(stream.hearingImpaired), "ext": EXT_ALIASES.get(ext, ext)}


def is_downloaded(stream, include_external: bool = False) -> bool:
    """A subtitle Plex fetched or was given (not embedded in the video).

    Embedded tracks have no stream URL. Ones from a provider carry provider details.
    With include_external, any stream that has a URL counts, sidecar files included.
    """
    if not stream.key:
        return False
    return include_external or bool(stream.providerTitle or stream.userID or stream.sourceKey)


def parse_map(text: str) -> tuple[str, str]:
    if "=" not in text:
        raise argparse.ArgumentTypeError("use SERVER_PATH=LOCAL_PATH, eg /data/media=/mnt/media")
    server, local = text.split("=", 1)
    return server.rstrip("/"), local.rstrip("/")


def map_path(path: str, mappings: list[tuple[str, str]]) -> Path:
    """Translate a path as the Plex server sees it into one on this machine."""
    for server, local in mappings or []:
        if path == server or path.startswith(server + "/"):
            return Path(local + path[len(server):])
    return Path(path)


def http_fetch(plex, stream) -> bytes:
    response = requests.get(plex.url(stream.key, includeToken=True), timeout=30)
    response.raise_for_status()
    return response.content


def expand_to_files(item) -> list:
    """Episodes of a show or season; movies and episodes as they are."""
    if item.type in ("show", "season"):
        return item.episodes()
    return [item]


def select_files(plex, args: argparse.Namespace) -> list[tuple]:
    """(section, movie-or-episode) pairs chosen by --title, --guid, --recent or --all."""
    pairs = []
    for section in pick_sections(plex, args.library):
        if args.title:
            items = section.search(title=args.title, libtype=section.TYPE)
        elif args.guid:
            items = find_by_guid(section, section.TYPE, args.guid)
        elif args.recent:
            items = section.recentlyAdded(maxresults=args.recent, libtype=FILE_LEVEL[section.TYPE])
        else:
            items = section.search(libtype=FILE_LEVEL[section.TYPE])
        for item in items:
            pairs += [(section, f) for f in expand_to_files(item)]
    return pairs


def add_selector_args(parser: argparse.ArgumentParser) -> None:
    add_library_arg(parser)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("-t", "--title", help="movies or shows whose title contains this (shows: all episodes)")
    group.add_argument("-g", "--guid", metavar="GUID", help="one movie or show, by Plex ID or imdb://, tmdb://, tvdb://")
    group.add_argument("-n", "--recent", type=int, metavar="N", help="the N most recently added items per library")
    group.add_argument("--all", action="store_true", help="every movie and episode (slow on big libraries)")


def add_path_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--map", action="append", type=parse_map, default=[], metavar="SERVER=LOCAL",
                        help="translate a server path to the matching path on this machine; "
                             "repeat for several, eg /data/media=/mnt/media")
    parser.add_argument("-f", "--force", action="store_true", help="overwrite subtitle files that already exist")
    parser.add_argument("--scan", action="store_true",
                        help="afterwards ask Plex to scan the folders that got new files")
    parser.add_argument("-y", "--commit", action="store_true", help="write changes (default is a dry run)")


# ---------------------------------------------------------------------------
# export
# ---------------------------------------------------------------------------

def lazy_header(item):
    """A print function that first prints the item's name, but only if something is printed."""
    state = {"shown": False}

    def emit(message: str) -> None:
        if not state["shown"]:
            print(f">> {describe(item)}")
            state["shown"] = True
        print(message)

    return emit


def export_item(plex, item, args: argparse.Namespace, fetch=None,
                only_ids: set | None = None, emit=print) -> tuple[int, set]:
    """Save an item's downloaded subtitles beside its video. Returns (files, server folders written)."""
    fetch = fetch or http_fetch
    written = 0
    folders: set[str] = set()
    item.subtitleStreams()  # loads the full item if it was only a search result
    for media in item.media:
        for part in media.parts:
            streams = [s for s in part.subtitleStreams()
                       if is_downloaded(s, getattr(args, "all_external", False))
                       and (only_ids is None or s.id in only_ids)
                       and (not getattr(args, "lang", None) or stream_lang(s) == short_lang(args.lang))]
            if not streams:
                continue
            video = map_path(part.file, args.map)
            for stream, out in zip(streams, output_names(video, [stream_track(s) for s in streams])):
                if out.exists() and not args.force:
                    emit(f"   {out.name}: exists, skipped (use --force)")
                    continue
                emit(f"   {stream.displayTitle or stream.title} ({stream.providerTitle or 'external'}) -> {out}")
                if args.commit:
                    if not out.parent.is_dir():
                        emit(paint(f"      ! {out.parent} not found here; use --map", "red"))
                        continue
                    out.write_bytes(fetch(plex, stream))
                written += 1
                folders.add(str(Path(part.file).parent))
    return written, folders


def note_folders(touched: dict, section, folders: set) -> None:
    """Remember which server folders got new files, per library (keyed by title)."""
    entry = touched.setdefault(section.title, (section, set()))
    entry[1].update(folders)


def rescan(touched: dict) -> None:
    for section, folders in touched.values():
        for folder in sorted(folders):
            section.update(path=folder)
            print(f"Asked Plex to scan {folder} in '{section.title}'.")


def run_export(args: argparse.Namespace) -> int:
    plex = connect(args)
    total = 0
    touched: dict = {}
    pairs = select_files(plex, args)
    for section, item in pairs:
        count, folders = export_item(plex, item, args, emit=lazy_header(item))
        total += count
        if count:
            note_folders(touched, section, folders)
    verb = "Saved" if args.commit else "Would save"
    print(f"\n{verb} {plural(total, 'subtitle file')} from {plural(len(pairs), 'item')} checked.")
    if not args.commit and total:
        print("Dry run only. Re-run with --commit to write them.")
    if args.commit and args.scan and touched:
        rescan(touched)
    return 0


# ---------------------------------------------------------------------------
# fetch
# ---------------------------------------------------------------------------

def has_language(item, lang: str) -> bool:
    return any(stream_lang(s) == lang for s in item.subtitleStreams())


def rank(candidates: list, min_score: int = 0) -> list:
    """Best first: perfect matches, then most downloaded. Drops low scorers (but never perfect matches)."""
    kept = [c for c in candidates if c.perfectMatch or (c.score or 0) >= min_score]
    return sorted(kept, key=lambda c: (bool(c.perfectMatch), c.score or 0), reverse=True)


def candidate_line(number: int, c) -> str:
    flags = " ".join(f for f, on in (("forced", c.forced), ("sdh", c.hearingImpaired)) if on)
    perfect = "*" if c.perfectMatch else " "
    return (f"  {number:>3} {perfect} score {c.score or 0:<7} {c.providerTitle or '?':<16} "
            f"{(c.format or c.codec or '?'):<5} {flags:<11} {c.title or c.displayTitle or ''}")


def ask_choice(count: int) -> int | None:
    """Prompt for a candidate. Returns its index, None to skip this item; raises on quit."""
    while True:
        answer = input(f"Pick 1-{count}, Enter for #1, s to skip, q to quit: ").strip().lower()
        if answer == "":
            return 0
        if answer == "s":
            return None
        if answer == "q":
            raise PlexToolError("Stopped at your request.")
        if answer.isdigit() and 1 <= int(answer) <= count:
            return int(answer) - 1
        print("  Not a valid choice.")


def wait_for_new(item, before: set, lang: str, timeout: float, interval: float = 2.0) -> set:
    """Ids of subtitle streams that appeared on item since `before`, in lang (empty if none arrive)."""
    deadline = time.monotonic() + timeout
    while True:
        item.reload()
        new = {s.id for s in item.subtitleStreams() if s.id not in before and stream_lang(s) == lang}
        if new or time.monotonic() >= deadline:
            return new
        time.sleep(interval)


def run_fetch(args: argparse.Namespace) -> int:
    if args.export and not args.commit:
        print("(Dry run: nothing will be downloaded or exported.)")
    if args.choose and not sys.stdin.isatty():
        raise PlexToolError("--choose needs a terminal to ask you on.")
    lang = short_lang(args.lang)
    options = {"hearingImpaired": PREFERENCE.get(args.sdh, 0), "forced": PREFERENCE.get(args.forced, 0)}

    plex = connect(args)
    pairs = select_files(plex, args)
    print(f"Checking {plural(len(pairs), 'item')} for '{lang}' subtitles...")
    requested = []   # (section, item, ids before download)
    skipped_present = no_candidates = 0
    for section, item in pairs:
        if not args.include_present and has_language(item, lang):
            skipped_present += 1
            continue
        try:
            candidates = rank(item.searchSubtitles(language=lang, **options), args.min_score)
        except (BadRequest, NotFound) as e:
            print(paint(f"{describe(item)}: subtitle search failed ({e})", "yellow"))
            continue
        if not candidates:
            no_candidates += 1
            print(f"{describe(item)}: no subtitles found")
            continue

        shown = candidates[:args.candidates]
        print(paint(f"\n{describe(item)}: {plural(len(candidates), 'candidate')}", "cyan"))
        if args.list or args.choose:
            for number, c in enumerate(shown, start=1):
                print(candidate_line(number, c))
        if args.list:
            continue
        pick = ask_choice(len(shown)) if args.choose else 0
        if pick is None:
            continue
        chosen = shown[pick]
        print(f"  {'Downloading' if args.commit else 'Would download'}: "
              f"{chosen.providerTitle} score {chosen.score or 0}"
              f"{' (perfect match)' if chosen.perfectMatch else ''}")
        if args.commit:
            before = {s.id for s in item.subtitleStreams()}
            item.downloadSubtitles(chosen)
            requested.append((section, item, before))

    print(f"\nRequested {len(requested)} download(s); {skipped_present} already had '{lang}'; "
          f"{no_candidates} had nothing available.")
    if not args.commit and not args.list:
        print("Dry run only. Re-run with --commit to download.")
    if not (args.commit and args.export and requested):
        return 0

    print("Waiting for Plex to finish downloading...")
    total = 0
    touched: dict = {}
    for section, item, before in requested:
        new = wait_for_new(item, before, lang, args.wait)
        if not new:
            print(paint(f"{describe(item)}: subtitle hasn't arrived yet; run 'subs export' later", "yellow"))
            continue
        print(f">> {describe(item)}")
        count, folders = export_item(plex, item, args, only_ids=new)
        total += count
        if count:
            note_folders(touched, section, folders)
    print(f"\nSaved {plural(total, 'subtitle file')}.")
    if args.scan and touched:
        rescan(touched)
    return 0


# ---------------------------------------------------------------------------
# Registering the commands
# ---------------------------------------------------------------------------

def add_actions(sub) -> None:
    export = add_command(
        sub, "export", "save Plex's downloaded subtitles next to the videos",
        "Subtitles that Plex downloads on demand live in its database, not beside the video. "
        "This saves them as files next to the video, named like 'subs extract' names tracks "
        "(Movie.en.srt, Movie.en.forced.srt, Movie.en.sdh.srt, Movie.2.en.srt). Nothing is "
        "written unless --commit is given. Every selected item is loaded from the server, so "
        "--all is slow on large libraries.\n\nThis script has to be able to reach the video "
        "files. If Plex sees them under a different path than this machine does, translate "
        "with --map SERVER=LOCAL.",
        ["plextool subs export -t 'Some Show'",
         "plextool subs export --all --lang eng --commit --scan",
         "plextool subs export -l Movies -n 20 --map /data/media=/mnt/media --commit"])
    add_connection_args(export)
    add_selector_args(export)
    export.add_argument("--lang", help="only this language, eg en or eng")
    export.add_argument("--all-external", action="store_true",
                        help="also export subtitle files that were already beside the video (normally "
                             "only ones downloaded from a provider are exported)")
    add_path_args(export)
    export.set_defaults(run=run_export)

    fetch = add_command(
        sub, "fetch", "search for subtitles in a language and download one",
        "For movies and episodes with no subtitle in --lang, ask Plex's subtitle search for "
        "candidates and download one into Plex. Candidates are ranked perfect matches first, "
        "then by download count (score), but the top one isn't always the best. Use --list to "
        "see what is available, or --choose to be shown the candidates for each item and pick "
        "yourself. Add --export to also save the result beside the video.\n\nNothing is "
        "downloaded unless --commit is given. Downloads happen in the background on the server.",
        ["plextool subs fetch -t 'Some Movie' --lang en --list        # just look",
         "plextool subs fetch -t 'Some Show' --lang fr --choose --commit",
         "plextool subs fetch -n 20 --lang en --sdh prefer --export --commit"])
    add_connection_args(fetch)
    add_selector_args(fetch)
    fetch.add_argument("--lang", required=True, help="language to look for, eg en or eng")
    fetch.add_argument("--sdh", choices=PREFERENCE, help="SDH (hearing impaired) subtitles: prefer, only or exclude")
    fetch.add_argument("--forced", choices=PREFERENCE, help="forced subtitles: prefer, only or exclude")
    fetch.add_argument("--min-score", type=int, default=0, metavar="N",
                       help="ignore candidates with a lower download count (perfect matches are always kept)")
    fetch.add_argument("--candidates", type=int, default=10, metavar="N", help="show at most N candidates (default 10)")
    how = fetch.add_mutually_exclusive_group()
    how.add_argument("--list", action="store_true", help="show the candidates and stop; downloads nothing")
    how.add_argument("--choose", action="store_true", help="show the candidates for each item and ask which to download")
    fetch.add_argument("--include-present", action="store_true",
                       help="also search items that already have a subtitle in this language")
    fetch.add_argument("--export", action="store_true", help="after downloading, save the subtitle beside the video")
    fetch.add_argument("--wait", type=float, default=30.0, metavar="SECONDS",
                       help="with --export, how long to wait for each download to arrive (default 30)")
    add_path_args(fetch)
    fetch.set_defaults(run=run_fetch)
