"""subs: extract embedded subtitle tracks from MKV and MP4 files."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
from pathlib import Path

from .common import (
    PlexToolError,
    add_command,
    add_connection_args,
    connect,
    paint,
    pick_sections,
    plural,
)

# mkv subtitle codec_id -> file extension
CODEC_EXT = {
    "S_TEXT/UTF8": "srt",
    "S_TEXT/ASCII": "srt",
    "S_TEXT/ASS": "ass",
    "S_TEXT/SSA": "ass",
    "S_TEXT/WEBVTT": "vtt",
    "S_HDMV/PGS": "sup",
    "S_VOBSUB": "sub",  # also produces an .idx file
    "S_TEXT/USF": "usf",
}

# ffprobe codec_name -> (file extension, ffmpeg subtitle codec). Text formats only: ffmpeg
# can't turn the image-based ones found in MP4 files into usable sidecar files.
FFMPEG_TEXT = {
    "mov_text": ("srt", "srt"),
    "subrip": ("srt", "srt"),
    "srt": ("srt", "srt"),
    "text": ("srt", "srt"),
    "ass": ("ass", "ass"),
    "ssa": ("ass", "ass"),
    "webvtt": ("vtt", "webvtt"),
}

# Minimal ISO 639-2 -> 639-1 mapping for common languages; others stay 3-letter.
ISO3_TO_ISO1 = {
    "eng": "en", "spa": "es", "fre": "fr", "fra": "fr", "ger": "de", "deu": "de", "ita": "it",
    "jpn": "ja", "chi": "zh", "zho": "zh", "kor": "ko", "rus": "ru", "por": "pt", "dut": "nl",
    "nld": "nl", "ara": "ar", "pol": "pl", "swe": "sv", "nor": "no", "dan": "da", "fin": "fi",
}

FORCED_NAME = re.compile(r"\bforced\b", re.IGNORECASE)
SDH_NAME = re.compile(r"\bsdh\b|hearing[ -]impaired|closed[ -]caption|\bcc\b", re.IGNORECASE)


def codec_ext(codec_id: str) -> str:
    return CODEC_EXT.get(codec_id, "sub")


def lang_code(ietf: str | None, iso3: str | None) -> str:
    """Short language code for a track. Prefers the BCP-47 tag ('pt-BR' -> 'pt'), else maps ISO 639-2."""
    if ietf and ietf != "und":
        return ietf.split("-")[0]
    if not iso3 or iso3 == "und":
        return "und"
    return ISO3_TO_ISO1.get(iso3, iso3)


def flags_for(name: str | None, forced: bool, sdh: bool) -> tuple[bool, bool]:
    """Combine a track's real flags with hints in its name ('English (SDH)', 'Forced')."""
    name = name or ""
    return (bool(forced) or bool(FORCED_NAME.search(name)),
            bool(sdh) or bool(SDH_NAME.search(name)))


# ---------------------------------------------------------------------------
# Reading tracks (each returns [{'id', 'lang', 'forced', 'sdh', 'ext', 'codec', ...}])
# ---------------------------------------------------------------------------

def mkv_tracks(identify: dict) -> list[dict]:
    """Subtitle tracks from `mkvmerge -J` output."""
    tracks = []
    for track in identify.get("tracks", []):
        if track.get("type") != "subtitles":
            continue
        props = track.get("properties", {})
        forced, sdh = flags_for(props.get("track_name"), props.get("forced_track"),
                                props.get("flag_hearing_impaired"))
        codec = props.get("codec_id", "")
        tracks.append({
            "id": track["id"],
            "codec": codec,
            "ext": codec_ext(codec),
            "lang": lang_code(props.get("language_ietf"), props.get("language")),
            "forced": forced,
            "sdh": sdh,
        })
    return tracks


def mp4_tracks(probe: dict) -> list[dict]:
    """Subtitle streams from `ffprobe -show_streams` output; 'ext' is None if not extractable."""
    tracks = []
    for stream in probe.get("streams", []):
        if stream.get("codec_type") != "subtitle":
            continue
        tags = stream.get("tags", {})
        disposition = stream.get("disposition", {})
        forced, sdh = flags_for(tags.get("title") or tags.get("handler_name"),
                                disposition.get("forced"), disposition.get("hearing_impaired"))
        codec = stream.get("codec_name", "")
        ext, ff_codec = FFMPEG_TEXT.get(codec, (None, None))
        tracks.append({
            "id": stream["index"],
            "codec": codec,
            "ext": ext,
            "ffmpeg_codec": ff_codec,
            "lang": lang_code(None, tags.get("language")),
            "forced": forced,
            "sdh": sdh,
        })
    return tracks


def output_names(video: Path, tracks: list[dict]) -> list[Path]:
    """Where each track goes: <video>.<lang>[.forced][.sdh].<ext>.

    Plex reads the language and flags from the end of the name. Tracks that would get the same
    name (same language and flags) are told apart with a number in front of the language:
    <video>.2.<lang>.<ext>, <video>.3.<lang>.<ext>.
    """
    seen: dict[tuple, int] = {}
    names = []
    for track in tracks:
        key = (track["lang"], track["forced"], track["sdh"])
        count = seen.get(key, 0)
        seen[key] = count + 1
        middle = track["lang"] if count == 0 else f"{count + 1}.{track['lang']}"
        if track["forced"]:
            middle += ".forced"
        if track["sdh"]:
            middle += ".sdh"
        names.append(video.with_name(f"{video.stem}.{middle}.{track['ext']}"))
    return names


# ---------------------------------------------------------------------------
# Calling the external tools
# ---------------------------------------------------------------------------

def _run(cmd: list[str]):
    return subprocess.run(cmd, check=False, capture_output=True, text=True)


def probe_mkv(path: Path) -> list[dict]:
    result = _run(["mkvmerge", "-J", str(path)])
    if result.returncode >= 2:  # 1 is just warnings
        raise PlexToolError(result.stderr.strip() or result.stdout.strip() or "mkvmerge failed")
    return mkv_tracks(json.loads(result.stdout))


def extract_mkv(path: Path, track: dict, out: Path) -> str | None:
    result = _run(["mkvextract", "tracks", str(path), f"{track['id']}:{out}"])
    return result.stdout.strip() or "mkvextract failed" if result.returncode >= 2 else None


def probe_mp4(path: Path) -> list[dict]:
    result = _run(["ffprobe", "-v", "error", "-print_format", "json", "-show_streams",
                   "-select_streams", "s", str(path)])
    if result.returncode != 0:
        raise PlexToolError(result.stderr.strip() or "ffprobe failed")
    return mp4_tracks(json.loads(result.stdout))


def extract_mp4(path: Path, track: dict, out: Path) -> str | None:
    result = _run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(path),
                   "-map", f"0:{track['id']}", "-c:s", track["ffmpeg_codec"], str(out)])
    return result.stderr.strip() or "ffmpeg failed" if result.returncode != 0 else None


# What each kind of video file needs. A kind whose tools are missing is skipped, not fatal.
KINDS = {
    "mkv": {"suffixes": (".mkv",), "tools": ("mkvmerge", "mkvextract"), "package": "MKVToolNix",
            "probe": probe_mkv, "extract": extract_mkv},
    "mp4": {"suffixes": (".mp4", ".m4v"), "tools": ("ffmpeg", "ffprobe"), "package": "FFmpeg",
            "probe": probe_mp4, "extract": extract_mp4},
}


def find_videos(root: Path, kinds: list[str]) -> dict[str, list[Path]]:
    """Files under root, grouped by kind ('mkv', 'mp4')."""
    found: dict[str, list[Path]] = {k: [] for k in kinds}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        for kind in kinds:
            if path.suffix.lower() in KINDS[kind]["suffixes"]:
                found[kind].append(path)
    return found


def missing_tools(kind: str) -> list[str]:
    return [tool for tool in KINDS[kind]["tools"] if not shutil.which(tool)]


def extract_file(kind: str, video: Path, commit: bool, force: bool) -> int:
    """Extract (or preview extracting) every subtitle track; returns how many were written/planned."""
    print(f">> {video}")
    try:
        tracks = KINDS[kind]["probe"](video)
    except (PlexToolError, ValueError) as e:
        print(paint(f"   ! cannot read this file, skipping: {e}", "yellow"))
        return 0
    if not tracks:
        print("   (no subtitle tracks)")
        return 0

    usable = []
    for track in tracks:
        if track["ext"] is None:
            print(paint(f"   track {track['id']} ({track['codec']}): can't be extracted, skipped", "yellow"))
        else:
            usable.append(track)

    count = 0
    for track, out in zip(usable, output_names(video, usable)):
        print(f"   track {track['id']} ({track['codec']}, lang={track['lang']}) -> {out.name}")
        if out.exists() and not force:
            print("      [exists] skipped (use --force to overwrite)")
            continue
        if commit:
            error = KINDS[kind]["extract"](video, track, out)
            if error:
                print(paint(f"      ! failed: {error}", "red"))
                continue
        count += 1
    return count


# ---------------------------------------------------------------------------
# Command
# ---------------------------------------------------------------------------

def parse_types(text: str) -> list[str]:
    types = [t.strip().lower() for t in text.split(",") if t.strip()]
    bad = [t for t in types if t not in KINDS]
    if bad or not types:
        raise argparse.ArgumentTypeError(f"types must be from: {', '.join(KINDS)}")
    return types


def add_parser(subparsers) -> None:
    parser = add_command(
        subparsers, "subs", "extract embedded subtitles from MKV and MP4 files",
        "Work with subtitles inside video files. MKV files need mkvmerge and mkvextract (from "
        "MKVToolNix); MP4 files need ffmpeg and ffprobe. You only need the tools for the file "
        "types you use: files whose tools are missing are skipped with a note.",
        ["plextool subs extract /mnt/media/Movies                 # preview",
         "plextool subs extract /mnt/media/Movies --commit --scan Movies"])
    sub = parser.add_subparsers(dest="subs_command", required=True, metavar="action")

    extract = add_command(
        sub, "extract", "extract every subtitle track next to its video",
        "Recursively find .mkv, .mp4 and .m4v files under DIRECTORY and save each subtitle track "
        "beside its video, named so Plex finds it: Movie.en.srt, with .forced or .sdh after the "
        "language for tracks flagged that way (Movie.en.forced.srt). Flags come from the track's "
        "own flags or from its name. If two tracks would get the same name, the later ones are "
        "numbered: Movie.2.en.srt. Existing files are skipped unless --force. Nothing is "
        "written unless --commit is given.\n\nImage-based subtitles in MP4 files can't be "
        "extracted and are reported. With --scan LIBRARY, ask Plex to scan afterwards so the new "
        "files show up. That is the only part that needs a Plex connection.",
        ["plextool subs extract /mnt/media/Movies",
         "plextool subs extract /mnt/media/Movies --commit",
         "plextool subs extract . --types mkv --commit",
         "plextool subs extract . --commit --scan Movies --scan-path /data/Movies"])
    extract.add_argument("directory", nargs="?", default=".", help="where to search (default: current directory)")
    extract.add_argument("--types", type=parse_types, default=list(KINDS), metavar="LIST",
                         help="file types to process, comma-separated from: "
                              f"{', '.join(KINDS)} (default: all)")
    extract.add_argument("-f", "--force", action="store_true", help="overwrite subtitle files that already exist")
    extract.add_argument("-y", "--commit", action="store_true", help="write the files (default is a dry run)")
    extract.add_argument("--scan", metavar="LIBRARY", help="after extracting, scan this Plex library")
    extract.add_argument("--scan-path", metavar="PATH",
                         help="folder to scan, as the Plex server sees it (default: DIRECTORY)")
    add_connection_args(extract)
    extract.set_defaults(run=run_extract)


def run_extract(args: argparse.Namespace) -> int:
    root = Path(args.directory)
    if not root.is_dir():
        raise PlexToolError(f"Not a directory: {root}")

    groups = find_videos(root, args.types)
    if not any(groups.values()):
        print(f"No {'/'.join(args.types)} files found under {root}.")
        return 0

    total = videos = 0
    skipped: list[str] = []
    for kind, files in groups.items():
        if not files:
            continue
        absent = missing_tools(kind)
        if absent:
            skipped.append(f"{plural(len(files), kind + ' file')} skipped: {' and '.join(absent)} "
                           f"not found (install {KINDS[kind]['package']})")
            continue
        for video in files:
            total += extract_file(kind, video, args.commit, args.force)
        videos += len(files)

    for note in skipped:
        print(paint(f"\n! {note}", "yellow"))
    if skipped and not videos:
        raise PlexToolError("None of the video files found can be processed with the tools installed.")

    verb = "Extracted" if args.commit else "Would extract"
    print(f"\n{verb} {plural(total, 'subtitle file')} from {plural(videos, 'video')}.")
    if not args.commit and total:
        print("Dry run only. Re-run with --commit to write them.")

    if args.scan and args.commit and total:
        plex = connect(args)
        (section,) = pick_sections(plex, [args.scan])
        path = args.scan_path or str(root.resolve())
        section.update(path=path)
        print(f"Asked Plex to scan {path} in '{section.title}'.")
    elif args.scan and not args.commit:
        print(f"(With --commit, Plex library '{args.scan}' would be scanned.)")
    return 0
