"""auth: sign in to Plex without hunting for a token, and look after what is saved."""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

from plexapi.exceptions import BadRequest, NotFound, Unauthorized
from plexapi.myplex import MyPlexAccount
from requests.exceptions import RequestException

from . import __version__
from .common import (
    SIGN_IN_AGAIN,
    PlexToolError,
    add_command,
    add_token_args,
    confirm_typed,
    paint,
    plural,
    resolve_token,
)

CONFIG_DIR_ENV = "PLEXTOOL_CONFIG_DIR"
STATE_FILE = "auth.json"
SERVER_FILE = "server.json"
PRIVATE_KEY_FILE = "jwt_private.key"
PUBLIC_KEY_FILE = "jwt_public.key"
KEY_FILES = (PRIVATE_KEY_FILE, PUBLIC_KEY_FILE)
ALL_FILES = (STATE_FILE, *KEY_FILES, SERVER_FILE)

# A JWT is renewed when it has less than this left.
REFRESH_WITHIN = timedelta(days=1)
LOGIN_TIMEOUT = 300


# ---------------------------------------------------------------------------
# Where things are kept
# ---------------------------------------------------------------------------

def config_dir() -> Path:
    """The folder holding the saved login and keys: $PLEXTOOL_CONFIG_DIR, else ~/.config/plextool."""
    if os.environ.get(CONFIG_DIR_ENV):
        return Path(os.environ[CONFIG_DIR_ENV]).expanduser()
    base = os.environ.get("XDG_CONFIG_HOME") or "~/.config"
    return Path(base).expanduser() / "plextool"


def write_private(path: Path, data: bytes) -> None:
    """Write a file that only its owner can read, never briefly readable by anyone else."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    os.replace(temp, path)


def load_state() -> dict:
    path = config_dir() / STATE_FILE
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        raise PlexToolError(f"Could not read {path}: {e}. 'plextool auth wipe' clears it.") from None


def save_state(state: dict) -> None:
    write_private(config_dir() / STATE_FILE, json.dumps(state, indent=2).encode())


def _require_jwt_support():
    try:
        import jwt  # noqa: F401
        from cryptography.hazmat.primitives.asymmetric import ed25519  # noqa: F401
        from plexapi.myplex import MyPlexJWTLogin
    except ImportError:
        raise PlexToolError("JWT sign-in needs plexapi 4.18 or later with PyJWT and cryptography. "
                            "Install them with: pip install 'plexapi>=4.18' 'pyjwt[crypto]'") from None
    return MyPlexJWTLogin


def _headers(client_id: str) -> dict:
    return {
        "X-Plex-Client-Identifier": client_id,
        "X-Plex-Product": "plextool",
        "X-Plex-Version": __version__,
        "X-Plex-Device-Name": f"plextool on {socket.gethostname()}",
    }


def _new_keypair() -> tuple[bytes, bytes]:
    """A fresh ED25519 keypair as raw bytes, the form plexapi expects."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519
    private = ed25519.Ed25519PrivateKey.generate()
    return (
        private.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
                              serialization.NoEncryption()),
        private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw),
    )


def _jwt_expiry(token: str) -> datetime | None:
    """When a JWT runs out, read without checking the signature. None if it can't be read."""
    import jwt
    try:
        exp = jwt.decode(token, options={"verify_signature": False}).get("exp")
    except jwt.InvalidTokenError:
        return None
    return datetime.fromtimestamp(exp, timezone.utc) if exp else None


# ---------------------------------------------------------------------------
# The token other commands use
# ---------------------------------------------------------------------------

def stored_token() -> str | None:
    """The token from the saved login, renewing a JWT that is close to expiring. None if not signed in."""
    state = load_state()
    token = state.get("token")
    if not token:
        return None
    if state.get("kind") != "jwt":
        return token
    expiry = _jwt_expiry(token)
    now = datetime.now(timezone.utc)
    if expiry and expiry - now > REFRESH_WITHIN:
        return token
    try:
        return _refresh(state)
    except (BadRequest, RequestException, PlexToolError) as e:
        if expiry and expiry > now:
            print(f"warning: could not renew the Plex JWT ({e}); using the current one until "
                  f"{expiry:%Y-%m-%d %H:%M} UTC.", file=sys.stderr)
            return token
        raise PlexToolError(f"The saved Plex JWT has expired and could not be renewed ({e}). "
                            "Run 'plextool auth login' again.") from None


def use_saved_identity() -> None:
    """Make plexapi's requests carry the saved device ID.

    A JWT is issued to one device and names it in the token, so a server may expect requests
    that use the JWT to come from that same X-Plex-Client-Identifier.
    """
    import plexapi
    state = load_state()
    if state.get("kind") == "jwt" and state.get("client_id"):
        plexapi.BASE_HEADERS["X-Plex-Client-Identifier"] = state["client_id"]


def _refresh(state: dict) -> str:
    login_class = _require_jwt_support()
    directory = config_dir()
    try:
        keys = tuple((directory / name).read_bytes() for name in KEY_FILES)
    except OSError as e:
        raise PlexToolError(f"The signing keys are missing ({e}). Run 'plextool auth login' again.") from None
    login = login_class(headers=_headers(state["client_id"]), jwtToken=state["token"], keypair=keys)
    state["token"] = login.refreshJWT()
    save_state(state)
    return state["token"]


# ---------------------------------------------------------------------------
# Signing in
# ---------------------------------------------------------------------------

def _short_link(url: str) -> str:
    """Trim plexapi's sign-in link to what Plex needs, so its QR code stays small enough to scan."""
    query = parse_qs(urlsplit(url).fragment.partition("?")[2])
    keep = {k: query[k][0] for k in ("clientID", "code", "context[device][product]") if k in query}
    return f"https://app.plex.tv/auth/#!?{urlencode(keep)}"


NEXT_STEP = "Next, choose your server with 'plextool server find' (the default is http://localhost:32400)."

KIND_BLURB = {
    "jwt": "a JWT: short-lived and renews itself using a signing key kept on this computer. "
           "Plex accepts it, but Plex Media Servers may not yet",
    "token": "a classic token: it never expires until you revoke it in your Plex account",
}


def show_link(url: str, kind: str) -> None:
    # The JWT sign-in is known to work with the trimmed link. The classic token sign-in is known to
    # work with the full link, so it gets that (and a bigger QR code).
    link = _short_link(url) if kind == "jwt" else url
    print(paint(f"Signing in for {KIND_BLURB[kind]}.", "bold") + "\n")
    print("Open this link in a browser and sign in to Plex:\n")
    print(f"  {link}\n")
    try:
        import segno
    except ImportError:
        print("(Install 'segno' to see a QR code here as well: pip install segno)\n")
    else:
        if sys.stdout.isatty():
            segno.make(link, error="l").terminal(compact=True)
            print("Or scan the code above with your phone.\n")
    print("Waiting for you to approve it...")


def _new_client_id() -> str:
    """A device ID for one sign-in. Every login gets its own: Plex's sign-in page refuses a device ID
    that already has a different key or token type registered, so IDs are never reused."""
    return str(uuid.uuid4())


def login_jwt(timeout: int) -> None:
    login_class = _require_jwt_support()
    client_id = _new_client_id()
    private, public = _new_keypair()
    login = login_class(headers=_headers(client_id), oauth=True, keypair=(private, public))
    try:
        login.run(timeout=timeout)
        show_link(login.oauthUrl(), "jwt")
        approved = login.waitForLogin()
    except RequestException as e:
        raise PlexToolError(f"Could not reach plex.tv: {e}") from None
    finally:
        login.stop()
    if not approved:
        raise PlexToolError("Sign-in was not approved in time. Nothing was saved.")
    directory = config_dir()
    write_private(directory / PRIVATE_KEY_FILE, private)
    write_private(directory / PUBLIC_KEY_FILE, public)
    save_state({"client_id": client_id, "kind": "jwt", "token": login.jwtToken})
    expiry = _jwt_expiry(login.jwtToken)
    print(paint("\nSigned in with a JWT.", "green") + f" Saved to {directory}")
    if expiry:
        print(f"This token runs out on {expiry:%Y-%m-%d %H:%M} UTC and renews itself when used.")
    print(NEXT_STEP)
    use_saved_identity()
    from . import server  # imported here because server itself uses this module
    outcome = server.check_saved(login.jwtToken)
    if outcome == "ok":
        print(paint("Your saved server accepted this JWT.", "green"))
    elif outcome:
        print(paint(outcome, "yellow"))
    else:
        print("Once you have chosen a server, 'plextool server test' shows whether it accepts a JWT.")


def login_token(timeout: int, print_only: bool) -> None:
    from plexapi.myplex import MyPlexPinLogin
    client_id = _new_client_id()
    login = MyPlexPinLogin(headers=_headers(client_id), oauth=True)
    try:
        login.run(timeout=timeout)
        show_link(login.oauthUrl(), "token")
        approved = login.waitForLogin()
    except RequestException as e:
        raise PlexToolError(f"Could not reach plex.tv: {e}") from None
    finally:
        login.stop()
    if not approved:
        raise PlexToolError("Sign-in was not approved in time. Nothing was saved.")
    if print_only:
        print(login.token)
        return
    directory = config_dir()
    save_state({"client_id": client_id, "kind": "token", "token": login.token})
    for name in KEY_FILES:  # a JWT login's keys are no use any more
        (directory / name).unlink(missing_ok=True)
    print(paint("\nSigned in with a classic token.", "green") + f" Saved to {directory}")
    print(paint("This token does not expire.", "yellow") +
          " Revoke it in your Plex account under Authorized Devices ('plextool').")
    print(NEXT_STEP)


# ---------------------------------------------------------------------------
# Devices on the Plex account
# ---------------------------------------------------------------------------

PRODUCT = "plextool"


def account_devices(token: str, everything: bool = False) -> list:
    """The devices on the Plex account: just plextool's own, unless everything is True."""
    try:
        devices = MyPlexAccount(token=token).devices()
    except Unauthorized:
        raise PlexToolError(f"plex.tv rejected the token. {SIGN_IN_AGAIN}") from None
    except (RequestException, BadRequest) as e:
        raise PlexToolError(f"Could not reach plex.tv: {e}") from None
    if not everything:
        devices = [d for d in devices if (d.product or "").lower() == PRODUCT]
    return sorted(devices, key=lambda d: d.lastSeenAt or datetime.min, reverse=True)


def _when(value) -> str:
    return f"{value:%Y-%m-%d %H:%M}" if value else "never"


def _short(device) -> str:
    return (device.clientIdentifier or "")[:8]


def describe_device(device, current_id: str | None) -> str:
    mark = paint("  (this login)", "green") if current_id and device.clientIdentifier == current_id else ""
    return (f"  {_short(device):<10}{device.name or '?':<40}created {_when(device.createdAt)}   "
            f"last seen {_when(device.lastSeenAt)}{mark}")


def list_devices(args: argparse.Namespace) -> None:
    token, _ = resolve_token(args)
    devices = account_devices(token, args.all)
    current = load_state().get("client_id")
    print(paint("Devices on your Plex account" + ("" if args.all else " signed in through plextool"), "cyan"))
    for device in devices:
        extra = f"  [{device.product}]" if args.all else ""
        print(describe_device(device, current) + extra)
    if not devices:
        print("  none")
    elif not args.all:
        print("\nRemove old ones with 'plextool auth revoke --others --commit'.")


def revoke_devices(args: argparse.Namespace) -> None:
    if not (args.ids or args.others or args.this):
        raise PlexToolError("Say what to remove: --others, --this, or one or more device IDs "
                            "from 'plextool auth devices'.")
    token, _ = resolve_token(args)
    devices = account_devices(token)
    current = load_state().get("client_id")
    chosen = {}
    if args.others:
        chosen.update({d.clientIdentifier: d for d in devices if d.clientIdentifier != current})
    if args.this:
        if not current:
            raise PlexToolError("No saved login, so there is no device of this computer to remove.")
        chosen.update({d.clientIdentifier: d for d in devices if d.clientIdentifier == current})
    for prefix in args.ids:
        matches = [d for d in devices if (d.clientIdentifier or "").startswith(prefix)]
        if not matches:
            raise PlexToolError(f"No plextool device starts with '{prefix}'. "
                                "'plextool auth devices' lists them.")
        if len(matches) > 1:
            raise PlexToolError(f"'{prefix}' matches {len(matches)} devices; give more of the ID.")
        chosen[matches[0].clientIdentifier] = matches[0]

    if not chosen:
        print("Nothing to remove.")
        return
    removing_current = current in chosen
    verb = "Removing" if args.commit else "Would remove"
    print(f"{verb} {plural(len(chosen), 'device')}:")
    for device in chosen.values():
        print(describe_device(device, current))
    if removing_current:
        print(paint("\nThat includes this login, which stops working. Sign in again with "
                    "'plextool auth login'.", "yellow"))
    if not args.commit:
        print("\nDry run only. Re-run with --commit to remove.")
        return
    failed = 0
    for device in chosen.values():
        try:
            device.delete()
        except (BadRequest, NotFound, RequestException) as e:
            failed += 1
            print(paint(f"  could not remove {_short(device)}: {e}", "red"))
    print(paint(f"Removed {len(chosen) - failed}.", "green") if not failed else f"{failed} failed.")


def wipe(assume_yes: bool) -> None:
    directory = config_dir()
    present = [directory / name for name in ALL_FILES if (directory / name).exists()]
    if not present:
        print(f"Nothing to remove in {directory}.")
        return
    print("This removes:")
    for path in present:
        print(f"  {path}")
    confirm_typed("WIPE", "The saved login, signing keys and chosen server are deleted from this computer.",
                  assume_yes)
    for path in present:
        path.unlink()
    try:
        directory.rmdir()
    except OSError:
        pass  # something else lives there
    print(paint("Removed.", "green") +
          " If you haven't revoked this sign-in, Plex still lists it under Authorized Devices: use "
          "'plextool auth revoke --this --commit' before wiping next time, or remove it in your Plex account.")


def status() -> None:
    directory = config_dir()
    state = load_state()
    print(paint("Config folder", "cyan") + f"  {directory}")
    for name in ALL_FILES:
        path = directory / name
        if path.exists():
            mode = path.stat().st_mode & 0o777
            note = "" if mode == 0o600 else paint("  (should be 0600)", "yellow")
            print(f"  {name:<16} {mode:04o}{note}")
        else:
            print(f"  {name:<16} not present")
    if not state.get("token"):
        print("\nNot signed in. Run 'plextool auth login'.")
        return
    print(paint("\nSaved login", "cyan"))
    if state.get("kind") == "jwt":
        expiry = _jwt_expiry(state["token"])
        print("  type      jwt (short-lived; renews itself using the signing keys)")
        if expiry:
            print(f"  expires   {expiry:%Y-%m-%d %H:%M} UTC")
    else:
        print("  type      token (classic; never expires until revoked in your Plex account)")
    print(f"  device    {state.get('client_id')}")


def add_parser(subparsers) -> None:
    parser = add_command(
        subparsers, "auth",
        "sign in to Plex and manage the saved login",
        "Sign in through your browser (or by scanning a QR code with your phone) so you never have "
        "to find or paste a token. 'login' saves the token in the config folder (~/.config/plextool, "
        "or $PLEXTOOL_CONFIG_DIR). With --type jwt it saves a short-lived JWT plus the signing keys "
        "that renew it, which never leave your computer. 'wipe' deletes everything saved. Other commands use the saved login unless "
        "you give --token, --token-file or set $PLEX_TOKEN.",
        ["plextool auth login",
         "plextool auth login --type token --print",
         "plextool auth status",
         "plextool auth devices",
         "plextool auth revoke --others --commit",
         "plextool auth wipe"])
    sub = parser.add_subparsers(dest="action", metavar="action", required=True)

    login = add_command(
        sub, "login", "sign in and save the login",
        "Prints a link (and a QR code, if 'segno' is installed) to approve in a browser. Both types "
        "use the same browser sign-in; they differ in what you get back. --type token (the default) "
        "gives the classic Plex token, which never expires until you revoke it, and which Plex Media "
        "Servers accept. --type jwt gives a short-lived JWT that renews itself with a signing key kept "
        "in the config folder. Plex accepts it, but Plex Media Servers may not yet: after a JWT login "
        "your saved server is checked and you are told.",
        ["plextool auth login",
         "plextool auth login --type jwt",
         "plextool auth login --type token --print > plex-token.txt"])
    login.add_argument("--type", dest="kind", choices=("jwt", "token"), default="token",
                       help="token: classic Plex token that never expires (default). "
                            "jwt: short-lived, renews itself, but servers may not accept it")
    login.add_argument("--print", dest="print_only", action="store_true",
                       help="with --type token, print the token and save nothing")
    login.add_argument("--timeout", type=int, default=LOGIN_TIMEOUT, metavar="SECONDS",
                       help=f"how long to wait for approval (default {LOGIN_TIMEOUT})")

    add_command(sub, "status", "show what is saved and when it expires",
                "Show where the login and keys are kept, their permissions and when the token runs "
                "out. The token itself is never shown.", ["plextool auth status"])

    devices = add_command(
        sub, "devices", "list the plextool sign-ins on your Plex account",
        "Every login adds a device to your Plex account (Authorized Devices). This lists the ones "
        "plextool made, newest first, and marks the one this computer's saved login uses.",
        ["plextool auth devices", "plextool auth devices --all"])
    add_token_args(devices)
    devices.add_argument("--all", action="store_true",
                         help="list every device on the account, not just plextool's (read-only)")

    revoke = add_command(
        sub, "revoke", "remove plextool sign-ins from your Plex account",
        "Remove plextool devices from your Plex account so their tokens stop working. Only "
        "plextool's own entries can be removed; other Plex apps and devices are never touched. "
        "Nothing is removed unless you pass --commit.",
        ["plextool auth revoke --others",
         "plextool auth revoke --others --commit",
         "plextool auth revoke 3895d339 --commit",
         "plextool auth revoke --this --commit"])
    add_token_args(revoke)
    revoke.add_argument("ids", nargs="*", metavar="ID",
                        help="start of a device ID shown by 'plextool auth devices'")
    revoke.add_argument("--others", action="store_true",
                        help="every plextool device except the one this login uses")
    revoke.add_argument("--this", action="store_true",
                        help="the device this login uses (it stops working; do this before 'auth wipe')")
    revoke.add_argument("--commit", action="store_true", help="actually remove them")

    wipe_parser = add_command(
        sub, "wipe", "delete the saved login and signing keys",
        "Delete the saved login and the signing keys from the config folder. To also revoke access "
        "on Plex's side, remove plextool under Authorized Devices in your Plex account.",
        ["plextool auth wipe", "plextool auth wipe --assume-yes"])
    wipe_parser.add_argument("-y", "--assume-yes", action="store_true", help="don't ask for confirmation")
    parser.set_defaults(run=run)


def run(args: argparse.Namespace) -> int:
    if args.action == "login":
        if args.print_only and args.kind != "token":
            raise PlexToolError("--print only works with --type token; a JWT is renewed from the saved keys.")
        if args.kind == "token":
            login_token(args.timeout, args.print_only)
        else:
            login_jwt(args.timeout)
    elif args.action == "wipe":
        wipe(args.assume_yes)
    elif args.action == "devices":
        list_devices(args)
    elif args.action == "revoke":
        revoke_devices(args)
    else:
        status()
    return 0
