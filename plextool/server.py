"""server: choose which Plex server the other commands talk to."""

from __future__ import annotations

import argparse
import json
import os
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit

import plexapi
import requests
from plexapi.exceptions import BadRequest, Unauthorized
from plexapi.myplex import MyPlexAccount
from plexapi.server import PlexServer
from requests.exceptions import RequestException

from . import auth
from .common import (
    DEFAULT_URL,
    SIGN_IN_AGAIN,
    URL_ENV,
    PlexToolError,
    add_command,
    add_token_args,
    paint,
    resolve_token,
)

CONNECT_TIMEOUT = 10
PROBE_TIMEOUT = 6
DNS_WORDS = ("name or service not known", "nameresolutionerror", "getaddrinfo",
             "temporary failure in name resolution", "no address associated")


# ---------------------------------------------------------------------------
# What is saved
# ---------------------------------------------------------------------------

def load_saved() -> dict:
    """The server chosen with 'server use', or {} if none."""
    path = auth.config_dir() / auth.SERVER_FILE
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        raise PlexToolError(f"Could not read {path}: {e}. 'plextool server forget' clears it.") from None


def save(saved: dict) -> None:
    auth.write_private(auth.config_dir() / auth.SERVER_FILE, json.dumps(saved, indent=2).encode())


def forget() -> bool:
    path = auth.config_dir() / auth.SERVER_FILE
    existed = path.exists()
    path.unlink(missing_ok=True)
    return existed


# ---------------------------------------------------------------------------
# Finding servers
# ---------------------------------------------------------------------------

def account_servers(token: str) -> list:
    """The servers on the signed-in Plex account, owned or shared, as plexapi resources."""
    try:
        resources = MyPlexAccount(token=token).resources()
    except Unauthorized:
        raise PlexToolError(f"plex.tv rejected the token. {SIGN_IN_AGAIN}") from None
    except (RequestException, BadRequest) as e:
        raise PlexToolError(f"Could not reach plex.tv: {e}") from None
    return [r for r in resources if "server" in (r.provides or "")]


def lan_servers() -> list[dict]:
    """Servers answering on this network (Plex's GDM broadcast). Needs no login and no internet."""
    from plexapi.gdm import GDM
    try:
        entries = GDM().all()
    except OSError:
        return []
    found = []
    for entry in entries:
        data = entry["data"]
        found.append({
            "name": data.get("Name", "?"),
            "url": f"http://{entry['from'][0]}:{data.get('Port', '32400')}",
            "version": data.get("Version", ""),
            "machine_id": data.get("Resource-Identifier", ""),
        })
    return found


def explain_error(error: Exception) -> str:
    """A short, plain reason for a failed request."""
    text = str(error).lower()
    if isinstance(error, requests.exceptions.Timeout):
        return "no response (timed out)"
    if isinstance(error, requests.exceptions.SSLError):
        return "TLS/certificate error"
    if isinstance(error, requests.exceptions.ConnectionError):
        if any(word in text for word in DNS_WORDS):
            return "DNS lookup failed"
        if "refused" in text:
            return "connection refused"
        return "could not connect"
    return type(error).__name__


def probe(url: str, token: str, timeout: float = PROBE_TIMEOUT) -> tuple[bool, str]:
    """Ask a server for its root page with a token, as connecting does. Returns (worked, short reason).

    The root page needs a valid token. /identity doesn't, so it would say "ok" for a bad token.
    """
    try:
        response = requests.get(f"{url.rstrip('/')}/", headers={**plexapi.BASE_HEADERS, "X-Plex-Token": token},
                                timeout=timeout)
    except requests.exceptions.RequestException as e:
        return False, explain_error(e)
    if response.status_code == 200:
        return True, "ok"
    if response.status_code == 401:
        return False, "rejected the token (401)"
    return False, f"HTTP {response.status_code}"


def _short_address(uri: str) -> str:
    """'https://114-23-165-200.abc.plex.direct:21351' -> '114-23-165-200:21351'."""
    parts = urlsplit(uri)
    host = parts.hostname or ""
    if host.endswith(".plex.direct"):
        host = host.split(".", 1)[0]
    return f"{host}:{parts.port}" if parts.port else host


def probe_resource(resource, account_token: str) -> list[dict]:
    """Try every address plex.tv lists for a server, in Plex's preferred order, with the server's
    own token and with the login token."""
    by_uri = {c.uri: c for c in resource.connections}
    ordered = [by_uri[u] for u in resource.preferred_connections() if u in by_uri] or list(by_uri.values())

    def one(conn):
        return {
            "kind": "relay" if conn.relay else "local" if conn.local else "remote",
            "host": _short_address(conn.uri),
            "uri": conn.uri,
            "server_token": probe(conn.uri, resource.accessToken),
            "login_token": probe(conn.uri, account_token),
            "same_token": resource.accessToken == account_token,
        }
    with ThreadPoolExecutor(max_workers=8) as pool:
        return list(pool.map(one, ordered))


def advise(rows: list[dict]) -> str:
    """One suggestion for what the results point to, or '' if there is nothing to say."""
    if not rows:
        return "Plex lists no addresses for this server."
    if any(r["server_token"][0] for r in rows):
        if not any(r["login_token"][0] for r in rows):
            return "The server accepts its own access token but not your login token."
        return ""
    reasons = {r["server_token"][1] for r in rows}
    if reasons == {"rejected the token (401)"} and {r["login_token"][1] for r in rows} == reasons:
        same = all(r.get("same_token") for r in rows)
        return ("The server answered but rejected the token"
                + (" (Plex gave the same token for the server as for your login)" if same else "")
                + ". The token may have been revoked or have expired: sign in again with "
                  "'plextool auth login'. If it is a JWT, Plex Media Server may not accept JWTs yet "
                  "(1.43.5.11079 did not); a classic token, the default, works.")
    if reasons == {"DNS lookup failed"}:
        return ("Every address failed DNS lookup. Your router or DNS resolver may be blocking Plex's "
                "*.plex.direct names (DNS rebinding protection). Allow plex.direct there, or use the "
                "server's address directly: plextool server use http://HOST:32400")
    if reasons == {"no response (timed out)"}:
        return ("Nothing answered. This computer may be on a different network, or a firewall is "
                "blocking it. If you are on the server's network, use its address directly: "
                "plextool server use http://HOST:32400")
    if "TLS/certificate error" in reasons:
        return "A TLS/certificate error can come from a proxy or antivirus inspecting HTTPS traffic."
    return ""


def pick_row(rows: list[dict], resource_token: str, login_token: str):
    """The address to use: the first in Plex's order that accepts the server's own token, else the
    login token. Returns (row, token) or (None, None)."""
    for row in rows:
        if row["server_token"][0]:
            return row, resource_token
        if row["login_token"][0]:
            return row, login_token
    return None, None


def check_saved(token: str) -> str | None:
    """Does the saved server accept this token? 'ok', a warning to show, or None if no server is saved."""
    saved = load_saved()
    if not saved:
        return None
    try:
        connect_saved(saved, token)
    except (Unauthorized, RequestException, PlexToolError):
        return ("Your saved server did not accept this JWT. Plex accepts it, but Plex Media Servers may "
                "not yet. Run 'plextool server test' for details, or sign in with 'plextool auth login' "
                "(a classic token) instead.")
    return "ok"


def format_rows(rows: list[dict], used: dict | None = None) -> list[str]:
    def cell(result):
        return paint(result[1], "green" if result[0] else "red")
    width = max((len(r["host"]) for r in rows), default=0) + 2
    return [f"  {r['kind']:<7}{r['host']:<{width}}server token: {cell(r['server_token'])}   "
            f"login token: {cell(r['login_token'])}"
            + (paint("   <- used", "green") if used is not None and r is used else "") for r in rows]


def connect_saved(saved: dict, token: str) -> PlexServer:
    """Open the server chosen with 'server use'.

    A server chosen by name is looked up on plex.tv each time, so a changed address is
    followed. If plex.tv can't be reached, the address that last worked is tried.
    """
    if saved.get("kind") == "url":
        return PlexServer(saved["url"], token)
    last_url = saved.get("last_url")
    try:
        resource = next((r for r in account_servers(token)
                         if r.clientIdentifier == saved.get("machine_id")), None)
    except PlexToolError:
        if last_url:
            return PlexServer(last_url, token)
        raise
    if not resource:
        raise PlexToolError(f"'{saved.get('name')}' is no longer on your Plex account. "
                            "Pick another with 'plextool server find' and 'plextool server use'.")
    rows = probe_resource(resource, token)
    row, use_token = pick_row(rows, resource.accessToken, token)
    plex = PlexServer(row["uri"], use_token, timeout=CONNECT_TIMEOUT) if row else None
    if not plex:
        if last_url:
            return PlexServer(last_url, token)
        lines = [f"Could not reach '{resource.name}' on any address plex.tv lists:", *format_rows(rows)]
        if advice := advise(rows):
            lines.append(advice)
        lines.append("'plextool server test' repeats this check.")
        raise PlexToolError("\n".join(lines))
    if plex._baseurl != last_url or saved.get("last_kind") != row["kind"]:
        save({**saved, "last_url": plex._baseurl, "last_kind": row["kind"]})
    return plex


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def describe_connection(conn) -> str:
    kind = "relay" if conn.relay else "local" if conn.local else "remote"
    return f"{kind} {conn.uri}"


def run_find(args: argparse.Namespace) -> int:
    print(paint("On your Plex account", "cyan"))
    try:
        token, _ = resolve_token(args)
        servers = account_servers(token)
    except PlexToolError as e:
        servers = None
        print(f"  not available: {e}")
        print("  (Sign in with 'plextool auth login' to list the servers on your account.)")
    if servers is not None:
        for server in servers:
            owner = "owned" if server.owned else f"shared by {server.sourceTitle}"
            state = "online" if server.presence else "offline"
            print(f"  {paint(server.name, 'bold')}  {owner}, {state}")
            for conn in server.connections:
                print(f"      {describe_connection(conn)}")
        if not servers:
            print("  no servers found")

    if not args.no_lan:
        print(paint("\nOn this network", "cyan"))
        found = lan_servers()
        for entry in found:
            print(f"  {paint(entry['name'], 'bold')}  {entry['url']}  {entry['version']}".rstrip())
        if not found:
            print("  none answered (this only works on the same network, and some networks block it)")

    print("\nChoose one with 'plextool server use NAME' (from your account) or "
          "'plextool server use http://HOST:32400'.")
    return 0


def run_use(args: argparse.Namespace) -> int:
    target = args.server
    if target.lower().startswith(("http://", "https://")):
        saved = {"kind": "url", "url": target.rstrip("/")}
        if not args.no_check:
            token, _ = resolve_token(args)
            try:
                saved["name"] = PlexServer(saved["url"], token).friendlyName
            except Unauthorized:
                raise PlexToolError("That server rejected the token (401). "
                                    "Use --no-check to save the address anyway.") from None
            except RequestException as e:
                raise PlexToolError(f"Could not reach {target}: {e}. "
                                    "Use --no-check to save the address anyway.") from None
        save(saved)
        print(f"Using {saved.get('name', target)} at {saved['url']}")
        return 0

    token, _ = resolve_token(args)
    servers = account_servers(token)
    matches = [s for s in servers if s.name.lower() == target.lower()]
    if not matches:
        names = ", ".join(s.name for s in servers) or "none"
        raise PlexToolError(f"No server called '{target}' on your account. Available: {names}")
    server = matches[0]
    save({"kind": "account", "name": server.name, "machine_id": server.clientIdentifier})
    print(f"Using {server.name} from your Plex account. Only the name is saved: each time you run "
          "a command, plextool asks plex.tv for the server's current address, so a changed IP is followed.")
    return 0


def run_test(args: argparse.Namespace) -> int:
    token, _ = resolve_token(args)
    target = args.server
    if target and target.lower().startswith(("http://", "https://")):
        ok, reason = probe(target, token)
        print(f"{target}  {paint(reason, 'green' if ok else 'red')}")
        return 0 if ok else 1
    saved = load_saved()
    name = target or saved.get("name")
    if not target and saved.get("kind") == "url":
        ok, reason = probe(saved["url"], token)
        print(f"{saved['url']}  {paint(reason, 'green' if ok else 'red')}")
        return 0 if ok else 1
    if not name:
        raise PlexToolError("No server given and none saved. Try 'plextool server test NAME'.")
    matches = [s for s in account_servers(token) if s.name.lower() == name.lower()]
    if not matches:
        raise PlexToolError(f"No server called '{name}' on your account.")
    rows = probe_resource(matches[0], token)
    used, _ = pick_row(rows, matches[0].accessToken, token)
    print(paint(matches[0].name, "bold"))
    print("\n".join(format_rows(rows, used)))
    if advice := advise(rows):
        print(f"\n{advice}")
    return 0 if any(r["server_token"][0] for r in rows) else 1


def run_show(args: argparse.Namespace) -> int:
    saved = load_saved()
    print(paint("Config folder", "cyan") + f"  {auth.config_dir()}")
    if saved.get("kind") == "url":
        label = f"{saved['name']} at " if saved.get("name") else ""
        print(f"Saved server  {label}{saved['url']}")
    elif saved:
        print(f"Saved server  {saved.get('name')} (looked up on your Plex account)")
        if saved.get("last_url"):
            kind = f"{saved['last_kind']} " if saved.get("last_kind") else ""
            print(f"Last address  {kind}{saved['last_url']}")
    else:
        print("Saved server  none")
    if os.environ.get(URL_ENV):
        print(f"${URL_ENV} is set to {os.environ[URL_ENV]}, which takes priority over the saved server.")
    elif not saved:
        print(f"Commands will use {DEFAULT_URL}.")
    return 0


def run_forget(args: argparse.Namespace) -> int:
    print("Forgot the saved server." if forget() else "No server was saved.")
    return 0


def add_parser(subparsers) -> None:
    parser = add_command(
        subparsers, "server",
        "choose which Plex server to use",
        "Find Plex servers and save the one the other commands should use, so you don't need "
        "--base-url every time. Servers come from your Plex account (which also follows address "
        "changes and works from outside your network) and from a scan of this network. The order "
        "commands use is --base-url, then $PLEX_URL, then the saved server, then "
        f"{DEFAULT_URL}. Nothing here needs the internet except the account list.",
        ["plextool server find",
         "plextool server use \"My Server\"",
         "plextool server use http://192.168.1.20:32400",
         "plextool server show",
         "plextool server forget"])
    sub = parser.add_subparsers(dest="action", metavar="action", required=True)

    find = add_command(
        sub, "find", "list servers on your account and on this network",
        "Lists the servers on your Plex account with every address Plex knows for them, then scans "
        "this network for servers. The scan needs no login and no internet.",
        ["plextool server find", "plextool server find --no-lan"])
    add_token_args(find)
    find.add_argument("--no-lan", action="store_true", help="skip the scan of this network")
    find.set_defaults(run=run_find)

    use = add_command(
        sub, "use", "save the server to use",
        "Save a server by name (from your Plex account) or by address. A name is looked up on "
        "plex.tv each time, so it keeps working if the address changes. An address is used as "
        "given. The server is contacted once to check it, unless you pass --no-check.",
        ["plextool server use \"My Server\"",
         "plextool server use http://192.168.1.20:32400",
         "plextool server use https://plex.example.com:32400 --no-check"])
    add_token_args(use)
    use.add_argument("server", metavar="NAME_OR_URL", help="server name, or an http(s):// address")
    use.add_argument("--no-check", action="store_true",
                     help="save an address without contacting it (and without a token)")
    use.set_defaults(run=run_use)

    test = add_command(
        sub, "test", "check every address of a server and say why any fail",
        "Tries each address Plex lists for a server (or one address you give) and reports whether it "
        "answers, using both the server's own access token and your login token. Failures say why: "
        "DNS lookup failed, timed out, TLS error, token rejected. Use it when a command can't reach "
        "your server. With no argument it tests the saved server.",
        ["plextool server test", "plextool server test \"My Server\"",
         "plextool server test http://192.168.1.20:32400"])
    add_token_args(test)
    test.add_argument("server", nargs="?", metavar="NAME_OR_URL",
                      help="server name or address (default: the saved server)")
    test.set_defaults(run=run_test)

    show = add_command(sub, "show", "show the saved server", "Show which server commands will use.",
                       ["plextool server show"])
    show.set_defaults(run=run_show)

    forgot = add_command(sub, "forget", "forget the saved server",
                         "Delete the saved server. Commands go back to $PLEX_URL or "
                         f"{DEFAULT_URL}.", ["plextool server forget"])
    forgot.set_defaults(run=run_forget)
