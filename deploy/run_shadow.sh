#!/bin/bash
# DL-G5: soak a CANDIDATE registry beside the armed loop, writing nothing the armed loop reads.
#
# The canary answers one question - would this registry, deployed, behave like a working deployment? -
# and deliberately not whether the candidate has any edge (KILL-AR-04).  Reading it as an alpha filter
# is how a good sleeve gets blocked by a venue hiccup and the block gets recorded against the sleeve.
#
# Three isolations, each of which has to hold on its own:
#   --dry-run     no venue writes, and `--state-dir` refuses to run without it or --paper;
#   --state-dir   a separate state.json, cycles.jsonl and heartbeat, so the armed loop's record is
#                 untouched even if this process crashes mid-write;
#   --registry    a candidate file, so the armed loop's own registry is never opened for writing here.
#
# It does NOT restart, promote or write the real registry.  `starquant governance apply` does that, and
# only while the autonomy switch is on.
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

CANDIDATE="${1:-config/alpha_registry.candidate.yaml}"
STATE_DIR="${2:-.starquant/live-shadow}"
CYCLES="${3:-168}"

if [ ! -f "$CANDIDATE" ]; then
  echo "shadow: no candidate registry at $CANDIDATE" >&2
  exit 64
fi
# The one check worth making before spending 168 hours: refuse to soak the file the armed loop reads.
if [ "$(cd "$(dirname "$CANDIDATE")" && pwd)/$(basename "$CANDIDATE")" = "$REPO/config/alpha_registry.yaml" ]; then
  echo "shadow: refusing to soak the live registry; copy it and edit the copy" >&2
  exit 64
fi

echo "shadow: soaking $CANDIDATE for $CYCLES cycles into $STATE_DIR"
exec .venv/bin/starquant live run \
  --profile config/live.demo.yaml \
  --registry "$CANDIDATE" \
  --dry-run \
  --state-dir "$STATE_DIR" \
  --cycles "$CYCLES"
