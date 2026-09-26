"""L3's criterion, computed - and computed twice, because §5 states it two ways that disagree.

Nothing read `.starquant/paper-l3` until 2026-09-09.  The soak ran, launchd kept it alive, and the
criterion it was running against lived only in prose.

**The two readings.**  §5's L3 row says "7 天无 ERROR 相".  The Testnet paragraph of the same section
says "到币安的路径经系统代理 1082，间歇 503——ERROR 相**不产生任何治理决定**", and KILL-AR-20 turned
that into `Policy.no_decision_phases`.  Those are not two wordings of one rule.  The first counts
ERROR cycles; the second says an ERROR cycle is a cycle that decided nothing, which is a statement
about consequences.  Measured on the armed record 2026-09-09: 2 ERROR cycles in 6.29 days, rate
0.318/day, longest clean run 4.92 days, and **both ERROR cycles produced zero governance side effect**
- no orders, nothing leaving, nothing quarantined, the ladder untouched, no universe update.

Under a Poisson fit that rate gives a 10.8% chance of seven consecutive clean days, 1.2% of fourteen,
0.03% of thirty.  So the literal reading is not a demanding criterion, it is a mostly unreachable one,
and it is unreachable for a reason §5 itself names two paragraphs later.  This module reports both and
rules on neither: `literal_pass` and `no_decision_pass`, side by side, with the counts under each.

A third number is reported because neither reading covers it: the longest ERROR STREAK.  One 503 is
the proxy blinking; six hours of them is the venue being unreachable, and only the second is a fact
about whether this deployment works.

**Ruled 2026-09-10.**  The gate is the no-decision reading AND a bar on that streak; the literal count
stays computed and printed and gates nothing.

Why the no-decision reading, stated so it is not mistaken for picking the criterion that passes: only
one of the two sentences has a mechanism behind it.  `no_decision_phases` exists, is enforced, and is
falsifiable per cycle - an ERROR cycle that placed an order, quarantined a sleeve or moved the ladder
fails it and the row says so.  The literal count has no mechanism; it tallies a phase whose meaning is
"the loop declined to act on bad data", which is the loop working.  The contradiction in §5 predates
every measurement here.

And the criterion is made HARDER where it was blind.  Six hours of 503s decide nothing either, so the
no-decision reading alone cannot see an outage.  The streak bar is `STUCK_IN_ERROR_STREAK` - the same
3 that `live status --check` already pages on - rather than a number chosen here: a week that held an
incident the hourly check was alerting about is not a week that proved unattended operation.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from starquant_live.health import STUCK_IN_ERROR_STREAK

#: What a cycle must not have done to count as having decided nothing.  Each is a governance action
#: the loop can take on its own; an ERROR cycle that took one would be KILL-AR-20 failing in practice.
DECISION_KEYS = ("orders", "leaving", "quarantined", "universe_update", "risk_ladder")


def no_decisions() -> dict[str, Any]:
    """An ERROR row's decision keys, all empty.

    The writer is `engine.guarded_cycle`, a thousand lines from `_decided`, and it used to build the
    ERROR row from scratch with `orders` hardcoded to `[]` and the other four absent - so `_decided`
    returned `()` on every engine-produced row and the gate could not fail.  Both halves now name this
    one function, so a sixth key cannot be added to the reader without the writer gaining it too.
    """
    return {"orders": [], "leaving": [], "quarantined": [], "universe_update": None, "risk_ladder": {}}


@dataclass(frozen=True)
class SoakReading:
    cycles: int = 0
    days: float = 0.0
    required_days: float = 7.0
    error_cycles: int = 0
    skipped_cycles: int = 0
    longest_error_streak: int = 0
    max_error_streak: int = STUCK_IN_ERROR_STREAK
    longest_clean_days: float = 0.0
    deciding_errors: tuple[str, ...] = ()
    transactions_closed: bool | None = None
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def long_enough(self) -> bool:
        return self.days >= self.required_days

    @property
    def literal_pass(self) -> bool:
        """§5 L3 as written: seven days and not one ERROR phase."""
        return self.long_enough and self.error_cycles == 0 and self.transactions_closed is not False

    @property
    def no_decision_pass(self) -> bool:
        """§5's Testnet clause: seven days in which no ERROR cycle decided anything."""
        return self.long_enough and not self.deciding_errors and self.transactions_closed is not False

    @property
    def streak_pass(self) -> bool:
        """No run of ERROR cycles long enough for the hourly check to have called the loop stuck."""
        return self.longest_error_streak < self.max_error_streak

    @property
    def passes(self) -> bool:
        """L3 as ruled on 2026-09-10.  This is the one `--check` gates on."""
        return self.no_decision_pass and self.streak_pass


def _acted(key: str, value: Any) -> bool:
    """Did this key record an action, as opposed to a reading?

    Presence is not the question - `key in row` calls every cycle a decision - but neither is emptiness
    for two of the five, and that only became reachable when the ERROR path started carrying them.

    `risk_ladder` is never `{}`: `_risk_ladder` returns ten keys on the quietest cycle, including
    `acting: False`.  The ladder DECIDED when it acted; that it computed a reading is the loop
    measuring itself, which is the thing KILL-AR-20 says must not retire a book.

    `universe_update` is `None` on nearly every cycle, but under a pinned universe it writes
    `adopted: False` once a UTC day - the proposal recorded deliberately and deliberately not taken -
    and on a failed refresh it writes `error` while keeping the previous pool.  Neither changed what is
    traded, so neither is a decision.

    The other three are lists, and for them emptiness is exactly right.
    """
    if not isinstance(value, Mapping):
        return bool(value)
    if key == "risk_ladder":
        return bool(value.get("acting"))
    if key == "universe_update":
        return bool(value) and not value.get("error") and value.get("adopted", True)
    return bool(value)


def _decided(row: Mapping[str, Any]) -> tuple[str, ...]:
    """What a cycle did that a no-decision cycle must not have done."""
    return tuple(key for key in DECISION_KEYS if _acted(key, row.get(key)))


def score(
    cycles: Sequence[Mapping[str, Any]],
    *,
    required_days: float = 7.0,
    transactions_closed: bool | None = None,
    no_decision_phases: Sequence[str] = ("ERROR",),
) -> SoakReading:
    """Both readings of L3 over one soak's record."""
    if not cycles:
        return SoakReading(required_days=required_days, notes=("the record is empty",))

    stamps: list[datetime] = []
    for row in cycles:
        try:
            stamps.append(datetime.fromisoformat(str(row.get("at"))))
        except ValueError:
            # Carry the previous stamp forward: one unreadable row inside a soak is a torn write, not a
            # reason to refuse the whole reading.  An unreadable FIRST row is different - there is no
            # previous stamp, and inventing an epoch would silently make `days` enormous and pass a
            # criterion about seven days on a record that cannot say when it started.
            if not stamps:
                return SoakReading(
                    cycles=len(cycles),
                    required_days=required_days,
                    transactions_closed=transactions_closed,
                    notes=(
                        f"the first cycle's timestamp is unreadable ({row.get('at')!r}); no window can be measured",
                    ),
                )
            stamps.append(stamps[-1])
    days = (stamps[-1] - stamps[0]).total_seconds() / 86_400.0

    errors = [i for i, row in enumerate(cycles) if str(row.get("phase")) in set(no_decision_phases)]
    skipped = sum(1 for row in cycles if str(row.get("phase")) == "SKIPPED")

    streak = longest = 0
    for row in cycles:
        streak = streak + 1 if str(row.get("phase")) in set(no_decision_phases) else 0
        longest = max(longest, streak)

    marks = [stamps[0], *[stamps[i] for i in errors], stamps[-1]]
    clean = max((marks[i + 1] - marks[i]).total_seconds() / 86_400.0 for i in range(len(marks) - 1))

    deciding = tuple(f"{cycles[i].get('at')}: {', '.join(_decided(cycles[i]))}" for i in errors if _decided(cycles[i]))
    notes: list[str] = []
    if errors and not deciding:
        notes.append(f"{len(errors)} ERROR cycles, none of which decided anything (KILL-AR-20's shape)")
    if longest >= STUCK_IN_ERROR_STREAK:
        notes.append(
            f"longest ERROR streak {longest} >= {STUCK_IN_ERROR_STREAK}: this is the run `live status "
            "--check` calls the loop stuck, and L3 does not pass a week that held one"
        )
    elif longest > 1:
        notes.append(f"longest ERROR streak {longest}: a run is the venue being unreachable, not a blink")
    return SoakReading(
        cycles=len(cycles),
        days=days,
        required_days=required_days,
        error_cycles=len(errors),
        skipped_cycles=skipped,
        longest_error_streak=longest,
        longest_clean_days=clean,
        deciding_errors=deciding,
        transactions_closed=transactions_closed,
        notes=tuple(notes),
    )


def render(reading: SoakReading) -> str:
    lines = [
        f"soak     {reading.cycles} cycles, {reading.days:.2f}/{reading.required_days:.0f} days",
        f"phases   ERROR {reading.error_cycles}, SKIPPED {reading.skipped_cycles}, "
        f"longest ERROR streak {reading.longest_error_streak}",
        f"clean    longest run without an ERROR: {reading.longest_clean_days:.2f} days",
        f"§5 L3 字面   {'PASS' if reading.literal_pass else 'FAIL'}  (7 天无 ERROR 相；已裁定不作门，仍照报)",
        f"§5 no-decision {'PASS' if reading.no_decision_pass else 'FAIL'}  (7 天内没有 ERROR 周期做过决定)",
        f"ERROR 连段   {'PASS' if reading.streak_pass else 'FAIL'}  "
        f"(最长 {reading.longest_error_streak} < {reading.max_error_streak}，与 live status --check 同一条)",
        f"L3 判据     {'PASS' if reading.passes else 'FAIL'}  (2026-09-10 裁定：no-decision + 连段)",
    ]
    if reading.transactions_closed is not None:
        lines.append(f"事务链     {'closed' if reading.transactions_closed else 'BROKEN'}")
    lines.extend(f"  - {note}" for note in reading.notes)
    lines.extend(f"  ! ERROR cycle decided something: {why}" for why in reading.deciding_errors)
    return "\n".join(lines)
