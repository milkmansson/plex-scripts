"""token: make tokens for other tools, and list and revoke them, without sharing the main login."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime
from pathlib import Path

from plexapi.exceptions import BadRequest, NotFound, Unauthorized
from plexapi.server import PlexServer
from requests.exceptions import RequestException

from . import auth
from .common import (
    DEFAULT_TIMEOUT,
    URL_ENV,
    PlexToolError,
    add_command,
    add_connection_args,
    connect,
    paint,
    plex_account,
    resolve_token,
    user_access_token,
)

RECORD_FILE = "tokens.json"

RW_NOTICE = (
    "This token has the same power as the Plex account that approved it: whatever that account can do "
    "to the server, the tool holding the token can do too. Plex has no smaller kind of token for "
    "an account.")
RO_NOTICE = (
    "This is {user}'s own token for this server, so it can only see what is shared with {user} "
    "(the libraries listed above), and Plex lets only the server owner delete media. Plex has no "
    "truly read-only token: it can still change {user}'s own watched state and playlists, and anything "
    "else Plex allows that user to do.")
RO_CANCEL = ("A --ro token is a user's own access, so it has no device of its own to remove. It stops "
             "working when that user's access to the server is removed in Plex (Settings, then Users "
             "& Sharing).")


# ---------------------------------------------------------------------------
# The local record of what was made (no secrets in it)
# ---------------------------------------------------------------------------

def record_path() -> Path:
    return auth.config_dir() / RECORD_FILE


def load_record() -> list[dict]:
    try:
        return json.loads(record_path().read_text(encoding="utf-8")).get("tokens", [])
    except FileNotFoundError:
        return []
    except (OSError, ValueError, AttributeError) as e:
        raise PlexToolError(f"Could not read {record_path()}: {e}. Delete it to start the list again; "
                            "tokens already made keep working.") from None


def save_record(entries: list[dict]) -> None:
    auth.write_private(record_path(), json.dumps({"tokens": entries}, indent=2).encode())


def record_key(entry: dict) -> tuple[str, str]:
    return entry["name"].lower(), entry.get("access", "")


def add_record(entry: dict) -> None:
    save_record([e for e in load_record() if record_key(e) != record_key(entry)] + [entry])


# ---------------------------------------------------------------------------
# new
# ---------------------------------------------------------------------------

def known_url(args: argparse.Namespace) -> str | None:
    """The server address to put in the file, from what is already chosen. Nothing is contacted."""
    if args.base_url:
        return args.base_url
    if os.environ.get(URL_ENV):
        return os.environ[URL_ENV]
    from . import server  # imported here because server itself uses this module
    saved = server.load_saved() or {}
    return saved.get("url") or saved.get("last_url")


def env_text(access: str, url: str | None, token: str, label: str) -> str:
    lines = [f"# Made by plextool on {date.today():%Y-%m-%d}: {label} ({access})"]
    if url:
        lines.append(f"{URL_ENV}={url}")
    lines.append(f"PLEX_TOKEN={token}")
    return "\n".join(lines) + "\n"


def deliver(args: argparse.Namespace, token: str, text: str) -> None:
    """Hand the token over as the user asked: a private file, or standard output."""
    if args.print_only:
        print(token)
        return
    path = Path(args.file).expanduser()
    if path.exists() and not args.force:
        raise PlexToolError(f"{path} already exists. Use --force to replace it, or choose another file.")
    auth.write_private(path, text.encode())
    print(f"Wrote {path} (readable only by its owner).", file=sys.stderr)


def make_rw(args: argparse.Namespace) -> tuple[str, dict]:
    """A full-access token under its own entry in Authorized Devices. Returns (token, record)."""
    device = f"{auth.NAMED_TOKEN_PREFIX}{args.name}"
    print(paint(f"Making a read/write token, to be listed in Plex as '{device}'.", "bold"), file=sys.stderr)
    token, client_id = auth.request_token(args.timeout, device, file=sys.stderr)
    print("\n" + paint(RW_NOTICE, "yellow"), file=sys.stderr)
    print(f"Cancel it any time: 'plextool token revoke {args.name} --commit'.", file=sys.stderr)
    return token, {"name": args.name, "access": "rw", "device_id": client_id}


def make_ro(args: argparse.Namespace) -> tuple[str, dict, str]:
    """A shared user's token for this server. Returns (token, record, server address)."""
    if not args.user:
        raise PlexToolError("--ro needs --user: the token comes from a user the server is shared with, and "
                            "what it can see is whatever is shared with that user.")
    admin = connect(args)
    token = user_access_token(args, admin, args.user)
    if token is None:
        raise PlexToolError(f"'{args.user}' is the owner of this server, and the owner's access cannot be "
                            "limited. Use --rw for a separate full-access token, or name a shared user.")
    try:
        libraries = [s.title for s in PlexServer(admin._baseurl, token, timeout=DEFAULT_TIMEOUT).library.sections()]
    except Unauthorized:
        raise PlexToolError(f"The server did not accept {args.user}'s token.") from None
    except RequestException as e:
        raise PlexToolError(f"Could not check {args.user}'s token against the server: {e}") from None
    print(paint(f"Token for {args.user} on this server.", "bold"), file=sys.stderr)
    print(f"Libraries it can see: {', '.join(libraries) or 'none'}", file=sys.stderr)
    print(paint(RO_NOTICE.format(user=args.user), "yellow"), file=sys.stderr)
    record = {"name": args.name or args.user, "access": "ro", "user": args.user,
              "machine_id": admin.machineIdentifier}
    return token, record, admin._baseurl


def run_new(args: argparse.Namespace) -> int:
    if args.rw and args.user:
        raise PlexToolError("--user goes with --ro. A --rw token is a new sign-in to the account itself.")
    if args.name is not None:
        args.name = auth.token_label(args.name.strip())   # 'plextool/mcp' and 'mcp' mean the same
        if not args.name:
            raise PlexToolError("--name cannot be empty.")
    if args.rw and not args.name:
        raise PlexToolError("--rw needs --name, so the token can be found and revoked later "
                            "(it appears in Plex as 'plextool/NAME').")
    if args.ro:
        token, record, url = make_ro(args)
        access = "shared user"
    else:
        token, record = make_rw(args)
        access = "read/write"
        url = known_url(args)
        if not url and not args.print_only:
            print("No server address is chosen yet, so the file has only PLEX_TOKEN.", file=sys.stderr)
    deliver(args, token, env_text(access, url, token, record["name"]))
    record.update({"created": date.today().isoformat(), "server_url": url,
                   "file": None if args.print_only else str(Path(args.file).expanduser().resolve())})
    add_record(record)
    return 0


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------

def named_devices(devices: list) -> dict:
    """The devices made with 'token new --rw', by device ID."""
    return {d.clientIdentifier: d for d in devices
            if (d.product or "").lower() == auth.PRODUCT and auth.is_named_token(d)}


def short_name(device) -> str:
    return auth.token_label(device.name or "")


def shared_with_server(args: argparse.Namespace, machine_id: str | None) -> list:
    """(user, share) pairs for the users this server is shared with."""
    if not machine_id:
        return []
    pairs = []
    for user in plex_account(args).users():
        for share in user.servers:
            if share.machineIdentifier == machine_id and not share.pending:
                pairs.append((user, share))
    return pairs


def user_kind(user) -> str:
    if str(getattr(user, "restricted", "")) == "1":
        return "managed user"
    return "home member" if getattr(user, "home", False) else "shared user"


def library_count(share) -> str:
    if share.allLibraries:
        return "all libraries"
    count = share.numLibraries or 0
    return f"{count} librar{'y' if count == 1 else 'ies'}"


def describe_authorised(device, named: dict, current: str | None, servers: frozenset | set = frozenset()) -> str:
    """One line for a device on the account, marking the ones plextool made."""
    if device.clientIdentifier in named:
        mark = paint(f"  token for another tool: {short_name(device)}", "yellow")
    elif current and device.clientIdentifier == current:
        mark = paint("  this login", "green")
    elif auth.is_server(device) or device.clientIdentifier in servers:
        mark = paint("  Plex Media Server (not removable with plextool)", "yellow")
    elif (device.product or "").lower() == auth.PRODUCT:
        mark = "  plextool sign-in"
    else:
        mark = ""
    return (f"  {(device.clientIdentifier or '')[:8]:<10}{device.name or '?':<34}{device.product or '?':<22}"
            f"last seen {auth._when(device.lastSeenAt)}{mark}")


def run_list(args: argparse.Namespace) -> int:
    args.token, _ = resolve_token(args)
    devices = auth.account_devices(args.token, everything=True)
    named = named_devices(devices)
    record = load_record()
    by_device = {e.get("device_id"): e for e in record if e.get("device_id")}

    current = auth.load_state().get("client_id")
    listed = [d for d in devices if not args.plextool or (d.product or "").lower() == auth.PRODUCT]
    print(paint("Apps and devices authorised on the Plex account" + (" (plextool's only)" if args.plextool else ""),
                "cyan"))
    for device in sorted(listed, key=lambda d: d.lastSeenAt or datetime.min, reverse=True):
        print(describe_authorised(device, named, current))
    if not listed:
        print("  none")

    print(paint("\nTokens made with 'plextool token'", "cyan"))
    shown = False
    for device in sorted(named.values(), key=lambda d: d.createdAt or d.lastSeenAt or datetime.min, reverse=True):
        entry = by_device.get(device.clientIdentifier, {})
        shown = True
        print(f"  {short_name(device):<20} read/write  {device.clientIdentifier[:8]}  "
              f"created {auth._when(device.createdAt)}  last seen {auth._when(device.lastSeenAt)}"
              + paint("  active", "green"))
        if entry.get("file"):
            print(f"  {'':<20} file {entry['file']}")
    for entry in record:
        if entry.get("access") == "rw" and entry.get("device_id") not in named:
            shown = True
            print(f"  {entry['name']:<20} read/write  {entry['device_id'][:8]}  made {entry.get('created', '?')}"
                  + paint("  no longer on the account (revoked or removed)", "yellow"))

    machine_id = next((e.get("machine_id") for e in record if e.get("machine_id")), None)
    shares = []
    if not args.no_users:
        try:
            machine_id = connect(args).machineIdentifier
        except PlexToolError as e:
            print(f"\n(Could not reach the server, so the users list is skipped: {e})", file=sys.stderr)
        shares = shared_with_server(args, machine_id)
    ro_entries = [e for e in record if e.get("access") == "ro"]
    holders = {name.lower() for u, _ in shares for name in (u.title, u.username, getattr(u, "email", None)) if name}
    for entry in ro_entries:
        shown = True
        if entry["user"].lower() in holders:
            state = paint("  user still has access", "green")
        elif shares:
            state = paint("  user no longer has access", "yellow")
        else:
            state = "  (access not checked)"
        print(f"  {entry['name']:<20} shared user {entry['user']:<14} made {entry.get('created', '?')}{state}")
        if entry.get("file"):
            print(f"  {'':<20} file {entry['file']}")
    if not shown:
        print("  none")

    if shares:
        print(paint("\nUsers with access to this server", "cyan"))
        made_for = {e["user"].lower() for e in ro_entries}
        for user, share in sorted(shares, key=lambda p: (p[0].title or "").lower()):
            name = user.title or user.username
            mark = "  (a token was made with 'plextool token')" if name.lower() in made_for else ""
            print(f"  {name:<24}{user_kind(user):<14}{library_count(share)}{mark}")
    print("\nPlex cannot list temporary tokens, or tokens copied out of an app. A server may keep accepting "
          "a revoked token for a short while.")
    return 0


# ---------------------------------------------------------------------------
# revoke
# ---------------------------------------------------------------------------

def run_revoke(args: argparse.Namespace) -> int:
    args.token, _ = resolve_token(args)
    everything = auth.account_devices(args.token, everything=True)
    devices = named_devices(everything)
    record = load_record()
    chosen_devices, chosen_records, ro_hits = {}, [], []
    for wanted in args.names:
        low = wanted.lower()
        hits = [d for d in devices.values()
                if short_name(d).lower() == low or d.clientIdentifier.lower().startswith(low)]
        ro = [e for e in record if e.get("access") == "ro" and e["name"].lower() == low]
        rw_gone = [e for e in record if e.get("access") == "rw" and e["name"].lower() == low
                   and e.get("device_id") not in devices]
        if len(hits) > 1:
            raise PlexToolError(f"'{wanted}' matches {len(hits)} tokens; give more of the ID.")
        if hits:
            chosen_devices[hits[0].clientIdentifier] = hits[0]
        elif ro:
            ro_hits += ro
        elif rw_gone:
            chosen_records += rw_gone
        else:
            other = [d for d in everything if (d.clientIdentifier or "").lower().startswith(low)
                     or (d.name or "").lower() == low]
            if other and (other[0].product or "").lower() == auth.PRODUCT:
                raise PlexToolError(f"'{wanted}' is a plain plextool sign-in, not a token made with 'token new'. "
                                    f"Remove it with: plextool auth revoke {other[0].clientIdentifier[:8]} --commit")
            if other:
                raise PlexToolError(
                    f"'{wanted}' is '{other[0].name or '?'}' ({other[0].product or 'unknown app'}), which plextool "
                    f"did not make, so 'token revoke' will not remove it. "
                    f"'plextool devices remove {other[0].clientIdentifier[:8]}' removes other apps.")
            raise PlexToolError(f"No token named or starting '{wanted}'. 'plextool token list' shows them.")

    verb = "Removing" if args.commit else "Would remove"
    for device in chosen_devices.values():
        print(f"{verb} the sign-in '{short_name(device)}' ({device.clientIdentifier[:8]}) from the Plex account.")
    for entry in chosen_records:
        print(f"'{entry['name']}' is already gone from the account; {verb.lower()} its record.")
    for entry in ro_hits:
        print(paint(f"'{entry['name']}' is a --ro token for {entry['user']}. ", "yellow") + RO_CANCEL)
        if args.forget:
            print(f"{verb} the local record of it (the token itself keeps working until access is removed).")
    if args.delete_file:
        for path in {e.get("file") for e in record if e.get("device_id") in chosen_devices} - {None}:
            print(f"{verb} the file {path}.")
    if not (chosen_devices or chosen_records or (ro_hits and args.forget)):
        return 0
    if not args.commit:
        print("\nDry run only. Re-run with --commit to do it.")
        return 0

    failed = 0
    for device in chosen_devices.values():
        try:
            device.delete()
        except (BadRequest, NotFound, RequestException) as e:
            failed += 1
            print(paint(f"  could not remove {device.clientIdentifier[:8]}: {e}", "red"))
    gone = set(chosen_devices)
    if args.delete_file:
        for entry in record:
            if entry.get("device_id") in gone and entry.get("file"):
                Path(entry["file"]).unlink(missing_ok=True)
    drop = {record_key(e) for e in chosen_records} | {record_key(e) for e in ro_hits if args.forget}
    drop |= {record_key(e) for e in record if e.get("device_id") in gone}
    save_record([e for e in record if record_key(e) not in drop])
    removed = len(chosen_devices) - failed
    print(paint(f"Removed {removed}.", "green") if not failed else f"{failed} failed.")
    if removed:
        print("plex.tv rejects a removed sign-in's token straight away, but a Plex server can keep "
              "accepting it for a while.")
    return 1 if failed else 0


# ---------------------------------------------------------------------------
# Command
# ---------------------------------------------------------------------------

def add_parser(subparsers) -> None:
    parser = add_command(
        subparsers, 'token',
        'make, list and revoke tokens for other tools',
        "Make a token to hand to another program, such as a Plex MCP server, without giving it the "
        "saved login, and keep track of what was made. 'new' makes one: --rw is a separate "
        "full-access token that shows in Plex under Authorized Devices (a browser sign-in), --ro is "
        "the token of a shared user, which sees only what is shared with that user. Plex has no "
        "read-only token, and the output says what a token can do. 'list' shows the apps authorised on the "
        "account, the tokens made, whether they are still active, and who has access to the server. 'revoke' removes one. "
        "Nothing is removed without --commit.",
        ['plextool token new --rw --name mcp-server --file ~/.plex-mcp.env',
         'plextool token new --ro --user alice --file ~/.plex-reader.env',
         'plextool token list',
         'plextool token revoke mcp-server --delete-file --commit'])
    sub = parser.add_subparsers(dest="action", metavar="action", required=True)

    new = add_command(
        sub, 'new', 'make a token for another tool',
        "Say what the token is for (--rw or --ro) and where it goes (--file or --print); neither is "
        "guessed. --rw opens a browser sign-in that creates a separate full-access token, listed in "
        "Plex as 'plextool/NAME' and revocable on its own. --ro takes the token of a shared user "
        "(--user), which sees only what is shared with that user. --file writes PLEX_URL and "
        "PLEX_TOKEN to a file only its owner can read. --print prints only the token.",
        ['plextool token new --rw --name mcp-server --file ~/.plex-mcp.env',
         'plextool token new --ro --user alice --file ~/.plex-reader.env',
         'plextool token new --rw --name backup-script --print'])
    add_connection_args(new)
    access = new.add_mutually_exclusive_group(required=True)
    access.add_argument("--rw", action="store_true",
                        help="a separate token with full access, revocable on its own")
    access.add_argument("--ro", action="store_true",
                        help="the token of a shared user (needs --user): sees only what is shared with them")
    where = new.add_mutually_exclusive_group(required=True)
    where.add_argument("--file", metavar="PATH", help="write PLEX_URL and PLEX_TOKEN to this file (mode 0600)")
    where.add_argument("--print", dest="print_only", action="store_true", help="print only the token")
    new.add_argument("--name", metavar="LABEL",
                     help="what the token is for; it names the entry in Plex's Authorized Devices (needed for --rw)")
    new.add_argument("--user", metavar="NAME", help="the user whose token to make (for --ro)")
    new.add_argument("--force", action="store_true", help="replace the file if it exists")
    new.add_argument("--timeout", type=int, default=auth.LOGIN_TIMEOUT, metavar="SECONDS",
                     help="how long to wait for the browser approval (--rw; default %(default)s)")

    lst = add_command(
        sub, 'list', 'list the tokens made, and who has access to the server',
        "Shows every app and device authorised on the Plex account (what Plex calls Authorized Devices), "
        "with plextool's own sign-ins and tokens marked, then the tokens made with 'token new' and whether "
        "each is still active, then the users this server is shared with. Read-only.",
        ['plextool token list', 'plextool token list --plextool', 'plextool token list --no-users'])
    add_connection_args(lst)
    lst.add_argument("--plextool", action="store_true",
                     help="list only the devices plextool made, not every app on the account")
    lst.add_argument("--no-users", action="store_true",
                     help="skip the users list (it needs a connection to the server)")

    rev = add_command(
        sub, 'revoke', 'remove a token made with token new --rw',
        "Remove the Authorized Devices entry of a --rw token, by the name it was made with or the start "
        "of its device ID, so plex.tv rejects it. Only tokens made with 'token new' can be removed here; "
        "other Plex apps and devices are removed with 'plextool devices remove'. A --ro token has no device to remove (see "
        "--forget). Nothing is removed unless --commit is given.",
        ['plextool token revoke mcp-server', 'plextool token revoke mcp-server --delete-file --commit'])
    add_connection_args(rev)
    rev.add_argument("names", nargs="+", metavar="NAME_OR_ID",
                     help="a token name, or the start of a device ID, from 'plextool token list'")
    rev.add_argument("--delete-file", action="store_true", help="also delete the file the token was written to")
    rev.add_argument("--forget", action="store_true",
                     help="for a --ro token: drop plextool's record of it (the token keeps working until "
                          "the user's access is removed in Plex)")
    rev.add_argument("--commit", action="store_true", help="actually remove it")
    parser.set_defaults(run=run)


def run(args: argparse.Namespace) -> int:
    return {"new": run_new, "list": run_list, "revoke": run_revoke}[args.action](args)
