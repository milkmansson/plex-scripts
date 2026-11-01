"""status: a quick look at the server, its libraries and who is watching."""

from __future__ import annotations

import argparse
import json

from .common import add_command, add_connection_args, connect, describe, paint, plural, pretty_size


def collect(plex) -> dict:
    libraries = []
    for section in plex.library.sections():
        libraries.append({
            "title": section.title,
            "type": section.TYPE,
            "items": section.totalSize,
            "storage": section.totalStorage,
            "scanning": bool(section.refreshing),
        })
    sessions = []
    for item in plex.sessions():
        users = getattr(item, "usernames", None) or ["?"]
        players = getattr(item, "players", None) or []
        sessions.append({
            "user": users[0],
            "title": describe(item),
            "state": players[0].state if players else None,
            "player": players[0].title if players else None,
        })
    return {
        "name": plex.friendlyName,
        "version": plex.version,
        "platform": plex.platform,
        "libraries": libraries,
        "sessions": sessions,
        "transcodes": len(plex.transcodeSessions()),
    }


def add_parser(subparsers) -> None:
    parser = add_command(
        subparsers, 'status',
        'show server, library and playback status',
        "Show the server version, each library's size and what is playing now. Read-only.",
        ['plextool status',
        'plextool status --json'])
    add_connection_args(parser)
    parser.add_argument("--json", action="store_true", help="print JSON instead of text")
    parser.set_defaults(run=run)


def run(args: argparse.Namespace) -> int:
    info = collect(connect(args))
    if args.json:
        print(json.dumps(info, indent=2, ensure_ascii=False))
        return 0
    print(paint(f"{info['name']}", "bold") + f"  Plex Media Server {info['version']} on {info['platform']}")
    print(paint("\nLibraries", "cyan"))
    for lib in info["libraries"]:
        flag = paint("  (scanning)", "yellow") if lib["scanning"] else ""
        print(f"  {lib['title']:<24} {lib['type']:<8} {plural(lib['items'] or 0, 'item'):<14} "
              f"{pretty_size(lib['storage'])}{flag}")
    print(paint(f"\nNow playing ({plural(len(info['sessions']), 'session')}, "
                f"{info['transcodes']} transcoding)", "cyan"))
    for s in info["sessions"]:
        print(f"  {s['user']}: {s['title']} [{s['state']}] on {s['player']}")
    return 0
