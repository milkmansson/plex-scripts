from argparse import ArgumentTypeError, Namespace
from datetime import datetime, timedelta
from types import SimpleNamespace as NS

import pytest

from plextool import dupes, recent
from plextool.cli import build_parser
from plextool.common import describe, plural, pretty_size


def test_pretty_size():
    assert pretty_size(0) == "0 B"
    assert pretty_size(None) == "0 B"
    assert pretty_size(1536) == "1.5 KB"
    assert pretty_size(13 * 1024**3) == "13.0 GB"


def test_plural():
    assert plural(1, "movie") == "1 movie"
    assert plural(3, "movie") == "3 movies"


def test_describe():
    assert describe(NS(type="movie", title="Heat", year=1995)) == "Heat (1995)"
    assert describe(NS(type="movie", title="Heat", year=None)) == "Heat"
    season = NS(type="season", parentTitle="Show", index=2)
    assert describe(season) == "Show S02"
    episode = NS(type="episode", grandparentTitle="Show", seasonNumber=1, episodeNumber=5, title="Pilot")
    assert describe(episode) == "Show S01E05 - Pilot"
    # Specials or unmatched episodes can lack numbers.
    episode = NS(type="episode", grandparentTitle="Show", seasonNumber=None, episodeNumber=None, title="X")
    assert describe(episode) == "Show S00E00 - X"


def test_parse_shift():
    assert recent.parse_shift("-30d") == -timedelta(days=30)
    assert recent.parse_shift("+2w") == timedelta(weeks=2)
    assert recent.parse_shift("6h") == timedelta(hours=6)
    assert recent.parse_shift("90min") == timedelta(minutes=90)
    for bad in ("", "d", "5", "5y", "1.5d"):
        with pytest.raises(ArgumentTypeError):
            recent.parse_shift(bad)


def test_parse_date():
    assert recent.parse_date("2020-01-02") == datetime(2020, 1, 2)
    assert recent.parse_date("2020-01-02 03:04:05") == datetime(2020, 1, 2, 3, 4, 5)
    with pytest.raises(ArgumentTypeError):
        recent.parse_date("yesterday")


def _args(**kw):
    base = {"date": None, "now": False, "release": False, "shift": None}
    base.update(kw)
    return Namespace(**base)


def test_new_date_modes():
    now = datetime(2025, 1, 1)
    item = NS(addedAt=datetime(2024, 6, 1), originallyAvailableAt=datetime(2010, 5, 5))
    assert recent.new_date(item, _args(date=datetime(2000, 1, 1)), now) == datetime(2000, 1, 1)
    assert recent.new_date(item, _args(now=True), now) == now
    assert recent.new_date(item, _args(release=True), now) == datetime(2010, 5, 5)
    assert recent.new_date(item, _args(shift=timedelta(days=-1)), now) == datetime(2024, 5, 31)


def test_new_date_without_release_date():
    item = NS(addedAt=datetime(2024, 6, 1), originallyAvailableAt=None)
    assert recent.new_date(item, _args(release=True), datetime(2025, 1, 1)) is None


class FakeShow:
    type = "show"

    def seasons(self):
        return ["s1", "s2"]

    def episodes(self):
        return ["e1", "e2", "e3"]


def test_expand_cascade():
    show = FakeShow()
    assert recent.expand(show, False) == [show]
    assert recent.expand(show, True) == [show, "s1", "s2", "e1", "e2", "e3"]
    season = NS(type="season", episodes=lambda: ["e1"])
    assert recent.expand(season, True) == [season, "e1"]
    movie = NS(type="movie")
    assert recent.expand(movie, True) == [movie]


def test_find_by_guid_agent_id():
    a = NS(guids=[NS(id="imdb://tt1"), NS(id="tmdb://2")])
    b = NS(guids=[NS(id="imdb://tt3")])
    section = NS(search=lambda **kw: [a, b])
    assert recent.find_by_guid(section, "movie", "imdb://tt3") == [b]
    assert recent.find_by_guid(section, "movie", "imdb://nope") == []


def test_find_by_guid_plex_id_uses_server_search():
    calls = []
    section = NS(search=lambda **kw: calls.append(kw) or ["hit"])
    assert recent.find_by_guid(section, "episode", "plex://episode/abc") == ["hit"]
    assert calls == [{"guid": "plex://episode/abc", "libtype": "episode"}]


class FakeItem:
    def __init__(self, added, **kw):
        self.type = "movie"
        self.addedAt = added
        self.edits = []
        self.__dict__.update(kw)

    def editAddedAt(self, date, locked=True):
        self.edits.append((date, locked))
        self.addedAt = date

    def reload(self):
        pass


def test_apply_dates_dry_run_writes_nothing(capsys):
    item = FakeItem(datetime(2024, 1, 1))
    args = _args(date=datetime(2000, 1, 1), commit=False, cascade=False)
    counts = recent.apply_dates(item, args, datetime(2025, 1, 1))
    assert counts == {"changed": 1, "unchanged": 0, "skipped": 0}
    assert item.edits == []


def test_apply_dates_commit_writes(capsys):
    item = FakeItem(datetime(2024, 1, 1))
    args = _args(date=datetime(2000, 1, 1, 12, 0, 0), commit=True, cascade=False, no_lock=False)
    recent.apply_dates(item, args, datetime(2025, 1, 1))
    assert item.edits == [(datetime(2000, 1, 1, 12, 0, 0), True)]
    assert item.addedAt == datetime(2000, 1, 1, 12)


def test_apply_dates_cascade_release_dates(capsys):
    ep1 = FakeItem(datetime(2024, 1, 1), originallyAvailableAt=datetime(2001, 1, 1), type="episode")
    ep2 = FakeItem(datetime(2024, 1, 1), originallyAvailableAt=None, type="episode")
    show = FakeItem(datetime(2024, 1, 1), originallyAvailableAt=datetime(2000, 1, 1), type="show")
    show.seasons = list
    show.episodes = lambda: [ep1, ep2]
    args = _args(release=True, commit=True, cascade=True, no_lock=False)
    counts = recent.apply_dates(show, args, datetime(2025, 1, 1))
    assert counts == {"changed": 2, "unchanged": 0, "skipped": 1}
    assert ep1.addedAt == datetime(2001, 1, 1)
    assert ep2.edits == []


def _media(res, codec, *parts, height=1080):
    return NS(videoResolution=res, videoCodec=codec, height=height,
              parts=[NS(file=f, size=s) for f, s in parts])


def test_summarise_duplicates():
    item = NS(type="movie", title="Heat", year=1995, guid="plex://movie/1", media=[
        _media("1080", "h264", ("/a.mkv", 8000)),
        _media("720", "h264", ("/b1.avi", 300), ("/b2.avi", 200)),
    ])
    entry = dupes.summarise(item)
    assert entry["title"] == "Heat (1995)"
    assert entry["versions"][1]["size"] == 500
    assert len(entry["versions"][1]["parts"]) == 2
    assert entry["reclaimable"] == 500


def test_summarise_handles_missing_sizes():
    item = NS(type="movie", title="X", year=None, guid="g", media=[
        _media(None, None, ("/a", None)), _media(None, None, ("/b", 10))])
    assert dupes.summarise(item)["reclaimable"] == 0


def test_cli_requires_one_selector_and_one_date_mode():
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["recent", "--release"])
    with pytest.raises(SystemExit):
        parser.parse_args(["recent", "-t", "x"])
    with pytest.raises(SystemExit):
        parser.parse_args(["recent", "-t", "x", "-r", "-N"])
    args = parser.parse_args(["recent", "-t", "x", "--shift=-7d", "-y"])
    assert args.commit and args.shift == -timedelta(days=7)
