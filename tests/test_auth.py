import json
import stat
from datetime import datetime
from types import SimpleNamespace as NS
from unittest import mock

import pytest

from plextool import auth, common
from plextool.cli import build_parser
from plextool.common import PlexToolError


@pytest.fixture
def config(tmp_path, monkeypatch):
    monkeypatch.setenv(auth.CONFIG_DIR_ENV, str(tmp_path / "cfg"))
    for name in (common.TOKEN_ENV, common.TOKEN_CMD_ENV):
        monkeypatch.delenv(name, raising=False)
    return tmp_path / "cfg"


def args(**kw):
    return NS(token=kw.get("token"), token_file=kw.get("token_file"))


def test_config_dir_override_and_xdg(monkeypatch, tmp_path):
    monkeypatch.setenv(auth.CONFIG_DIR_ENV, str(tmp_path / "x"))
    assert auth.config_dir() == tmp_path / "x"
    monkeypatch.delenv(auth.CONFIG_DIR_ENV)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert auth.config_dir() == tmp_path / "plextool"


def test_state_is_private(config):
    auth.save_state({"kind": "token", "token": "abc"})
    assert stat.S_IMODE((config / auth.STATE_FILE).stat().st_mode) == 0o600
    assert stat.S_IMODE(config.stat().st_mode) == 0o700
    assert auth.load_state()["token"] == "abc"


def test_stored_token_none_when_not_signed_in(config):
    assert auth.stored_token() is None


def test_stored_classic_token(config):
    auth.save_state({"kind": "token", "token": "abc"})
    assert auth.stored_token() == "abc"


def test_resolve_order(config, monkeypatch, tmp_path, capsys):
    auth.save_state({"kind": "token", "token": "saved"})
    assert common.resolve_token(args()) == ("saved", "saved login")
    monkeypatch.setenv(common.TOKEN_CMD_ENV, "echo fromcmd")
    assert common.resolve_token(args()) == ("fromcmd", "$PLEX_TOKEN_CMD")
    monkeypatch.setenv(common.TOKEN_ENV, "fromenv")
    assert common.resolve_token(args()) == ("fromenv", "$PLEX_TOKEN")
    f = tmp_path / "tok"
    f.write_text("fromfile\n")
    assert common.resolve_token(args(token_file=str(f))) == ("fromfile", "--token-file")
    assert common.resolve_token(args(token="flag")) == ("flag", "--token")
    assert "shell history" in capsys.readouterr().err


def test_resolve_errors(config, monkeypatch, tmp_path):
    with pytest.raises(PlexToolError, match="auth login"):
        common.resolve_token(args())
    empty = tmp_path / "empty"
    empty.write_text("\n")
    with pytest.raises(PlexToolError, match="empty"):
        common.resolve_token(args(token_file=str(empty)))
    with pytest.raises(PlexToolError, match="Could not read"):
        common.resolve_token(args(token_file=str(tmp_path / "missing")))
    monkeypatch.setenv(common.TOKEN_CMD_ENV, "false")
    with pytest.raises(PlexToolError, match="no token"):
        common.resolve_token(args())


def test_short_link_keeps_only_what_plex_needs():
    long = ("https://app.plex.tv/auth/#!?clientID=cid&context%5Bdevice%5D%5Bproduct%5D=plextool"
            "&context%5Bdevice%5D%5Bversion%5D=1&context%5Bdevice%5D%5Bplatform%5D=Linux&code=CODE")
    link = auth._short_link(long)
    assert "clientID=cid" in link and "code=CODE" in link and "plextool" in link
    assert "version" not in link and "platform" not in link


def test_wipe(config):
    for name in auth.ALL_FILES:
        (config).mkdir(parents=True, exist_ok=True)
        (config / name).write_bytes(b"x")
    auth.wipe(assume_yes=True)
    assert not config.exists()
    auth.wipe(assume_yes=True)  # nothing left: no error


def test_wipe_keeps_folder_with_other_files(config):
    config.mkdir(parents=True)
    (config / auth.STATE_FILE).write_text("{}")
    (config / "other").write_text("keep")
    auth.wipe(assume_yes=True)
    assert [p.name for p in config.iterdir()] == ["other"]


def test_status_never_prints_token(config, capsys):
    auth.save_state({"kind": "token", "token": "SECRET", "client_id": "cid"})
    auth.status()
    out = capsys.readouterr().out
    assert "SECRET" not in out and "classic" in out


def test_jwt_roundtrip_expiry(config):
    import jwt
    private, public = auth._new_keypair()
    assert len(private) == len(public) == 32
    token = jwt.encode({"exp": 2000000000}, "k" * 32, algorithm="HS256")
    assert auth._jwt_expiry(token).year == 2033
    assert auth._jwt_expiry("garbage") is None


def test_print_requires_token_type():
    args_ = build_parser().parse_args(["auth", "login", "--type", "jwt", "--print"])
    with pytest.raises(PlexToolError, match="--type token"):
        args_.run(args_)


def test_login_json_state_has_no_surprises(config):
    auth.save_state({"client_id": "c", "kind": "jwt", "token": "t"})
    assert set(json.loads((config / auth.STATE_FILE).read_text())) == {"client_id", "kind", "token"}


def test_login_type_choices():
    parse = build_parser().parse_args
    assert parse(["auth", "login"]).kind == "token"
    assert parse(["auth", "login", "--type", "jwt"]).kind == "jwt"
    with pytest.raises(SystemExit):
        parse(["auth", "login", "--type", "oauth"])


def test_link_trimmed_for_jwt_but_full_for_token(capsys):
    full = ("https://app.plex.tv/auth/#!?clientID=cid&context%5Bdevice%5D%5Bproduct%5D=plextool"
            "&context%5Bdevice%5D%5Bversion%5D=1&code=CODE")
    auth.show_link(full, "jwt")
    jwt_out = capsys.readouterr().out
    auth.show_link(full, "token")
    token_out = capsys.readouterr().out
    assert full not in jwt_out and "version" not in jwt_out
    assert full in token_out


def test_every_login_gets_a_new_device_id():
    ids = {auth._new_client_id() for _ in range(5)}
    assert len(ids) == 5


def test_saved_jwt_device_id_is_sent_with_requests(config):
    import plexapi
    before = plexapi.BASE_HEADERS["X-Plex-Client-Identifier"]
    try:
        auth.save_state({"kind": "jwt", "client_id": "dev-1", "token": "t"})
        auth.use_saved_identity()
        assert plexapi.BASE_HEADERS["X-Plex-Client-Identifier"] == "dev-1"
        auth.save_state({"kind": "token", "client_id": "dev-2", "token": "t"})
        auth.use_saved_identity()
        assert plexapi.BASE_HEADERS["X-Plex-Client-Identifier"] == "dev-1"  # classic tokens don't need it
    finally:
        plexapi.BASE_HEADERS["X-Plex-Client-Identifier"] = before


# ---------------------------------------------------------------------------
# Devices on the account
# ---------------------------------------------------------------------------

def device(cid, product="plextool", seen=(2026, 11, 2), deleted=None, fail=False):
    def delete():
        if fail:
            raise auth.BadRequest("nope")
        deleted.append(cid)
    return NS(clientIdentifier=cid, product=product, name=f"{product} on host", id=cid,
              createdAt=datetime(2026, 11, 1), lastSeenAt=datetime(*seen), delete=delete)


def run_cmd(argv, devices, config_state=None):
    args = build_parser().parse_args(argv)
    with mock.patch.object(auth, "MyPlexAccount") as account:
        account.return_value.devices.return_value = devices
        return args.run(args)


@pytest.fixture
def signed_in(config, monkeypatch):
    monkeypatch.setenv(common.TOKEN_ENV, "tok")
    auth.save_state({"kind": "token", "client_id": "aaaaaaaa-current", "token": "t"})


def test_devices_lists_only_plextool_and_marks_current(signed_in, capsys):
    gone = []
    devs = [device("aaaaaaaa-current", deleted=gone), device("bbbbbbbb-old", seen=(2026, 10, 1), deleted=gone),
            device("cccccccc-tv", product="Plex for LG", deleted=gone)]
    run_cmd(["auth", "devices"], devs)
    out = capsys.readouterr().out
    assert "aaaaaaaa" in out and "bbbbbbbb" in out and "cccccccc" not in out
    assert "this login" in out
    assert out.index("aaaaaaaa") < out.index("bbbbbbbb")  # newest first


def test_devices_all_shows_other_products(signed_in, capsys):
    run_cmd(["auth", "devices", "--all"], [device("cccccccc-tv", product="Plex for LG", deleted=[])])
    assert "Plex for LG" in capsys.readouterr().out


def test_revoke_others_is_a_dry_run_by_default(signed_in, capsys):
    gone = []
    devs = [device("aaaaaaaa-current", deleted=gone), device("bbbbbbbb-old", deleted=gone)]
    run_cmd(["auth", "revoke", "--others"], devs)
    assert gone == []
    out = capsys.readouterr().out
    assert "Would remove 1 device" in out and "Dry run" in out


def test_revoke_others_commit_spares_current_and_other_apps(signed_in, capsys):
    gone = []
    devs = [device("aaaaaaaa-current", deleted=gone), device("bbbbbbbb-old", deleted=gone),
            device("cccccccc-tv", product="Plex for LG", deleted=gone)]
    run_cmd(["auth", "revoke", "--others", "--commit"], devs)
    assert gone == ["bbbbbbbb-old"]


def test_revoke_by_id_prefix_and_this(signed_in, capsys):
    gone = []
    devs = [device("aaaaaaaa-current", deleted=gone), device("bbbbbbbb-old", deleted=gone)]
    run_cmd(["auth", "revoke", "bbbb", "--commit"], devs)
    assert gone == ["bbbbbbbb-old"]
    gone.clear()
    run_cmd(["auth", "revoke", "--this", "--commit"], devs)
    assert gone == ["aaaaaaaa-current"]
    out = capsys.readouterr().out
    assert "plex.tv will stop accepting" in out
    assert "can keep accepting it for a while" in out


def test_revoke_refuses_other_products_and_bad_ids(signed_in):
    devs = [device("cccccccc-tv", product="Plex for LG", deleted=[]), device("dddd1111", deleted=[]),
            device("dddd2222", deleted=[])]
    with pytest.raises(PlexToolError, match="No plextool device starts with 'cccc'"):
        run_cmd(["auth", "revoke", "cccc", "--commit"], devs)
    with pytest.raises(PlexToolError, match="matches 2 devices"):
        run_cmd(["auth", "revoke", "dddd", "--commit"], devs)


def test_revoke_needs_a_selection(signed_in):
    with pytest.raises(PlexToolError, match="Say what to remove"):
        run_cmd(["auth", "revoke"], [])


def test_revoke_reports_a_failed_removal(signed_in, capsys):
    run_cmd(["auth", "revoke", "bbbb", "--commit"], [device("bbbbbbbb-old", fail=True)])
    assert "could not remove" in capsys.readouterr().out
