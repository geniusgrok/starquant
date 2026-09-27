#!/usr/bin/env bash
# Idempotent bootstrap for the starquant Cloud Agent environment.
#
# Mirrors the canonical install used by .github/workflows/ci.yml:
#   pip install -r requirements.lock       # pinned, reproducible versions
#   pip install -e . --no-deps             # the project itself
#
# The requirements.lock anchor exists precisely so CI and local dev do NOT
# re-resolve dependencies to "today's latest" (see the header of that file),
# so we always prefer it when present. A generic fallback keeps this script
# usable if the repository layout ever changes.
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$REPO_ROOT"

PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV_DIR="${VENV_DIR:-.venv}"
GITLEAKS_VERSION="${GITLEAKS_VERSION:-8.30.1}"

# The Ubuntu base image ships Python but not the venv/ensurepip module, which is
# required to create virtualenvs. Install it once (idempotent) if missing.
if ! "${PYTHON_BIN}" -c 'import ensurepip' >/dev/null 2>&1; then
  echo "==> Installing python3-venv/python3-dev (needed to create virtualenvs)"
  sudo apt-get update -y
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y python3-venv python3-dev
fi

echo "==> Preparing Python virtualenv at ${VENV_DIR} (Ubuntu system Python is externally managed)"
if [ ! -x "${VENV_DIR}/bin/python" ]; then
  "${PYTHON_BIN}" -m venv "${VENV_DIR}"
fi
# shellcheck disable=SC1091
source "${VENV_DIR}/bin/activate"
python -m pip install --upgrade pip

if [ -f requirements.lock ]; then
  echo "==> Installing pinned dependencies (requirements.lock) — mirrors CI"
  python -m pip install -r requirements.lock
  echo "==> Installing starquant package (editable, no deps)"
  python -m pip install -e . --no-deps
else
  echo "==> requirements.lock not found; using generic dependency detection"
  if [ -f requirements.txt ]; then
    python -m pip install -r requirements.txt
  fi
  if [ -f requirements-dev.txt ]; then
    python -m pip install -r requirements-dev.txt
  fi
  if [ -f pyproject.toml ] || [ -f setup.py ] || [ -f setup.cfg ]; then
    python -m pip install -e . || python -m pip install .
  fi
  if [ -f package.json ]; then
    if [ -f package-lock.json ]; then npm ci; else npm install; fi
  fi
fi

# Secret-scanning tool used by the repo's git hooks (.githooks) and the CI
# "Secrets" gate. Optional (hooks no-op without it) but installing it makes the
# local dev loop match the project. Pin to the version CI uses.
if [ -f .gitleaks.toml ] && ! command -v gitleaks >/dev/null 2>&1; then
  echo "==> Installing gitleaks ${GITLEAKS_VERSION}"
  tmp="$(mktemp -d)"
  if curl -sSfL -o "${tmp}/gitleaks.tar.gz" \
      "https://github.com/gitleaks/gitleaks/releases/download/v${GITLEAKS_VERSION}/gitleaks_${GITLEAKS_VERSION}_linux_x64.tar.gz"; then
    tar -xzf "${tmp}/gitleaks.tar.gz" -C "${tmp}" gitleaks
    sudo install -m 0755 "${tmp}/gitleaks" /usr/local/bin/gitleaks
  else
    echo "    (could not download gitleaks; hooks will no-op until it is installed)"
  fi
  rm -rf "${tmp}"
fi

# Route git to the repo-tracked hooks so commit/push secret scanning is active.
if [ -d .githooks ]; then
  git config core.hooksPath .githooks || true
  chmod +x .githooks/* 2>/dev/null || true
fi

echo "==> Install complete."
