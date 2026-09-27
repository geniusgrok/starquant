"""One channel, so "delivered" has to mean delivered.

The operator ruled on 2026-09-07 that a second webhook is not wanted and the Lark channel is the one
to make good.  That ruling removes the redundancy DL-L3 was built on and puts all of the weight on a
single return value: `send()` -> True is the only thing standing between the breaker exiting quietly
and a book that stops without saying so (RISK-P1 / KILL-P1).

That return value was `response.status_code < 300`, and the channel is a Lark custom bot, which
answers **HTTP 200 with an error body** when it does not understand the payload:

    {"code": 19001, "msg": "param invalid"}     <- HTTP 200

So a wrong payload shape reads as success.  Nothing in this repository's logs shows an alert ever
being attempted, delivered or rejected, so whether the one channel has EVER worked was unverified at
the time these tests were written - which is the reason they exist rather than a footnote to them.

The rule added here is deliberately narrow: when a provider states its own result, believe the
provider; when it does not, keep trusting the status code.  It can only turn a false success into a
failure, never the reverse.
"""

from __future__ import annotations

import httpx
import pytest

from starquant_live.alerts import WebhookAlerts


def _transport(*responses: httpx.Response) -> httpx.MockTransport:
    queue = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        return queue.pop(0) if queue else httpx.Response(200, json={"code": 0})

    return httpx.MockTransport(handler)


async def test_a_lark_error_body_under_http_200_is_not_a_delivery() -> None:
    alerts = WebhookAlerts(
        "https://open.larksuite.com/x",
        transport=_transport(httpx.Response(200, json={"code": 19001, "msg": "param invalid"})),
    )

    assert await alerts.send("hello") is False


async def test_a_lark_success_body_is_a_delivery() -> None:
    alerts = WebhookAlerts(
        "https://open.larksuite.com/x",
        transport=_transport(httpx.Response(200, json={"code": 0, "msg": "success"})),
    )

    assert await alerts.send("hello") is True


async def test_the_other_spelling_is_read_too() -> None:
    """Lark answers `StatusCode` on some endpoints and `code` on others."""
    alerts = WebhookAlerts(
        "https://open.larksuite.com/x",
        transport=_transport(httpx.Response(200, json={"StatusCode": 9499, "StatusMessage": "bad"})),
    )

    assert await alerts.send("hello") is False


async def test_a_provider_that_says_nothing_is_still_trusted_on_its_status() -> None:
    """Slack answers `ok` in plain text; Discord answers 204 with no body at all."""
    for response in (httpx.Response(200, text="ok"), httpx.Response(204)):
        alerts = WebhookAlerts("https://hooks.slack.com/x", transport=_transport(response))

        assert await alerts.send("hello") is True


async def test_a_non_json_error_body_still_fails_on_status() -> None:
    alerts = WebhookAlerts("https://x/y", transport=_transport(httpx.Response(500, text="boom")))

    assert await alerts.send("hello") is False


async def test_the_payload_is_the_shape_lark_documents() -> None:
    """`{"text": ...}` is Slack's shape.  A Lark custom bot wants msg_type/content.

    Sending one shape to both is how the single channel could have been silently dead: Slack accepts
    the flat form, Lark answers 200 and drops it.
    """
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json as _json

        seen.append(_json.loads(request.content))
        return httpx.Response(200, json={"code": 0})

    alerts = WebhookAlerts(
        "https://open.larksuite.com/open-apis/bot/v2/hook/abc", transport=httpx.MockTransport(handler)
    )
    await alerts.send("hello")

    assert seen[0] == {"msg_type": "text", "content": {"text": "hello"}}


async def test_a_non_lark_url_keeps_the_flat_shape() -> None:
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json as _json

        seen.append(_json.loads(request.content))
        return httpx.Response(200, text="ok")

    alerts = WebhookAlerts("https://hooks.slack.com/services/x", transport=httpx.MockTransport(handler))
    await alerts.send("hello")

    assert seen[0] == {"text": "hello"}


@pytest.mark.parametrize("host", ["open.larksuite.com", "open.feishu.cn"])
async def test_both_lark_hosts_are_recognised(host: str) -> None:
    from starquant_live.alerts import payload_for

    assert payload_for(f"https://{host}/open-apis/bot/v2/hook/x", "hi") == {
        "msg_type": "text",
        "content": {"text": "hi"},
    }
