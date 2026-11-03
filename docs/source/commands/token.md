# plextool token

Makes tokens for other programs, such as a Plex MCP server or a backup script, so those
programs do not have to share the saved login. It also lists what was made and revokes it.

- `token new` makes a token.
- `token list` shows the apps authorised on the Plex account, the tokens made, whether each is still active, and who has access to the server.
- `token revoke` removes one.

Handy when:
- A tool such as plex_mcp_server asks for `PLEX_URL` and `PLEX_TOKEN`, and the main login should stay out of it.
- A script needs its own token, so it can be cancelled without signing out everywhere else.
- A tool only needs to see certain libraries, and a shared user's token fits better than full access.
- It is unclear which tokens exist, or which are still in use, and old ones need cancelling.

```console
$ plextool token new --rw --name mcp-server --file ~/.plex-mcp.env
$ plextool token new --ro --user alice --file ~/.plex-reader.env
$ plextool token list
$ plextool token revoke mcp-server --delete-file --commit
```

## token new

Two things must always be said, and nothing is guessed: what the token is for (`--rw` or
`--ro`), and where it goes (`--file` or `--print`).

### Choosing what it is for

Exactly one of these is required.

| Option | What is made |
| --- | --- |
| `--rw` | A new sign-in to the account itself, approved in a browser the same way as [`plextool auth login`](auth.md). The token has the same power as the account. It is listed under [Authorized Devices](https://support.plex.tv/articles/115007577087-devices/) as `plextool/NAME`, so it can be revoked on its own. Needs `--name`. |
| `--ro` | The token of a shared (or managed) user (`--user NAME`). It can only see what is shared with that user, and Plex lets only the server owner delete media. |

Plex has no read-only token. A `--ro` token is a different person's access, and that user
can still change their own watched state and playlists, and anything else Plex allows them.
The command lists the libraries the token can see and says this again when it finishes.

`--ro` is refused for the server owner, since the owner's access cannot be limited. Use
`--rw` for a separate token, or name a shared user. A user to hold the narrower access can be
invited with [`plextool users invite`](users.md), or in Plex (Settings, then Users and Sharing), with only the wanted
libraries shared.

### Plex's roles

Plex has no scopes or permission levels for tokens. A token is as powerful as the account
it belongs to. The roles Plex names are:

| Role | Meaning |
| --- | --- |
| Server owner (admin) | The account that claimed the server. Can do everything, and is the only account that can delete media, and only when the server's ["Allow media deletion"](https://support.plex.tv/articles/200289526-library/) setting is on. |
| Home Admin | The account that owns a Plex Home. Usually the same as the owner. Only it can give a managed user access to server content. |
| Managed user | A profile inside a Plex Home, with no separate login and a preset restriction profile. |
| Shared user | A separate Plex account that has been given access to specific libraries. With Plex Pass on the owner's account, the access can also be limited by content rating and label. |

`--rw` makes a token for the owner's account. `--ro` makes a token for a shared or managed user.
See Plex's articles on [restrictions on library access](https://support.plex.tv/articles/204232573-restricting-the-shares/),
[managed accounts](https://support.plex.tv/articles/203948776-managed-users/) and the
[consequences of being in a Plex Home](https://support.plex.tv/articles/203960236-consequences-of-being-in-a-plex-home/).

### Choosing where it goes

Exactly one of these is required.

| Option | What happens |
| --- | --- |
| `--file PATH` | Writes `PLEX_URL` and `PLEX_TOKEN` to an env file that only its owner can read (mode `0600`). Refuses to replace an existing file unless `--force` is given. |
| `--print` | Prints only the token on standard output. Everything else goes to standard error, so the output can be captured safely. |

`PLEX_URL` comes from the server already chosen (`--base-url`, `$PLEX_URL` or `plextool server use`).
Without one, the file holds only the token.

### Other options

| Option | Meaning |
| --- | --- |
| `--name LABEL` | What the token is for. Names the entry in Authorized Devices. Required for `--rw`. |
| `--user NAME` | The user whose token to make. Only for `--ro`. |
| `--force` | Replace the file if it exists. |
| `--timeout SECONDS` | How long to wait for the browser approval (`--rw`; default 300). |

## token list

Shows three things: every app and device authorised on the Plex account, the tokens made with `token new`,
and who has access to the server.

```console
$ plextool token list
Apps and devices authorised on the Plex account
  3895d339  plextool/mcp-server               plextool              last seen 2026-11-03 10:40  token for another tool: mcp-server
  a6e9e891  plextool on host                  plextool              last seen 2026-11-03 09:12  this login
  d00d0002  Pixel 8                           Plex for Android      last seen 2026-11-03 08:30
  c0ffee01  Living Room TV                    Plex for LG           last seen 2026-11-02 21:05

Tokens made with 'plextool token'
  mcp-server           read/write  3895d339  created 2026-10-01 09:00  last seen 2026-11-03 10:40  active
                       file /home/me/.plex-mcp.env
  alice-reader         shared user alice          made 2026-11-02  user still has access

Users with access to this server
  alice                   shared user   3 libraries  (a token was made with 'plextool token')
  bob                     shared user   all libraries
```

The first section lists everything authorised on the account, which Plex calls
[Authorized Devices](https://support.plex.tv/articles/115007577087-devices/): phones, TVs, browsers and so on,
most recently used first. plextool's own entries are marked. `this login` is the saved login of this computer,
`plextool sign-in` is any other sign-in made with `auth login`, and `token for another tool` is a token made with
`token new --rw`. `--plextool` limits the list to plextool's entries.

The second section covers the tokens made with `token new`. Each `--rw` token is checked against the account and
shown as active, or as no longer on the account if it has been revoked or removed. Each `--ro` token shows whether
its user still has access to the server.

The last section lists the users this server is shared with, how many libraries each has, and which of them has a
token made with `plextool token`. It needs a connection to the server. If that fails the section is skipped, and
`--no-users` skips it on purpose.

Plex cannot list the temporary tokens a server makes, or a token copied out of an app, so those never
appear. A server may also keep accepting a revoked token for a short while.

## token revoke

```console
$ plextool token revoke mcp-server                       # preview
$ plextool token revoke mcp-server --commit
$ plextool token revoke mcp-server --delete-file --commit
$ plextool token revoke 3895d339 --commit                # by the start of the device ID
```

Removes the Authorized Devices entry of a `--rw` token, so plex.tv rejects it. Like the other commands that
change things, it is a dry run unless `--commit` is passed. Only tokens made with `token new` are removed
here. Plain plextool sign-ins and other Plex apps are not removed here. Giving the ID of one is refused with a message
saying what it is and which command removes it ([`plextool auth revoke`](auth.md) for sign-ins,
[`plextool devices remove`](devices.md) for other apps).

| Option | Meaning |
| --- | --- |
| `--delete-file` | Also delete the file the token was written to. |
| `--forget` | For a `--ro` token, drop plextool's record of it. The token itself keeps working. |
| `--commit` | Actually remove it. |

A `--ro` token has no device of its own to remove. It is a user's access, so it stops working when that
user's access to the server is removed in Plex. The command says so, and shows which user.

As with [`plextool auth revoke`](auth.md), removing the device blocks the token at plex.tv straight away, but
a Plex server can keep accepting it for a while.

## The record

`token new` keeps a record of what it made in `tokens.json` in the plextool config folder (see
[where things are kept](auth.md#where-things-are-kept)). It holds names, dates, user names and file paths, and
never a token. It is what lets `token list` show `--ro` tokens and file paths. If it is lost, `--rw` tokens
still show, because their device names are on the Plex account. `auth wipe` does not delete it, since it is
the only way to find a `--ro` token again.
