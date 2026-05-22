#!/usr/bin/env bash
# Source this script to activate the project's venv in any
# bash/zsh/fish session. One-time per terminal:
#
#   source ./activate.sh
#
# Equivalent to:  source venv/bin/activate
# but auto-detects whether the repo has venv/ or .venv/ on disk, and
# warns clearly if neither exists. For direnv users this is handled
# automatically by .envrc on `cd`.

# Refuse to run if not sourced (so `./activate.sh` doesn't silently
# do nothing — a common confusing failure mode).
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    echo "Error: this script must be sourced, not executed."
    echo "Try:  source ./activate.sh"
    exit 1
fi

if [ -d "venv" ]; then
    # shellcheck disable=SC1091
    source venv/bin/activate
    echo "✓ venv activated  (Python $(python --version 2>&1 | cut -d' ' -f2))"
elif [ -d ".venv" ]; then
    # shellcheck disable=SC1091
    source .venv/bin/activate
    echo "✓ .venv activated  (Python $(python --version 2>&1 | cut -d' ' -f2))"
else
    echo "✗ No venv/ or .venv/ found in $(pwd)."
    echo "  Create one:  python3.12 -m venv venv && pip install -e ."
fi
