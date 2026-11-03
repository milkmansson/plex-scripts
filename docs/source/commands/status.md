# plextool status

A quick look at the server: version, each library's size, and what is playing.
Read-only.

Handy when:
- A quick check is needed that the server is up, and which version it runs.
- Who is watching, and whether it is transcoding, needs checking before a restart or a scan.
- Which libraries are scanning right now needs checking.

```console
$ plextool status
My Server  Plex Media Server 1.x.x on Linux

Libraries
  Movies                   movie    1204 items     5.1 TB
  TV Shows                 show     312 items      9.8 TB  (scanning)

Now playing (1 session, 0 transcoding)
  alice: Some Show S02E04 - Title [playing] on Living Room TV
```

`--json` prints the same information for scripts. Libraries that are currently
scanning are flagged.
