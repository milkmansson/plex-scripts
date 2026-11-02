# plextool server

Choose which Plex server the other commands talk to, so you don't need
`--base-url` every time.

```console
$ plextool server find
On your Plex account
  My Server  owned, online
      local http://192.168.1.20:32400
      remote https://203-0-113-5.abcdef.plex.direct:32400
      relay https://...

On this network
  My Server  http://192.168.1.20:32400  1.x.x

$ plextool server use "My Server"
Using My Server from your Plex account. Its address is looked up each time, so it can change.
```

## Three ways to choose

| | How | Good for | Needs |
| --- | --- | --- | --- |
| **By name** | `server use "My Server"` | Servers you reach from several places, or whose address changes. | A login (`plextool auth login`) and internet access to plex.tv. |
| **By address** | `server use http://192.168.1.20:32400` | A fixed address, including a server on this machine or one with no internet. | Nothing. The server is contacted once to check it, unless you pass `--no-check`. |
| **By scan** | `server find` | Discovering what is on your network. | Nothing. Works with no login and no internet, but only on the same network, and some networks block it. |

Choosing **by name** saves only the server's name and Plex's ID for it. Each
time you run a command, plextool asks plex.tv for the server's current
addresses (local, remote and relay), tries them all at once and uses the first
that answers. If plex.tv can't be reached, it falls back to the address that
last worked.

Choosing **by address** saves the address you gave. Nothing is looked up.

## Which server is used

In this order, the first one found wins:

1. `--base-url URL` on the command.
2. The `PLEX_URL` environment variable.
3. The server saved with `server use`.
4. `http://localhost:32400`.

## Commands

| Command | What it does |
| --- | --- |
| `plextool server find [--no-lan]` | List servers on your account (all their addresses) and scan the network. |
| `plextool server use NAME_OR_URL [--no-check]` | Save the server to use. |
| `plextool server test [NAME_OR_URL]` | Check every address of a server and say why any fail. |
| `plextool server show` | Show what is saved, and whether `PLEX_URL` overrides it. |
| `plextool server forget` | Delete the saved server. |

The choice is stored in `server.json` in the same folder as your login
(`~/.config/plextool/`, see [`plextool auth`](auth.md)). It holds a name, an
ID or an address, and the last address that worked. There are no tokens in it.
`plextool auth wipe` deletes it along with the login and keys.

## When a server can't be reached

Run `plextool server test`. It tries every address Plex lists for the server
using both the server's own access token and your login token, and says why
each one failed. A failed connection from any other command prints the same
table.

```console
$ plextool server test
My Server
  local  172-16-171-111   server token: DNS lookup failed   login token: DNS lookup failed
  remote 114-23-165-200   server token: DNS lookup failed   login token: DNS lookup failed
  relay  66-175-223-75    server token: DNS lookup failed   login token: DNS lookup failed

Every address failed DNS lookup. Your router or DNS resolver may be blocking Plex's
*.plex.direct names (DNS rebinding protection). ...
```

| Reason shown | What it usually means |
| --- | --- |
| `DNS lookup failed` | Your router or resolver blocks Plex's `*.plex.direct` names (DNS rebinding protection). Allow `plex.direct`, or use the server's address: `server use http://HOST:32400`. |
| `no response (timed out)` | Different network, or a firewall in the way. |
| `connection refused` | The address is reachable but nothing is listening on that port. |
| `TLS/certificate error` | Often a proxy or antivirus inspecting HTTPS traffic. |
| `rejected the token (401)` | The server answered but refused that token. If the server token works and the login token doesn't, plextool still connects using the server token. A JWT login token is rejected by Plex Media Server at the moment, so on a server you own both columns show 401 until you sign in with a classic token. |

## Working offline, or directly against the server

Every command except those that need plex.tv works with no internet, talking
straight to the server's own port (32400 by default).

**On the server's own machine.** Nothing to choose: the default is
`http://localhost:32400`. You only need a token.

**From another machine on the same network.**

```console
$ plextool server use http://192.168.1.20:32400
```

or, for a one-off, `plextool status --base-url http://192.168.1.20:32400`, or
`export PLEX_URL=http://192.168.1.20:32400`. For an address with no internet
at all, add `--no-check` to `server use`, which saves it without contacting the
server or needing a token.

**Giving it a token without plex.tv.** `plextool auth login` needs plex.tv, so
get a token once, while you do have access, and keep it for the offline machine:

```console
$ plextool auth login --print > /secure/place/plex-token
$ plextool status --token-file /secure/place/plex-token
```

Use the classic token, which `auth login` gives by default. A JWT is renewed by
plex.tv, so it stops working offline once it expires. You can also copy the
owner's token from the server's own `Preferences.xml` (the `PlexOnlineToken`
value) on the machine it runs on. That is the owner's full token, so treat it
like a password.

**What works with no internet.** Commands that only talk to the server:
`status`, `scan`, `recent`, `dupes`, `stale`, `audit`, `resume`, `playlists`,
`subs`, and `watched` for the owner. `server find`'s network scan works too.

**What needs plex.tv.**

| Needs plex.tv | Why |
| --- | --- |
| `auth login` | The browser sign-in is done by plex.tv. |
| JWT renewal | A JWT is renewed with plex.tv. |
| `server find` account list, `server use NAME` | They list your account's servers. |
| Running against a server saved by name | The address is looked up on plex.tv. It falls back to the last address that worked. |
| `watched` with `--user` (any user, including the owner) | Other users' tokens come from your Plex account. |
