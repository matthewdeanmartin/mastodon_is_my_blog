from __future__ import annotations

from mastodon_is_my_blog import cli


def test_main_runs_init_before_start_when_no_accounts(monkeypatch) -> None:
    events: list[str] = []

    monkeypatch.setattr(cli, "has_configured_identities", lambda: False)
    monkeypatch.setattr(cli, "run_init_command", lambda: events.append("init"))
    monkeypatch.setattr(
        cli,
        "start_server",
        lambda host, port, reload_, workers: events.append(
            f"start:{host}:{port}:{reload_}:{workers}"
        ),
    )

    result = cli.main(["start", "--port", "9000"])

    assert result == 0
    assert events == ["init", "start:127.0.0.1:9000:False:1"]


def test_main_init_runs_even_when_accounts_exist(monkeypatch) -> None:
    events: list[str] = []

    monkeypatch.setattr(cli, "has_configured_identities", lambda: True)
    monkeypatch.setattr(cli, "run_init_command", lambda: events.append("init"))

    result = cli.main(["init"])

    assert result == 0
    assert events == ["init"]
