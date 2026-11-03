# plextool users

Shows who has access to the server, and invites, changes and removes people from the command line. It covers
the same ground as Plex's own [Managing Library Access](https://support.plex.tv/articles/201105738-creating-and-managing-server-shares/)
page, and asks the same questions as that page's invite wizard, as options. It needs the server owner's login, and
everything that changes anything is a preview until `--commit` is given.

Handy when:
- Someone needs access to a few libraries, and clicking through the invite wizard is slower than one command.
- It is unclear who has access, to what, and with which restrictions.
- A person's libraries, restrictions or downloads need changing, or their access removing.
- Invitations were sent and it is unknown which are still waiting.

```console
$ plextool users list
$ plextool users invite alice@example.com --libraries "Movies,TV Shows" --movies-rating G,PG
$ plextool users share alice --libraries all --downloads no
$ plextool users remove alice --server-access --commit
$ plextool users invites
$ plextool users cancel alice@example.com --commit
```

## users list

Everyone this server is shared with: how many libraries each can see, and their features and restrictions.
`--detail` also names the libraries (one more request per user). It ends with the number of invitations still
waiting. Read-only.

## users invite

Sends an invitation to share libraries on this server, to an email address or Plex username. Plex emails the
invitation, and it has no effect until the person accepts it. A person needs no Plex account to receive one; they
can make a free account when accepting. See Plex's [Friends/People](https://support.plex.tv/articles/friends/)
page: sharing libraries and being friends are separate things, and this command only does the sharing.

`--libraries` is required, so sharing everything is always a choice (`--libraries all`). The other options
are the questions the Plex wizard asks.

| Option | Meaning |
| --- | --- |
| `--libraries NAMES` | `all`, or library names separated by commas. Names are not case sensitive. |
| `--movies-rating`, `--tv-rating` | Restrict by content rating, such as `G,PG`. A value starting with `!` is excluded instead of allowed: `--movies-rating "G,!R"`. |
| `--movies-label`, `--tv-label`, `--music-label` | Restrict by label, with the same `!` form. |
| `--downloads`, `--camera-upload`, `--channels` | `yes` or `no`. All three are off for an invitation unless given. |
| `--commit` | Send it. Without it, the command only shows what would be granted. |

Plex says that custom restrictions need Plex Pass on the owner's account (see
[Restrictions on Library Access](https://support.plex.tv/articles/204232573-restricting-the-shares/)). If Plex refuses
a request that used them, the message says so.

An invitation is refused if the person already has access (`users share` changes that), or if an invitation to
them is already waiting (`users cancel` cancels it first).

## users share

Changes what someone who already has access can see or do. Only what is named is changed. It takes the same
options as `invite`, except that `--libraries` is optional, and adds `--clear-restrictions`, which removes every
restriction. Giving `--libraries` to someone with no access grants it, and the preview says so.

## users remove

Takes access away, and says which kind. One of these is required:

| Option | Meaning |
| --- | --- |
| `--server-access` | Take away their access to this server. They stay a friend. |
| `--friend` | Remove them as a friend, which ends access to everything the owner shared with them. |

The preview lists what they lose, and any tokens made for them with
[`plextool token new --ro`](token.md), which stop working. If the person also shares a server with the owner,
removing them as a friend may affect that too.

The owner cannot be removed. Members of a Plex Home are removed in Plex, under Plex Home settings (see
[Creating a Plex Home](https://support.plex.tv/articles/204234323-creating-a-plex-home/) and
[Managed Accounts](https://support.plex.tv/articles/203948776-managed-users/)), not here.

## users invites and users cancel

`invites` lists the invitations sent from this account that nobody has accepted yet, with the date each was sent
and what each grants. Plex's reply for an invitation holds only the server name and how many libraries it covers,
so that is always shown. For the rest, plextool looks in this order:

1. Plex's shared list. It asks Plex for the list of what is shared on the server, which is the list behind the
   web app's Manage Library Access page. If that has an entry for the invitation, the libraries, features and
   restrictions in it are shown, marked `(from Plex)`. This works for any invitation, however it was sent.
2. plextool's own record. For an invitation sent with `users invite`, plextool also kept what it granted. If
   Plex's list had nothing, that is shown instead, marked `(as recorded when invited)`. The record is a small
   file, `invites.json`, in the plextool config folder. It holds no secrets, and an entry is dropped once its
   invitation is accepted or cancelled.
3. Neither. Only the count is shown, with a note that Plex does not say more.

The shared list is also what holds each person's access token, so it is never printed. `--raw` prints Plex's reply for
each invitation, and the matching entry from the shared list with its tokens removed, so that what Plex returns
can be seen. If the list has nothing for an invitation, `--raw` says so.

`cancel` cancels one, by the email address or username it was sent to. It is a preview unless `--commit` is given.

## Not covered

Plex Home members and managed users are not created or edited here. The web app asks for details, such as a
restriction profile and a PIN, that this command cannot set.
