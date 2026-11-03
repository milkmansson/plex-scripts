import io
import json
import sys
from argparse import ArgumentTypeError
from datetime import datetime, timedelta
from types import SimpleNamespace as NS

import pytest

from plextool import audit, dupes, playlists, resume, stale, watched
from plextool.cli import build_parser
from plextool.common import PlexToolError, confirm_typed, item_size, read_json, write_json

NOW = datetime(2025, 6, 1)


def part(path="/a.mkv", size=100, exists=True):
    return NS(file=path, size=size, exists=exists,
              subtitleStreams=list, audioStreams=list)


def episode(show, n, size=100, views=0, added=None, last=None):
    return NS(type="episode", title=f"E{n}", grandparentTitle=show, seasonNumber=1, episodeNumber=n,
              guid=f"plex://episode/{show}{n}", media=[NS(parts=[part(size=size)])],
              viewCount=views, addedAt=added, lastViewedAt=last)


# --- stale ---------------------------------------------------------------

def test_item_size_sums_all_versions():
    item = NS(media=[NS(parts=[part(size=5), part(size=6)]), NS(parts=[part(size=7)])])
    assert item_size(item) == 18


def test_build_rows_groups_episodes_by_show():
    old, new = datetime(2020, 1, 1), datetime(2024, 1, 1)
    items = [episode("Show", 1, 100, views=1, added=new, last=old),
             episode("Show", 2, 200, views=2, added=old, last=new),
             episode("Other", 1, 50)]
    rows = {r["name"]: r for r in stale.build_rows(items, "show")}
    assert rows["Show"] == {"name": "Show", "size": 300, "added": old, "last_viewed": new,
                            "views": 3, "count": 2}
    assert rows["Other"]["last_viewed"] is None


def test_filter_rows():
    rows = [
        {"name": "never", "size": 10, "added": NOW - timedelta(days=400), "last_viewed": None, "views": 0},
        {"name": "recent", "size": 10, "added": NOW - timedelta(days=400),
         "last_viewed": NOW - timedelta(days=5), "views": 3},
        {"name": "stale", "size": 10, "added": NOW - timedelta(days=400),
         "last_viewed": NOW - timedelta(days=300), "views": 1},
        {"name": "new", "size": 10, "added": NOW - timedelta(days=2), "last_viewed": None, "views": 0},
        {"name": "tiny", "size": 1, "added": NOW - timedelta(days=400), "last_viewed": None, "views": 0},
    ]
    names = lambda **kw: [r["name"] for r in stale.filter_rows(rows, NOW, **kw)]
    assert names(unwatched=True) == ["never", "new", "tiny"]
    assert names(idle_days=100) == ["never", "stale", "new", "tiny"]
    assert names(age_days=30) == ["never", "recent", "stale", "tiny"]
    assert names(min_size=5, unwatched=True, age_days=30) == ["never"]


def test_parse_size():
    assert stale.parse_size("2GB") == 2 * 1024**3
    assert stale.parse_size("1.5mb") == int(1.5 * 1024**2)
    assert stale.parse_size("100") == 100
    with pytest.raises(ArgumentTypeError):
        stale.parse_size("lots")


# --- audit ---------------------------------------------------------------

def test_audit_basic_checks():
    assert audit.check_unmatched(NS(guid="local://123"), None)
    assert audit.check_unmatched(NS(guid="plex://movie/1"), None) is None
    assert audit.check_no_poster(NS(thumb=None), None)
    assert audit.check_no_summary(NS(summary=""), None)
    assert audit.check_no_summary(NS(summary="x"), None) is None


def test_audit_missing_files_and_low_res():
    gone = NS(media=[NS(parts=[part("/x.mkv", exists=False), part("/y.mkv")])])
    assert "/x.mkv" in audit.check_missing_files(gone, None)
    assert audit.check_missing_files(NS(media=[NS(parts=[part()])]), None) is None
    assert audit.check_low_res(NS(media=[NS(videoResolution="480")]), None)
    assert audit.check_low_res(NS(media=[NS(videoResolution="480"), NS(videoResolution="1080")]), None) is None
    assert audit.check_low_res(NS(media=[NS(videoResolution=None)]), None) is None


def test_audit_language_checks():
    sub = NS(languageCode="eng")
    p = NS(subtitleStreams=lambda: [sub], audioStreams=list)
    item = NS(media=[NS(parts=[p])])
    assert audit.check_no_subs(item, "eng") is None
    assert audit.check_no_subs(item, "fra")
    assert audit.check_no_audio(item, "eng")


def test_run_check_reloads_only_when_needed():
    reloads = []
    item = NS(type="movie", title="T", year=None, guid="local://1", thumb="x",
              reload=lambda: reloads.append(1), media=[NS(parts=[part()])])
    assert audit.run_check("unmatched", [item], None)[0]["reason"].startswith("not matched")
    assert reloads == []
    audit.run_check("no-subs", [item], "eng")
    assert reloads == [1]


# --- resume --------------------------------------------------------------

def test_resume_select_and_percent():
    a = NS(viewOffset=500, duration=1000, lastViewedAt=NOW - timedelta(days=60))
    b = NS(viewOffset=100, duration=1000, lastViewedAt=NOW - timedelta(days=1))
    c = NS(viewOffset=None, duration=1000, lastViewedAt=None)
    assert resume.percent(a) == 50
    assert resume.percent(c) == 0
    assert resume.select([a, b, c], NOW) == [a, b]
    assert resume.select([a, b, c], NOW, idle_days=30) == [a]


# --- dupes ---------------------------------------------------------------

def entry(*versions):
    return {"title": "T", "versions": [
        {"index": i, "size": s, "height": h, "parts": [{"file": f"/{i}"}] * n}
        for i, (s, h, n) in enumerate(versions)]}


def test_choose_deletions():
    e = entry((500, 1080, 1), (900, 720, 1), (100, 480, 1))
    assert dupes.choose_deletions(e, "largest") == ([0, 2], None)
    assert dupes.choose_deletions(e, "smallest") == ([0, 1], None)
    assert dupes.choose_deletions(e, "best-resolution") == ([1, 2], None)


def test_choose_deletions_skips_multipart():
    indices, reason = dupes.choose_deletions(entry((500, 1080, 2), (900, 720, 1)), "largest")
    assert indices == [] and "multi-part" in reason


def test_dupes_commit_requires_keep():
    args = build_parser().parse_args(["dupes", "-T", "x", "--commit"])
    with pytest.raises(PlexToolError):
        args.run(args)


def test_confirm_typed(monkeypatch):
    confirm_typed("DELETE", "msg", assume_yes=True)
    monkeypatch.setattr("sys.stdin", NS(isatty=lambda: False))
    with pytest.raises(PlexToolError):
        confirm_typed("DELETE", "msg")
    monkeypatch.setattr("sys.stdin", NS(isatty=lambda: True))
    monkeypatch.setattr("builtins.input", lambda _: "no")
    with pytest.raises(PlexToolError):
        confirm_typed("DELETE", "msg")
    monkeypatch.setattr("builtins.input", lambda _: "DELETE")
    confirm_typed("DELETE", "msg")


# --- watched / playlists ---------------------------------------------------

def test_watched_file_round_trip():
    data = watched.to_file_data("alice", {"movies": {"g1": "One"}, "episodes": {"g2": "Two"}})
    assert data["user"] == "alice"
    assert watched.from_file_data(data) == {"movies": {"g1": "One"}, "episodes": {"g2": "Two"}}
    with pytest.raises(PlexToolError):
        watched.from_file_data({"version": 99})


def test_watched_kind_flags():
    parser = build_parser()
    both = parser.parse_args(["watched", "export", "f.json"])
    assert [k[0] for k in watched.wanted_kinds(both)] == ["movies", "episodes"]
    shows = parser.parse_args(["watched", "export", "f.json", "--shows"])
    assert [k[0] for k in watched.wanted_kinds(shows)] == ["episodes"]


def test_playlist_data():
    items = [NS(guid="plex://movie/1", type="movie", title="One", year=2000)]
    pl = NS(title="Faves", playlistType="video", smart=False, items=lambda: items)
    assert playlists.playlist_data(pl) == {
        "title": "Faves", "type": "video", "smart": False,
        "items": [{"guid": "plex://movie/1", "title": "One (2000)", "type": "movie"}]}
    smart = NS(title="S", playlistType="video", smart=True, items=lambda: 1 / 0)
    assert playlists.playlist_data(smart)["items"] == []


def test_cli_parses_new_commands():
    parser = build_parser()
    assert parser.parse_args(["scan", "--path", "/m", "-l", "Movies", "--wait"]).path == "/m"
    assert parser.parse_args(["stale", "--idle", "365", "--min-size", "1GB"]).min_size == 1024**3
    assert parser.parse_args(["audit", "-c", "no-subs", "--lang", "eng"]).check == ["no-subs"]
    assert parser.parse_args(["resume", "--clear", "watched", "-y"]).commit
    assert parser.parse_args(["playlists", "export", "f.json"]).file == "f.json"
    assert parser.parse_args(["watched", "mark", "-t", "X", "--unwatched"]).unwatched


def test_audit_requires_lang():
    args = build_parser().parse_args(["audit", "-T", "x", "-c", "no-subs"])
    with pytest.raises(PlexToolError):
        args.run(args)


def test_write_json_to_stdout_keeps_messages_out_of_the_data(capsys):
    stream = write_json("-", {"a": 1})
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {"a": 1}
    assert stream is sys.stderr


def test_write_and_read_json_file(tmp_path, capsys):
    path = str(tmp_path / "x.json")
    assert write_json(path, {"b": "é"}) is sys.stdout
    assert read_json(path) == {"b": "é"}


def test_read_json_from_stdin(monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.StringIO('{"c": 2}'))
    assert read_json("-") == {"c": 2}


def test_read_json_errors(tmp_path, monkeypatch):
    with pytest.raises(PlexToolError, match="Could not read"):
        read_json(str(tmp_path / "missing.json"))
    monkeypatch.setattr(sys, "stdin", io.StringIO("not json"))
    with pytest.raises(PlexToolError, match="standard input"):
        read_json("-")
