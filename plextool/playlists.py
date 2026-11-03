"""playlists: list, back up and restore video playlists."""

from __future__ import annotations

import argparse

from plexapi.exceptions import BadRequest

from .common import (
    PlexToolError,
    add_command,
    add_connection_args,
    connect,
    describe,
    paint,
    plural,
    read_json,
    scan,
    write_json,
)

FORMAT_VERSION = 1
VIDEO_TYPES = ("movie", "episode")


def playlist_data(playlist) -> dict:
    """A plain-data description of a playlist; smart playlists are recorded without items."""
    items = [] if playlist.smart else [
        {"guid": i.guid, "title": describe(i), "type": i.type} for i in playlist.items()]
    return {"title": playlist.title, "type": playlist.playlistType, "smart": bool(playlist.smart),
            "items": items}


def guid_lookup(plex, guids: set) -> dict:
    """Find the server's movies and episodes for a set of GUIDs."""
    found = {}
    wanted = {"movie": "movie", "show": "episode"}
    for section in plex.library.sections():
        libtype = wanted.get(section.TYPE)
        if libtype:
            for item in scan(section, libtype=libtype):
                if item.guid in guids:
                    found[item.guid] = item
    return found


def add_parser(subparsers) -> None:
    parser = add_command(
        subparsers, 'playlists',
        'list, export or import video playlists',
        "Back up and restore the token owner's video playlists. Items are matched by Plex GUID. Smart playlists are listed but not exported or recreated.",
        ['plextool playlists list',
        'plextool playlists export playlists.json',
        'plextool playlists import playlists.json --commit'])
    sub = parser.add_subparsers(dest="playlists_command", required=True, metavar="action")

    ls = add_command(
        sub, 'list',
        'list playlists',
        "List the token owner's playlists with their type and size. Read-only.",
        ['plextool playlists list'])
    add_connection_args(ls)
    ls.set_defaults(run=run_list)

    export = add_command(
        sub, 'export',
        'save playlists to a JSON file',
        'Write playlists and the GUIDs of their items to a file. Smart playlists are recorded without items. Read-only on the server.',
        ['plextool playlists export playlists.json',
        'plextool playlists export christmas.json --name Christmas'])
    add_connection_args(export)
    export.add_argument("file", help="file to write ('-' for standard output)")
    export.add_argument("--name", action="append", help="playlist to export; repeat for several (default: all)")
    export.set_defaults(run=run_export)

    imp = add_command(
        sub, 'import',
        'recreate playlists from a JSON file',
        "Recreate playlists from a file made by 'playlists export'. Items not found on this server are skipped. Playlists that already exist are skipped unless you pass --replace, which deletes and recreates them.",
        ['plextool playlists import playlists.json               # preview',
        'plextool playlists import playlists.json --replace --commit'])
    add_connection_args(imp)
    imp.add_argument("file", help="file written by 'playlists export' ('-' for standard input)")
    imp.add_argument("--replace", action="store_true", help="delete and recreate playlists that already exist")
    imp.add_argument("-y", "--commit", action="store_true", help="write the changes (default is a dry run)")
    imp.set_defaults(run=run_import)


def run_list(args: argparse.Namespace) -> int:
    plex = connect(args)
    playlists = plex.playlists()
    for p in playlists:
        kind = "smart" if p.smart else p.playlistType
        print(f"  {p.title}  ({kind}, {plural(p.leafCount or 0, 'item')})")
    print(f"\n{plural(len(playlists), 'playlist')}.")
    return 0


def run_export(args: argparse.Namespace) -> int:
    plex = connect(args)
    chosen = [p for p in plex.playlists() if not args.name or p.title in args.name]
    if args.name:
        missing = set(args.name) - {p.title for p in chosen}
        if missing:
            raise PlexToolError(f"No such playlist: {', '.join(sorted(missing))}")
    data = {"version": FORMAT_VERSION, "playlists": [playlist_data(p) for p in chosen]}
    out = write_json(args.file, data)
    print(f"Wrote {plural(len(chosen), 'playlist')} to "
          f"{'standard output' if args.file == '-' else args.file}", file=out)
    return 0


def run_import(args: argparse.Namespace) -> int:
    data = read_json(args.file)
    if data.get("version") != FORMAT_VERSION:
        raise PlexToolError("Unrecognised file: not a plextool playlist export.")

    plex = connect(args)
    existing = {p.title: p for p in plex.playlists()}
    todo = []
    for entry in data["playlists"]:
        if entry["smart"]:
            print(paint(f"  skip {entry['title']}: smart playlists can't be recreated", "yellow"))
        elif entry["type"] != "video":
            print(paint(f"  skip {entry['title']}: only video playlists are supported", "yellow"))
        elif entry["title"] in existing and not args.replace:
            print(paint(f"  skip {entry['title']}: already exists (use --replace)", "yellow"))
        else:
            todo.append(entry)

    wanted = {i["guid"] for e in todo for i in e["items"]}
    found = guid_lookup(plex, wanted) if wanted else {}
    created = 0
    for entry in todo:
        items = [found[i["guid"]] for i in entry["items"] if i["guid"] in found]
        lost = len(entry["items"]) - len(items)
        note = f", {lost} not found on this server" if lost else ""
        if not items:
            print(paint(f"  skip {entry['title']}: none of its items are on this server", "yellow"))
            continue
        verb = "Created" if args.commit else "Would create"
        print(f"  {verb} {entry['title']}: {plural(len(items), 'item')}{note}")
        if args.commit:
            if entry["title"] in existing:
                existing[entry["title"]].delete()
            try:
                plex.createPlaylist(entry["title"], items=items)
            except BadRequest as e:
                raise PlexToolError(f"Server refused playlist '{entry['title']}': {e}") from None
        created += 1
    print(f"\n{plural(created, 'playlist')} {'created' if args.commit else 'would be created'}.")
    if not args.commit and created:
        print("Dry run only. Re-run with --commit to apply.")
    return 0
