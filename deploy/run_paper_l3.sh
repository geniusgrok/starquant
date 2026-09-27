#!/bin/bash
# Launch wrapper for the L3 soak (used by com.starquant.paper-l3.plist).
#
# §5 L3 asks for "7 days with no ERROR phase and a closed transaction log", and a soak that is not
# running accumulates nothing: on 2026-09-09 the record held two rows from one end-to-end run-through
# and the criterion had been open for a day.  A run-through is not a soak.
#
# No credentials, deliberately.  `--paper` matches in-process at mainnet marks and never writes to the
# exchange, so this wrapper - unlike run_live.sh - has nothing to source and nothing to leak.  It is
# also why there is no `--armed` here and cannot be: `--state-dir` is refused without `--dry-run` or
# `--paper`, so this process cannot be turned into a trading one by editing a flag.
#
# It shares the machine with the armed loop and must not share its record.  `--state-dir` keeps the
# cycles, trades and state apart; `trades_the_account()` (2026-09-09) keeps the SHARED files - the
# metrics snapshot and `universe.json` - writable only by the process that holds the account, which is
# the collision this soak would otherwise reproduce every hour.
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"
exec "$REPO/.venv/bin/starquant" live run --profile config/live.demo.yaml --immediate \
    --paper --state-dir .starquant/paper-l3 "$@"
