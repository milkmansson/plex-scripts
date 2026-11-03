"""labels: add, remove and count labels on movies and shows in bulk."""

from __future__ import annotations

import argparse

from .common import (
    PlexToolError,
    add_command,
    add_connection_args,
    add_library_arg,
    connect,
    describe,
    paint,
    pick_sections,
    plural,
    scan,
)

SHOW_FIRST = 15


def label_names(section) -> list[str]:
    """Labels in use in a library, as the server lists them."""
    return sorted(c.title for c in section.listFilterChoices("label"))


def run_list(args: argparse.Namespace) -> int:
    plex = connect(args)
    total = 0
    for section in pick_sections(plex, args.library):
        names = label_names(section)
        print(paint(f"\n{section.title}", "cyan"))
        if not names:
            print("  no labels")
        for name in names:
            count = len(scan(section, autoreload=False, label=name))
            print(f"  {name:<30} {plural(count, 'item')}")
        total += len(names)
    print(f"\n{plural(total, 'label')} in use.")
    return 0


def selection(args: argparse.Namespace) -> dict:
    """The search filters the options ask for."""
    filters: dict = {}
    if args.title:
        filters["title"] = args.title
    if args.genre:
        filters["genre"] = args.genre
    if args.collection:
        filters["collection"] = args.collection
    if args.year:
        filters["year"] = args.year
    if args.with_label:
        filters["label"] = args.with_label
    if args.unwatched:
        filters["unwatched"] = True
    if not filters and not args.all_items:
        raise PlexToolError("Say which items to change: --title, --genre, --collection, --year, --with-label or "
                            "--unwatched, or --all-items for everything in the chosen libraries.")
    return filters


def run_change(args: argparse.Namespace, adding: bool) -> int:
    filters = selection(args)
    label = args.label.strip()
    if not label:
        raise PlexToolError("The label cannot be empty.")
    plex = connect(args)
    verb, past = ("add", "added") if adding else ("remove", "removed")
    # Ask the server only for items that need the change, so nothing is touched twice.
    wanted = {**filters}
    if adding:
        wanted["label!"] = label
    elif "label" in filters and filters["label"] != label:
        raise PlexToolError("--with-label cannot be a different label when removing.")
    else:
        wanted["label"] = label
    todo = []
    for section in pick_sections(plex, args.library):
        todo += [(section, item) for item in scan(section, autoreload=False, **wanted)]
    if not todo:
        print(f"Nothing to {verb}: no matching item {'lacks' if adding else 'has'} the label '{label}'.")
        return 0
    print(f"{plural(len(todo), 'item')} to {verb} the label '{label}' {'to' if adding else 'from'}:")
    for _, item in todo[:SHOW_FIRST]:
        print(f"  {describe(item)}")
    if len(todo) > SHOW_FIRST:
        print(f"  ... and {len(todo) - SHOW_FIRST} more")
    if not args.commit:
        print(paint("Dry run. Pass --commit to apply.", "yellow"))
        return 0
    for _, item in todo:
        (item.addLabel if adding else item.removeLabel)(label)
    print(paint(f"Label '{label}' {past} on {plural(len(todo), 'item')}.", "green"))
    return 0


def add_parser(subparsers) -> None:
    parser = add_command(
        subparsers, 'labels',
        'add, remove and count labels in bulk',
        "Labels group items for sharing: a user's library access can be limited to items with (or without) a label "
        "(see 'plextool users invite --movies-label'). 'list' counts the labels in use. 'add' and 'remove' change "
        "every item matching the options given, as a preview unless --commit is given. Items that already have "
        "(or lack) the label are left alone.",
        ['plextool labels list',
         'plextool labels add kids --genre Animation --commit',
         "plextool labels add kids -l Movies --collection 'Pixar'",
         'plextool labels remove kids --title Saw --commit'])
    sub = parser.add_subparsers(dest="action", metavar="action", required=True)

    lst = add_command(sub, 'list', 'count the labels in use', "Lists each library's labels with how many items have each. Read-only.",
                      ['plextool labels list', "plextool labels list -l Movies"])
    add_connection_args(lst)
    add_library_arg(lst)

    def change(name, summary, text):
        p = add_command(sub, name, summary, text + " Choose items with at least one option below, or --all-items. "
                        "Options combine with AND. A dry run unless --commit is given.",
                        [f'plextool labels {name} kids --genre Animation', f"plextool labels {name} kids --title Shrek --commit"])
        add_connection_args(p)
        add_library_arg(p)
        p.add_argument("label", help="the label")
        p.add_argument("--title", metavar="TEXT", help="title contains TEXT")
        p.add_argument("--genre", metavar="NAME", help="has this genre")
        p.add_argument("--collection", metavar="NAME", help="is in this collection")
        p.add_argument("--year", type=int, metavar="YEAR", help="released in this year")
        p.add_argument("--with-label", metavar="LABEL", help="already has this other label")
        p.add_argument("--unwatched", action="store_true", help="not yet watched by the token's user")
        p.add_argument("--all-items", action="store_true", help="every item in the chosen libraries")
        p.add_argument("--commit", action="store_true", help="actually apply")

    change("add", "add a label to items", "Adds a label to matching movies or shows.")
    change("remove", "remove a label from items", "Removes a label from matching movies or shows.")
    parser.set_defaults(run=run)


def run(args: argparse.Namespace) -> int:
    if args.action == "list":
        return run_list(args)
    return run_change(args, adding=args.action == "add")
