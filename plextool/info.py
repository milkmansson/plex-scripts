"""info: show everything Plex knows about a movie, show, season or episode, or compare several."""

from __future__ import annotations

import argparse
import json
import shutil
import textwrap
import xml.etree.ElementTree as ET
from datetime import datetime
from itertools import chain

from plexapi.exceptions import NotFound

from .common import (
    SECTION_LEVELS,
    PlexToolError,
    add_command,
    add_connection_args,
    add_library_arg,
    connect,
    describe,
    no_autoreload,
    paint,
    pick_sections,
    plural,
    pretty_size,
    working,
)
from .recent import find_by_guid

GROUPS = ("summary", "people", "tags", "playback", "tech", "extras")
DEFAULT_GROUPS = ("summary", "tech")

HDR_BY_TRANSFER = {"smpte2084": "HDR10", "arib-std-b67": "HLG"}
NOT_ANALYSED = "not analysed"


# ---------------------------------------------------------------------------
# Turning Plex's objects into plain data
# ---------------------------------------------------------------------------

def fmt_duration(ms: int | None) -> str | None:
    """Milliseconds as '2h 03m' or '45m 10s'."""
    if not ms:
        return None
    seconds = round(ms / 1000)
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}h {minutes:02d}m" if hours else f"{minutes}m {secs:02d}s"


def tag_names(tags) -> list[str]:
    return [t.tag for t in tags or [] if getattr(t, "tag", None)]


def hdr_label(stream) -> str | None:
    """A short name for the HDR format of a video stream, from the fields Plex reports."""
    if getattr(stream, "DOVIPresent", None):
        profile = getattr(stream, "DOVIProfile", None)
        return f"Dolby Vision (profile {profile})" if profile is not None else "Dolby Vision"
    return HDR_BY_TRANSFER.get(getattr(stream, "colorTrc", None) or "")


def video_info(stream) -> dict:
    size = f"{stream.width}x{stream.height}" if getattr(stream, "width", None) and getattr(stream, "height", None) else None
    return {
        "codec": getattr(stream, "codec", None),
        "profile": getattr(stream, "profile", None),
        "resolution": size,
        "bit depth": getattr(stream, "bitDepth", None),
        "frame rate": getattr(stream, "frameRate", None),
        "bitrate (kbps)": getattr(stream, "bitrate", None),
        "hdr": hdr_label(stream),
        "colour space": getattr(stream, "colorSpace", None),
    }


def audio_info(stream) -> dict:
    return {
        "language": getattr(stream, "language", None),
        "code": getattr(stream, "languageCode", None),
        "codec": getattr(stream, "codec", None),
        "channels": getattr(stream, "channels", None),
        "layout": getattr(stream, "audioChannelLayout", None),
        "bitrate (kbps)": getattr(stream, "bitrate", None),
        "title": getattr(stream, "title", None),
        "default": bool(getattr(stream, "default", False)),
    }


def subtitle_info(stream) -> dict:
    return {
        "language": getattr(stream, "language", None),
        "code": getattr(stream, "languageCode", None),
        "format": getattr(stream, "format", None) or getattr(stream, "codec", None),
        "forced": bool(getattr(stream, "forced", False)),
        "sdh": bool(getattr(stream, "hearingImpaired", False)),
        "title": getattr(stream, "title", None),
        "source": "external" if getattr(stream, "key", None) else "embedded",
        "provider": getattr(stream, "providerTitle", None),
    }


def version_info(media) -> dict:
    """One file version of an item: its files and the video, audio and subtitle streams in them."""
    parts = list(getattr(media, "parts", None) or [])
    video, audio, subs, files = {}, [], [], []
    for part in parts:
        files.append({"path": getattr(part, "file", None), "size": getattr(part, "size", None),
                      "container": getattr(part, "container", None)})
        if not video and part.videoStreams():
            video = video_info(part.videoStreams()[0])
        audio += [audio_info(s) for s in part.audioStreams()]
        subs += [subtitle_info(s) for s in part.subtitleStreams()]
    analysed = bool(video or audio or subs)  # Plex lists streams only for files it has analysed
    if not video:  # fall back on what the version itself says
        video = {"codec": getattr(media, "videoCodec", None), "profile": getattr(media, "videoProfile", None),
                 "resolution": f"{media.width}x{media.height}" if getattr(media, "width", None) else None,
                 "frame rate": getattr(media, "videoFrameRate", None)}
    return {
        "container": getattr(media, "container", None),
        "duration": fmt_duration(getattr(media, "duration", None)),
        "bitrate (kbps)": getattr(media, "bitrate", None),
        "aspect ratio": getattr(media, "aspectRatio", None),
        "analysed": analysed,
        "files": files,
        "size": sum(f["size"] or 0 for f in files),
        "video": video,
        "audio": audio,
        "subtitles": subs,
    }


def dated(value) -> str | None:
    return value.strftime("%Y-%m-%d %H:%M") if isinstance(value, datetime) else None


def item_info(item) -> dict:
    """Everything plextool shows about one fully loaded item, as plain data."""
    ids = {}
    for guid in getattr(item, "guids", None) or []:
        scheme, _, value = guid.id.partition("://")
        ids[scheme] = value
    released = getattr(item, "originallyAvailableAt", None)
    summary = {
        "title": getattr(item, "title", None),
        "kind": getattr(item, "type", None),
        "year": getattr(item, "year", None),
        "original title": getattr(item, "originalTitle", None),
        "tagline": getattr(item, "tagline", None),
        "summary": getattr(item, "summary", None),
        "content rating": getattr(item, "contentRating", None),
        "studio": getattr(item, "studio", None),
        "network": getattr(item, "network", None),
        "released": released.strftime("%Y-%m-%d") if isinstance(released, datetime) else None,
        "runtime": fmt_duration(getattr(item, "duration", None)),
        "critic rating": getattr(item, "rating", None),
        "audience rating": getattr(item, "audienceRating", None),
        "library": getattr(item, "librarySectionTitle", None),
        "added": dated(getattr(item, "addedAt", None)),
        "updated": dated(getattr(item, "updatedAt", None)),
        "rating key": getattr(item, "ratingKey", None),
        "guid": getattr(item, "guid", None),
    }
    if getattr(item, "type", None) == "episode":
        summary["show"] = getattr(item, "grandparentTitle", None)
        summary["season"] = getattr(item, "parentIndex", None)
        summary["episode"] = getattr(item, "index", None)
    people = {
        "directors": tag_names(getattr(item, "directors", None)),
        "writers": tag_names(getattr(item, "writers", None)),
        "producers": tag_names(getattr(item, "producers", None)),
        "cast": [f"{r.tag} as {r.role}" if getattr(r, "role", None) else r.tag
                 for r in getattr(item, "roles", None) or []],
    }
    tags = {
        "genres": tag_names(getattr(item, "genres", None)),
        "collections": tag_names(getattr(item, "collections", None)),
        "labels": tag_names(getattr(item, "labels", None)),
        "countries": tag_names(getattr(item, "countries", None)),
        "ids": ids,
    }
    playback = {
        "watched": bool(getattr(item, "isPlayed", False)),
        "view count": getattr(item, "viewCount", None),
        "last viewed": dated(getattr(item, "lastViewedAt", None)),
        "resume at": fmt_duration(getattr(item, "viewOffset", None)),
    }
    extras = {
        "chapters": len(getattr(item, "chapters", None) or []),
        "markers": [f"{m.type} {fmt_duration(m.start) or '0m 00s'} to {fmt_duration(m.end) or '?'}"
                    for m in getattr(item, "markers", None) or []],
    }
    versions = [version_info(m) for m in getattr(item, "media", None) or []]
    info = {"summary": summary, "people": people, "tags": tags, "playback": playback,
            "tech": versions, "extras": extras}
    if getattr(item, "type", None) in ("show", "season"):
        info["children"] = {
            "seasons": getattr(item, "childCount", None),
            "episodes": getattr(item, "leafCount", None),
            "watched episodes": getattr(item, "viewedLeafCount", None),
        }
    return info


def episode_rows(item) -> list[dict]:
    """One row per episode of a show or season, from the list view (no extra request per episode)."""
    rows = []
    for ep in no_autoreload(item.episodes()):
        media = (ep.media or [None])[0]
        rows.append({
            "episode": f"S{ep.seasonNumber or 0:02d}E{ep.episodeNumber or 0:02d}",
            "title": ep.title,
            "runtime": fmt_duration(ep.duration),
            "size": sum(getattr(p, "size", 0) or 0 for m in ep.media or [] for p in m.parts),
            "container": getattr(media, "container", None),
            "video": " ".join(str(x) for x in (getattr(media, "videoCodec", None),
                                               getattr(media, "videoResolution", None)) if x),
            "audio": " ".join(str(x) for x in (getattr(media, "audioCodec", None),
                                               getattr(media, "audioChannels", None)) if x),
        })
    return rows


# ---------------------------------------------------------------------------
# Finding the items
# ---------------------------------------------------------------------------

def candidate_line(item) -> str:
    return f"  -k {item.ratingKey}   {describe(item)}   [{getattr(item, 'librarySectionTitle', '?')}]"


def choose_one(query: str, found: list):
    """The single item a title matched, preferring an exact title, or an error listing the choices."""
    if not found:
        raise PlexToolError(f"Nothing matches '{query}'.")
    if len(found) > 1:
        exact = [i for i in found if (getattr(i, "title", "") or "").lower() == query.lower()]
        if len(exact) == 1:
            return exact[0]
        lines = "\n".join(candidate_line(i) for i in found[:15])
        more = f"\n  ... and {len(found) - 15} more" if len(found) > 15 else ""
        raise PlexToolError(f"'{query}' matches {len(found)} items. Pick one with -k, -g, a longer title "
                            f"or -l:\n{lines}{more}")
    return found[0]


def search_sections(sections, level: str | None, finder) -> list:
    found = []
    for section in sections:
        use = level or SECTION_LEVELS[section.TYPE][0]
        if use not in SECTION_LEVELS[section.TYPE]:
            continue
        with working(f"searching {section.title}"):
            found += finder(section, use)
    return found


def resolve_items(plex, args: argparse.Namespace) -> list:
    sections = pick_sections(plex, args.library)
    items = []
    for title in args.title:
        items.append(choose_one(title, search_sections(
            sections, args.level, lambda s, lv, t=title: s.search(title=t, libtype=lv))))
    for guid in args.guid:
        items.append(choose_one(guid, search_sections(
            sections, args.level, lambda s, lv, g=guid: find_by_guid(s, lv, g))))
    for key in args.rating_key:
        try:
            items.append(plex.fetchItem(key))
        except NotFound:
            raise PlexToolError(f"No item has the rating key {key}.") from None
    for item in items:
        item.reload()
    return items


# ---------------------------------------------------------------------------
# Showing it
# ---------------------------------------------------------------------------

def show_value(value) -> str:
    if value is None or value == "" or value == []:
        return "-"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    if isinstance(value, dict):
        return ", ".join(f"{k}: {v}" for k, v in value.items())
    return str(value)


def print_pairs(pairs: dict, indent: int = 2) -> None:
    shown = {k: v for k, v in pairs.items() if v not in (None, "", [], {})}
    if not shown:
        print(" " * indent + "-")
        return
    width = max(len(k) for k in shown)
    for key, value in shown.items():
        text = show_value(value)
        wrapped = textwrap.wrap(text, 100 - width - indent, break_long_words=False) or [text]
        print(f"{' ' * indent}{key:<{width}}  {wrapped[0]}")
        for more in wrapped[1:]:
            print(f"{' ' * (indent + width + 2)}{more}")


def heading(text: str) -> None:
    print(paint(f"\n{text}", "cyan"))


def print_version(number: int, total: int, version: dict) -> None:
    label = f"Version {number} of {total}" if total > 1 else "File"
    print(paint(f"  {label}", "bold"))
    size = pretty_size(version["size"]) if version["size"] else None
    print_pairs({"container": version["container"], "runtime": version["duration"], "size": size,
                 "bitrate (kbps)": version["bitrate (kbps)"], "aspect ratio": version["aspect ratio"]}, 4)
    for file in version["files"]:
        print(f"    path  {file['path']}")
    if not version["analysed"]:
        print("    video  (from the file summary; Plex has not analysed this file yet)")
        print_pairs(version["video"], 6)
        print(f"    audio      {NOT_ANALYSED}")
        print(f"    subtitles  {NOT_ANALYSED}")
        return
    print("    video")
    print_pairs(version["video"], 6)
    print(f"    audio ({len(version['audio'])})" + ("  none" if not version["audio"] else ""))
    for number_, audio in enumerate(version["audio"], start=1):
        parts = [audio["language"] or audio["code"] or "unknown language", audio["codec"],
                 audio["layout"] or (f"{audio['channels']} ch" if audio["channels"] else None),
                 f"{audio['bitrate (kbps)']} kbps" if audio["bitrate (kbps)"] else None,
                 "default" if audio["default"] else None, audio["title"]]
        print(f"      {number_}. " + ", ".join(str(p) for p in parts if p))
    print(f"    subtitles ({len(version['subtitles'])})" + ("  none" if not version["subtitles"] else ""))
    for number_, sub in enumerate(version["subtitles"], start=1):
        parts = [sub["language"] or sub["code"] or "unknown language", sub["format"], sub["source"],
                 "forced" if sub["forced"] else None, "SDH" if sub["sdh"] else None,
                 sub["provider"], sub["title"]]
        print(f"      {number_}. " + ", ".join(str(p) for p in parts if p))


def print_item(info: dict, groups, episodes: list | None) -> None:
    summary = info["summary"]
    year = f" ({summary['year']})" if summary.get("year") else ""
    print(paint(f"{summary['title']}{year}", "bold") + f"  [{summary['kind']}]")
    if "summary" in groups:
        heading("Summary")
        print_pairs({k: v for k, v in summary.items() if k not in ("title", "year", "kind")})
        if "children" in info:
            print_pairs(info["children"])
    if "people" in groups:
        heading("People")
        print_pairs(info["people"])
    if "tags" in groups:
        heading("Tags and IDs")
        print_pairs(info["tags"])
    if "playback" in groups:
        heading("Playback (token owner)")
        print_pairs(info["playback"])
    if "extras" in groups:
        heading("Chapters and markers")
        print_pairs(info["extras"])
    if "tech" in groups:
        heading("Technical")
        if not info["tech"]:
            print("  no files (a show or season holds none itself; add --episodes)")
        for number, version in enumerate(info["tech"], start=1):
            print_version(number, len(info["tech"]), version)
    if episodes is not None:
        heading(f"Episodes ({plural(len(episodes), 'episode')}, "
                f"{pretty_size(sum(e['size'] for e in episodes))})")
        for row in episodes:
            print(f"  {row['episode']}  {pretty_size(row['size']):>9}  {row['runtime'] or '-':>8}  "
                  f"{row['container'] or '-':<5} {row['video'] or '-':<12} {row['audio'] or '-':<10} {row['title']}")


# ---------------------------------------------------------------------------
# Comparing
# ---------------------------------------------------------------------------

def language_list(tracks: list[dict], extra=None) -> str:
    names = []
    for t in tracks:
        name = t["code"] or t["language"] or "?"
        flags = [f for f in ((extra or (lambda _: None))(t),) if f]
        names.append(name + (f" ({', '.join(flags)})" if flags else ""))
    return ", ".join(names)


def audio_summary(tracks: list[dict]) -> str:
    return "; ".join(
        " ".join(str(x) for x in (t["code"] or t["language"], t["codec"],
                                  t["layout"] or (f"{t['channels']}ch" if t["channels"] else None)) if x)
        for t in tracks)


def subtitle_summary(tracks: list[dict]) -> str:
    def flags(t):
        return ", ".join(x for x in ("forced" if t["forced"] else None, "SDH" if t["sdh"] else None, t["source"]) if x)
    return language_list(tracks, flags)


def stream_only(value, analysed: bool):
    """A field only analysed files have: its value, or a label saying why there is none."""
    return value if value not in (None, "") or analysed else NOT_ANALYSED


def comparison_columns(infos: list[dict]) -> list[tuple[str, dict]]:
    """One column per file version of every item, as (heading, {row label: value})."""
    columns = []
    for info in infos:
        summary = info["summary"]
        base = summary["title"] + (f" ({summary['year']})" if summary.get("year") else "")
        versions = info["tech"] or [None]
        for number, version in enumerate(versions, start=1):
            heading_ = f"{base} [v{number}]" if len(versions) > 1 else base
            rows = {"kind": summary.get("kind"), "library": summary.get("library"),
                    "runtime": summary.get("runtime"), "content rating": summary.get("content rating")}
            if version:
                video = version["video"]
                analysed = version["analysed"]

                rows.update({
                    "container": version["container"],
                    "size": pretty_size(version["size"]) if version["size"] else None,
                    "bitrate (kbps)": version["bitrate (kbps)"],
                    "video codec": video.get("codec"), "video profile": video.get("profile"),
                    "resolution": video.get("resolution"), "bit depth": stream_only(video.get("bit depth"), analysed),
                    "frame rate": video.get("frame rate"), "hdr": stream_only(video.get("hdr"), analysed),
                    "audio": (audio_summary(version["audio"]) or "none") if analysed else NOT_ANALYSED,
                    "subtitles": (subtitle_summary(version["subtitles"]) or "none") if analysed else NOT_ANALYSED,
                    "path": "\n".join(f["path"] for f in version["files"] if f["path"]),
                })
            columns.append((heading_, rows))
    return columns


def print_comparison(columns: list[tuple[str, dict]]) -> None:
    labels = []
    for _, rows in columns:
        labels += [k for k in rows if k not in labels]
    label_width = max(len(label) for label in labels) + 2
    total = shutil.get_terminal_size((120, 24)).columns
    cell = max(18, (total - label_width - 2) // len(columns) - 2)

    def block(texts: list[str]) -> list[list[str]]:
        return [list(chain.from_iterable(textwrap.wrap(line, cell, break_long_words=True) or [""]
                                         for line in text.split("\n")))
                for text in texts]

    print(paint("".ljust(label_width) + "  ".join(h[:cell].ljust(cell) for h, _ in columns), "bold"))
    for label in labels:
        values = [show_value(rows.get(label)) for _, rows in columns]
        differs = len(set(values)) > 1
        cells = block(values)
        for line_no in range(max(len(c) for c in cells)):
            mark = (label + (" *" if differs else "")) if line_no == 0 else ""
            line = f"{mark:<{label_width}}" + "  ".join((c[line_no] if line_no < len(c) else "").ljust(cell) for c in cells)
            print(paint(line.rstrip(), "yellow") if differs else line.rstrip())
    print("\n* differs between the columns")


# ---------------------------------------------------------------------------
# Command
# ---------------------------------------------------------------------------

def parse_groups(text: str) -> tuple[str, ...]:
    chosen = tuple(g.strip().lower() for g in text.split(",") if g.strip())
    bad = [g for g in chosen if g not in GROUPS]
    if bad or not chosen:
        raise argparse.ArgumentTypeError(f"'{text}' is not a list of groups; choose from {', '.join(GROUPS)}")
    return chosen


def add_parser(subparsers) -> None:
    parser = add_command(
        subparsers, 'info',
        'show everything Plex knows about an item, or compare items',
        "Look up a movie, show, season or episode and print what Plex holds: summary, people, "
        "tags and IDs, playback, chapters and markers, and the technical side (files and paths, "
        "video, audio and subtitle tracks). Choose items with --title, --guid or --rating-key; "
        "give more than one, or use --compare, to see them side by side with differences marked. "
        "--raw prints the server's reply unchanged. Read-only.",
        ['plextool info -t "Ran"',
         'plextool info -t "Ran" --all',
         'plextool info -t "Ran" --only tech,people',
         'plextool info -l "TV Shows" -t "The Expanse" --episodes',
         'plextool info -t "Ran" -t "Seven Samurai"          # side by side',
         'plextool info -t "Ran" --compare                   # compare its own file versions',
         'plextool info -k 4812 --raw'])
    add_connection_args(parser)
    add_library_arg(parser)
    parser.add_argument("-t", "--title", action="append", default=[], metavar="TITLE",
                        help="item to show, by title (substring match; an exact title wins). Repeat to compare")
    parser.add_argument("-g", "--guid", action="append", default=[], metavar="GUID",
                        help="item to show, by Plex ID (plex://movie/...) or agent ID (imdb://tt..., tmdb://..., tvdb://...)")
    parser.add_argument("-k", "--rating-key", action="append", default=[], type=int, metavar="ID",
                        help="item to show, by Plex's rating key (listed when a title matches several)")
    parser.add_argument("--level", choices=sorted({lv for lvs in SECTION_LEVELS.values() for lv in lvs}),
                        help="what a title or ID names: movie, show, season or episode "
                             "(default: movie for movie libraries, show for TV libraries)")
    parser.add_argument("--only", type=parse_groups, metavar="GROUPS",
                        help=f"comma-separated groups to show: {', '.join(GROUPS)} "
                             f"(default: {', '.join(DEFAULT_GROUPS)})")
    parser.add_argument("--all", action="store_true", help="show every group")
    parser.add_argument("--episodes", action="store_true",
                        help="for a show or season, also list its episodes with size and format")
    parser.add_argument("--compare", action="store_true",
                        help="show side by side even for one item, comparing its file versions")
    parser.add_argument("--json", action="store_true", help="print JSON instead of text")
    parser.add_argument("--raw", action="store_true", help="print the server's own reply for each item")
    parser.set_defaults(run=run)


def run(args: argparse.Namespace) -> int:
    if not (args.title or args.guid or args.rating_key):
        raise PlexToolError("Say which item: --title, --guid or --rating-key.")
    plex = connect(args)
    items = resolve_items(plex, args)
    groups = GROUPS if args.all else (args.only or DEFAULT_GROUPS)

    if args.raw:
        for item in items:
            ET.indent(item._data)
            print(ET.tostring(item._data, encoding="unicode"))
        return 0

    infos = [item_info(item) for item in items]
    listings = [episode_rows(item) if args.episodes and item.type in ("show", "season") else None
                for item in items]
    if args.json:
        out = []
        for info, listing in zip(infos, listings, strict=True):
            out.append({**{g: info[g] for g in groups if g in info}, "summary": info["summary"],
                        **({"children": info["children"]} if "children" in info else {}),
                        **({"episodes": listing} if listing is not None else {})})
        print(json.dumps(out if len(out) > 1 else out[0], indent=2, ensure_ascii=False, default=str))
        return 0

    if len(items) > 1 or args.compare:
        print_comparison(comparison_columns(infos))
        return 0
    print_item(infos[0], groups, listings[0])
    return 0
