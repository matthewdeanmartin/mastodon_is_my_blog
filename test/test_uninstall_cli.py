import argparse
from pathlib import Path

import pytest

from mastodon_is_my_blog import uninstall_cli
from mastodon_is_my_blog.account_config import ConfiguredAccount


def make_args(dry_run: bool = False, yes: bool = False, keyring: bool = False, drop_db: bool = False) -> argparse.Namespace:
    return argparse.Namespace(dry_run=dry_run, yes=yes, keyring=keyring, drop_db=drop_db)


@pytest.fixture
def fake_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    data_dir = tmp_path / "appdata"
    data_dir.mkdir()
    (data_dir / "app.db").write_text("sqlite bits", encoding="utf-8")
    (data_dir / "accounts.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(uninstall_cli, "home_directories", lambda: [data_dir])
    monkeypatch.setattr(uninstall_cli, "list_keyring_entries", lambda: [])
    monkeypatch.setenv("DB_URL", f"sqlite+aiosqlite:///{data_dir / 'app.db'}")
    return data_dir


def test_dry_run_changes_nothing(fake_home: Path, capsys: pytest.CaptureFixture) -> None:
    result = uninstall_cli.run_uninstall(make_args(dry_run=True))

    assert result == 0
    assert fake_home.exists()
    out = capsys.readouterr().out
    assert str(fake_home) in out
    assert "Dry run — nothing was changed" in out
    assert "Step 1" in out
    assert "Step 2" in out
    assert "Step 3" in out


def test_yes_wipes_home_but_never_implies_keyring_or_postgres(fake_home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    monkeypatch.setattr(uninstall_cli, "list_keyring_entries", lambda: ["ALICE:access_token"])
    prompts: list[str] = []
    monkeypatch.setattr("mastodon_is_my_blog.cli.prompt_yes_no", lambda prompt, **kwargs: prompts.append(prompt) or True)

    result = uninstall_cli.run_uninstall(make_args(yes=True))

    assert result == 0
    assert not fake_home.exists()
    assert prompts == []  # --yes must never silently confirm the other steps
    out = capsys.readouterr().out
    assert "Step 2 skipped (pass --keyring to include it)." in out


def test_declining_the_prompt_keeps_everything(fake_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("mastodon_is_my_blog.cli.prompt_yes_no", lambda prompt, **kwargs: False)

    result = uninstall_cli.run_uninstall(make_args())

    assert result == 0
    assert fake_home.exists()


def test_keyring_entries_listed_and_wiped(fake_home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    deleted: list[tuple[str, str]] = []
    monkeypatch.setattr(uninstall_cli, "list_keyring_entries", lambda: ["ALICE:client_id", "ALICE:access_token"])
    monkeypatch.setattr(uninstall_cli, "delete_credential", lambda name, field_name: deleted.append((name, field_name)))

    result = uninstall_cli.run_uninstall(make_args(yes=True, keyring=True))

    assert result == 0
    assert deleted == [("ALICE", "client_id"), ("ALICE", "access_token")]
    out = capsys.readouterr().out
    assert "- ALICE:client_id" in out
    assert "- ALICE:access_token" in out


def test_custom_sqlite_file_outside_home_is_in_the_plan(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home"
    home.mkdir()
    elsewhere = tmp_path / "elsewhere" / "my.db"
    elsewhere.parent.mkdir()
    elsewhere.write_text("data", encoding="utf-8")
    monkeypatch.setenv("DB_URL", f"sqlite+aiosqlite:///{elsewhere}")

    assert uninstall_cli.custom_sqlite_file([home.resolve()]) == elsewhere.resolve()
    # Inside a wiped dir it must not be double-listed.
    inside = home / "app.db"
    inside.write_text("data", encoding="utf-8")
    monkeypatch.setenv("DB_URL", f"sqlite+aiosqlite:///{inside}")
    assert uninstall_cli.custom_sqlite_file([home.resolve()]) is None


def test_unreachable_postgres_is_reported_and_not_offered(fake_home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    monkeypatch.setenv("DB_URL", "postgresql+asyncpg://user:secret@127.0.0.1:1/mimb_gone")

    result = uninstall_cli.run_uninstall(make_args(yes=True))

    assert result == 0
    out = capsys.readouterr().out
    assert "Cannot connect" in out
    assert "Step 3 skipped: Postgres is configured but unreachable." in out
    assert "secret" not in out  # password never printed


def test_list_keyring_entries_probes_keyring_not_env(monkeypatch: pytest.MonkeyPatch) -> None:
    stored = {("mastodon_is_my_blog", "ALICE:access_token"): "tok"}

    class FakeKeyring:
        @staticmethod
        def get_password(service: str, username: str) -> str | None:
            return stored.get((service, username))

    monkeypatch.setitem(__import__("sys").modules, "keyring", FakeKeyring())
    monkeypatch.setattr(uninstall_cli, "load_configured_accounts", lambda: [ConfiguredAccount(name="ALICE", base_url="https://example.social")])

    assert uninstall_cli.list_keyring_entries() == ["ALICE:access_token"]
