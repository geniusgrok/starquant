"""Optional webhook alerts (Slack/Telegram-style JSON POST).  Empty URL = disabled.

Two properties an unattended loop needs from its only output channel, added 2026-09-06 (DL-L3):

*Deduplication.*  A repeated alert is how the one that matters gets missed - measured in this repo's
own logs as 36 identical FAIL lines over 36 hours, unhandled (KILL-R7).  The same alert is sent once
per ``dedup_window_seconds``; a standing problem still re-announces itself hourly rather than never,
and ``clear`` re-arms a key when the condition it describes goes away.  The window is measured from
when the CALLER asked, against a window strictly shorter than any caller's period, and each persisted
row carries a wall reading beside its monotonic one - three corrections to the same mistake, that an
interval between two numbers is only a duration if both were read off the same clock.

*A second channel.*  One URL is a single point of silence.  Both are tried, and delivery to either
counts - which matters because the breaker (DL-L2) now stops the loop cleanly, and it is only
allowed to do that if it can first say so out loud.  ``force`` bypasses dedup for exactly that case,
and the return value is what lets the caller refuse to exit quietly.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)


# The window has to be strictly SHORTER than the cadence of whoever is calling, or a standing problem
# is announced on a coin flip.  Every caller here runs hourly at the fastest - the check job on the
# hour, the loop once a bar - and neither lands on an exact 3600s grid: the loop's cycles start a few
# seconds apart, and a delivery takes as long as the provider takes.  Measured 2026-09-14 against a
# 3600s window: the same hourly FAIL was delivered at 10:10Z and 11:10Z and dropped at 12:10Z, which
# was the one that day the operator needed.  A minute of margin still re-announces every hour.
HOURLY_CALLER_WINDOW_SECONDS = 3540.0


# Lark/Feishu custom bots take `{"msg_type": "text", "content": {"text": ...}}`; Slack and most
# generic relays take the flat `{"text": ...}`.  Sending one shape to both is how a channel dies
# quietly: Slack accepts the flat form, and Lark answers HTTP 200 and drops it.
LARK_HOSTS = ("open.larksuite.com", "open.feishu.cn")


def payload_for(url: str, text: str) -> dict[str, object]:
    """The body this provider actually reads."""
    host = urlparse(url).netloc.lower()
    if any(host == known or host.endswith(f".{known}") for known in LARK_HOSTS):
        return {"msg_type": "text", "content": {"text": text}}
    return {"text": text}


def accepted(response: httpx.Response) -> bool:
    """Did the provider say it took the message?

    A status code is the weakest possible evidence here, and for this repository's one channel it is
    the wrong evidence: a Lark custom bot answers HTTP 200 with `{"code": 19001}` when it cannot read
    the payload, so `status_code < 300` reads a dropped message as a delivery - and the breaker is
    allowed to exit quietly on exactly that boolean (RISK-P1).

    The rule is narrow on purpose: when the provider states its own result, believe the provider; when
    it does not, keep trusting the status.  It can turn a false success into a failure, never the
    reverse.
    """
    if response.status_code >= 300:
        return False
    try:
        body = response.json()
    except ValueError:
        return True
    if not isinstance(body, dict):
        return True
    for field in ("code", "StatusCode"):
        value = body.get(field)
        if isinstance(value, int):
            return value == 0
    return True


class WebhookAlerts:
    def __init__(
        self,
        url: str = "",
        timeout: float = 10.0,
        *,
        secondary_url: str = "",
        dedup_window_seconds: float = HOURLY_CALLER_WINDOW_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
        transport: httpx.AsyncBaseTransport | None = None,
        state_path: Path | None = None,
    ) -> None:
        self.url = url.strip()
        self.secondary_url = secondary_url.strip()
        self._timeout = timeout
        self._window = float(dedup_window_seconds)
        self._clock = clock
        # `clock` is monotonic so that nothing inside one process's life depends on the wall clock.
        # But monotonic counts from the machine's last BOOT, and the state file below outlives boots,
        # so a stored number means nothing on its own - it is kept beside the wall time it was written
        # at, and a row is only evidence if both readings agree it is recent.  See `_load_state`.
        self._wall_clock = wall_clock
        self._transport = transport
        # DL-L3's other half.  KILL-R7's evidence was 36 identical FAIL lines over 36 hours, and those
        # came from the HOURLY CHECK JOB - a fresh process every hour, whose in-memory dedup dict is
        # empty every time and can suppress nothing.  Dedup that only works inside one long-lived
        # process is dedup aimed away from the case that produced the finding.
        #
        # A cache, not a ledger: it may never be the reason a message does not go out, so every read
        # and write of it is allowed to fail quietly and cost at most one duplicate.
        self._state_path = Path(state_path) if state_path is not None else None
        self._last_sent: dict[str, float] = self._load_state()

    def _load_state(self) -> dict[str, float]:
        """The rows this process may use as evidence that a delivery already happened.

        A row is kept only if BOTH clocks put it inside the window.  The monotonic reading is the one
        `_suppressed` subtracts; the wall reading is what says the monotonic one belongs to this boot
        at all.  Measured 2026-09-14, with only the first: after the 2026-09-10 reboot `check-verify`
        held 630465.2 against an uptime of 374798.0, so `clock() - last` was -255667 - below any
        window, with no path back.  24 of that key's 28 FAIL lines were never delivered and it had 71
        hours left to run.  The same error points the other way too: a previous boot SHORTER than this
        one leaves a number that reads as a recent delivery and suppresses a real alert.

        Everything else is dropped - a pre-2026-09-14 bare number, a half-written row, a clock that
        moved.  Dropping costs one duplicate; keeping costs the silence this docstring is about.
        """
        if self._state_path is None or not self._state_path.exists():
            return {}
        try:
            payload = json.loads(self._state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if not isinstance(payload, dict):
            return {}
        now, wall_now = self._clock(), self._wall_clock()
        kept: dict[str, float] = {}
        for key, row in payload.items():
            if not isinstance(row, dict):
                continue
            at, wall = row.get("at"), row.get("wall")
            if not (isinstance(at, (int, float)) and isinstance(wall, (int, float))):
                continue
            if 0.0 <= now - at <= self._window and 0.0 <= wall_now - wall <= self._window:
                kept[str(key)] = float(at)
        return kept

    def _save_state(self) -> None:
        if self._state_path is None:
            return
        now, wall_now = self._clock(), self._wall_clock()
        payload = {key: {"at": at, "wall": wall_now - (now - at)} for key, at in self._last_sent.items()}
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            self._state_path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        except OSError as exc:
            logger.warning("could not persist the alert dedup state (%s): a duplicate may follow", exc)

    @property
    def enabled(self) -> bool:
        return bool(self.url or self.secondary_url)

    @property
    def urls(self) -> tuple[str, ...]:
        return tuple(u for u in (self.url, self.secondary_url) if u)

    def clear(self, key: str) -> None:
        """Forget a key so the next alert under it fires: the condition it described has cleared."""
        if self._last_sent.pop(key, None) is not None:
            self._save_state()

    def _suppressed(self, key: str) -> bool:
        last = self._last_sent.get(key)
        return last is not None and (self._clock() - last) < self._window

    async def send(self, text: str, *, key: str | None = None, force: bool = False) -> bool:
        """Deliver ``text``; return True only if a channel accepted it.

        A suppressed duplicate returns False - it was not delivered, and a caller that needs to know
        its message got out (the breaker) can tell the difference.
        """
        if not self.enabled:
            return False
        fingerprint = key if key is not None else text
        if not force and self._suppressed(fingerprint):
            logger.debug("alert suppressed as a duplicate: %s", fingerprint)
            return False
        # The window measures the CALLER's cadence, so it runs from the moment the caller asked, not
        # from whenever the provider got back to us.  Remembering the later instant shortens the next
        # gap by however long delivery took, which is enough to push an hourly caller's next attempt
        # inside the window: measured 2026-09-14, an 8-second delivery at 11:10Z dropped 12:10Z's.
        asked = self._clock()
        delivered = False
        async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
            for url in self.urls:
                try:
                    response = await client.post(url, json=payload_for(url, text))
                except httpx.HTTPError as exc:
                    logger.warning("alert delivery failed (%s): %s", url, exc)
                    continue
                if accepted(response):
                    delivered = True
                else:
                    logger.warning("alert rejected by %s: HTTP %s %s", url, response.status_code, response.text[:200])
        if delivered:
            self._last_sent[fingerprint] = asked
            self._save_state()
        return delivered
