from argparse import ArgumentTypeError, Namespace
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from plextool import ondemand
from plextool.cli import build_parser
from plextool.common import PlexToolError


def stream(sid=1, lang="eng", tag="en", fmt="srt", key="/library/streams/1", provider="OpenSubtitles",
           forced=False, sdh=False, score=100, perfect=False, title="Rel.Name"):
    return NS(id=sid, languageCode=lang, languageTag=tag, format=fmt, codec=fmt, key=key,
              providerTitle=provider, userID=None, sourceKey=None, forced=forced,
              hearingImpaired=sdh, score=score, perfectMatch=perfect, title=title,
              displayTitle=f"{tag} ({fmt})")


def test_short_lang():
    assert ondemand.short_lang("eng") == "en"
    assert ondemand.short_lang("EN") == "en"
    assert ondemand.short_lang("tha") == "tha"
    assert ondemand.short_lang(None) == ""


def test_stream_track():
    t = ondemand.stream_track(stream(forced=True, fmt="subrip"))
    assert t == {"lang": "en", "forced": True, "sdh": False, "ext": "srt"}


def test_is_downloaded():
    assert ondemand.is_downloaded(stream())
    assert not ondemand.is_downloaded(stream(key=None))                      # embedded
    sidecar = stream(provider=None)
    assert not ondemand.is_downloaded(sidecar)
    assert ondemand.is_downloaded(sidecar, include_external=True)


def test_map_path():
    maps = [ondemand.parse_map("/data/media=/mnt/media/")]
    assert ondemand.map_path("/data/media/Movies/A.mkv", maps) == Path("/mnt/media/Movies/A.mkv")
    assert ondemand.map_path("/data/mediabackup/A.mkv", maps) == Path("/data/mediabackup/A.mkv")
    assert ondemand.map_path("/x/A.mkv", []) == Path("/x/A.mkv")
    with pytest.raises(ArgumentTypeError):
        ondemand.parse_map("nope")


def test_rank_orders_and_filters():
    a = stream(sid=1, score=50)
    b = stream(sid=2, score=900)
    c = stream(sid=3, score=10, perfect=True)
    d = stream(sid=4, score=None)
    assert [s.id for s in ondemand.rank([a, b, c, d])] == [3, 2, 1, 4]
    assert [s.id for s in ondemand.rank([a, b, c, d], min_score=100)] == [3, 2]


def test_candidate_line_shows_flags_and_perfect():
    line = ondemand.candidate_line(2, stream(forced=True, sdh=True, perfect=True))
    assert "*" in line and "forced sdh" in line and "OpenSubtitles" in line


def test_ask_choice(monkeypatch):
    answers = iter(["x", "9", "3"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    assert ondemand.ask_choice(5) == 2
    monkeypatch.setattr("builtins.input", lambda _: "")
    assert ondemand.ask_choice(5) == 0
    monkeypatch.setattr("builtins.input", lambda _: "s")
    assert ondemand.ask_choice(5) is None
    monkeypatch.setattr("builtins.input", lambda _: "q")
    with pytest.raises(PlexToolError):
        ondemand.ask_choice(5)


class FakeItem:
    """A movie/episode with one part and a changeable list of subtitle streams."""

    def __init__(self, tmp_path, streams, name="Movie", item_type="movie"):
        self.type = item_type
        self.title = name
        self.year = 2000
        self.file = str(tmp_path / f"{name}.mkv")
        self.streams = list(streams)
        self.downloaded = []
        self.pending = []
        self.part = NS(file=self.file, subtitleStreams=lambda: self.streams)
        self.media = [NS(parts=[self.part])]

    def subtitleStreams(self):
        return self.streams

    def reload(self):
        self.streams += self.pending
        self.pending = []

    def searchSubtitles(self, language, hearingImpaired, forced):
        self.search_args = (language, hearingImpaired, forced)
        return self.candidates

    def downloadSubtitles(self, chosen):
        self.downloaded.append(chosen)
        self.pending = [stream(sid=100 + chosen.id, key=f"/library/streams/{100 + chosen.id}")]


def export_args(**kw):
    base = {"all_external": False, "lang": None, "map": [], "force": False, "commit": True}
    return Namespace(**{**base, **kw})


def fetcher(plex, s):
    return f"data{s.id}".encode()


def test_export_writes_named_files(tmp_path):
    item = FakeItem(tmp_path, [
        stream(sid=1), stream(sid=2, forced=True), stream(sid=3, sdh=True), stream(sid=4),
        stream(sid=5, key=None),                         # embedded: never exported
    ])
    count, folders = ondemand.export_item(None, item, export_args(), fetch=fetcher)
    assert count == 4 and folders == {str(tmp_path)}
    names = sorted(p.name for p in tmp_path.iterdir())
    assert names == ["Movie.2.en.srt", "Movie.en.forced.srt", "Movie.en.sdh.srt", "Movie.en.srt"]
    assert (tmp_path / "Movie.en.srt").read_bytes() == b"data1"


def test_export_dry_run_and_existing(tmp_path):
    item = FakeItem(tmp_path, [stream(sid=1)])
    count, _ = ondemand.export_item(None, item, export_args(commit=False), fetch=fetcher)
    assert count == 1 and list(tmp_path.iterdir()) == []
    (tmp_path / "Movie.en.srt").write_text("old")
    count, _ = ondemand.export_item(None, item, export_args(), fetch=fetcher)
    assert count == 0 and (tmp_path / "Movie.en.srt").read_text() == "old"
    count, _ = ondemand.export_item(None, item, export_args(force=True), fetch=fetcher)
    assert count == 1 and (tmp_path / "Movie.en.srt").read_bytes() == b"data1"


def test_export_language_filter_and_ids(tmp_path):
    item = FakeItem(tmp_path, [stream(sid=1), stream(sid=2, lang="fra", tag="fr")])
    count, _ = ondemand.export_item(None, item, export_args(lang="fr"), fetch=fetcher)
    assert count == 1 and [p.name for p in tmp_path.iterdir()] == ["Movie.fr.srt"]
    count, _ = ondemand.export_item(None, item, export_args(), fetch=fetcher, only_ids={1})
    assert count == 1


def test_export_maps_paths_and_reports_missing_folder(tmp_path, capsys):
    item = FakeItem(Path("/server/media"), [stream(sid=1)])
    args = export_args(map=[("/server/media", str(tmp_path))])
    assert ondemand.export_item(None, item, args, fetch=fetcher)[0] == 1
    assert (tmp_path / "Movie.en.srt").exists()
    gone = FakeItem(Path("/server/media"), [stream(sid=1)])
    assert ondemand.export_item(None, gone, export_args(), fetch=fetcher)[0] == 0
    assert "use --map" in capsys.readouterr().out


def test_wait_for_new_finds_arrivals(tmp_path):
    item = FakeItem(tmp_path, [stream(sid=1)])
    item.pending = [stream(sid=7), stream(sid=8, lang="fra", tag="fr")]
    assert ondemand.wait_for_new(item, {1}, "en", timeout=5, interval=0) == {7}
    gone = FakeItem(tmp_path, [stream(sid=1)])
    assert ondemand.wait_for_new(gone, {1}, "en", timeout=0, interval=0) == set()


# --- fetch ------------------------------------------------------------------

@pytest.fixture
def fetch_env(tmp_path, monkeypatch):
    """Two items needing English, one that already has it; fake server plumbing."""
    needs_a = FakeItem(tmp_path, [], name="A")
    needs_b = FakeItem(tmp_path, [], name="B")
    has_it = FakeItem(tmp_path, [stream(sid=50, key=None)], name="C")
    for item in (needs_a, needs_b, has_it):
        item.candidates = [stream(sid=1, score=10), stream(sid=2, score=500), stream(sid=3, score=20, perfect=True)]
    section = NS(title="Movies", update=lambda path: None)
    monkeypatch.setattr(ondemand, "connect", lambda args: NS())
    monkeypatch.setattr(ondemand, "select_files", lambda plex, args: [(section, i) for i in (needs_a, needs_b, has_it)])
    return needs_a, needs_b, has_it


def fetch_args(**kw):
    base = {"lang": "eng", "sdh": None, "forced": None, "min_score": 0, "candidates": 10, "list": False,
            "choose": False, "include_present": False, "export": False, "wait": 0.0, "map": [],
            "force": False, "scan": False, "commit": False}
    return Namespace(**{**base, **kw})


def test_fetch_dry_run_downloads_nothing(fetch_env, capsys):
    a, b, c = fetch_env
    assert ondemand.run_fetch(fetch_args()) == 0
    assert a.downloaded == [] and b.downloaded == []
    assert a.search_args == ("en", 0, 0) and not hasattr(c, "search_args")
    assert "Dry run only" in capsys.readouterr().out


def test_fetch_list_shows_candidates_only(fetch_env, capsys):
    ondemand.run_fetch(fetch_args(list=True, commit=True))
    out = capsys.readouterr().out
    assert out.count("OpenSubtitles") == 6          # 3 candidates for each of 2 items
    assert all(not i.downloaded for i in fetch_env)


def test_fetch_auto_picks_best_ranked(fetch_env):
    a, b, _ = fetch_env
    ondemand.run_fetch(fetch_args(commit=True))
    assert [s.id for s in a.downloaded] == [3]       # the perfect match, not the highest score
    assert [s.id for s in b.downloaded] == [3]


def test_fetch_choose_lets_user_pick(fetch_env, monkeypatch):
    a, b, _ = fetch_env
    monkeypatch.setattr("sys.stdin", NS(isatty=lambda: True))
    answers = iter(["2", "s"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    ondemand.run_fetch(fetch_args(choose=True, commit=True))
    assert [s.id for s in a.downloaded] == [2]       # second in ranked order (score 500)
    assert b.downloaded == []                        # skipped


def test_fetch_choose_needs_terminal(fetch_env, monkeypatch):
    monkeypatch.setattr("sys.stdin", NS(isatty=lambda: False))
    with pytest.raises(PlexToolError, match="terminal"):
        ondemand.run_fetch(fetch_args(choose=True))


def test_fetch_passes_flag_preferences(fetch_env):
    ondemand.run_fetch(fetch_args(sdh="prefer", forced="exclude"))
    assert fetch_env[0].search_args == ("en", 1, 3)


def test_fetch_include_present(fetch_env):
    fetch_env[2].candidates = [stream(sid=9)]
    ondemand.run_fetch(fetch_args(include_present=True, commit=True))
    assert [s.id for s in fetch_env[2].downloaded] == [9]


def test_fetch_export_saves_new_subtitle(fetch_env, tmp_path, monkeypatch):
    monkeypatch.setattr(ondemand, "http_fetch", fetcher)
    ondemand.run_fetch(fetch_args(commit=True, export=True))
    assert (tmp_path / "A.en.srt").read_bytes() == b"data103"


def test_cli_parses_fetch_and_export():
    parser = build_parser()
    args = parser.parse_args(["subs", "fetch", "-t", "X", "--lang", "en", "--choose", "--sdh", "prefer"])
    assert args.choose and args.sdh == "prefer"
    args = parser.parse_args(["subs", "export", "--all", "--map", "/a=/b", "-y"])
    assert args.map == [("/a", "/b")] and args.commit
    with pytest.raises(SystemExit):
        parser.parse_args(["subs", "fetch", "--lang", "en"])          # needs a selector
    with pytest.raises(SystemExit):
        parser.parse_args(["subs", "fetch", "-t", "X", "--lang", "en", "--list", "--choose"])
