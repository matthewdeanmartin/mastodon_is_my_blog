from __future__ import annotations

import pytest

from mastodon_is_my_blog import cli
from mastodon_is_my_blog.account_config import normalize_base_url


def test_main_starts_without_forcing_init_when_no_accounts(monkeypatch) -> None:
    """A clean machine must never be interrogated for client IDs: `mimb start`
    just starts, and onboarding happens in the web UI (Connect Account)."""
    events: list[str] = []

    monkeypatch.setattr(cli, "run_init_command", lambda: events.append("init"))
    monkeypatch.setattr(
        cli,
        "start_server",
        lambda host, port, reload_, workers, no_open: events.append(f"start:{host}:{port}:{reload_}:{workers}:{no_open}"),
    )

    result = cli.main(["start", "--port", "9000", "--no-open"])

    assert result == 0
    assert events == ["start:127.0.0.1:9000:False:1:True"]


def test_main_init_runs_even_when_accounts_exist(monkeypatch) -> None:
    events: list[str] = []

    monkeypatch.setattr(cli, "run_init_command", lambda: events.append("init"))

    result = cli.main(["init"])

    assert result == 0
    assert events == ["init"]


def test_version_flag(capsys) -> None:
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["--version"])
    assert excinfo.value.code == 0
    out = capsys.readouterr().out.strip()
    assert out  # prints the installed version
    assert out[0].isdigit()


def test_version_subcommand_still_works(capsys) -> None:
    assert cli.main(["version"]) == 0
    assert capsys.readouterr().out.strip()


@pytest.mark.parametrize(
    ("typed", "expected"),
    [
        ("https://mastodon.social", "https://mastodon.social"),
        ("https://mastodon.social/", "https://mastodon.social"),
        ("http://mock.local", "http://mock.local"),
        ("mastodon.social", "https://mastodon.social"),
        ("mistersql@mastodon.social", "https://mastodon.social"),
        ("@mistersql@mastodon.social", "https://mastodon.social"),
    ],
)
def test_normalize_base_url_is_forgiving(typed: str, expected: str) -> None:
    assert normalize_base_url(typed) == expected


@pytest.mark.parametrize("typed", ["", "   ", "https://", "@"])
def test_normalize_base_url_rejects_garbage(typed: str) -> None:
    with pytest.raises(ValueError):
        normalize_base_url(typed)


def make_summary(name: str = "MAIN"):
    from mastodon_is_my_blog.account_config import ConfiguredAccountSummary

    return ConfiguredAccountSummary(
        name=name,
        base_url="https://mastodon.social",
        has_client_id=True,
        has_client_secret=True,
        has_access_token=True,
    )


async def noop_sync() -> None:
    return None


def test_init_with_accounts_lists_and_never_prompts_for_keys(monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "list_account_summaries", lambda: [make_summary()])
    monkeypatch.setattr(cli, "prompt_yes_no", lambda *a, **k: False)
    monkeypatch.setattr(cli, "sync_identity_state", noop_sync)

    cli.run_init_command()

    out = capsys.readouterr().out
    assert "MAIN" in out
    assert "mimb auth" in out
    assert "Client ID" not in out


def test_init_with_no_accounts_offers_oauth_login(monkeypatch, capsys) -> None:
    from mastodon_is_my_blog import auth_cli

    answers = iter([False, True])  # don't change db; yes, connect now
    logins: list = []
    monkeypatch.setattr(cli, "list_account_summaries", lambda: [])
    monkeypatch.setattr(cli, "prompt_yes_no", lambda *a, **k: next(answers))
    monkeypatch.setattr(cli, "sync_identity_state", noop_sync)
    monkeypatch.setattr(auth_cli, "run_login", lambda handle, **kw: logins.append(handle) or "MAIN")

    cli.run_init_command()

    assert logins == [None]
    assert "Client ID" not in capsys.readouterr().out


@pytest.mark.parametrize(
    ("typed", "expected"),
    [
        ("postgresql://u:p@localhost:5432/mimb", "postgresql+asyncpg://u:p@localhost:5432/mimb"),
        ("postgres://u@h/db", "postgresql+asyncpg://u@h/db"),
        ("postgresql+asyncpg://u@h/db", "postgresql+asyncpg://u@h/db"),
    ],
)
def test_normalize_postgres_url(typed: str, expected: str) -> None:
    assert cli.normalize_postgres_url(typed) == expected


def test_normalize_postgres_url_rejects_non_postgres() -> None:
    with pytest.raises(ValueError):
        cli.normalize_postgres_url("mysql://nope")


def test_admin_publish_doctor_parser_wiring() -> None:
    parser = cli.build_parser()

    args = parser.parse_args(["admin", "sync", "--no-force", "--account", "MAIN"])
    assert (args.command, args.admin_command, args.no_force, args.account) == ("admin", "sync", True, "MAIN")

    args = parser.parse_args(["admin", "catchup", "--mode", "trickle", "--max-accounts", "5"])
    assert (args.admin_command, args.mode, args.max_accounts) == ("catchup", "trickle", 5)

    for name in ["download-friends", "download-notifications", "rebin", "backfill-flags", "nlp-backfill"]:
        assert parser.parse_args(["admin", name]).admin_command == name

    args = parser.parse_args(["publish", "--build-only", "--pages-workflow", "-m", "hi"])
    assert (args.command, args.build_only, args.pages_workflow, args.message) == ("publish", True, True, "hi")

    assert parser.parse_args(["doctor"]).command == "doctor"


def test_doctor_dispatch(monkeypatch) -> None:
    from mastodon_is_my_blog import admin_cli

    monkeypatch.setattr(admin_cli, "run_doctor_command", lambda: 0)
    assert cli.main(["doctor"]) == 0


def test_write_db_url_to_env(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DB_URL", "placeholder")  # so monkeypatch restores it after
    cli.write_db_url_to_env("postgresql+asyncpg://u@h/db")
    env_text = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "DB_URL" in env_text
    assert "postgresql+asyncpg://u@h/db" in env_text
    import os

    assert os.environ["DB_URL"] == "postgresql+asyncpg://u@h/db"
