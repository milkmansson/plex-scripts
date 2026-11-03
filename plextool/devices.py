"""devices: list the apps and devices authorised on the Plex account, and remove the ones no longer wanted."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta

from plexapi.exceptions import BadRequest, NotFound
from requests.exceptions import RequestException

from . import auth
from .common import (
    PlexToolError,
    add_command,
    add_token_args,
    paint,
    plex_account,
    plural,
    resolve_token,
)
from .tokens import describe_authorised, named_devices


def server_ids(args: argparse.Namespace) -> set[str]:
    """IDs of the servers on the account (owned and shared), as plex.tv lists them.

    This is a second check, besides the product name, that an entry is a server. If it cannot be
    made, nothing is removed: guessing wrong could cut off a server.
    """
    try:
        return {r.clientIdentifier for r in plex_account(args).resources()
                if "server" in [p.strip() for p in (r.provides or "").split(",")]}
    except (RequestException, BadRequest, NotFound, PlexToolError) as e:
        raise PlexToolError(f"Could not ask plex.tv which entries are servers ({e}), so nothing was "
                            "removed. Try again.") from None


def is_protected(device, servers: set[str]) -> bool:
    """True for a Plex Media Server's entry, by either check."""
    return auth.is_server(device) or device.clientIdentifier in servers


def matches(device, args: argparse.Namespace, cutoff: datetime | None) -> bool:
    """True if the device meets every filter that was given."""
    if cutoff is not None and not (device.lastSeenAt is None or device.lastSeenAt < cutoff):
        return False
    if args.product and (device.product or "").lower() not in {p.lower() for p in args.product}:
        return False
    return not (args.name and args.name.lower() not in (device.name or "").lower())


def run_list(args: argparse.Namespace) -> int:
    args.token, _ = resolve_token(args)
    devices = auth.account_devices(args.token, everything=True)
    named, current = named_devices(devices), auth.load_state().get("client_id")
    cutoff = datetime.now() - timedelta(days=args.unused_for) if args.unused_for else None
    try:
        servers = server_ids(args)
    except PlexToolError:
        servers = set()   # listing is read-only, so a missing second check only loses a label
    shown = sorted((d for d in devices if matches(d, args, cutoff)),
                   key=lambda d: d.lastSeenAt or datetime.min, reverse=True)
    print(paint("Apps and devices authorised on the Plex account", "cyan"))
    for device in shown:
        print(describe_authorised(device, named, current, servers))
    if not shown:
        print("  none")
    print(f"\n{plural(len(shown), 'device')}. 'plextool devices remove ID' removes one.")
    return 0


def run_remove(args: argparse.Namespace) -> int:
    filtered = args.unused_for is not None or bool(args.product or args.name)
    if not (args.ids or filtered):
        raise PlexToolError("Say what to remove: one or more device IDs from 'plextool devices list', or "
                            "filters (--unused-for DAYS, --product NAME, --name TEXT).")
    if args.unused_for is not None and args.unused_for < 1:
        raise PlexToolError("--unused-for must be at least 1 day.")
    args.token, _ = resolve_token(args)
    devices = auth.account_devices(args.token, everything=True)
    named, current = named_devices(devices), auth.load_state().get("client_id")
    cutoff = datetime.now() - timedelta(days=args.unused_for) if args.unused_for is not None else None
    servers = server_ids(args)

    chosen = {}
    for prefix in args.ids:
        hits = [d for d in devices if (d.clientIdentifier or "").startswith(prefix)]
        if not hits:
            raise PlexToolError(f"No device on the account starts with '{prefix}'. 'plextool devices list' shows them.")
        if len(hits) > 1:
            raise PlexToolError(f"'{prefix}' matches {len(hits)} devices; give more of the ID.")
        if is_protected(hits[0], servers):
            raise PlexToolError(f"'{hits[0].name}' is a Plex Media Server ({hits[0].product}). plextool does not remove "
                                "servers, since that could cut off the server itself.")
        chosen[hits[0].clientIdentifier] = hits[0]
    if filtered:
        skipped = 0
        for device in devices:
            if not matches(device, args, cutoff):
                continue
            if is_protected(device, servers) or device.clientIdentifier == current or device.clientIdentifier in named:
                skipped += 1   # servers, this login and tokens for other tools are only removed by naming them
                continue
            chosen[device.clientIdentifier] = device
        if skipped:
            print(f"Not selecting {plural(skipped, 'matching device')}: Plex Media Servers, this login and tokens "
                  "made with 'plextool token' are only removed by naming their ID.")
    if not chosen:
        print("Nothing to remove.")
        return 0

    verb = "Removing" if args.commit else "Would remove"
    if any(is_protected(d, servers) for d in chosen.values()):   # unreachable by the code above; a last guard
        raise PlexToolError("Refusing to remove a Plex Media Server. Nothing was removed.")
    print(f"{verb} {plural(len(chosen), 'device')}:")
    for device in sorted(chosen.values(), key=lambda d: d.lastSeenAt or datetime.min, reverse=True):
        print(describe_authorised(device, named, current, servers))
    if current in chosen:
        print(paint("\nThat includes this computer's saved login. Sign in again with 'plextool auth login'.", "yellow"))
    print("\nEach app or device removed is signed out, and will ask to sign in again if it is used.")
    if not args.commit:
        print("Dry run only. Re-run with --commit to remove.")
        return 0
    failed = 0
    for device in chosen.values():
        try:
            device.delete()
        except (BadRequest, NotFound, RequestException) as e:
            failed += 1
            print(paint(f"  could not remove {(device.clientIdentifier or '')[:8]}: {e}", "red"))
    print(paint(f"Removed {len(chosen) - failed}.", "green") if not failed else f"{failed} failed.")
    return 1 if failed else 0


def add_parser(subparsers) -> None:
    parser = add_command(
        subparsers, 'devices',
        'list and remove the apps and devices authorised on the Plex account',
        "Every phone, TV, browser and app signed in to the Plex account is an entry under Authorized "
        "Devices, which is awkward to tidy in the web app. 'list' shows them, most recently used first. "
        "'remove' signs out the ones given by ID or chosen by filters (--unused-for, --product, --name); "
        "filters combine with AND. Plex Media Servers are never removed. The saved login and tokens made with "
        "'plextool token' are only removed when named by ID. Nothing is removed without --commit.",
        ['plextool devices list',
         'plextool devices list --product "Plex Web"',
         'plextool devices remove --unused-for 180',
         'plextool devices remove --product "Plex Web" --unused-for 30 --commit',
         'plextool devices remove 3895d339 --commit'])
    sub = parser.add_subparsers(dest="action", metavar="action", required=True)

    def filters(p):
        p.add_argument("--unused-for", type=int, metavar="DAYS", help="not used in the last DAYS days (or never)")
        p.add_argument("--product", action="append", default=[], metavar="NAME",
                       help="only this app, as 'devices list' shows it (eg 'Plex Web'); repeat for several")
        p.add_argument("--name", metavar="TEXT", help="only devices whose name contains TEXT")

    lst = add_command(sub, 'list', 'list the apps and devices on the account',
                      "Lists every app and device authorised on the Plex account, optionally narrowed by "
                      "filters. Read-only.",
                      ['plextool devices list', 'plextool devices list --unused-for 90',
                       'plextool devices list --product "Plex Web"'])
    add_token_args(lst)
    filters(lst)

    rem = add_command(sub, 'remove', 'sign out apps and devices by ID or filter',
                      "Remove devices from the Plex account, by ID or by filters. Plex Media Servers are never "
                      "removed. With filters, the saved login and tokens made with 'plextool token' are skipped. "
                      "A dry run unless --commit is given.",
                      ['plextool devices remove 3895d339', 'plextool devices remove --unused-for 180',
                       'plextool devices remove --product "Plex Web" --unused-for 30 --commit'])
    add_token_args(rem)
    rem.add_argument("ids", nargs="*", metavar="ID", help="start of a device ID shown by 'plextool devices list'")
    filters(rem)
    rem.add_argument("--commit", action="store_true", help="actually remove them")
    parser.set_defaults(run=run)


def run(args: argparse.Namespace) -> int:
    return {"list": run_list, "remove": run_remove}[args.action](args)
