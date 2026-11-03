from types import SimpleNamespace as NS
from unittest import mock

import pytest

from plextool import auth, common, server
from plextool.cli import build_parser
from plextool.common import PlexToolError


@pytest.fixture
def config(tmp_path, monkeypatch):
    monkeypatch.setenv(auth.CONFIG_DIR_ENV, str(tmp_path / "cfg"))
    for name in (common.TOKEN_ENV, common.TOKEN_CMD_ENV, common.URL_ENV):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(common.TOKEN_ENV, "tok")
    return tmp_path / "cfg"


def fake_plex(url):
    return NS(_baseurl=url, friendlyName="Home")


def conn_args(base_url=None):
    return NS(token=None, token_file=None, base_url=base_url)


def resource(name="Home", machine_id="m1", url="http://10.0.0.5:32400"):
    conn = NS(uri=url, relay=False, local=True)
    return NS(name=name, clientIdentifier=machine_id, provides="server", owned=True,
              sourceTitle="me", presence=True, connections=[conn], accessToken="srv",
              preferred_connections=lambda: [url])


def test_default_is_localhost(config):
    with mock.patch.object(common, "PlexServer", side_effect=lambda u, t: fake_plex(u)) as ps:
        args = conn_args()
        common.connect(args)
    ps.assert_called_once_with(common.DEFAULT_URL, "tok")
    assert args.base_url == common.DEFAULT_URL


def test_priority_flag_env_saved_default(config, monkeypatch):
    server.save({"kind": "url", "url": "http://saved:32400"})
    seen = []
    def make(url, token):
        seen.append(url)
        return fake_plex(url)
    with mock.patch.object(common, "PlexServer", side_effect=make), \
            mock.patch.object(server, "PlexServer", side_effect=make):
        common.connect(conn_args())
        monkeypatch.setenv(common.URL_ENV, "http://env:32400")
        common.connect(conn_args())
        common.connect(conn_args("http://flag:32400"))
    assert seen == ["http://saved:32400", "http://env:32400", "http://flag:32400"]


def test_account_server_follows_address_and_caches_it(config):
    res = resource(url="http://new:32400")
    server.save({"kind": "account", "name": "Home", "machine_id": "m1", "last_url": "http://old:32400"})
    with mock.patch.object(server, "account_servers", return_value=[res]), \
            mock.patch.object(server, "probe", return_value=(True, "ok")), \
            mock.patch.object(server, "PlexServer", side_effect=lambda u, t, **k: fake_plex(u)):
        plex = server.connect_saved(server.load_saved(), "tok")
    assert plex._baseurl == "http://new:32400"
    assert server.load_saved()["last_url"] == "http://new:32400"


def test_account_server_falls_back_to_last_url_when_plextv_is_down(config):
    server.save({"kind": "account", "name": "Home", "machine_id": "m1", "last_url": "http://old:32400"})
    with mock.patch.object(server, "account_servers", side_effect=PlexToolError("down")), \
            mock.patch.object(server, "PlexServer", side_effect=lambda u, t: fake_plex(u)):
        assert server.connect_saved(server.load_saved(), "tok")._baseurl == "http://old:32400"


def test_account_server_offline_without_last_url_explains(config):
    saved = {"kind": "account", "name": "Home", "machine_id": "m1"}
    with mock.patch.object(server, "account_servers", side_effect=PlexToolError("down")), \
            pytest.raises(PlexToolError, match="down"):
        server.connect_saved(saved, "tok")


def test_account_server_gone(config):
    saved = {"kind": "account", "name": "Home", "machine_id": "m1"}
    with mock.patch.object(server, "account_servers", return_value=[resource(machine_id="other")]), \
            pytest.raises(PlexToolError, match="no longer on your Plex account"):
        server.connect_saved(saved, "tok")


def test_use_name_saves_machine_id(config, capsys):
    args = build_parser().parse_args(["server", "use", "home"])
    with mock.patch.object(server, "account_servers", return_value=[resource()]):
        assert args.run(args) == 0
    assert server.load_saved() == {"kind": "account", "name": "Home", "machine_id": "m1"}


def test_use_unknown_name_lists_choices(config):
    args = build_parser().parse_args(["server", "use", "nope"])
    with mock.patch.object(server, "account_servers", return_value=[resource()]), \
            pytest.raises(PlexToolError, match="Available: Home"):
        args.run(args)


def test_use_url_checks_and_saves(config):
    args = build_parser().parse_args(["server", "use", "http://10.0.0.5:32400/"])
    with mock.patch.object(server, "PlexServer", side_effect=lambda u, t: fake_plex(u)):
        args.run(args)
    assert server.load_saved() == {"kind": "url", "url": "http://10.0.0.5:32400", "name": "Home"}


def test_use_url_no_check_needs_no_token_or_network(config, monkeypatch):
    monkeypatch.delenv(common.TOKEN_ENV)
    args = build_parser().parse_args(["server", "use", "http://10.0.0.5:32400", "--no-check"])
    with mock.patch.object(server, "PlexServer", side_effect=AssertionError("must not connect")):
        args.run(args)
    assert server.load_saved()["url"] == "http://10.0.0.5:32400"


def test_show_and_forget(config, capsys):
    parse = build_parser().parse_args
    a = parse(["server", "show"]); a.run(a)
    assert "none" in capsys.readouterr().out
    server.save({"kind": "url", "url": "http://x:32400"})
    a.run(a)
    assert "http://x:32400" in capsys.readouterr().out
    f = parse(["server", "forget"]); f.run(f)
    assert server.load_saved() == {}


def test_lan_scan_reads_gdm_entries():
    entry = {"data": {"Name": "Home", "Port": "32400", "Version": "1.4", "Resource-Identifier": "m1"},
             "from": ("192.168.1.9", 32414)}
    with mock.patch("plexapi.gdm.GDM") as gdm:
        gdm.return_value.all.return_value = [entry]
        found = server.lan_servers()
    assert found == [{"name": "Home", "url": "http://192.168.1.9:32400", "version": "1.4", "machine_id": "m1"}]


def test_lan_scan_without_network_is_empty():
    with mock.patch("plexapi.gdm.GDM") as gdm:
        gdm.return_value.all.side_effect = OSError
        assert server.lan_servers() == []


def test_wipe_includes_server_file(config):
    server.save({"kind": "url", "url": "http://x"})
    auth.wipe(assume_yes=True)
    assert server.load_saved() == {}


def rows(*results):
    return [{"kind": "local", "host": "h", "uri": "u", "server_token": s, "login_token": g}
            for s, g in results]


def test_explain_error():
    import requests
    ex = requests.exceptions
    assert server.explain_error(ex.ConnectTimeout("t")) == "no response (timed out)"
    assert server.explain_error(ex.SSLError("bad")) == "TLS/certificate error"
    assert server.explain_error(ex.ConnectionError("Name or service not known")) == "DNS lookup failed"
    assert server.explain_error(ex.ConnectionError("Connection refused")) == "connection refused"
    assert server.explain_error(ex.ConnectionError("???")) == "could not connect"


def test_probe_results():
    import requests
    def fake(status):
        return mock.patch.object(server.requests, "get", return_value=NS(status_code=status))
    with fake(200):
        assert server.probe("http://x", "t") == (True, "ok")
    with fake(401):
        assert server.probe("http://x", "t") == (False, "rejected the token (401)")
    with fake(500):
        assert server.probe("http://x", "t") == (False, "HTTP 500")
    with mock.patch.object(server.requests, "get", side_effect=requests.exceptions.ConnectTimeout()):
        assert server.probe("http://x", "t") == (False, "no response (timed out)")


def test_advice():
    bad_dns = (False, "DNS lookup failed")
    assert "rebinding" in server.advise(rows((bad_dns, bad_dns)))
    assert "different network" in server.advise(rows(((False, "no response (timed out)"),) * 2))
    assert "not your login token" in server.advise(rows(((True, "ok"), (False, "rejected the token (401)"))))
    assert server.advise(rows(((True, "ok"), (True, "ok")))) == ""
    assert "no addresses" in server.advise([])


def test_connect_failure_explains_each_address(config):
    res = resource(url="https://10-0-0-5.abc.plex.direct:32400")
    saved = {"kind": "account", "name": "Home", "machine_id": "m1"}
    with mock.patch.object(server, "account_servers", return_value=[res]), \
            mock.patch.object(server, "probe", return_value=(False, "DNS lookup failed")), \
            pytest.raises(PlexToolError) as info:
        server.connect_saved(saved, "tok")
    message = str(info.value)
    assert "10-0-0-5" in message and "DNS lookup failed" in message and "rebinding" in message
    assert "server test" in message


def test_server_test_command(config, capsys):
    res = resource(url="https://10-0-0-5.abc.plex.direct:32400")
    args = build_parser().parse_args(["server", "test", "Home"])
    with mock.patch.object(server, "account_servers", return_value=[res]), \
            mock.patch.object(server, "probe", return_value=(True, "ok")):
        assert args.run(args) == 0
    out = capsys.readouterr().out
    assert "10-0-0-5" in out and "server token" in out and "login token" in out


def test_connect_uses_login_token_when_only_it_works(config):
    res = resource(url="http://a:32400")
    used = []
    def fake_probe(url, token):
        return (token == "tok", "ok" if token == "tok" else "rejected the token (401)")
    def fake_server(url, token, **kw):
        used.append(token)
        return fake_plex(url)
    saved = {"kind": "account", "name": "Home", "machine_id": "m1"}
    with mock.patch.object(server, "account_servers", return_value=[res]), \
            mock.patch.object(server, "probe", side_effect=fake_probe), \
            mock.patch.object(server, "PlexServer", side_effect=fake_server):
        server.connect_saved(saved, "tok")
    assert used == ["tok"]


def test_connect_skips_dead_addresses_in_preferred_order(config):
    dead, live = "http://dead:32400", "http://live:32400"
    res = resource(url=dead)
    res.connections.append(NS(uri=live, relay=True, local=False))
    res.preferred_connections = lambda: [dead, live]
    saved = {"kind": "account", "name": "Home", "machine_id": "m1"}
    with mock.patch.object(server, "account_servers", return_value=[res]), \
            mock.patch.object(server, "probe", side_effect=lambda u, t: (u == live, "ok")), \
            mock.patch.object(server, "PlexServer", side_effect=lambda u, t, **k: fake_plex(u)):
        assert server.connect_saved(saved, "tok")._baseurl == live


def test_address_shows_port():
    assert server._short_address("https://114-23-165-200.abc.plex.direct:21351") == "114-23-165-200:21351"
    assert server._short_address("http://10.0.0.5:32400") == "10.0.0.5:32400"
    assert server._short_address("https://plex.example.com") == "plex.example.com"


def test_advice_when_every_token_is_rejected():
    rejected = (False, "rejected the token (401)")
    message = server.advise([{**r, "same_token": True} for r in rows((rejected, rejected))])
    assert "JWT" in message and "classic token" in message and "same token" in message
    assert "auth login" in message and "revoked" in message


def test_check_saved_reports_rejection_and_acceptance(config):
    assert server.check_saved("tok") is None
    server.save({"kind": "url", "url": "http://x:32400"})
    with mock.patch.object(server, "PlexServer", side_effect=lambda u, t: fake_plex(u)):
        assert server.check_saved("tok") == "ok"
    with mock.patch.object(server, "PlexServer", side_effect=server.Unauthorized("401")):
        assert "did not accept this JWT" in server.check_saved("tok")


def test_rows_line_up_with_long_addresses():
    long_host = "2401-7000-7110-5000-d61f-f386-a954-fa64:32400"
    lines = server.format_rows(rows(((True, "ok"), (True, "ok")))
                               + [{**rows(((True, "ok"), (True, "ok")))[0], "host": long_host}])
    assert all("server token:" in line for line in lines)
    assert lines[0].index("server token:") == lines[1].index("server token:")


def test_a_revoked_saved_login_says_to_sign_in_again(config, monkeypatch):
    monkeypatch.delenv(common.TOKEN_ENV)
    auth.save_state({"kind": "token", "client_id": "c", "token": "revoked"})
    with mock.patch.object(common, "PlexServer", side_effect=common.Unauthorized("401")), \
            pytest.raises(PlexToolError, match="saved login.*revoked.*plextool auth login"):
        common.connect(conn_args())


def test_a_rejected_flag_token_does_not_blame_the_saved_login(config):
    with mock.patch.object(common, "PlexServer", side_effect=common.Unauthorized("401")), \
            pytest.raises(PlexToolError) as info:
        common.connect(NS(token="x", token_file=None, base_url=None))
    assert "revoked" not in str(info.value) and "Check that token" in str(info.value)


def test_pick_row_prefers_first_working_address_and_server_token():
    dead = (False, "no response (timed out)")
    ok, bad = (True, "ok"), (False, "rejected the token (401)")
    local = {"kind": "local", "server_token": dead, "login_token": dead}
    remote = {"kind": "remote", "server_token": ok, "login_token": bad}
    relay = {"kind": "relay", "server_token": ok, "login_token": ok}
    assert server.pick_row([local, remote, relay], "srv", "login") == (remote, "srv")
    only_login = {"kind": "remote", "server_token": bad, "login_token": ok}
    assert server.pick_row([local, only_login], "srv", "login") == (only_login, "login")
    assert server.pick_row([local], "srv", "login") == (None, None)


def test_connect_records_the_kind_of_address_used(config):
    res = resource(url="http://a:32400")
    saved = {"kind": "account", "name": "Home", "machine_id": "m1"}
    server.save(saved)
    with mock.patch.object(server, "account_servers", return_value=[res]), \
            mock.patch.object(server, "probe", return_value=(True, "ok")), \
            mock.patch.object(server, "PlexServer", side_effect=lambda u, t, **k: fake_plex(u)):
        server.connect_saved(saved, "tok")
    assert server.load_saved()["last_kind"] == "local"
    assert server.load_saved()["last_url"] == "http://a:32400"


def test_test_command_marks_the_address_that_would_be_used(config, capsys):
    res = resource(url="https://10-0-0-5.abc.plex.direct:32400")
    args = build_parser().parse_args(["server", "test", "Home"])
    with mock.patch.object(server, "account_servers", return_value=[res]), \
            mock.patch.object(server, "probe", return_value=(True, "ok")):
        args.run(args)
    assert "<- used" in capsys.readouterr().out


def test_show_displays_the_kind_of_the_last_address(config, capsys):
    server.save({"kind": "account", "name": "Home", "machine_id": "m1",
                 "last_url": "https://x:32400", "last_kind": "relay"})
    args = build_parser().parse_args(["server", "show"])
    args.run(args)
    assert "relay https://x:32400" in capsys.readouterr().out
