# plextool auth

Sign in to Plex from the command line without finding or pasting a token, and
manage what gets saved on the computer.

Handy when:
- plextool is being set up for the first time and digging out a token by hand is not wanted.
- The machine has no browser. The link can be opened, or the QR code scanned, on another device.
- The devices signed in to the account need listing, and old ones removing.
- The machine is being handed over, and the saved login and keys should be wiped.

```console
$ plextool auth login
Signing in for a classic token: it never expires until you revoke it in your Plex account.

Open this link in a browser and sign in to Plex:

  https://app.plex.tv/auth/#!?clientID=...&code=...

(a QR code appears here too, if `segno` is installed)

Waiting for you to approve it...

Signed in with a classic token. Saved to /home/you/.config/plextool
This token does not expire. Revoke it in your Plex account under Authorized Devices ('plextool').
```

The first line says which type is being issued. Open the link on any device,
including a phone, and approve **plextool**. Every other command then uses
the saved login, so `--token` can be left off.

## Which type of login?

Both types use the same browser sign-in (Plex OAuth). What differs is the
token that comes back, which `--type` selects:

| | `--type token` (default) | `--type jwt` |
| --- | --- | --- |
| Result | The classic Plex token | A JWT, signed in with a key kept on the computer |
| Expires | Never, until it is revoked | After about a week, and renews itself |
| If it leaks | Full access until it is revoked | Useless once it expires |
| Accepted by plex.tv | Yes | Yes |
| Accepted by the server | Yes | **Not by the servers tried** |
| Needs | Nothing else | The signing keys saved on the computer |

**The default is the classic token, because Plex Media Server doesn't accept a
JWT.** A JWT is the better design: it expires by itself and Plex is moving to
it. But plex.tv is the only part of Plex that accepts it so far. Plex Media
Server 1.43.5.11079 answers every request that carries one with `401
Unauthorized`, as did two shared servers that were tried. Most commands in plextool
talk to the server, so a JWT login would leave them unable to connect.

`--type jwt` is there for when servers start accepting JWTs. After a JWT login,
plextool tests the saved server straight away and says if it is rejected.
`plextool server test` repeats that check at any time.

To keep a classic token from sitting in one file, it can be stored in a password
manager and point `PLEX_TOKEN_CMD` at it (see below), or use `--print`. To limit
the damage if it leaks, revoke it under Authorized Devices in the Plex account.

## Where things are kept

Everything lives in one folder, readable only by the current user (folder `0700`, files
`0600`):

| Path | Contents |
| --- | --- |
| `~/.config/plextool/auth.json` | The current token, the sign-in type and a random device ID. |
| `~/.config/plextool/jwt_private.key` | The **private signing key**. This is the secret that matters. It never leaves the computer. |
| `~/.config/plextool/jwt_public.key` | The matching public key. Plex holds a copy. |

The folder is `$XDG_CONFIG_HOME/plextool` if that is set, and
`$PLEXTOOL_CONFIG_DIR` overrides both. The keys are created by `auth login`
and replaced by every new login. Every login makes a new device ID (and a new key pair for a JWT), because Plex's sign-in page refuses a device ID that already has a different key or token type. Each login therefore adds an entry under Authorized Devices in the Plex account; list them with `plextool auth devices` and remove old ones with `plextool auth revoke --others --commit`. A classic-token login stores only
`auth.json`.

With `--type jwt`, the private key can renew the JWT without anything needing approval again, so look
after it like an SSH key: don't copy it to shared folders or back it up to
places others can read.

## Choosing a server

Signing in does not choose a server. Use [`plextool server`](server.md) for that.
Without a choice, commands use `http://localhost:32400`.

## Commands

### `plextool auth login`

```console
$ plextool auth login                          # same as --type token: classic token, works with servers
$ plextool auth login --type jwt               # short-lived; plex.tv accepts it, servers may not
$ plextool auth login --print                  # print the token, save nothing
```

`--print` only works with `--type token`. `--timeout SECONDS` sets how long to wait for approval (default 300). Nothing
is saved if approval does not happen in time.

### `plextool auth status`

Shows the folder, which files exist, their permissions, the sign-in type and
when a JWT expires. The token is never printed.

### `plextool auth devices`

Every login adds a device to the Plex account, shown under **Authorized
Devices** in Plex's settings. This lists the ones plextool made, newest first,
and marks the one the saved login uses:

```console
$ plextool auth devices
Devices on your Plex account signed in through plextool
  3895d339  plextool on localhost.localdomain   created 2026-11-02 14:10   last seen 2026-11-02 14:41  (this login)
  a6e9e891  plextool on localhost.localdomain   created 2026-11-02 13:52   last seen 2026-11-02 14:12
  730dc1cb  plextool on localhost.localdomain   created 2026-11-02 13:23   last seen 2026-11-02 13:30
```

The ID is the start of the device ID. `--all` lists every device on the
account, whatever made it. That view is read-only.

### `plextool auth revoke`

Removes plextool devices from the Plex account, so plex.tv rejects their tokens.
It only ever removes plextool's own entries; Plex apps, TVs and other
devices are never touched. Like the other commands that change things, it
is a dry run unless `--commit` is passed.

```console
$ plextool auth revoke --others                 # preview: every plextool device except this login's
$ plextool auth revoke --others --commit        # remove them
$ plextool auth revoke 730dc1cb --commit        # one device, by the start of its ID
$ plextool auth revoke --this --commit          # this login's own device
```

- `--others` is the usual clean-up: it keeps the login this computer is using.
- `--this` removes this login's device from the account. Do it before
  `plextool auth wipe` to have the sign-in revoked on Plex's side too, since
  the wipe deletes the token needed to do it later.
- Several IDs can be given at once. An ID that matches nothing, or more than one
  device, is an error.

**It is not an instant cut-off.** In testing, plex.tv rejected a removed
device's token straight away, but a Plex Media Server kept accepting the same
token at least five minutes later. A server remembers a token it has already
accepted for a while; how long is up to Plex and not something plextool
controls. Removing the device still blocks the token at plex.tv, so it can no
longer be used to sign in, list servers or manage the account, and servers stop
accepting it once they check again. If a token has leaked, revoke it straight
away and don't assume the server stops at that moment.

### `plextool auth wipe`

Deletes `auth.json`, both key files and the server chosen with `plextool server`, then removes the folder if it is
empty. It asks for `WIPE` to be typed first; `--assume-yes` skips that.

Wiping only removes things from this computer. To cut off access on Plex's
side too, run `plextool auth revoke --this --commit` before wiping, or remove
**plextool** under **Authorized Devices** in the Plex account afterwards. Do
that as well if a computer is lost or a key or token may have been copied. See
[the note on revoking](#plextool-auth-revoke): a server can keep accepting a
revoked token for a while.

## How other commands find the token

In this order, the first one found wins:

1. `--token TOKEN`. This puts the token in the shell history and process list,
   so plextool prints a warning. Avoid it.
2. `--token-file FILE`. Reads the token from a file. `-` reads standard input.
3. The `PLEX_TOKEN` environment variable.
4. `PLEX_TOKEN_CMD`, a command whose output is the token, for password managers:
   `export PLEX_TOKEN_CMD='pass show plex/token'`.
5. The login saved by `plextool auth login`. A JWT within a day of expiring is
   renewed automatically with the saved key.

If a server rejects a token, the error says which of these it came from.

## QR code

Install [`segno`](https://pypi.org/project/segno/) to get the QR code in the
terminal: `pip install 'plextool[qr]'`. Without it only the link is shown. The
QR code is only drawn when the output is a terminal.
