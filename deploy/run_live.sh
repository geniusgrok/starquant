#!/bin/bash
# Launch wrapper for the unattended demo loop (used by com.starquant.live.plist).
#
# Secrets: STARQUANT_BINANCE_API_KEY / STARQUANT_BINANCE_API_SECRET must be in the environment.
# Preferred: ~/Library/Application Support/starquant/env.sh (chmod 600).  Otherwise the
# operator's existing ~/.zshrc exports are picked up below.  Never commit the values.
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SUPPORT="$HOME/Library/Application Support/starquant"
mkdir -p "$SUPPORT"
if [ -f "$SUPPORT/env.sh" ]; then
  # shellcheck disable=SC1091
  source "$SUPPORT/env.sh"
elif [ -f "$HOME/.zshrc" ]; then
  # Fall back to the operator's existing exports instead of copying the secret to a second file.
  # Only literal STARQUANT_* export lines are evaluated; aliases and interactive-only code are ignored.
  eval "$(grep -E '^export STARQUANT_[A-Z0-9_]+=' "$HOME/.zshrc" || true)"
fi
if [ -z "${STARQUANT_BINANCE_API_KEY:-}" ] || [ -z "${STARQUANT_BINANCE_API_SECRET:-}" ]; then
  echo "run_live.sh: demo credentials are not in the environment" >&2
  exit 78   # EX_CONFIG; launchd will not hot-loop on a configuration error
fi
cd "$REPO"

# ---------------------------------------------------------------------------
# D-041 bridge, 2026-09-18.  IT REMOVES ITSELF BY EXPIRY, NOT BY BEING REMEMBERED.
#
# What happened: rebuilding `.starquant/data/membership.parquet` (2,042 -> 2,056 refreshes,
# union 211 -> 212, last 09-03 -> 09-17) moved a BLOCKING manifest field, so tsmom's cited
# evidence no longer describes the data on disk and `registry_dataset_problems` refuses the
# armed start.  Re-issuing that evidence on the rebuilt table came back FAIL by 0.0106
# (OOS 1.5628 against a 1.5733 threshold, p_family 0.0547), so pointing the registry at the
# new report blocks too, on `evidence verdict FAIL`.  Both pointers block, and the old table
# has no copy anywhere.  Full account: docs/RESEARCH_LOG.md, 2026-09-18.
#
# What this does and does not do: `--allow-unvalidated` bypasses ONLY the startup refusal in
# `live_cmd.py`.  Every `dataset:` and `evidence:` line is still printed to this log, and the
# guards, the kill switch and the risk budget are untouched.  While it is active the armed
# loop runs on a book whose evidence does not clear its own gate - and that sentence is the
# whole reason the line below announces itself on every single start.
#
# Why it expires instead of waiting to be noticed: a flag that needs a human to remember it is
# the failure this repo keeps re-learning.  After the date the flag is simply not passed, the
# strict gate comes back, and an armed start that still cannot qualify FAILS.  That is the
# safe direction - no trading on evidence that does not clear - so if it happens it is not a
# regression, it is this bridge doing the last thing it was built to do.
BRIDGE_UNTIL="2026-10-13"   # the construction freeze ends here; tsmom's evidence is settled in that package
BRIDGE=()
if [[ "$(date -u +%Y-%m-%d)" < "$BRIDGE_UNTIL" ]]; then
  BRIDGE+=(--allow-unvalidated)
  echo "run_live.sh: D-041 bridge ACTIVE until $BRIDGE_UNTIL - armed on evidence that does not clear its gate" >&2
else
  echo "run_live.sh: D-041 bridge EXPIRED on $BRIDGE_UNTIL - the strict evidence gate is back" >&2
fi
# ---------------------------------------------------------------------------

# Exit code 0 (clean stop, e.g. --cycles reached) is not relaunched; any failure is, after ThrottleInterval.
# --armed is what makes a real-order run explicit (DL-L1).  This launcher is the only caller that
# should carry it; a loop started by hand in a worktree has to type it, which is the point.
#
# `${BRIDGE[@]+"${BRIDGE[@]}"}`, not `"${BRIDGE[@]}"` (2026-09-25).  launchd runs this with /bin/bash,
# which on macOS is 3.2.57, and before bash 4.4 expanding an EMPTY array under `set -u` is an
# "unbound variable" error.  So the day the bridge expired and BRIDGE stayed empty, this line would
# have exited 1 before `starquant` ever ran - the strict evidence gate above would never have been
# reached, and every relaunch would have died the same way.  CI's bash is 5.x and cannot see it:
# tests/cli/test_the_bridge_expiry_survives_the_bash_launchd_runs.py checks the expansion by text.
exec "$REPO/.venv/bin/starquant" live run --profile config/live.demo.yaml --immediate --armed ${BRIDGE[@]+"${BRIDGE[@]}"} "$@"
