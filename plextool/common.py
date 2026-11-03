"""Helpers shared by the plextool commands: connection, output styling, naming."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import TextIO

from plexapi.exceptions import NotFound, Unauthorized
from plexapi.server import PlexServer
from requests.exceptions import RequestException

DEFAULT_URL = "http://localhost:32400"
TOKEN_ENV = "PLEX_TOKEN"
TOKEN_CMD_ENV = "PLEX_TOKEN_CMD"
SIGN_IN_AGAIN = ("It may have been revoked or have expired. "
                 "Sign in again with 'plextool auth login'.")
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


def add_token_args(parser: argparse.ArgumentParser) -> None:
    """Add --token and --token-file."""
    parser.add_argument(
        "-T", "--token", dest="token", default=None,
        help="Plex token. Visible in your shell history and process list; "
             "prefer 'plextool auth login', --token-file or $PLEX_TOKEN")
    parser.add_argument(
        "--token-file", dest="token_file", metavar="FILE", default=None,
        help="read the Plex token from FILE ('-' reads standard input)")


def add_connection_args(parser: argparse.ArgumentParser) -> None:
    """Add --token, --token-file and --base-url, which every command needs."""
    add_token_args(parser)
    parser.add_argument(
        "-b", "--base-url", dest="base_url", default=None,
        help=f"Plex server URL (default: ${URL_ENV}, else the server chosen with "
             f"'plextool server use', else {DEFAULT_URL})")


def _token_from_file(path: str) -> str:
    try:
        text = sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8")
    except OSError as e:
        raise PlexToolError(f"Could not read the token file: {e}") from None
    token = text.strip()
    if not token:
        raise PlexToolError(f"The token file {path} is empty.")
    return token


def _token_from_command(command: str) -> str:
    try:
        done = subprocess.run(shlex.split(command), check=False, capture_output=True,
                              text=True, timeout=30)
    except (OSError, subprocess.SubprocessError, ValueError) as e:
        raise PlexToolError(f"${TOKEN_CMD_ENV} failed: {e}") from None
    token = done.stdout.strip()
    if done.returncode != 0 or not token:
        raise PlexToolError(f"${TOKEN_CMD_ENV} gave no token (exit status {done.returncode}).")
    return token


def resolve_token(args: argparse.Namespace) -> tuple[str, str]:
    """Find the Plex token to use, as (token, where it came from).

    Order: --token, --token-file, $PLEX_TOKEN, the output of $PLEX_TOKEN_CMD, then the
    login saved by 'plextool auth login'.
    """
    if args.token:
        print("warning: --token leaves the token in your shell history and process list. "
              f"Use 'plextool auth login', --token-file or ${TOKEN_ENV} instead.", file=sys.stderr)
        return args.token, "--token"
    if getattr(args, "token_file", None):
        return _token_from_file(args.token_file), "--token-file"
    if os.environ.get(TOKEN_ENV):
        return os.environ[TOKEN_ENV], f"${TOKEN_ENV}"
    if os.environ.get(TOKEN_CMD_ENV):
        return _token_from_command(os.environ[TOKEN_CMD_ENV]), f"${TOKEN_CMD_ENV}"
    from . import auth  # imported here because auth itself uses this module
    token = auth.stored_token()
    if token:
        auth.use_saved_identity()
        return token, "saved login"
    raise PlexToolError("No Plex token found. Run 'plextool auth login', or use --token-file "
                        f"or set ${TOKEN_ENV}.")


def connect(args: argparse.Namespace) -> PlexServer:
    """Connect to the server named in args, with friendly errors.

    The server is --base-url, else $PLEX_URL, else the one saved by 'plextool server use',
    else the default on this machine. args.base_url is set to the address that worked.
    """
    args.token, source = resolve_token(args)
    url = args.base_url or os.environ.get(URL_ENV)
    try:
        if url:
            plex = PlexServer(url, args.token)
        else:
            from . import server  # imported here because server itself uses this module
            saved = server.load_saved()
            plex = server.connect_saved(saved, args.token) if saved else PlexServer(DEFAULT_URL, args.token)
    except Unauthorized:
        hint = SIGN_IN_AGAIN if source == "saved login" else "Check that token, or use 'plextool auth login'."
        raise PlexToolError(f"The Plex server rejected the token from {source} (401). {hint}") from None
    except RequestException as e:
        raise PlexToolError(f"Could not reach {url or DEFAULT_URL}: {e}") from None
    args.base_url = plex._baseurl
    return plex


def write_json(path: str, data: dict) -> TextIO:
    """Write data as JSON to a file, or to standard output if path is '-'.

    Returns the stream a status message should go to: standard error when the data is
    on standard output, so the message can't end up inside it.
    """
    if path == "-":
        json.dump(data, sys.stdout, indent=2, ensure_ascii=False)
        sys.stdout.write("\n")
        return sys.stderr
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except OSError as e:
        raise PlexToolError(f"Could not write {path}: {e}") from None
    return sys.stdout


def read_json(path: str) -> dict:
    """Read JSON from a file, or from standard input if path is '-'."""
    try:
        if path == "-":
            return json.load(sys.stdin)
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError) as e:
        raise PlexToolError(f"Could not read {'standard input' if path == '-' else path}: {e}") from None


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
