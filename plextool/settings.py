"""settings: list, search and change the Plex server's own settings."""

from __future__ import annotations

import argparse
import json

from plexapi.exceptions import BadRequest, NotFound

from .common import PlexToolError, add_command, add_connection_args, connect, paint, plural

TRUE_WORDS = {"true", "yes", "on", "1"}
FALSE_WORDS = {"false", "no", "off", "0"}


def shown(setting, value=None) -> str:
    """A setting's value as text. Secure settings are never printed."""
    value = setting.value if value is None else value
    if getattr(setting, "secure", False) and value not in (None, ""):
        return "(hidden)"
    if isinstance(value, bool):
        return "true" if value else "false"
    return "" if value is None else str(value)


def find_setting(plex, name: str):
    """The setting called `name` (case of the first letter does not matter), or a PlexToolError that suggests close ones."""
    try:
        return plex.settings.get(name)
    except NotFound:
        close = [s.id for s in plex.settings.all() if name.lower() in s.id.lower()][:8]
        hint = f" Similar: {', '.join(close)}." if close else " 'plextool settings list --search TEXT' finds them."
        raise PlexToolError(f"No setting called '{name}'.{hint}") from None


def parse_value(setting, text: str):
    """Turn what was typed into the type the setting needs."""
    kind = setting.type
    try:
        if kind == "bool":
            if text.lower() in TRUE_WORDS:
                return True
            if text.lower() in FALSE_WORDS:
                return False
            raise ValueError
        if kind == "int":
            return int(text)
        if kind == "double":
            return float(text)
    except ValueError:
        want = "true or false" if kind == "bool" else f"a {kind}"
        raise PlexToolError(f"'{setting.id}' needs {want}, not '{text}'.") from None
    return text


def options(setting) -> str:
    values = setting.enumValues
    if not values:
        return ""
    if isinstance(values, dict):
        return ", ".join(str(k) if str(k) == str(v) else f"{k} ({v})" for k, v in values.items())
    return ", ".join(str(v) for v in values)


def as_dict(setting) -> dict:
    return {"id": setting.id, "label": setting.label, "group": setting.group, "type": setting.type,
            "value": None if getattr(setting, "secure", False) else setting.value,
            "default": setting.default, "advanced": bool(setting.advanced), "summary": setting.summary}


def chosen(plex, args: argparse.Namespace) -> list:
    found = [s for s in plex.settings.all() if args.hidden or not s.hidden]
    if args.group:
        found = [s for s in found if (s.group or "").lower() == args.group.lower()]
    if args.search:
        needle = args.search.lower()
        found = [s for s in found if needle in " ".join(
            str(x or "") for x in (s.id, s.label, s.summary, s.group)).lower()]
    if args.changed:
        found = [s for s in found if s.value != s.default]
    return found


def run_list(args: argparse.Namespace) -> int:
    plex = connect(args)
    found = chosen(plex, args)
    if args.json:
        print(json.dumps([as_dict(s) for s in found], indent=2, ensure_ascii=False))
        return 0
    if not found:
        print("No settings match.")
        return 0
    group = None
    for s in found:
        if s.group != group:
            group = s.group
            print(paint(f"\n{group or 'other'}", "cyan"))
        note = "" if s.value == s.default else f"   (default {shown(s, s.default)})"
        print(f"  {s.id:<34} {shown(s):<14}{note}   {s.label or ''}")
    print(f"\n{plural(len(found), 'setting')}.")
    return 0


def run_get(args: argparse.Namespace) -> int:
    setting = find_setting(connect(args), args.name)
    if args.json:
        print(json.dumps(as_dict(setting), indent=2, ensure_ascii=False))
        return 0
    print(f"{setting.id} = {shown(setting)}")
    print(f"  {setting.label or ''} ({setting.type}, group {setting.group or 'none'})")
    print(f"  default: {shown(setting, setting.default)}")
    if setting.enumValues:
        print(f"  choices: {options(setting)}")
    if setting.summary:
        print(f"  {setting.summary}")
    return 0


def run_set(args: argparse.Namespace) -> int:
    plex = connect(args)
    setting = find_setting(plex, args.name)
    value = parse_value(setting, args.value)
    old = shown(setting)
    new = shown(setting, value)
    if setting.value == value:
        print(f"{setting.id} is already {new}. Nothing to change.")
        return 0
    print(f"{setting.id}: {old} -> {new}   ({setting.label or setting.id})")
    if not args.commit:
        print(paint("Dry run. Pass --commit to change it.", "yellow"))
        return 0
    try:
        setting.set(value)
        plex.settings.save()
    except BadRequest as e:
        raise PlexToolError(f"Plex refused the change: {e}") from None
    print(paint(f"{setting.id} is now {shown(plex.settings.get(setting.id))}.", "green"))
    return 0


def add_parser(subparsers) -> None:
    parser = add_command(
        subparsers, 'settings',
        "list, search and change the Plex server's settings",
        "The server's settings are spread over many pages of the web app. 'list' shows them all in one place and "
        "can search them or show only the ones changed from their defaults. 'get' shows one with its explanation. "
        "'set' changes one, as a preview unless --commit is given. Only settings the server lists are changed, and "
        "values are checked against the setting's type and choices first.",
        ['plextool settings list --search transcode',
         'plextool settings list --changed',
         'plextool settings get FriendlyName',
         'plextool settings set TranscoderTempDirectory /fast/disk --commit'])
    sub = parser.add_subparsers(dest="action", metavar="action", required=True)

    lst = add_command(sub, 'list', 'list settings', "Lists the server's settings, grouped. Read-only.",
                      ['plextool settings list', 'plextool settings list --search transcode',
                       'plextool settings list --changed --json'])
    add_connection_args(lst)
    lst.add_argument("--search", metavar="TEXT", help="only settings whose name, label, description or group contains TEXT")
    lst.add_argument("--group", metavar="NAME", help="only this group, as 'settings list' shows it")
    lst.add_argument("--changed", action="store_true", help="only settings that differ from their default")
    lst.add_argument("--hidden", action="store_true", help="include settings the web app hides")
    lst.add_argument("--json", action="store_true", help="print JSON instead of text")

    get = add_command(sub, 'get', 'show one setting', "Shows one setting's value, default, choices and explanation. Read-only.",
                      ['plextool settings get FriendlyName'])
    add_connection_args(get)
    get.add_argument("name", help="the setting's ID, as 'settings list' shows it")
    get.add_argument("--json", action="store_true", help="print JSON instead of text")

    setp = add_command(sub, 'set', 'change one setting',
                       "Changes one setting. The value must suit the setting's type (true or false, a number, text) "
                       "and be one of its choices if it has a list. A dry run unless --commit is given.",
                       ['plextool settings set FriendlyName "Home Plex"',
                        'plextool settings set TranscoderTempDirectory /fast/disk --commit'])
    add_connection_args(setp)
    setp.add_argument("name", help="the setting's ID")
    setp.add_argument("value", help="the new value")
    setp.add_argument("--commit", action="store_true", help="actually change it")
    parser.set_defaults(run=run)


def run(args: argparse.Namespace) -> int:
    return {"list": run_list, "get": run_get, "set": run_set}[args.action](args)
