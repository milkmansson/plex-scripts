"""Tests for settings, sessions, labels and audit --clean-missing, using fakes in place of a server."""

from types import SimpleNamespace as NS

import pytest
from plexapi.exceptions import BadRequest, NotFound

from plextool import audit, labels, sessions, settings
from plextool.cli import build_parser
from plextool.common import PlexToolError


def args_for(*argv):
    return build_parser().parse_args(list(argv))


# --- settings --------------------------------------------------------------

class FakeSetting:
    def __init__(self, id, value, default, type="text", group="general", label=None, secure=False,
                 hidden=False, enum=None):
        self.id, self.value, self.default, self.type, self.group = id, value, default, type, group
        self.label, self.secure, self.hidden, self.enumValues = label or id, secure, hidden, enum
        self.advanced, self.summary, self.pending = False, f"about {id}", None

    def set(self, value):
        if self.enumValues and value not in self.enumValues:
            raise BadRequest("not a choice")
        self.pending = value


class FakeSettings:
    def __init__(self, *items):
        self.items, self.saved = {s.id: s for s in items}, False

    def all(self):
        return list(self.items.values())

    def get(self, id):
        if id not in self.items:
            raise NotFound(id)
        return self.items[id]

    def save(self):
        self.saved = True
        for s in self.items.values():
            if s.pending is not None:
                s.value, s.pending = s.pending, None


@pytest.fixture
def plex_settings(monkeypatch):
    store = FakeSettings(
        FakeSetting("FriendlyName", "Home", ""),
        FakeSetting("LanNetworksBandwidth", 0, 0, type="int", group="network"),
        FakeSetting("EnableIPv6", True, False, type="bool", group="network"),
        FakeSetting("Secret", "abc", "", secure=True),
        FakeSetting("Hidden", "x", "", hidden=True),
        FakeSetting("Quality", 3, 2, type="int", enum={1: "low", 3: "high"}),
    )
    monkeypatch.setattr(settings, "connect", lambda args: NS(settings=store))
    return store


def test_settings_list_hides_hidden_and_secret(plex_settings, capsys):
    assert settings.run(args_for("settings", "list")) == 0
    out = capsys.readouterr().out
    assert "FriendlyName" in out and "Hidden" not in out
    assert "abc" not in out and "(hidden)" in out


def test_settings_list_changed_and_search(plex_settings, capsys):
    settings.run(args_for("settings", "list", "--changed"))
    out = capsys.readouterr().out
    assert "EnableIPv6" in out and "Quality" in out and "LanNetworksBandwidth" not in out
    settings.run(args_for("settings", "list", "--search", "bandwidth"))
    assert "LanNetworksBandwidth" in capsys.readouterr().out


def test_settings_set_is_a_dry_run_by_default(plex_settings, capsys):
    settings.run(args_for("settings", "set", "FriendlyName", "Den"))
    assert "Home -> Den" in capsys.readouterr().out
    assert plex_settings.get("FriendlyName").value == "Home" and not plex_settings.saved


def test_settings_set_commit_changes_and_converts_types(plex_settings, capsys):
    settings.run(args_for("settings", "set", "EnableIPv6", "no", "--commit"))
    settings.run(args_for("settings", "set", "LanNetworksBandwidth", "50", "--commit"))
    assert plex_settings.get("EnableIPv6").value is False
    assert plex_settings.get("LanNetworksBandwidth").value == 50 and plex_settings.saved


def test_settings_set_rejects_bad_values_and_unknown_names(plex_settings):
    with pytest.raises(PlexToolError, match="true or false"):
        settings.run(args_for("settings", "set", "EnableIPv6", "maybe", "--commit"))
    with pytest.raises(PlexToolError, match="needs a int"):
        settings.run(args_for("settings", "set", "LanNetworksBandwidth", "fast", "--commit"))
    with pytest.raises(PlexToolError, match="refused"):
        settings.run(args_for("settings", "set", "Quality", "2", "--commit"))
    with pytest.raises(PlexToolError, match="Similar: FriendlyName"):
        settings.run(args_for("settings", "set", "friendly", "x", "--commit"))
    assert not plex_settings.saved


def test_settings_set_same_value_changes_nothing(plex_settings, capsys):
    settings.run(args_for("settings", "set", "FriendlyName", "Home", "--commit"))
    assert "already" in capsys.readouterr().out and not plex_settings.saved


def test_settings_get_shows_choices_and_hides_secret(plex_settings, capsys):
    settings.run(args_for("settings", "get", "Quality"))
    assert "1 (low), 3 (high)" in capsys.readouterr().out
    settings.run(args_for("settings", "get", "Secret"))
    assert "abc" not in capsys.readouterr().out


# --- sessions --------------------------------------------------------------

def stream(key, user, title="Movie", sid="s1", transcode=False):
    return NS(sessionKey=key, usernames=[user], type="movie", title=title, year=2020,
              player=NS(title="TV", product="Plex", state="playing"),
              session=NS(id=sid, location="lan") if sid else None,
              transcodeSession=NS(videoDecision="transcode") if transcode else None,
              viewOffset=600000, duration=3600000, stopped=None,
              stop=lambda reason="", _log=[]: _log.append(reason))


@pytest.fixture
def streams(monkeypatch):
    items = [stream(1, "alice"), stream(2, "bob", transcode=True), stream(3, "alice", sid=None)]
    for i in items:
        i.stopped = []
        i.stop = (lambda reason="", _i=i: _i.stopped.append(reason))
    monkeypatch.setattr(sessions, "connect", lambda args: NS(sessions=lambda: items))
    return items


def test_sessions_list(streams, capsys):
    assert sessions.run(args_for("sessions", "list")) == 0
    out = capsys.readouterr().out
    assert "alice" in out and "transcode" in out and "10m/60m" in out and "3 streams" in out


def test_sessions_stop_needs_a_choice_and_is_a_dry_run(streams, capsys):
    with pytest.raises(PlexToolError, match="Say which streams"):
        sessions.run(args_for("sessions", "stop"))
    sessions.run(args_for("sessions", "stop", "--user", "ALICE"))
    assert "2 streams to stop" in capsys.readouterr().out
    assert all(not i.stopped for i in streams)


def test_sessions_stop_commit_sends_the_reason(streams, capsys):
    assert sessions.run(args_for("sessions", "stop", "2", "--reason", "Restarting", "--commit")) == 0
    assert streams[1].stopped == ["Restarting"] and not streams[0].stopped


def test_sessions_stop_reports_a_stream_with_no_id(streams, capsys):
    code = sessions.run(args_for("sessions", "stop", "--all", "--commit"))
    out = capsys.readouterr().out
    assert code == 1 and "cannot be stopped" in out
    assert streams[0].stopped and streams[1].stopped and not streams[2].stopped


def test_sessions_stop_unknown_number_or_user(streams):
    with pytest.raises(PlexToolError, match="No stream numbered 9"):
        sessions.run(args_for("sessions", "stop", "9"))
    with pytest.raises(PlexToolError, match="No stream is playing for 'carol'"):
        sessions.run(args_for("sessions", "stop", "--user", "carol"))


# --- labels ----------------------------------------------------------------

class FakeLabelled:
    def __init__(self, title, tags=()):
        self.type, self.title, self.year, self.tags = "movie", title, 2020, set(tags)

    def addLabel(self, label):
        self.tags.add(label)

    def removeLabel(self, label):
        self.tags.discard(label)


class FakeLabelSection:
    TYPE, title = "movie", "Movies"

    def __init__(self, items):
        self.items = items

    def listFilterChoices(self, field):
        return [NS(title=t) for t in sorted({t for i in self.items for t in i.tags})]

    def search(self, **filters):
        found = self.items
        if "title" in filters:
            found = [i for i in found if filters["title"].lower() in i.title.lower()]
        if "label" in filters:
            found = [i for i in found if filters["label"] in i.tags]
        if "label!" in filters:
            found = [i for i in found if filters["label!"] not in i.tags]
        return list(found)


@pytest.fixture
def movies(monkeypatch):
    items = [FakeLabelled("Shrek"), FakeLabelled("Shrek 2", {"kids"}), FakeLabelled("Saw", {"adult"})]
    section = FakeLabelSection(items)
    plex = NS(library=NS(sections=lambda: [section]))
    monkeypatch.setattr(labels, "connect", lambda args: plex)
    monkeypatch.setattr(labels, "pick_sections", lambda plex, names: [section])
    return items


def test_labels_list_counts(movies, capsys):
    labels.run(args_for("labels", "list"))
    out = capsys.readouterr().out
    assert "kids" in out and "1 item" in out and "2 labels in use" in out


def test_labels_add_dry_run_then_commit_skips_items_that_have_it(movies, capsys):
    labels.run(args_for("labels", "add", "kids", "--title", "shrek"))
    out = capsys.readouterr().out
    assert "1 item to add" in out and "Shrek (2020)" in out and "Dry run" in out
    assert "kids" not in movies[0].tags
    labels.run(args_for("labels", "add", "kids", "--title", "shrek", "--commit"))
    assert "kids" in movies[0].tags and movies[2].tags == {"adult"}


def test_labels_remove(movies, capsys):
    labels.run(args_for("labels", "remove", "kids", "--all-items", "--commit"))
    assert movies[1].tags == set() and movies[2].tags == {"adult"}
    labels.run(args_for("labels", "remove", "kids", "--all-items", "--commit"))
    assert "Nothing to remove" in capsys.readouterr().out


def test_labels_change_needs_a_selection(movies):
    with pytest.raises(PlexToolError, match="Say which items"):
        labels.run(args_for("labels", "add", "kids"))
    with pytest.raises(PlexToolError, match="cannot be empty"):
        labels.run(args_for("labels", "add", " ", "--all-items"))


# --- audit --clean-missing -------------------------------------------------

def file_item(title, exists=True):
    part = NS(file=f"/m/{title}.mkv", exists=exists)
    return NS(type="movie", title=title, year=2020, media=[NS(parts=[part])])


class FakeCleanSection:
    TYPE = "movie"

    def __init__(self, title, items):
        self.title, self.items, self.calls = title, items, []

    def search(self, **kw):
        return self.items

    def update(self):
        self.calls.append("update")

    def emptyTrash(self):
        self.calls.append("emptyTrash")


@pytest.fixture
def clean(monkeypatch):
    def make(total, missing):
        items = [file_item(f"m{i}", exists=i >= missing) for i in range(total)]
        section = FakeCleanSection("Movies", items)
        monkeypatch.setattr(audit, "pick_sections", lambda plex, names: [section])
        monkeypatch.setattr(audit, "wait_for_scans", lambda plex, titles: None)
        return section
    return make


def test_clean_missing_dry_run_changes_nothing(clean, capsys):
    section = clean(10, 1)
    assert audit.clean_missing(NS(), args_for("audit", "--clean-missing")) == 0
    assert "Dry run" in capsys.readouterr().out and section.calls == []


def test_clean_missing_commit_scans_then_empties_trash(clean, capsys):
    section = clean(10, 1)
    audit.clean_missing(NS(), args_for("audit", "--clean-missing", "--commit"))
    assert section.calls == ["update", "emptyTrash"]


def test_clean_missing_refuses_when_most_of_a_library_is_missing(clean):
    section = clean(10, 6)
    with pytest.raises(PlexToolError, match="not mounted"):
        audit.clean_missing(NS(), args_for("audit", "--clean-missing", "--commit"))
    assert section.calls == []
    audit.clean_missing(NS(), args_for("audit", "--clean-missing", "--commit", "--force"))
    assert section.calls == ["update", "emptyTrash"]


def test_clean_missing_with_nothing_missing(clean, capsys):
    section = clean(5, 0)
    audit.clean_missing(NS(), args_for("audit", "--clean-missing", "--commit"))
    assert "Nothing to clean" in capsys.readouterr().out and section.calls == []
