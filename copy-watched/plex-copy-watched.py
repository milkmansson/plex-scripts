#!/usr/bin/env python3
"""
plex-copy-watched.py
--------------------
Copy watched state (movies + TV episodes) from one Plex account to another,
using the Plex API only — no direct database access required.

Both accounts must already have access to the server (shared friends).
The script connects as the server admin, then switches user context for each
account so that watched state is read/written per-user via the API.

Usage:
    python3 plex-copy-watched.py [options]

    --server       URL of your Plex Media Server  (default: http://localhost:32400)
    --admin-token  Server admin token (from Plex Web > Account > Authorized Devices)
    --src-user     Source account email/username
    --src-pass     Source account password
    --dst-user     Destination account email/username
    --dst-pass     Destination account password
    --commit       Apply changes (default is dry-run mode)
    --movies       Transfer movies only
    --shows        Transfer TV episodes only
                   (if neither --movies nor --shows is given, both are transferred)

Examples:
    # Dry run — see what would be marked watched without changing anything:
    python3 plex-copy-watched.py \\
        --server http://127.0.0.1:32400 \\
        --admin-token xxxxxxxxxxxxxxxxxxxx \\
        --src-user alice@example.com --src-pass hunter2 \\
        --dst-user bob@example.com   --dst-pass letmein

    # Apply the changes:
    python3 plex-copy-watched.py \\
        --server http://127.0.0.1:32400 \\
        --admin-token xxxxxxxxxxxxxxxxxxxx \\
        --src-user alice@example.com --src-pass hunter2 \\
        --dst-user bob@example.com   --dst-pass letmein \\
        --commit

Requirements:
    pip install plexapi
"""

import argparse
import sys
from plexapi.server import PlexServer
from plexapi.myplex import MyPlexAccount
from plexapi.exceptions import BadRequest, NotFound, Unauthorized


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def login(username: str, password: str, label: str) -> MyPlexAccount:
    """Authenticate against plex.tv and return a MyPlexAccount."""
    print(f"  Authenticating {label} ({username}) …")
    try:
        account = MyPlexAccount(username, password)
        print(f"  OK — logged in as '{account.friendlyName or account.username}'")
        return account
    except Unauthorized:
        print(f"  ERROR: Authentication failed for {label} ({username}). "
              "Check username/password.")
        sys.exit(1)
    except BadRequest as e:
        print(f"  ERROR: Bad request while authenticating {label}: {e}")
        sys.exit(1)


def connect_admin(server_url: str, admin_token: str) -> PlexServer:
    """Connect to the Plex server as the admin account."""
    print(f"  Connecting as admin to {server_url} …")
    try:
        admin = PlexServer(server_url, admin_token)
        print(f"  OK — connected to '{admin.friendlyName}'")
        return admin
    except Unauthorized:
        print("  ERROR: Admin token was rejected (401). Check --admin-token.")
        sys.exit(1)
    except Exception as e:
        print(f"  ERROR: Could not connect to server: {e}")
        sys.exit(1)


def switch_to_user(admin_server: PlexServer, account: MyPlexAccount, label: str) -> PlexServer:
    """
    Use the admin server connection to switch into the given user's context.
    Tries matching by email first, then by username.
    """
    # switchUser accepts username, email, or user id
    for identifier in [account.email, account.username]:
        if not identifier:
            continue
        try:
            user_server = admin_server.switchUser(identifier)
            print(f"  OK — switched to {label} ('{account.friendlyName or account.username}')")
            return user_server
        except NotFound:
            continue
        except Exception as e:
            print(f"  ERROR: Could not switch to {label} ({identifier}): {e}")
            sys.exit(1)

    print(f"  ERROR: {label} ({account.email or account.username}) not found as a user on "
          "this server. Make sure they have been shared this server in Plex.")
    sys.exit(1)


def get_watched_movies(server: PlexServer) -> dict:
    """Return {guid: title} for every watched movie (as seen by this user).
    Uses a flat paginated search so the count is accurate regardless of library size."""
    watched = {}
    for section in server.library.sections():
        if section.type != "movie":
            continue
        for movie in section.search(libtype="movie", filters={"unwatched": False}):
            watched[movie.guid] = movie.title
    return watched


def get_watched_episodes(server: PlexServer) -> dict:
    """Return {guid: label} for every watched episode (as seen by this user).
    Uses a flat paginated libtype search rather than show→season→episode nesting,
    so the count accurately reflects the true total across all pages."""
    watched = {}
    for section in server.library.sections():
        if section.type != "show":
            continue
        for episode in section.search(libtype="episode", filters={"unwatched": False}):
            label = (f"{episode.grandparentTitle} "
                     f"S{episode.seasonNumber:02d}E{episode.episodeNumber:02d}")
            watched[episode.guid] = label
    return watched


def mark_movies_watched(src_watched: dict, dst_server: PlexServer, commit: bool) -> int:
    """Mark unwatched movies on dst_server as watched, where the source has seen them."""
    print(f"\n{'MOVIES':=<60}")
    to_mark = []

    for section in dst_server.library.sections():
        if section.type != "movie":
            continue
        for movie in section.search(libtype="movie"):
            if movie.guid in src_watched and not movie.isWatched:
                to_mark.append(movie)

    if not to_mark:
        print("  Nothing to do — all source movies already watched by destination user.")
        return 0

    for movie in to_mark:
        if commit:
            movie.markPlayed()
            print(f"  [MARKED]  {movie.title}")
        else:
            print(f"  [DRY RUN] Would mark watched: {movie.title}")

    return len(to_mark)


def mark_episodes_watched(src_watched: dict, dst_server: PlexServer, commit: bool) -> int:
    """Mark unwatched episodes on dst_server as watched, where the source has seen them."""
    print(f"\n{'TV EPISODES':=<60}")
    to_mark = []

    for section in dst_server.library.sections():
        if section.type != "show":
            continue
        for episode in section.search(libtype="episode"):
            if episode.guid in src_watched and not episode.isWatched:
                to_mark.append(episode)

    if not to_mark:
        print("  Nothing to do — all source episodes already watched by destination user.")
        return 0

    for episode in to_mark:
        label = (f"{episode.grandparentTitle} "
                 f"S{episode.seasonNumber:02d}E{episode.episodeNumber:02d}"
                 f" — {episode.title}")
        if commit:
            episode.markPlayed()
            print(f"  [MARKED]  {label}")
        else:
            print(f"  [DRY RUN] Would mark watched: {label}")

    return len(to_mark)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Copy Plex watched state from one account to another via the API.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--server",      default="http://localhost:32400",
                        help="Plex Media Server URL (default: http://localhost:32400)")
    parser.add_argument("--admin-token", required=True,
                        help="Server admin X-Plex-Token")
    parser.add_argument("--src-user",    required=True, help="Source account username/email")
    parser.add_argument("--src-pass",    required=True, help="Source account password")
    parser.add_argument("--dst-user",    required=True, help="Destination account username/email")
    parser.add_argument("--dst-pass",    required=True, help="Destination account password")
    parser.add_argument("--commit",      action="store_true",
                        help="Apply changes (omit for dry run)")
    parser.add_argument("--movies",      action="store_true", help="Transfer movies only")
    parser.add_argument("--shows",       action="store_true", help="Transfer TV shows only")
    args = parser.parse_args()

    do_movies = args.movies or not (args.movies or args.shows)
    do_shows  = args.shows  or not (args.movies or args.shows)

    mode = "COMMIT" if args.commit else "DRY RUN"
    print(f"\n{'='*60}")
    print(f"  plex-copy-watched  [{mode}]")
    print(f"  Server : {args.server}")
    print(f"  Source : {args.src_user}")
    print(f"  Dest   : {args.dst_user}")
    scope = " + ".join(filter(None, ["movies" if do_movies else "", "TV episodes" if do_shows else ""]))
    print(f"  Scope  : {scope}")
    if not args.commit:
        print("\n  *** DRY RUN — no changes will be made ***")
        print("  *** Pass --commit to apply changes    ***")
    print(f"{'='*60}\n")

    # --- Authenticate both accounts against plex.tv ---
    print("Authenticating with plex.tv …")
    src_account = login(args.src_user, args.src_pass, "source")
    dst_account = login(args.dst_user, args.dst_pass, "destination")

    # --- Connect to the server as admin ---
    print("\nConnecting to Plex Media Server …")
    admin_server = connect_admin(args.server, args.admin_token)

    # --- Switch to each user's context via the admin connection ---
    print("\nSwitching user context …")
    src_server = switch_to_user(admin_server, src_account, "source")
    dst_server = switch_to_user(admin_server, dst_account, "destination")

    total_marked = 0

    # --- Movies ---
    if do_movies:
        print("\nReading source watched movies …")
        src_movies = get_watched_movies(src_server)
        print(f"  Source has watched {len(src_movies)} movie(s).")
        total_marked += mark_movies_watched(src_movies, dst_server, args.commit)

    # --- TV Episodes ---
    if do_shows:
        print("\nReading source watched episodes …")
        src_episodes = get_watched_episodes(src_server)
        print(f"  Source has watched {len(src_episodes)} episode(s).")
        total_marked += mark_episodes_watched(src_episodes, dst_server, args.commit)

    # --- Summary ---
    print(f"\n{'='*60}")
    if args.commit:
        print(f"  Done. {total_marked} item(s) marked as watched for destination user.")
    else:
        print(f"  Dry run complete. {total_marked} item(s) would be marked as watched.")
        print("  Re-run with --commit to apply.")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
