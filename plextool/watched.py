"""watched: copy, back up, restore and bulk-set watched state."""

from __future__ import annotations

import argparse
import json
from datetime import datetime

from plexapi.exceptions import NotFound
from plexapi.myplex import MyPlexAccount
from plexapi.server import PlexServer
from requests.exceptions import RequestException

from .common import (
    SECTION_LEVELS,
    PlexToolError,
    add_connection_args,
    add_library_arg,
    connect,
    describe,
    paint,
    pick_sections,
    plural,
)

# Each kind of watched item: (name in files and flags, library type, item type)
KINDS = (("movies", "movie", "movie"), ("episodes", "show", "episode"))
FORMAT_VERSION = 1


def user_server(args: argparse.Namespace, admin: PlexServer, name: str | None) -> PlexServer:
    """Open the server as the named user (the owner if name is None or is the owner)."""
    if not name:
        return admin
    try:
        account = MyPlexAccount(token=args.token)
    except RequestException as e:
        raise PlexToolError(f"Could not reach plex.tv: {e}") from None
    own_names = {n.lower() for n in (account.username, account.email, account.title) if n}
    if name.lower() in own_names:
        return admin
    try:
        user = account.user(name)
    except NotFound:
        raise PlexToolError(f"'{name}' is not a user on this account.") from None
    token = user.get_token(admin.machineIdentifier)
    if not token:
        raise PlexToolError(
            f"Could not get an access token for '{name}'. Is this server shared with them?")
    try:
        return PlexServer(args.base_url, token)
    except RequestException as e:
        raise PlexToolError(f"Could not connect as '{name}': {e}") from None


def wanted_kinds(args: argparse.Namespace) -> list[tuple[str, str, str]]:
    both = not (args.movies or args.shows)
    return [k for k in KINDS if both or (k[0] == "movies" and args.movies)
            or (k[0] == "episodes" and args.shows)]


def collect_watched(server: PlexServer, kinds) -> dict:
    """{'movies': {guid: title}, 'episodes': {guid: title}} of what this user has watched."""
    found = {}
    for label, section_type, libtype in kinds:
        found[label] = {}
        for section in server.library.sections():
            if section.TYPE == section_type:
                for item in section.search(libtype=libtype, unwatched=False):
                    found[label][item.guid] = describe(item)
    return found


def apply_watched(server: PlexServer, watched: dict, kinds, commit: bool) -> int:
    """Mark items watched where `watched` says they should be; returns how many."""
    count = 0
    for label, section_type, libtype in kinds:
        guids = watched.get(label, {})
        if not guids:
            continue
        print(paint(f"\n{label.upper()}", "cyan"))
        for section in server.library.sections():
            if section.TYPE != section_type:
                continue
            for item in section.search(libtype=libtype, unwatched=True):
                if item.guid not in guids:
                    continue
                if commit:
                    item.markPlayed()
                    print(f"  [MARKED]  {describe(item)}")
                else:
                    print(f"  [DRY RUN] Would mark watched: {describe(item)}")
                count += 1
    return count


def report(total: int, who: str, commit: bool) -> None:
    verb = "Marked" if commit else "Would mark"
    print(f"\n{verb} {total} item(s) as watched for {who}.")
    if not commit and total:
        print("Dry run only. Re-run with --commit to apply.")


def to_file_data(user: str, watched: dict) -> dict:
    return {
        "version": FORMAT_VERSION,
        "user": user,
        "exported": datetime.now().replace(microsecond=0).isoformat(),
        **{label: [{"guid": g, "title": t} for g, t in items.items()] for label, items in watched.items()},
    }


def from_file_data(data: dict) -> dict:
    if data.get("version") != FORMAT_VERSION:
        raise PlexToolError("Unrecognised file: not a plextool watched export.")
    return {label: {e["guid"]: e["title"] for e in data.get(label, [])} for label, _, _ in KINDS}


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def run_copy(args: argparse.Namespace) -> int:
    admin = connect(args)
    if args.source.lower() == args.dest.lower():
        raise PlexToolError("--from and --to are the same user.")
    kinds = wanted_kinds(args)
    print(f"Source: {args.source}   Destination: {args.dest}   "
          f"Mode: {'COMMIT' if args.commit else 'DRY RUN'}")
    watched = collect_watched(user_server(args, admin, args.source), kinds)
    for label, items in watched.items():
        print(f"  Source has watched {plural(len(items), label.rstrip('s'))}.")
    total = apply_watched(user_server(args, admin, args.dest), watched, kinds, args.commit)
    report(total, args.dest, args.commit)
    return 0


def run_export(args: argparse.Namespace) -> int:
    admin = connect(args)
    watched = collect_watched(user_server(args, admin, args.user), wanted_kinds(args))
    data = to_file_data(args.user or "owner", watched)
    with open(args.file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"Wrote {sum(len(v) for v in watched.values())} watched item(s) to {args.file}")
    return 0


def run_import(args: argparse.Namespace) -> int:
    try:
        with open(args.file, encoding="utf-8") as f:
            watched = from_file_data(json.load(f))
    except (OSError, ValueError) as e:
        raise PlexToolError(f"Could not read {args.file}: {e}") from None
    admin = connect(args)
    total = apply_watched(user_server(args, admin, args.user), watched, wanted_kinds(args), args.commit)
    report(total, args.user or "the owner", args.commit)
    return 0


def run_mark(args: argparse.Namespace) -> int:
    admin = connect(args)
    server = user_server(args, admin, args.user)
    # The user's view of the library, so match sections by name on their connection.
    names = [s.title for s in pick_sections(admin, args.library)]
    count = 0
    for name in names:
        section = server.library.section(name)
        level = args.level or section.TYPE
        if level not in SECTION_LEVELS[section.TYPE]:
            continue
        for item in section.search(title=args.title, libtype=level):
            action = "unwatched" if args.unwatched else "watched"
            print(f"  {'[MARKED]' if args.commit else '[DRY RUN]'} {describe(item)} -> {action}")
            if args.commit:
                item.markUnplayed() if args.unwatched else item.markPlayed()
            count += 1
    print(f"\n{plural(count, 'item')} {'updated' if args.commit else 'would be updated'}.")
    if not args.commit and count:
        print("Dry run only. Re-run with --commit to apply.")
    return 0


def _kind_flags(parser) -> None:
    parser.add_argument("--movies", action="store_true", help="movies only")
    parser.add_argument("--shows", action="store_true", help="TV episodes only")


def add_parser(subparsers) -> None:
    parser = subparsers.add_parser(
        "watched", help="copy, back up, restore or bulk-set watched state",
        description="Work with watched state. --token must be the server owner's token. Watchlists "
                    "live on plex.tv and are not covered. Only the watched flag moves: view counts, "
                    "last-watched dates and resume positions do not.")
    sub = parser.add_subparsers(dest="watched_command", required=True, metavar="action")

    copy = sub.add_parser("copy", help="copy watched state from one user to another")
    add_connection_args(copy)
    copy.add_argument("--from", dest="source", required=True, metavar="USER",
                      help="user to copy from (username, email, or Home user name)")
    copy.add_argument("--to", dest="dest", required=True, metavar="USER", help="user to copy to")
    _kind_flags(copy)
    copy.add_argument("-y", "--commit", action="store_true", help="write the changes (default is a dry run)")
    copy.set_defaults(run=run_copy)

    export = sub.add_parser("export", help="save a user's watched state to a JSON file")
    add_connection_args(export)
    export.add_argument("file", help="file to write")
    export.add_argument("--user", metavar="USER", help="user to export (default: the token owner)")
    _kind_flags(export)
    export.set_defaults(run=run_export)

    imp = sub.add_parser("import", help="restore watched state from a JSON file")
    add_connection_args(imp)
    imp.add_argument("file", help="file written by 'watched export'")
    imp.add_argument("--user", metavar="USER", help="user to import into (default: the token owner)")
    _kind_flags(imp)
    imp.add_argument("-y", "--commit", action="store_true", help="write the changes (default is a dry run)")
    imp.set_defaults(run=run_import)

    mark = sub.add_parser("mark", help="mark movies, shows, seasons or episodes watched/unwatched")
    add_connection_args(mark)
    add_library_arg(mark)
    mark.add_argument("-t", "--title", required=True, help="title to match (substring)")
    mark.add_argument("--level", choices=sorted({lv for lvs in SECTION_LEVELS.values() for lv in lvs}),
                      help="item type (default: movie in movie libraries, show in TV libraries)")
    mark.add_argument("--unwatched", action="store_true", help="mark unwatched instead of watched")
    mark.add_argument("--user", metavar="USER", help="user to change (default: the token owner)")
    mark.add_argument("-y", "--commit", action="store_true", help="write the changes (default is a dry run)")
    mark.set_defaults(run=run_mark)
