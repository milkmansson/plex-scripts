# plextool info

Shows what Plex holds about a movie, show, season or episode: the summary, the people,
the tags and IDs, the playback state, and the technical side, with every file, path and
video, audio and subtitle track. More than one item can be shown side by side, with
the differences marked. Read-only. Plex's own page for a single item is
[Viewing Item Details](https://support.plex.tv/articles/202462186-viewing-item-details/).

Handy when:
- A movie or episode needs checking for audio languages, subtitles or video format.
- Two copies of a title exist, and the better one has to be chosen (see also [`plextool dupes`](dupes.md)).
- The path of a file on disk is needed, or the list of files that make up a title.
- Everything Plex holds about an item is wanted, including fields no other command shows.
- A show's episodes need listing with their size and format.

```console
$ plextool info -t "Ran"
$ plextool info -t "Ran" --all
$ plextool info -t "Ran" --only tech,people
$ plextool info -l "TV Shows" -t "The Expanse" --episodes
$ plextool info -t "Ran" -t "Seven Samurai"          # side by side
$ plextool info -t "Ran" --compare                   # compare its own file versions
$ plextool info -k 4812 --raw
```

## Choosing items

Any of these, and each can be repeated. Giving more than one item switches to the side by
side view.

| Option | Meaning |
| --- | --- |
| `-t`, `--title TITLE` | Select by title (substring match). An exact title wins over longer matches, so `Ran` finds `Ran`, not `Ran (Remastered)`. |
| `-g`, `--guid GUID` | Select by Plex ID (`plex://movie/...`) or agent ID (`imdb://tt...`, `tmdb://...`, `tvdb://...`). |
| `-k`, `--rating-key ID` | Select by Plex's own numeric ID. Works for any kind of item. |
| `-l`, `--library NAME` | Look only in this library. Repeat for several. Default is all movie and TV libraries. |
| `--level` | What a title or ID names: `movie`, `show`, `season` or `episode`. Default is movie for movie libraries and show for TV libraries. |

If a title matches several items, nothing is shown. The matches are listed with their
rating keys, and one of them can then be chosen with `-k`, `-g` or a longer title.

## What is shown

By default the Summary and Technical groups are shown. `--only` picks groups, as a
comma-separated list, and `--all` shows every group.

| Group | Contents |
| --- | --- |
| `summary` | Title, year, original title, tagline, summary, content rating, studio or network, release date, runtime, ratings, library, added and updated dates, rating key and GUID. For episodes, the show, season and episode number. For shows and seasons, the season and episode counts. |
| `people` | Directors, writers, producers and the cast with their roles. |
| `tags` | Genres, collections, labels, countries and external IDs (IMDb, TMDB, TVDB). |
| `playback` | Whether it is watched, the view count, when it was last viewed and the resume position. This is the token owner's, not other users'. |
| `tech` | Each file version: container, runtime, size, bitrate, aspect ratio and the path of every file. Then the video (codec, profile, resolution, bit depth, frame rate, bitrate, HDR, colour space), each audio track (language, codec, channel layout, bitrate, title, default) and each subtitle track (language, format, forced, SDH, whether it is embedded or external, the provider). |
| `extras` | The number of chapters and the intro and credits markers. |

## Other options

| Option | Meaning |
| --- | --- |
| `--episodes` | For a show or season, list its episodes with runtime, size, container, video and audio. This uses one request for the whole list and not one per episode. |
| `--compare` | Show side by side even for one item, with a column for each of its file versions. |
| `--json` | Print JSON instead of text. |
| `--raw` | Print the server's own reply for each item, unchanged. This holds every field Plex returns, including ones plextool has no name for. |

## Comparing

With two or more items, or `--compare`, the output is a table with one column for each
file version. A title with two versions gets two columns, `[v1]` and `[v2]`. Rows that
differ between the columns are marked with `*` and shown in colour. The rows are the
kind, library, runtime, content rating, container, size, bitrate, video codec and
profile, resolution, bit depth, frame rate, HDR, audio tracks, subtitle tracks and path.

## Notes

- Track details, bit depth and HDR are filled in by Plex when it analyses a file. A file
  Plex has not analysed yet shows `not analysed` for its audio and subtitles (and in the
  comparison for bit depth and HDR), with the video details taken from the file summary.
  An analysed file with no tracks of a kind shows `none`, so the two cases can be told apart.
- `hdr` is worked out from fields Plex reports: the Dolby Vision flags, or the colour
  transfer characteristic (`smpte2084` is shown as HDR10 and `arib-std-b67` as HLG).
- A subtitle shows as `external` when Plex holds it as a separate stream with an address of
  its own (a file beside the video, or one Plex downloaded), and `embedded` otherwise.
- One item is one request, plus one more to load its full details. Add `-v` to see them.
