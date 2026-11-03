"""users: see who has access to the server, and invite, change and remove them."""

from __future__ import annotations

import argparse
import json
import sys
import xml.etree.ElementTree as ET
from datetime import date, datetime

from plexapi.exceptions import BadRequest, NotFound, Unauthorized
from requests.exceptions import RequestException

from . import auth
from .common import (
    PlexToolError,
    add_command,
    add_connection_args,
    connect,
    paint,
    plex_account,
    plural,
    resolve_token,
)
from .tokens import library_count, user_kind

FILTER_KEYS = {"movies": "filterMovies", "tv": "filterTelevision", "music": "filterMusic"}
PLEX_PASS = ("Custom restrictions, and adding a regular account to a Plex Home, need Plex Pass on the owner's "
             "account.")


# ---------------------------------------------------------------------------
# What to grant
# ---------------------------------------------------------------------------

def split_list(text: str) -> list[str]:
    return [part.strip() for part in text.split(",") if part.strip()]


def pick_libraries(plex, text: str) -> list:
    """The library sections named by --libraries: 'all', or a comma-separated list of names."""
    sections = plex.library.sections()
    if text.strip().lower() == "all":
        return list(sections)
    by_name = {s.title.lower(): s for s in sections}
    chosen = []
    for name in split_list(text):
        if name.lower() not in by_name:
            raise PlexToolError(f"No library called '{name}'. Available: {', '.join(s.title for s in sections)}. "
                                "Use --libraries all for every library.")
        if by_name[name.lower()] not in chosen:
            chosen.append(by_name[name.lower()])
    if not chosen:
        raise PlexToolError("--libraries needs 'all' or at least one library name.")
    return chosen


def restriction(rating: str | None, label: str | None) -> dict | None:
    """A Plex restriction from comma-separated lists; a value starting with ! is excluded, not allowed."""
    found = {}
    for key, text in (("contentRating", rating), ("label", label)):
        values = split_list(text or "")
        allowed = [v for v in values if not v.startswith("!")]
        excluded = [v[1:].strip() for v in values if v.startswith("!") and v[1:].strip()]
        if allowed:
            found[key] = allowed
        if excluded:
            found[key + "!"] = excluded
    return found or None


def build_filters(args: argparse.Namespace) -> dict:
    """{plexapi argument: restriction dict}, for the kinds of media the options mention."""
    given = {
        "filterMovies": restriction(args.movies_rating, args.movies_label),
        "filterTelevision": restriction(args.tv_rating, args.tv_label),
        "filterMusic": restriction(None, args.music_label),
    }
    if getattr(args, "clear_restrictions", False):
        if any(given.values()):
            raise PlexToolError("--clear-restrictions cannot be combined with restriction options.")
        return {name: {} for name in given}
    return {name: value for name, value in given.items() if value}


def build_features(args: argparse.Namespace) -> dict:
    """{plexapi argument: bool} for the features the options mention (yes or no)."""
    given = {"allowSync": args.downloads, "allowCameraUpload": args.camera_upload, "allowChannels": args.channels}
    return {name: value == "yes" for name, value in given.items() if value}


def describe_grant(libraries: list | None, filters: dict, features: dict) -> list[str]:
    lines = []
    if libraries is not None:
        lines.append("libraries: " + (", ".join(s.title for s in libraries) or "none"))
    names = {"filterMovies": "movies", "filterTelevision": "TV", "filterMusic": "music"}
    for arg, kind in names.items():
        if arg in filters:
            value = filters[arg]
            text = "; ".join(f"{k.replace('!', ' not')} {', '.join(v)}" for k, v in value.items()) or "none (cleared)"
            lines.append(f"{kind} restrictions: {text}")
    labels = {"allowSync": "downloads", "allowCameraUpload": "camera upload", "allowChannels": "channels"}
    for arg, label in labels.items():
        if arg in features:
            lines.append(f"{label}: {'allowed' if features[arg] else 'not allowed'}")
    return lines


# ---------------------------------------------------------------------------
# Finding people
# ---------------------------------------------------------------------------

def own_names(account) -> set[str]:
    return {n.lower() for n in (account.username, account.email, account.title) if n}


def find_user(account, name: str):
    """The account's user matching a username, email or name, never the owner."""
    if name.lower() in own_names(account):
        raise PlexToolError(f"'{name}' is the account that owns this server, which cannot be changed here.")
    try:
        return account.user(name)
    except NotFound:
        raise PlexToolError(f"'{name}' is not a user on this account. 'plextool users list' shows them; "
                            "'plextool users invite' adds one.") from None


def server_share(user, machine_id: str):
    """The user's access to this server, or None."""
    return next((s for s in user.servers if s.machineIdentifier == machine_id and not s.pending), None)


def user_name(user) -> str:
    return user.title or user.username or user.email or "?"


def owner_account(args: argparse.Namespace):
    """The owner's plex.tv account, without contacting the server."""
    args.token, _ = resolve_token(args)
    return plex_account(args)


def sent_invites(account) -> list:
    return account.pendingInvites(includeSent=True, includeReceived=False)


def invite_matches(invite, name: str) -> bool:
    low = name.lower()
    return low in {(invite.email or "").lower(), (invite.username or "").lower(),
                   (invite.friendlyName or "").lower()}


def refused(error: Exception, used_restrictions: bool = False) -> PlexToolError:
    """A short explanation for a request Plex turned down."""
    hint = f" {PLEX_PASS}" if used_restrictions else ""
    if isinstance(error, Unauthorized):
        return PlexToolError("Plex rejected the token. This needs the server owner's login." + hint)
    return PlexToolError(f"Plex did not accept that: {error}.{hint}")


def finish(args: argparse.Namespace, lines: list[str], note: str | None = None) -> bool:
    """Print the preview; return True if the change should now be made."""
    for line in lines:
        print(f"  {line}")
    if note:
        print(f"\n{note}")
    if not args.commit:
        print("\nDry run only. Re-run with --commit to do it.")
        return False
    return True


# ---------------------------------------------------------------------------
# list, invites
# ---------------------------------------------------------------------------

def feature_text(user) -> str:
    flags = [name for name, on in (("downloads", user.allowSync), ("camera upload", user.allowCameraUpload),
                                   ("channels", user.allowChannels)) if on]
    return ", ".join(flags) or "none"


def restriction_text(user) -> str:
    parts = [f"{kind}: {value}" for kind, value in (("movies", user.filterMovies), ("TV", user.filterTelevision),
                                                    ("music", user.filterMusic)) if value]
    return "; ".join(parts) or "none"


def run_list(args: argparse.Namespace) -> int:
    plex = connect(args)
    account = plex_account(args)
    machine_id = plex.machineIdentifier
    print(paint(f"Users with access to {plex.friendlyName}", "cyan"))
    shown = 0
    for user in sorted(account.users(), key=lambda u: user_name(u).lower()):
        share = server_share(user, machine_id)
        if not share:
            continue
        shown += 1
        print(f"  {user_name(user):<24}{user_kind(user):<14}{library_count(share)}")
        print(f"  {'':<24}features: {feature_text(user)};  restrictions: {restriction_text(user)}")
        if args.detail:
            try:
                names = [s.title for s in share.sections() if s.shared]
            except (RequestException, BadRequest, NotFound) as e:
                names = [f"(could not read: {e})"]
            print(f"  {'':<24}shared: {', '.join(names) or 'none'}")
    if not shown:
        print("  nobody else")
    waiting = sent_invites(account)
    print(f"\n{plural(len(waiting), 'invitation')} waiting for a reply ('plextool users invites' lists them).")
    return 0


INVITES_FILE = "invites.json"


def load_invites() -> list[dict]:
    """What plextool granted in the invitations it sent. Plex itself only says the server and a library count."""
    try:
        return json.loads((auth.config_dir() / INVITES_FILE).read_text(encoding="utf-8")).get("invites", [])
    except (FileNotFoundError, ValueError, AttributeError, OSError):
        return []


def save_invites(entries: list[dict]) -> None:
    auth.write_private(auth.config_dir() / INVITES_FILE, json.dumps({"invites": entries}, indent=2).encode())


SECRET_ATTRS = ("accessToken", "token")


def shared_servers(account, machine_id: str) -> list:
    """Plex's own list of what is shared on this server, which also holds invitations not yet accepted.

    This is the list behind the web app's Manage Library Access page. Returns [] if Plex will not give it.
    """
    try:
        root = account.query(account.FRIENDINVITE.format(machineId=machine_id))
    except (RequestException, BadRequest, Unauthorized, NotFound):
        return []
    return list(root) if root is not None else []


def entry_for(invite, entries: list):
    """The shared-server entry that belongs to an invitation, matched by email or username."""
    wanted = {v.lower() for v in (invite.email, invite.username) if v}
    for entry in entries:
        values = {v.lower() for key, v in entry.attrib.items()
                  if key.lower() in ("invitedemail", "email", "username", "invitedusername") and v}
        if wanted & values:
            return entry
    return None


def without_secrets(entry):
    """A copy of an XML element with the access tokens removed, safe to print."""
    copy = ET.fromstring(ET.tostring(entry))
    for element in copy.iter():
        for key in SECRET_ATTRS:
            element.attrib.pop(key, None)
    return copy


def plex_lines(entry) -> list[str]:
    """What Plex's shared list says an invitation grants: libraries, features, restrictions."""
    lines = []
    libraries = [s.get("title") for s in entry.iter("Section") if s.get("shared") == "1" and s.get("title")]
    if libraries:
        lines.append(f"libraries: {', '.join(libraries)}")
    attrs = entry.attrib
    if any(k in attrs for k in ("allowSync", "allowCameraUpload", "allowChannels")):
        on = [label for key, label in (("allowSync", "downloads"), ("allowCameraUpload", "camera upload"),
                                       ("allowChannels", "channels")) if attrs.get(key) == "1"]
        lines.append("features: " + (", ".join(on) or "none"))
    restrictions = [f"{kind}: {attrs[key]}" for kind, key in (("movies", "filterMovies"), ("TV", "filterTelevision"),
                                                              ("music", "filterMusic")) if attrs.get(key)]
    if restrictions:
        lines.append("restrictions: " + "; ".join(restrictions))
    return lines


def invite_details(invite, recorded: dict | None, entry=None) -> list[str]:
    """What an invitation grants: the server and library count from the invitation, then the libraries and settings
    from Plex's shared list if it has them, else what plextool recorded when it sent the invitation."""
    lines = [f"{share.name or 'server'}: {library_count(share)}" for share in getattr(invite, "servers", None) or []]
    from_plex = plex_lines(entry) if entry is not None else []
    if from_plex:
        lines += [f"{line}  (from Plex)" for line in from_plex]
    elif recorded:
        lines += [f"{line}  (as recorded when invited)" for line in recorded["lines"]]
    elif lines:
        lines.append("(Plex does not say which libraries or settings; only the count)")
    return lines


def run_invites(args: argparse.Namespace) -> int:
    machine_id = None
    try:
        machine_id = connect(args).machineIdentifier
        account = plex_account(args)
    except PlexToolError as e:
        print(f"(Could not reach the server, so only the invitations themselves are shown: {e})", file=sys.stderr)
        account = owner_account(args)
    invites = sent_invites(account)
    entries = shared_servers(account, machine_id) if machine_id else []
    if args.raw:
        for invite in invites:
            ET.indent(invite._data)
            print(ET.tostring(invite._data, encoding="unicode"))
            entry = entry_for(invite, entries)
            if entry is None:
                print(f"<!-- the server's shared list ({plural(len(entries), 'entry').replace('entrys', 'entries')}) "
                      "has nothing for this invitation -->")
            else:
                clean = without_secrets(entry)
                ET.indent(clean)
                print(ET.tostring(clean, encoding="unicode"))
        return 0
    records = load_invites()
    print(paint("Invitations sent and not yet accepted", "cyan"))
    for invite in sorted(invites, key=lambda i: i.createdAt or datetime.min):
        what = "library access" if invite.server else ("home" if invite.home else "friend")
        sent = f"{invite.createdAt:%Y-%m-%d}" if invite.createdAt else "?"
        print(f"  {invite.email or invite.username or invite.friendlyName or '?':<36}{what:<16}sent {sent}")
        recorded = next((r for r in records if invite_matches(invite, r["who"])), None)
        for line in invite_details(invite, recorded, entry_for(invite, entries)):
            print(f"  {'':<36}{line}")
    if not invites:
        print("  none")
    kept = [r for r in records if any(invite_matches(i, r["who"]) for i in invites)]
    if len(kept) != len(records):   # accepted or cancelled since: nothing left to remember
        save_invites(kept)
    print("\n'plextool users cancel NAME_OR_EMAIL' cancels one. '--raw' prints exactly what Plex returns.")
    return 0


# ---------------------------------------------------------------------------
# invite, share, remove, cancel
# ---------------------------------------------------------------------------

def run_invite(args: argparse.Namespace) -> int:
    plex = connect(args)
    account = plex_account(args)
    libraries = pick_libraries(plex, args.libraries)
    filters, features = build_filters(args), build_features(args)
    who = args.who
    if who.lower() in own_names(account):
        raise PlexToolError("That is the account that owns this server.")
    for user in account.users():
        names = {(user.email or "").lower(), (user.username or "").lower(), (user.title or "").lower()}
        if who.lower() in names and server_share(user, plex.machineIdentifier):
            raise PlexToolError(f"{user_name(user)} already has access to this server. "
                                f"'plextool users share {who}' changes what they can see.")
    if any(invite_matches(i, who) for i in sent_invites(account)):
        raise PlexToolError(f"An invitation to {who} is already waiting. "
                            f"'plextool users cancel {who}' cancels it first.")
    verb = "Inviting" if args.commit else "Would invite"
    print(f"{verb} {who} to {plex.friendlyName}:")
    if not finish(args, describe_grant(libraries, filters, {"allowSync": False, "allowCameraUpload": False,
                                                               "allowChannels": False, **features}),
                  "Plex sends them an email. They have to accept it before they can see anything."):
        return 0
    try:
        account.inviteFriend(who, plex, sections=[s.title for s in libraries],
                             **{"allowSync": False, "allowCameraUpload": False, "allowChannels": False,
                                **features, **filters})
    except (BadRequest, Unauthorized, NotFound, RequestException) as e:
        raise refused(e, bool(filters)) from None
    save_invites([r for r in load_invites() if r["who"].lower() != who.lower()] +
                 [{"who": who, "server": plex.friendlyName, "created": date.today().isoformat(),
                   "lines": describe_grant(libraries, filters, {"allowSync": False, "allowCameraUpload": False,
                                                                   "allowChannels": False, **features})}])
    print(paint(f"Invited {who}.", "green") + " 'plextool users invites' shows it until it is accepted.")
    return 0


def run_share(args: argparse.Namespace) -> int:
    plex = connect(args)
    account = plex_account(args)
    user = find_user(account, args.who)
    libraries = pick_libraries(plex, args.libraries) if args.libraries else None
    filters, features = build_filters(args), build_features(args)
    if libraries is None and not filters and not features:
        raise PlexToolError("Say what to change: --libraries, a restriction option, --clear-restrictions, "
                            "--downloads, --camera-upload or --channels.")
    has_access = server_share(user, plex.machineIdentifier) is not None
    if not has_access and libraries is None:
        raise PlexToolError(f"{user_name(user)} has no access to this server yet. Say which libraries with "
                            "--libraries, or use 'plextool users invite'.")
    verb = "Changing" if args.commit else "Would change"
    print(f"{verb} what {user_name(user)} can do on {plex.friendlyName}:")
    note = None if has_access else "They have no access to this server yet, so this grants it."
    if not finish(args, describe_grant(libraries, filters, features), note):
        return 0
    try:
        account.updateFriend(user, plex, sections=[s.title for s in libraries] if libraries else None,
                             **features, **filters)
    except (BadRequest, Unauthorized, NotFound, RequestException) as e:
        raise refused(e, bool(filters)) from None
    print(paint(f"Updated {user_name(user)}.", "green"))
    return 0


def recorded_tokens(name: str) -> list[dict]:
    """Tokens made with 'plextool token new --ro' for this user."""
    from .tokens import load_record
    return [e for e in load_record() if e.get("access") == "ro" and e.get("user", "").lower() == name.lower()]


def run_remove(args: argparse.Namespace) -> int:
    plex = connect(args)
    account = plex_account(args)
    user = find_user(account, args.who)
    share = server_share(user, plex.machineIdentifier)
    if args.friend and getattr(user, "home", False):
        raise PlexToolError(f"{user_name(user)} is in the Plex Home. Home members are removed in Plex, under "
                            "Plex Home settings, not here.")
    if args.server_access and not share:
        raise PlexToolError(f"{user_name(user)} has no access to {plex.friendlyName}.")
    verb = "Removing" if args.commit else "Would remove"
    if args.server_access:
        print(f"{verb} {user_name(user)}'s access to {plex.friendlyName}. They stay a friend.")
        lines = [f"loses: {library_count(share)}"]
    else:
        print(f"{verb} {user_name(user)} as a friend, which ends their access to every library shared with them.")
        lines = ["loses: access to every library shared with them"]
    tokens = recorded_tokens(user_name(user)) + recorded_tokens(user.username or "")
    if tokens:
        names = ", ".join(sorted({t["name"] for t in tokens}))
        lines.append(f"the --ro token(s) made for them ({names}) stop working")
    note = ("If this person also shares a server with you, removing them as a friend may affect that too."
            if args.friend else None)
    if not finish(args, lines, note):
        return 0
    try:
        if args.server_access:
            # plexapi needs a non-empty section list to find the share; removeSections then drops the whole share
            account.updateFriend(user, plex, sections=[plex.library.sections()[0].title], removeSections=True)
        else:
            account.removeFriend(user)
    except (BadRequest, Unauthorized, NotFound, RequestException) as e:
        raise refused(e) from None
    print(paint(f"Removed {user_name(user)}.", "green"))
    return 0


def run_cancel(args: argparse.Namespace) -> int:
    account = owner_account(args)
    hits = [i for i in sent_invites(account) if invite_matches(i, args.who)]
    if not hits:
        raise PlexToolError(f"No waiting invitation to '{args.who}'. 'plextool users invites' lists them.")
    if len(hits) > 1:
        raise PlexToolError(f"'{args.who}' matches {len(hits)} invitations; use the full email address.")
    invite = hits[0]
    label = invite.email or invite.username or invite.friendlyName
    verb = "Cancelling" if args.commit else "Would cancel"
    print(f"{verb} the invitation to {label}.")
    if not finish(args, []):
        return 0
    try:
        account.cancelInvite(invite)
    except (BadRequest, Unauthorized, NotFound, RequestException) as e:
        raise refused(e) from None
    save_invites([r for r in load_invites() if not invite_matches(invite, r["who"])])
    print(paint("Cancelled.", "green"))
    return 0


# ---------------------------------------------------------------------------
# Command
# ---------------------------------------------------------------------------

def add_grant_options(parser, *, for_invite: bool) -> None:
    parser.add_argument("--libraries", metavar="NAMES", required=for_invite,
                        help="the libraries to share: 'all', or names separated by commas" +
                             ("" if for_invite else " (leave out to keep what they have)"))
    for kind, rating in (("movies", "movies"), ("tv", "TV")):
        parser.add_argument(f"--{kind}-rating", metavar="RATINGS",
                            help=f"restrict {rating} by content rating, eg G,PG (a leading ! excludes: !R). "
                                 "Needs Plex Pass")
        parser.add_argument(f"--{kind}-label", metavar="LABELS",
                            help=f"restrict {rating} by label, eg kids (a leading ! excludes). Needs Plex Pass")
    parser.add_argument("--music-label", metavar="LABELS", help="restrict music by label. Needs Plex Pass")
    for option, what in (("downloads", "downloads (sync)"), ("camera-upload", "camera upload"),
                         ("channels", "channels")):
        parser.add_argument(f"--{option}", choices=("yes", "no"),
                            help=f"allow {what}" + (" (default: no)" if for_invite else ""))
    parser.add_argument("--commit", action="store_true", help="actually do it (default is a preview)")


def add_parser(subparsers) -> None:
    parser = add_command(
        subparsers, 'users',
        'see who has access, and invite, change and remove people',
        "Manage who can use the server, from the command line: 'list' shows who has access and what they "
        "can see, 'invite' shares libraries with someone by email or username, 'share' changes what "
        "someone can see, 'remove' takes access away, and 'invites' and 'cancel' deal with invitations not yet "
        "accepted. Needs the server owner's login. Everything that changes anything is a preview until "
        "--commit is given, and shows exactly what would be granted or lost.",
        ['plextool users list',
         'plextool users invite alice@example.com --libraries "Movies,TV Shows" --movies-rating G,PG',
         'plextool users share alice --libraries all --downloads no',
         'plextool users remove alice --server-access --commit',
         'plextool users cancel alice@example.com --commit'])
    sub = parser.add_subparsers(dest="action", metavar="action", required=True)

    lst = add_command(sub, 'list', 'list who has access to the server',
                      "Lists the users this server is shared with, how many libraries each can see, and their "
                      "features and restrictions. Read-only.",
                      ['plextool users list', 'plextool users list --detail'])
    add_connection_args(lst)
    lst.add_argument("--detail", action="store_true",
                     help="also name the libraries each user can see (one more request per user)")

    inv = add_command(
        sub, 'invite', 'share libraries with someone',
        "Sends an invitation to share libraries on this server, to an email address or Plex username. "
        "--libraries is required, so granting everything is always a choice ('all'). Restrictions and "
        "feature options are the ones the Plex web app asks about; downloads, camera upload and channels "
        "are off unless given. Plex emails the invitation, and it has no effect until the person accepts it.",
        ['plextool users invite alice@example.com --libraries Movies',
         'plextool users invite alice@example.com --libraries all --downloads yes --commit',
         'plextool users invite kid@example.com --libraries "Movies,TV Shows" --movies-rating G,PG --tv-rating TV-Y,TV-G'])
    add_connection_args(inv)
    inv.add_argument("who", metavar="EMAIL_OR_USERNAME", help="who to invite")
    add_grant_options(inv, for_invite=True)

    shr = add_command(
        sub, 'share', 'change what someone can see',
        "Changes the libraries, restrictions or features of someone who already has access (or grants access "
        "to someone with none, if --libraries is given). Only what is named is changed; --clear-restrictions "
        "removes all restrictions.",
        ['plextool users share alice --libraries "Movies"',
         'plextool users share alice --movies-rating G,PG --downloads no',
         'plextool users share alice --clear-restrictions --commit'])
    add_connection_args(shr)
    shr.add_argument("who", metavar="NAME", help="username, email or name, as 'users list' shows")
    add_grant_options(shr, for_invite=False)
    shr.add_argument("--clear-restrictions", action="store_true", help="remove every restriction")

    rem = add_command(
        sub, 'remove', 'take someone\'s access away',
        "Removes access, and says which kind: --server-access takes away their access to this server and leaves "
        "them a friend; --friend removes them as a friend, which ends access to everything shared with them. "
        "One of the two is required. The owner cannot be removed, and Plex Home members are removed in "
        "Plex.",
        ['plextool users remove alice --server-access', 'plextool users remove alice --friend --commit'])
    add_connection_args(rem)
    rem.add_argument("who", metavar="NAME", help="username, email or name, as 'users list' shows")
    which = rem.add_mutually_exclusive_group(required=True)
    which.add_argument("--server-access", action="store_true", help="take away access to this server only")
    which.add_argument("--friend", action="store_true", help="remove them as a friend altogether")
    rem.add_argument("--commit", action="store_true", help="actually remove them (default is a preview)")

    wait = add_command(sub, 'invites', 'list invitations not yet accepted',
                       "Lists the invitations sent from this account that nobody has accepted yet. Plex's reply for an "
                       "invitation only gives the server and a library count, so plextool also looks in Plex's list of "
                       "what is shared on the server for the libraries, features and restrictions, and falls back on "
                       "what it recorded when it sent the invitation. --raw prints Plex's replies, with tokens "
                       "removed. Read-only.",
                       ['plextool users invites', 'plextool users invites --raw'])
    add_connection_args(wait)
    wait.add_argument("--raw", action="store_true", help="print the reply from Plex for each invitation, unchanged")

    can = add_command(sub, 'cancel', 'cancel an invitation not yet accepted',
                      "Cancels a waiting invitation, by the email address or username it was sent to. "
                      "A preview unless --commit is given.",
                      ['plextool users cancel alice@example.com', 'plextool users cancel alice@example.com --commit'])
    add_connection_args(can)
    can.add_argument("who", metavar="EMAIL_OR_USERNAME", help="who the invitation went to")
    can.add_argument("--commit", action="store_true", help="actually cancel it")
    parser.set_defaults(run=run)


def run(args: argparse.Namespace) -> int:
    return {"list": run_list, "invite": run_invite, "share": run_share, "remove": run_remove,
            "invites": run_invites, "cancel": run_cancel}[args.action](args)
