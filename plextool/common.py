"""Helpers shared by the plextool commands: connection, output styling, naming."""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import shlex
import subprocess
import sys
import textwrap
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import TextIO

import requests
from plexapi.exceptions import NotFound, Unauthorized
from plexapi.myplex import MyPlexAccount
from plexapi.server import PlexServer
from requests.exceptions import RequestException

DEFAULT_URL = "http://localhost:32400"
DEFAULT_TIMEOUT = 10   # seconds to wait for the default address, which may not be a Plex server at all
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


def format_duration(seconds: float) -> str:
    """Eg 4.2 -> '4.2s', 75 -> '1m 15s', 3700 -> '1h 1m 40s'."""
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, secs = divmod(round(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m {secs}s" if hours else f"{minutes}m {secs}s"


def plural(count: int, word: str) -> str:
    """'1 file', '2 files', '3 matches' (words ending s, x, ch or sh take 'es')."""
    if count == 1:
        return f"{count} {word}"
    return f"{count} {word}{'es' if word.endswith(('s', 'x', 'ch', 'sh')) else 's'}"


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
# Progress
# ---------------------------------------------------------------------------

VERBOSE = False     # set by enable_verbose(), for --verbose
_SECRETS: set[str] = set()   # tokens seen, hidden from --verbose output
_TOKEN_IN_URL = re.compile(r"(X-Plex-Token=)[^&\s]+", re.IGNORECASE)

FIRST_NOTICE = 10   # seconds of silence before the first "still working" line
NOTICE_EVERY = 20   # seconds between lines after that


class _HideTokens(logging.Filter):
    """Blank out any Plex token in a log line before it is printed."""

    def filter(self, record: logging.LogRecord) -> bool:
        text = _TOKEN_IN_URL.sub(r"\1HIDDEN", record.getMessage())
        for secret in _SECRETS:
            text = text.replace(secret, "HIDDEN")
        record.msg, record.args = text, None
        return True


_CONTAINER = re.compile(rb"<MediaContainer\b[^>]*>")


def describe_reply(status: int, body: bytes, seconds: float) -> str:
    """One line about a reply: status, records in this page (and of how many), size, time."""
    parts = [str(status)]
    tag = _CONTAINER.search(body[:2000])
    if tag:
        attrs = {name.decode(): int(value)
                 for name, value in re.findall(rb'\b(size|totalSize|offset)="(\d+)"', tag.group())}
        if "size" in attrs:
            text = plural(attrs["size"], "record")
            if "totalSize" in attrs:
                first = attrs.get("offset", 0) + 1
                span = f"{first}-{first + attrs['size'] - 1} of " if attrs["size"] else "of "
                text += f" ({span}{attrs['totalSize']})"
            parts.append(text)
    parts += [pretty_size(len(body)), f"{seconds:.2f}s"]
    return "  <- " + ", ".join(parts)


def _report_replies() -> None:
    """Log a line about each reply, as well as the request line plexapi already logs."""
    send = requests.Session.send
    if getattr(send, "_plextool", False):
        return
    log = logging.getLogger("plexapi")

    def timed_send(self, request, **kwargs):
        started = time.monotonic()
        response = send(self, request, **kwargs)
        if not kwargs.get("stream"):  # a streamed download must not be read here
            log.debug(describe_reply(response.status_code, response.content, time.monotonic() - started))
        return response

    timed_send._plextool = True
    requests.Session.send = timed_send


def enable_verbose() -> None:
    """Print every request sent to Plex (and when slow steps start and finish) on stderr."""
    global VERBOSE
    VERBOSE = True
    log = logging.getLogger("plexapi")
    if any(getattr(h, "_plextool", False) for h in log.handlers):
        return
    handler = logging.StreamHandler(sys.stderr)
    handler._plextool = True
    handler.setFormatter(logging.Formatter("%(asctime)s  %(message)s", "%H:%M:%S"))
    handler.addFilter(_HideTokens())
    log.addHandler(handler)
    log.setLevel(logging.DEBUG)
    log.propagate = False
    _report_replies()


class Working:
    """Handle from working(): set .detail (eg '120 of 900 items') to show it in the notices."""

    detail = ""


@contextmanager
def working(label: str, first: float | None = None):
    """Tell the user on stderr, now and then, that a slow step is still going.

    Quick steps print nothing. After FIRST_NOTICE seconds a line like
    'still reading TV Shows... 10s' appears, then another every NOTICE_EVERY seconds.
    `first` replaces FIRST_NOTICE for steps that should speak up sooner.
    stderr is used so --json output on stdout stays clean.
    """
    state = Working()
    done = threading.Event()
    started = time.monotonic()

    def notify():
        wait = FIRST_NOTICE if first is None else first
        while not done.wait(wait):
            detail = f" ({state.detail})" if state.detail else ""
            print(f"  still {label}... {int(time.monotonic() - started)}s{detail}", file=sys.stderr, flush=True)
            wait = NOTICE_EVERY

    thread = threading.Thread(target=notify, daemon=True)
    if VERBOSE:
        print(f"  {label}...", file=sys.stderr, flush=True)
    thread.start()
    try:
        yield state
    finally:
        done.set()
        thread.join()
        if VERBOSE:
            print(f"  ...finished {label} in {time.monotonic() - started:.1f}s", file=sys.stderr, flush=True)


def no_autoreload(items: list) -> list:
    """Stop plexapi fetching each item again when a field the list left blank is read.

    A field with no value (never watched, no year) makes plexapi assume the item is
    only partly loaded and request it in full, one request per item. Use this when
    blanks are expected and only the fields already in the list are needed.
    """
    for item in items:
        item._autoReload = False
    return items


def scan(section, autoreload: bool = True, **filters) -> list:
    """section.search(...) over a whole library, with 'still working' notices if it is slow.

    With autoreload=False, reading a blank field on an item does not fetch that item again.
    """
    with working(f"reading {section.title}"):
        items = section.search(**filters)
    return items if autoreload else no_autoreload(items)


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
    parser.add_argument(
        "-v", "--verbose", dest="verbose", action="store_true",
        help="print each request sent to Plex with its reply (records, size, time), and when slow steps start and finish, on stderr")


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
    """Find the Plex token to use, as (token, where it came from); --verbose never prints it."""
    token, source = _find_token(args)
    _SECRETS.add(token)
    return token, source


def _find_token(args: argparse.Namespace) -> tuple[str, str]:
    """Look for the token, in this order.

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


def short_reason(error: Exception) -> str:
    """A one-line reason for a failed connection, without requests' long wording."""
    text = str(error)
    if isinstance(error, requests.exceptions.Timeout) or "timed out" in text:
        return "no answer (timed out)"
    if "Connection refused" in text:
        return "connection refused (nothing is listening there)"
    if "Name or service not known" in text or "Temporary failure in name resolution" in text:
        return "the name could not be resolved"
    if "No route to host" in text or "Network is unreachable" in text:
        return "no route to the host"
    return text if len(text) <= 150 else text[:147] + "..."


def connect(args: argparse.Namespace) -> PlexServer:
    """Connect to the server named in args, with friendly errors.

    The server is --base-url, else $PLEX_URL, else the one saved by 'plextool server use',
    else the default on this machine. args.base_url is set to the address that worked.
    """
    args.token, source = resolve_token(args)
    url = args.base_url or os.environ.get(URL_ENV)
    chosen = bool(url)
    try:
        if url:
            plex = PlexServer(url, args.token)
        else:
            from . import server  # imported here because server itself uses this module
            saved = server.load_saved()
            chosen = bool(saved)
            if saved:
                plex = server.connect_saved(saved, args.token)
            else:
                with working(f"trying {DEFAULT_URL}, as no server is chosen (see 'plextool server use')", first=3):
                    plex = PlexServer(DEFAULT_URL, args.token, timeout=DEFAULT_TIMEOUT)
    except Unauthorized:
        hint = SIGN_IN_AGAIN if source == "saved login" else "Check that token, or use 'plextool auth login'."
        raise PlexToolError(f"The Plex server rejected the token from {source} (401). {hint}") from None
    except RequestException as e:
        hint = "" if chosen else (" No server is chosen, so this default was tried. "
                                  "Run 'plextool server find', then 'plextool server use'.")
        raise PlexToolError(f"Could not reach {url or DEFAULT_URL}: {short_reason(e)}.{hint}") from None
    args.base_url = plex._baseurl
    return plex


def plex_account(args: argparse.Namespace) -> MyPlexAccount:
    """The plex.tv account behind args.token (set by connect())."""
    try:
        return MyPlexAccount(token=args.token)
    except RequestException as e:
        raise PlexToolError(f"Could not reach plex.tv: {e}") from None


def user_server(args: argparse.Namespace, admin: PlexServer, name: str | None) -> PlexServer:
    """Open the server as the named user (the owner if name is None or is the owner)."""
    if not name:
        return admin
    account = plex_account(args)
    own_names = {n.lower() for n in (account.username, account.email, account.title) if n}
    if name.lower() in own_names:
        return admin
    try:
        user = account.user(name)
    except NotFound:
        raise PlexToolError(f"'{name}' is not a user on this account.") from None
    token = user.get_token(admin.machineIdentifier)
    if token:
        _SECRETS.add(token)
    if not token:
        raise PlexToolError(
            f"Could not get an access token for '{name}'. Is this server shared with them?")
    try:
        return PlexServer(args.base_url, token)
    except RequestException as e:
        raise PlexToolError(f"Could not connect as '{name}': {e}") from None


def shared_users(args: argparse.Namespace, admin: PlexServer) -> list[str]:
    """Names of the users this server is shared with (not the owner), as user_server() takes them."""
    users = plex_account(args).users()
    return [u.title or u.username for u in users
            if any(s.machineIdentifier == admin.machineIdentifier and not s.pending for s in u.servers)]


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
