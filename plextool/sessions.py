"""sessions: list what is playing on the server and stop streams."""

from __future__ import annotations

import argparse
import json

from plexapi.exceptions import BadRequest, NotFound
from requests.exceptions import RequestException

from .common import PlexToolError, add_command, add_connection_args, connect, describe, paint, plural

DEFAULT_REASON = "Playback was stopped by the server administrator."


def minutes(ms) -> str:
    return "?" if not isinstance(ms, int) else f"{ms // 60000}m"


def row(item) -> dict:
    """The facts shown for one stream."""
    player, session, transcode = item.player, item.session, item.transcodeSession
    decision = getattr(transcode, "videoDecision", None) if transcode else "direct"
    return {
        "key": str(item.sessionKey),
        "user": (item.usernames or ["?"])[0],
        "title": describe(item),
        "device": getattr(player, "title", None) or getattr(player, "product", None) or "unknown device",
        "state": getattr(player, "state", None) or "unknown",
        "where": getattr(session, "location", None) or "unknown",
        "video": decision or "unknown",
        "position": minutes(getattr(item, "viewOffset", None)),
        "length": minutes(getattr(item, "duration", None)),
        "stoppable": bool(session and getattr(session, "id", None)),
    }


def run_list(args: argparse.Namespace) -> int:
    rows = [row(i) for i in connect(args).sessions()]
    if args.json:
        print(json.dumps(rows, indent=2, ensure_ascii=False))
        return 0
    if not rows:
        print("Nothing is playing.")
        return 0
    for r in rows:
        print(f"  {r['key']:<6} {r['user']:<14} {r['title']:<44} {r['state']:<8} {r['position']}/{r['length']}  "
              f"{r['device']} ({r['where']}, {r['video']})")
    print(f"\n{plural(len(rows), 'stream')}.")
    return 0


def pick(items: list, args: argparse.Namespace) -> list:
    if not (args.keys or args.user or args.all):
        raise PlexToolError("Say which streams to stop: their numbers (from 'plextool sessions list'), --user NAME or --all.")
    by_key = {str(i.sessionKey): i for i in items}
    unknown = [k for k in args.keys if k not in by_key]
    if unknown:
        raise PlexToolError(f"No stream numbered {', '.join(unknown)}. 'plextool sessions list' shows what is playing now.")
    chosen = {k: by_key[k] for k in args.keys}
    for key, item in by_key.items():
        if args.all or (args.user and args.user.lower() in [u.lower() for u in item.usernames]):
            chosen[key] = item
    if not chosen:
        raise PlexToolError(f"No stream is playing for '{args.user}'.")
    return list(chosen.values())


def run_stop(args: argparse.Namespace) -> int:
    chosen = pick(connect(args).sessions(), args)
    print(f"{plural(len(chosen), 'stream')} to stop, with the message \"{args.reason}\":")
    for item in chosen:
        r = row(item)
        print(f"  {r['key']:<6} {r['user']:<14} {r['title']}  ({r['device']})")
    if not args.commit:
        print(paint("Dry run. Pass --commit to stop them.", "yellow"))
        return 0
    stopped = 0
    for item in chosen:
        r = row(item)
        if not r["stoppable"]:
            print(paint(f"  {r['key']}: Plex gave no stream ID, so it cannot be stopped from here.", "red"))
            continue
        try:
            item.stop(reason=args.reason)
            stopped += 1
        except (BadRequest, NotFound, RequestException) as e:
            print(paint(f"  {r['key']}: Plex refused to stop it ({e}).", "red"))
    print(paint(f"Stopped {plural(stopped, 'stream')}.", "green") if stopped else "Nothing was stopped.")
    return 0 if stopped == len(chosen) else 1


def add_parser(subparsers) -> None:
    parser = add_command(
        subparsers, 'sessions',
        'list what is playing and stop streams',
        "'list' shows every stream on the server: who, what, on which device, whether it is playing or paused, how far "
        "in, where from (lan or wan) and whether the video is direct or transcoded. 'stop' ends streams chosen by "
        "number, user or all, showing the viewer a message. A dry run unless --commit is given.",
        ['plextool sessions list',
         'plextool sessions stop 12 --reason "Restarting the server in 5 minutes" --commit',
         'plextool sessions stop --user alice',
         'plextool sessions stop --all --commit'])
    sub = parser.add_subparsers(dest="action", metavar="action", required=True)

    lst = add_command(sub, 'list', 'list the streams', "Lists the streams now playing. Read-only.",
                      ['plextool sessions list', 'plextool sessions list --json'])
    add_connection_args(lst)
    lst.add_argument("--json", action="store_true", help="print JSON instead of text")

    stop = add_command(sub, 'stop', 'stop streams',
                       "Stops streams by number (as 'sessions list' shows), by --user or --all. The viewer sees the "
                       "--reason message. A dry run unless --commit is given.",
                       ['plextool sessions stop 12', 'plextool sessions stop --user alice --commit'])
    add_connection_args(stop)
    stop.add_argument("keys", nargs="*", metavar="NUMBER", help="stream numbers from 'plextool sessions list'")
    stop.add_argument("--user", metavar="NAME", help="every stream of this user")
    stop.add_argument("--all", action="store_true", help="every stream")
    stop.add_argument("--reason", default=DEFAULT_REASON, help="message shown to the viewer")
    stop.add_argument("--commit", action="store_true", help="actually stop them")
    parser.set_defaults(run=run)


def run(args: argparse.Namespace) -> int:
    return {"list": run_list, "stop": run_stop}[args.action](args)
