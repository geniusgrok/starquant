#!/usr/bin/env bash
# Idempotent bootstrap for the starquant Cloud Agent environment.
#
# The repository is currently greenfield, so this script is written to be safe
# when no dependency manifests exist yet. As soon as real manifests land
# (requirements*.txt, pyproject.toml/setup.py, or package.json), they are
# picked up automatically without any further changes here.
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$REPO_ROOT"

PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV_DIR="${VENV_DIR:-.venv}"

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
python -m pip install --upgrade pip setuptools wheel

installed_any=0

if [ -f requirements.txt ]; then
  echo "==> Installing requirements.txt"
  python -m pip install -r requirements.txt
  installed_any=1
fi

if [ -f requirements-dev.txt ]; then
  echo "==> Installing requirements-dev.txt"
  python -m pip install -r requirements-dev.txt
  installed_any=1
fi

if [ -f pyproject.toml ] || [ -f setup.py ] || [ -f setup.cfg ]; then
  echo "==> Installing project package (editable)"
  # Fall back to a non-editable install if the project layout does not
  # support editable installs.
  python -m pip install -e . || python -m pip install .
  installed_any=1
fi

if [ -f package.json ]; then
  echo "==> Installing Node dependencies"
  if [ -f package-lock.json ]; then
    npm ci
  else
    npm install
  fi
  installed_any=1
fi

if [ "${installed_any}" -eq 0 ]; then
  echo "==> No dependency manifests found yet."
  echo "    Base virtualenv is ready; add requirements*.txt, pyproject.toml,"
  echo "    setup.py, or package.json and re-run to install project deps."
fi

echo "==> Install complete."
