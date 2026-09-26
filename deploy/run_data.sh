#!/bin/bash
# Daily refresh of the research data the loop's evidence is built from.
#
# The audit found the parquet store sixteen hours stale with one live pool member missing entirely, and
# nothing scheduled to refresh it.  Research therefore validated on data that stopped before the book it
# was validating started trading.  This job closes that: klines and funding for the current pool, then a
# pool refresh so `universe.json` and the store agree.  It touches no account and places no orders.
#
# `data spot` joined it on 2026-09-09, and the reason is the same one with the feed changed.  DL-D5
# shipped the store, the mapping, the contract and the `basis` leaf, and nothing ever RAN the ingest:
# `.starquant/data/` held no `spot_klines/` and no `spot_map.json`, so `research mine` narrowed the whole
# basis family away on every run and the live gate refused every candidate that reads spot - both
# correctly, both silently, and neither because anything was wrong with the data.
#
# Two costs the operator should know before the first run rather than after it.  The command's default
# is every symbol the kline store holds (880 here against `data sync`'s 32 volume-ranked candidates), and
# 362 of 528 perpetuals have a spot leg, so the FIRST run backfills from `history_start` (2021-01) and
# takes hours; every run after it is one REST tail per mapped symbol.  Narrow it with `--symbols` or
# pre-run it by hand if that does not fit the window.  It is placed after `data sync` because it maps
# what the perp store holds, and before `pool refresh` because neither reads the other's output.
set -uo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SUPPORT="$HOME/Library/Application Support/starquant"
if [ -f "$SUPPORT/env.sh" ]; then
  # shellcheck disable=SC1091
  source "$SUPPORT/env.sh"
elif [ -f "$HOME/.zshrc" ]; then
  eval "$(grep -E '^export STARQUANT_[A-Z0-9_]+=' "$HOME/.zshrc" || true)"
fi
cd "$REPO" || exit 78
STARQUANT="$REPO/.venv/bin/starquant"
[ -x "$STARQUANT" ] || STARQUANT="starquant"
stamp() { date -u '+%Y-%m-%dT%H:%M:%SZ'; }
fail=0
echo "[$(stamp)] data sync"
"$STARQUANT" data sync || { echo "[$(stamp)] FAIL data sync"; fail=1; }
echo "[$(stamp)] data spot"
"$STARQUANT" data spot || { echo "[$(stamp)] FAIL data spot"; fail=1; }
echo "[$(stamp)] pool refresh"
"$STARQUANT" data pool refresh || { echo "[$(stamp)] FAIL pool refresh"; fail=1; }
echo "[$(stamp)] status"
"$STARQUANT" data status || true
#
# 2026-09-10.  `starquant data onchain|index|macro` shipped that day and were HELD OUT of this job, each
# for a reason written out here: #29 index price because NOTHING read the store, #31 on-chain because a
# year of waiting costs the same 49 requests as one day of it, #32 macro because it has no store at all.
# The rule used was "a feed belongs here when something reads it on a schedule, or when waiting makes
# its history unrecoverable or the catch-up disproportionate".
#
# 2026-09-16: the operator WITHDREW all three.  Modules, commands and tests are out of the tree
# (`git show 71863e9e` has them).  So this block no longer lists anything to add, and what is worth
# keeping is the fact that it was RIGHT and that being right here was not enough:
#
#   This job was the only thing in the repository that had correctly judged those three feeds unread,
#   and it recorded that judgement as a comment.  Six days later a review had to re-derive the same
#   conclusion from scratch - `research_cmd._load` joins only metrics and spot, no leaf reads an
#   on-chain/index/macro column, `.starquant/data/` holds no store for any of them - because a comment in
#   a shell script is not something any guard consults.  `test_every_module_is_reachable_from_an_entry_point`
#   passed the whole time: it asks whether a module CAN be run, and all three could.  Nothing anywhere
#   asked whether anything DID.
#
# The precedent that survives them, and the reason this job stayed small: `data metrics` HAS a panel
# reader (`_load(metrics=…)`) and is still not scheduled here.  (`data spot` is, above, since 2026-09-09.)
# This job is the loop's own evidence - klines, funding, spot, pool - and putting a feed nobody reads
# into it turns a red data job into noise.
exit "$fail"
