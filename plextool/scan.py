"""scan: trigger library scans, metadata refreshes and clean-up."""

from __future__ import annotations

import argparse
import time

from .common import (
    PlexToolError,
    add_command,
    add_connection_args,
    add_library_arg,
    connect,
    paint,
    pick_sections,
)


def add_parser(subparsers) -> None:
    parser = add_command(
        subparsers, 'scan',
        'scan libraries, refresh metadata, empty trash',
        'Ask the server to scan libraries for new files. With no action option this is a plain scan. Scans run on the server, so the command returns at once unless you use --wait.',
        ['plextool scan',
        'plextool scan -l Movies --path /mnt/media/Movies/New --wait',
        "plextool scan -l 'TV Shows' --refresh",
        'plextool scan --empty-trash --optimize'])
    add_connection_args(parser)
    add_library_arg(parser)
    parser.add_argument("--path", help="scan only this folder (as the server sees it); needs one --library")
    parser.add_argument("--refresh", action="store_true",
                        help="force a metadata refresh from the internet (slow; locked fields are kept)")
    parser.add_argument("--empty-trash", action="store_true", help="empty the trash of each library")
    parser.add_argument("--optimize", action="store_true", help="optimize the server database")
    parser.add_argument("--clean-bundles", action="store_true", help="remove unused metadata bundles")
    parser.add_argument("--wait", action="store_true", help="wait until the scans finish")
    parser.set_defaults(run=run)


def run(args: argparse.Namespace) -> int:
    plex = connect(args)
    sections = pick_sections(plex, args.library)
    if args.path and len(sections) != 1:
        raise PlexToolError("--path needs exactly one --library.")

    only_maintenance = (args.empty_trash or args.optimize or args.clean_bundles) and not (
        args.refresh or args.path)
    for section in sections:
        if args.empty_trash:
            section.emptyTrash()
            print(f"Emptied trash: {section.title}")
        if args.refresh:
            section.refresh()
            print(f"Refreshing metadata: {section.title}")
        elif not only_maintenance:
            section.update(path=args.path)
            print(f"Scanning: {section.title}" + (f" ({args.path})" if args.path else ""))
    if args.optimize:
        plex.library.optimize()
        print("Database optimization started.")
    if args.clean_bundles:
        plex.library.cleanBundles()
        print("Bundle clean-up started.")

    if args.wait:
        wait_for_scans(plex, [s.title for s in sections])
    return 0


def wait_for_scans(plex, titles: list[str], interval: float = 3.0) -> None:
    """Poll until none of the named libraries report that they are refreshing."""
    # A scan may take a moment to show up as 'refreshing'.
    time.sleep(interval)
    while True:
        busy = [s.title for s in plex.library.sections() if s.title in titles and s.refreshing]
        if not busy:
            print(paint("Scans finished.", "green"))
            return
        print(f"  still working: {', '.join(busy)}")
        time.sleep(interval)
