# plextool devices

Lists the apps and devices authorised on the Plex account, and removes the ones that are no longer wanted. Every
phone, TV, browser and app signed in to the account is an entry under
[Authorized Devices](https://support.plex.tv/articles/115007577087-devices/), which is awkward to tidy in the web
app. Plex Media Servers are never removed.

Handy when:
- The account has years of old browser sessions, phones and TVs that nobody uses.
- A device is old or lost and should be signed out.
- Something unexpected shows up in the list and needs tracking down by name or app.
- Every sign-in from one app, such as Plex Web, needs clearing in one go.

```console
$ plextool devices list
$ plextool devices list --product "Plex Web"
$ plextool devices remove --unused-for 180                          # preview
$ plextool devices remove --product "Plex Web" --unused-for 30 --commit
$ plextool devices remove 3895d339 --commit
```

## devices list

Every app and device authorised on the account, most recently used first, with the ID, the name, the app and
when it was last seen. plextool's own entries are marked: `this login`, `plextool sign-in`, and
`token for another tool: NAME` (see [`plextool token`](token.md)). A Plex Media Server is marked as one.
Read-only.

| Option | Meaning |
| --- | --- |
| `--unused-for DAYS` | Only devices not used in the last DAYS days, or never. |
| `--product NAME` | Only this app, as the list shows it (for example `Plex Web`). Repeat for several. Not case sensitive. |
| `--name TEXT` | Only devices whose name contains TEXT. Not case sensitive. |

## devices remove

Signs out apps and devices, so plex.tv rejects their tokens. Each one removed will ask to sign in again if it is
used. Like the other commands that change things, it is a dry run unless `--commit` is passed.

Choose devices by ID, by filters, or both. The filters are the same as for `list` and combine with AND, so
`--product "Plex Web" --unused-for 30` means Plex Web sessions unused for 30 days. At least one ID or filter is
needed.

Plex Media Servers are never removed. An entry counts as a server if its app is `Plex Media Server`, if it
provides the `server` service, or if plex.tv lists it among the servers on the account (plextool asks plex.tv every
time). Age makes no difference, so `--unused-for 365` cannot remove a server that has not been seen for a year, and
naming a server's ID is refused. If plextool cannot ask plex.tv which entries are servers, it removes nothing and
says so.

With filters, this computer's saved login and the tokens made with `plextool token` are skipped as well. They are
removed only by naming their ID, so an age or app filter cannot cut off a tool by accident. The preview says how
many matching devices were skipped for that reason.

Removing this computer's saved login signs it out. The preview warns about that, and `plextool auth login`
signs in again.

As with [`plextool auth revoke`](auth.md), plex.tv rejects a removed device's token straight away, but a Plex
server can keep accepting it for a while.
