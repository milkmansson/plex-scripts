# plextool server

Choose which Plex server the other commands talk to, so that `--base-url`
is not needed every time.

Handy when:
- plextool is being set up and Plex runs on another machine.
- The server's address changes (for example with DHCP) and plextool should keep finding it.
- There is more than one server, and switching between them is needed.
- There is no internet access and the server must be reached directly.

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
Using My Server (found through your Plex account; its address is looked up on plex.tv each run).
```

## Three ways to choose

| | How | Good for | Needs |
| --- | --- | --- | --- |
| **By name** | `server use "My Server"` | Servers reached from several places, or whose address changes. | A login (`plextool auth login`) and internet access to plex.tv. |
| **By address** | `server use http://192.168.1.20:32400` | A fixed address, including a server on this machine or one with no internet. | Nothing. The server is contacted once to check it, unless `--no-check` is passed. |
| **By scan** | `server find` | Discovering what is on the network. | Nothing. Works with no login and no internet, but only on the same network, and some networks block it. |

Choosing **by name** saves only the server's name and Plex's ID for it. Each
time a command runs, plextool asks plex.tv for the server's current
addresses (local, remote and relay), tries them all at once and uses the first
that answers. If plex.tv can't be reached, it falls back to the address that
last worked.

Choosing **by address** saves the address given. Nothing is looked up.

## Which server is used

In this order, the first one found wins:

1. `--base-url URL` on the command.
2. The `PLEX_URL` environment variable.
3. The server saved with `server use`.
4. `http://localhost:32400`.

## Which address is used

A server chosen by name has several addresses (see `server find`). Each time a
command runs, plextool tests all of them at once with a real request and uses
the first one that answers, in Plex's fixed order:

1. **local**: the server's address on the local network. Fastest, and traffic
   stays inside the network.
2. **remote**: the server's public address, through the router.
3. **relay**: Plex's relay service. It always works but is slow and
   bandwidth-limited, so it is only used when nothing else answers.

Within each kind, HTTPS is tried before HTTP and IPv4 before IPv6. For each
address the server's own access token is tried first, then the login token. On
a server shared with the account (not one it owns), Plex's local addresses are skipped,
so only remote and relay are considered.

Because every address is tested before one is chosen, an address that doesn't
answer (a local address when away from home) can add a few seconds
to each command while it times out.

`plextool server test` shows the result, with the address that would be used
marked `<- used`. `plextool server show` shows the address, and whether it was
local, remote or relay, from the last time a command connected. To skip all of
this and use one fixed address, run `plextool server use http://HOST:32400`.

## Commands

| Command | What it does |
| --- | --- |
| `plextool server find [--no-lan]` | List servers on the account (all their addresses) and scan the network. |
| `plextool server use NAME_OR_URL [--no-check]` | Save the server to use. |
| `plextool server test [NAME_OR_URL]` | Check every address of a server and say why any fail. |
| `plextool server show` | Show what is saved, and whether `PLEX_URL` overrides it. |
| `plextool server forget` | Delete the saved server. |

The choice is stored in `server.json` in the same folder as the login
(`~/.config/plextool/`, see [`plextool auth`](auth.md)). It holds a name, an
ID or an address, and the last address that worked. There are no tokens in it.
`plextool auth wipe` deletes it along with the login and keys.

## When a server can't be reached

Run `plextool server test`. It tries every address Plex lists for the server
using both the server's own access token and the login token, and says why
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
| `DNS lookup failed` | The router or resolver blocks Plex's `*.plex.direct` names (DNS rebinding protection). Allow `plex.direct`, or use the server's address: `server use http://HOST:32400`. |
| `no response (timed out)` | Different network, or a firewall in the way. |
| `connection refused` | The address is reachable but nothing is listening on that port. |
| `TLS/certificate error` | Often a proxy or antivirus inspecting HTTPS traffic. |
| `rejected the token (401)` | The server answered but refused that token. If the server token works and the login token doesn't, plextool still connects using the server token. A JWT login token is rejected by Plex Media Server at the moment, so on a server owned by the account both columns show 401 until a classic token is used to sign in. |

## Working offline, or directly against the server

Every command except those that need plex.tv works with no internet, talking
straight to the server's own port (32400 by default).

**On the server's own machine.** Nothing to choose: the default is
`http://localhost:32400`. Only a token is needed.

**From another machine on the same network.**

```console
$ plextool server use http://192.168.1.20:32400
```

or, for a one-off, `plextool status --base-url http://192.168.1.20:32400`, or
`export PLEX_URL=http://192.168.1.20:32400`. For an address with no internet
at all, add `--no-check` to `server use`, which saves it without contacting the
server or needing a token.

**Giving it a token without plex.tv.** `plextool auth login` needs plex.tv, so
get a token once, while access is available, and keep it for the offline machine:

```console
$ plextool auth login --print > /secure/place/plex-token
$ plextool status --token-file /secure/place/plex-token
```

Use the classic token, which `auth login` gives by default. A JWT is renewed by
plex.tv, so it stops working offline once it expires. The
owner's token can also be copied from the server's own `Preferences.xml` (the `PlexOnlineToken`
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
| `server find` account list, `server use NAME` | They list the account's servers. |
| Running against a server saved by name | The address is looked up on plex.tv. It falls back to the last address that worked. |
| `watched` with `--user` (any user, including the owner) | Other users' tokens come from the Plex account. |
