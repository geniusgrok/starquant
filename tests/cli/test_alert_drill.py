"""`starquant live alert-test`: AC-L3 asks for a drill alert and there was no way to send one.

The only path to the alert channel was a real failure - the check job noticing something wrong, or
the breaker tripping.  So the one thing the breaker's clean exit depends on could not be exercised
without first breaking something, which is why it had never been exercised at all.

With one channel (operator ruling, 2026-09-07) this command is the whole verification instrument, so
it has to be honest in both directions: non-zero when nothing landed, and explicit that a suppressed
duplicate is not a delivery.
"""

from __future__ import annotations

import httpx
from click.testing import CliRunner

from starquant_cli import main


def _profile(tmp_path, url: str) -> str:
    path = tmp_path / "profile.yaml"
    path.write_text(
        "profile: test\nalerts:\n  webhook_url: " + f'"{url}"\n  dedup_window_seconds: 3600\n',
        encoding="utf-8",
    )
    return str(path)


def test_a_drill_that_lands_exits_zero(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import starquant_cli.live_cmd as live_cmd

    monkeypatch.setattr(
        live_cmd, "alert_transport", lambda: httpx.MockTransport(lambda r: httpx.Response(200, json={"code": 0}))
    )
    result = CliRunner().invoke(
        main, ["live", "alert-test", "--profile", _profile(tmp_path, "https://open.feishu.cn/x")]
    )

    assert result.exit_code == 0, result.output
    assert "已送达" in result.output


def test_a_drill_the_provider_drops_exits_non_zero(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """The case this exists for: HTTP 200 and the message is gone."""
    import starquant_cli.live_cmd as live_cmd

    monkeypatch.setattr(
        live_cmd,
        "alert_transport",
        lambda: httpx.MockTransport(lambda r: httpx.Response(200, json={"code": 19001, "msg": "param invalid"})),
    )
    result = CliRunner().invoke(
        main, ["live", "alert-test", "--profile", _profile(tmp_path, "https://open.feishu.cn/x")]
    )

    assert result.exit_code != 0
    assert "未送达" in result.output


def test_no_channel_configured_is_a_failure_not_a_pass(tmp_path) -> None:  # type: ignore[no-untyped-def]
    result = CliRunner().invoke(main, ["live", "alert-test", "--profile", _profile(tmp_path, "")])

    assert result.exit_code != 0
    assert "没有配置告警通道" in result.output


def test_the_drill_says_which_url_and_never_prints_it_whole(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """A webhook URL is a credential: whoever holds it can post as the bot."""
    import starquant_cli.live_cmd as live_cmd

    secret = "https://open.feishu.cn/open-apis/bot/v2/hook/SUPER-SECRET-TOKEN-VALUE"
    monkeypatch.setattr(
        live_cmd, "alert_transport", lambda: httpx.MockTransport(lambda r: httpx.Response(200, json={"code": 0}))
    )
    result = CliRunner().invoke(main, ["live", "alert-test", "--profile", _profile(tmp_path, secret)])

    assert result.exit_code == 0, result.output
    assert "open.feishu.cn" in result.output
    assert "SUPER-SECRET-TOKEN-VALUE" not in result.output


def test_repeating_the_drill_shows_the_dedup_window(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """AC-L3's second half: 10 triggers, 1 message."""
    import starquant_cli.live_cmd as live_cmd

    posts: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        posts.append(1)
        return httpx.Response(200, json={"code": 0})

    monkeypatch.setattr(live_cmd, "alert_transport", lambda: httpx.MockTransport(handler))
    result = CliRunner().invoke(
        main, ["live", "alert-test", "--profile", _profile(tmp_path, "https://open.feishu.cn/x"), "--repeat", "10"]
    )

    assert result.exit_code == 0, result.output
    assert len(posts) == 1
    assert "9 条因去重窗口被抑制" in result.output
