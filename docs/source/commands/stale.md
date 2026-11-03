# plextool stale

Finds what is taking disk space and not being watched. Movies are listed
individually; TV is summed per show. Read-only.

```console
$ plextool stale --unwatched --age 365 --min-size 5GB
$ plextool stale -l Movies --idle 730 -n 20
$ plextool stale --unwatched --all-users
$ plextool stale --idle 365 --user alice --user bob
```

| Option | Meaning |
| --- | --- |
| `-l`, `--library NAME` | Library to scan. Default is all movie and TV libraries. |
| `--unwatched` | Only things never watched. |
| `--idle DAYS` | Only things not watched in the last DAYS days (or never). |
| `--age DAYS` | Only things added more than DAYS days ago. |
| `--min-size SIZE` | Ignore anything smaller, eg `500MB`, `5GB`. |
| `--all-users` | Also count what every user the server is shared with has watched. Reads each library once per user, so it is slow on large libraries. |
| `--user NAME` | Also count what this user has watched. Repeat for more than one. Reads each library once per user named. |
| `-v`, `--verbose` | Print each request sent to Plex, with its reply (records, size, time), and when each library read starts and finishes, on standard error. Shows which user's library is being read. |
| `-n`, `--limit N` | Show the N biggest (default 50). |
| `--json` | Print JSON instead of text. |

Conditions combine with AND. Sizes add up every file attached to an item,
including duplicate versions.

## Whose viewing counts

By default, "watched" means watched by the **token owner** only. On a shared server
that is rarely what you want, since something the owner has never opened may be a
favourite of another user.

`--all-users` also counts what every user the server is shared with has watched, and
`--user NAME` (repeatable) does the same for the people you name. Each user adds one
extra pass over each library, so the more users you include, the longer it takes. A title then counts
as watched, and its last-watched date is the latest, across everyone included. So
`--unwatched` means no one included has watched it, and `--idle DAYS` means none of them
has watched it in that time. The text output says who watched it last:

```console
   1   42.1 GB  Some Show  (310 files)
                 added 2021-04-02, last watched 2025-03-02 by alice (also owner, bob)
```

In `--json`, each entry has a `watchers` object that maps each person (the owner is
`owner`) to the date they last watched it. The date is `null` if Plex has none, for
example when the title was marked as watched by hand.

Things to know:

- plextool signs in as each user, using the access the server owner has to the
  server, and reads what they have watched. It needs the owner's token and plex.tv
  to be reachable. This is the same method as [`plextool watched`](watched).
- **One pass per user.** Each user costs one extra read of each library, on top of the
  owner's. Only their watched items are fetched, which is lighter than the owner's full
  read, but with many users and big libraries it can still take a long time. Use `-l` to
  limit it to one library. While it works, plextool prints
  `still reading ...` lines to standard error every 20 seconds, after the first 10 seconds.
- `--all-users` covers users with a share on this server. A user whose access
  token can't be fetched is skipped with a warning. `--user` stops with an error
  instead.
- A user who can't see a library is not counted for it.
- Anything a user has not watched, or that they can't see, counts as unwatched for
  them. The owner is always included.
