"""Helpers shared by the plextool commands: connection, output styling, naming."""

from __future__ import annotations

import argparse
import os
import sys
import textwrap

from plexapi.exceptions import NotFound, Unauthorized
from plexapi.server import PlexServer
from requests.exceptions import RequestException

DEFAULT_URL = "http://localhost:32400"
TOKEN_ENV = "PLEX_TOKEN"
URL_ENV = "PLEX_URL"

# Which item types ('libtype') each kind of library section can be worked at.
SECTION_LEVELS = {
    "movie": ("movie",),
    "show": ("show", "season", "episode"),
}


# The item type that carries the media files in each kind of library.
FILE_LEVEL = {"movie": "movie", "show": "episode"}


class PlexToolError(Exception):
    """A problem to report to the user without a traceback."""


# ---------------------------------------------------------------------------
# Output styling
# ---------------------------------------------------------------------------

_CODES = {
    "bold": "1",
    "red": "91",
    "yellow": "93",
    "green": "92",
    "cyan": "96",
}


def _color_enabled(stream=None) -> bool:
    stream = stream or sys.stdout
    return stream.isatty() and "NO_COLOR" not in os.environ


def paint(text: str, *styles: str, stream=None) -> str:
    """Wrap text in ANSI styles, but only when writing to a colour-capable terminal."""
    if not styles or not _color_enabled(stream):
        return text
    codes = ";".join(_CODES[s] for s in styles)
    return f"\033[{codes}m{text}\033[0m"


def pretty_size(num_bytes: int | None) -> str:
    """Format a byte count for humans, eg 1536 -> '1.5 KB'."""
    size = float(num_bytes or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{int(size)} B" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def plural(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


# ---------------------------------------------------------------------------
# Describing items
# ---------------------------------------------------------------------------

def _num(value) -> int:
    return value if isinstance(value, int) else 0


def describe(item) -> str:
    """One-line human name for a movie, show, season or episode."""
    kind = getattr(item, "type", None)
    if kind == "season":
        return f"{item.parentTitle} S{_num(item.index):02d}"
    if kind == "episode":
        return (f"{item.grandparentTitle} S{_num(item.seasonNumber):02d}"
                f"E{_num(item.episodeNumber):02d} - {item.title}")
    year = getattr(item, "year", None)
    return f"{item.title} ({year})" if year else str(item.title)


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------

def add_command(subparsers, name: str, summary: str, description: str, examples: list[str]):
    """Add a (sub)command whose --help shows a wrapped description and worked examples."""
    description = "\n\n".join(textwrap.fill(p, 78) for p in description.split("\n\n"))
    epilog = "examples:\n" + "\n".join(f"  {e}" for e in examples)
    return subparsers.add_parser(
        name, help=summary, description=description, epilog=epilog,
        formatter_class=argparse.RawDescriptionHelpFormatter)


def add_connection_args(parser: argparse.ArgumentParser) -> None:
    """Add --token and --base-url, which every command needs."""
    parser.add_argument(
        "-T", "--token", "--admin-token", dest="token",
        default=os.environ.get(TOKEN_ENV),
        help=f"Plex token (default: ${TOKEN_ENV})")
    parser.add_argument(
        "-b", "--base-url", dest="base_url",
        default=os.environ.get(URL_ENV, DEFAULT_URL),
        help=f"Plex server URL (default: ${URL_ENV} or {DEFAULT_URL})")


def connect(args: argparse.Namespace) -> PlexServer:
    """Connect to the server named in args, with friendly errors."""
    if not args.token:
        raise PlexToolError(f"No Plex token given. Use --token or set ${TOKEN_ENV}.")
    try:
        return PlexServer(args.base_url, args.token)
    except Unauthorized:
        raise PlexToolError("The Plex server rejected the token (401).") from None
    except RequestException as e:
        raise PlexToolError(f"Could not reach {args.base_url}: {e}") from None


def pick_sections(plex: PlexServer, names: list[str] | None) -> list:
    """Return the named library sections, or every movie and TV section if none named."""
    if names:
        sections = []
        for name in names:
            try:
                sections.append(plex.library.section(name))
            except NotFound:
                available = ", ".join(s.title for s in plex.library.sections())
                raise PlexToolError(
                    f"No library called '{name}'. Available: {available}") from None
        unsupported = [s for s in sections if s.TYPE not in SECTION_LEVELS]
        if unsupported:
            raise PlexToolError(
                f"Library '{unsupported[0].title}' is a {unsupported[0].TYPE} library; "
                "only movie and TV libraries are supported.")
        return sections
    return [s for s in plex.library.sections() if s.TYPE in SECTION_LEVELS]


def add_library_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("-l", "--library", action="append", metavar="NAME",
                        help="library name; repeat for several (default: all movie and TV libraries)")


def item_size(item) -> int:
    """Total bytes of every file attached to a movie or episode, across all versions."""
    return sum(part.size or 0 for media in item.media for part in media.parts)


def confirm_typed(word: str, message: str, assume_yes: bool = False) -> None:
    """Make the user type `word` before a destructive step; raise PlexToolError if they don't."""
    if assume_yes:
        return
    if not sys.stdin.isatty():
        raise PlexToolError("Refusing to continue without a terminal to confirm on. "
                            "Pass --assume-yes to skip the prompt.")
    answer = input(f"{message}\nType {word} to continue: ")
    if answer.strip() != word:
        raise PlexToolError("Not confirmed; nothing was changed.")
