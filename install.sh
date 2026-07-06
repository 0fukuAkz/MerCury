#!/usr/bin/env bash
#
# MerCury automated installer — macOS / Linux
# =============================================================================
# Installs MerCury into an isolated virtualenv, initialises its database, and
# leaves a login-ready local instance. Works in two modes automatically:
#
#   * SOURCE mode  — run from a checkout of the MerCury repo (a pyproject.toml
#                    with `name = "mercury"` sits next to this script). Installs
#                    the local tree ("build from source").
#   * PACKAGE mode — run anywhere else. Installs `mercury` from PyPI ("download
#                    a released build"). Requires MerCury to be published.
#
# Virtualenv backend: prefers `uv` when it is installed (fast, and it is the
# only backend that works with uv-managed / python-build-standalone
# interpreters — stdlib `python -m venv` crashes on those with "No module named
# 'encodings'"). Falls back to `python -m venv` + `pip` when uv is absent.
#
# Usage:
#   ./install.sh [options]
#   curl -fsSL https://raw.githubusercontent.com/0fukuAkz/MerCury/main/install.sh | bash
#
# Run `./install.sh --help` for the full option list.
#
# Safety notes:
#   * Never overwrites an existing .env (your secrets are preserved).
#   * Reuses an existing virtualenv rather than wiping it (see --recreate).
#   * Only ever touches: the target venv, an absent .env, and the MerCury DB.
# =============================================================================

set -euo pipefail

# -----------------------------------------------------------------------------
# Defaults (override via flags below)
# -----------------------------------------------------------------------------
VENV_DIR=".venv"          # where the virtualenv is created / reused
PYTHON_BIN=""             # explicit interpreter (else auto-detect 3.12)
EXTRAS=""                 # comma list: postgres,redis,worker,observability,pdf,geo
DEV=0                     # editable install + [dev] extra
DO_DB=1                   # run `mercury db migrate` after install
DO_ENV=1                  # generate a starter .env if none exists
RECREATE=0               # wipe & rebuild the venv (--clear)
ASSUME_YES=0              # non-interactive; never prompt
NO_UV=0                   # force stdlib venv + pip even if uv is installed
BOOTSTRAP=1               # fresh system (no python + no uv): auto-install uv
UNINSTALL=0               # --uninstall: remove the venv (+ --purge for data)
PURGE=0                   # with --uninstall: also delete .env + local DB/logs

# MerCury targets exactly this Python (pyproject: requires-python >=3.12,<3.13).
REQUIRED_PY="3.12"

# Resolve where this script lives so SOURCE-mode detection is location-based,
# not cwd-based (matters for `curl | bash`, where there is no script file).
if [ -n "${BASH_SOURCE:-}" ] && [ -f "${BASH_SOURCE[0]}" ]; then
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
else
    SCRIPT_DIR="$(pwd)"
fi

# -----------------------------------------------------------------------------
# Pretty output (respects NO_COLOR and non-TTY pipes)
# -----------------------------------------------------------------------------
if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
    C_RESET="\033[0m"; C_BOLD="\033[1m"; C_DIM="\033[2m"
    C_BLUE="\033[34m"; C_GREEN="\033[32m"; C_YELLOW="\033[33m"; C_RED="\033[31m"
else
    C_RESET=""; C_BOLD=""; C_DIM=""; C_BLUE=""; C_GREEN=""; C_YELLOW=""; C_RED=""
fi
step() { printf "${C_BLUE}${C_BOLD}==>${C_RESET} ${C_BOLD}%s${C_RESET}\n" "$*"; }
info() { printf "    %s\n" "$*"; }
ok()   { printf "    ${C_GREEN}✓${C_RESET} %s\n" "$*"; }
warn() { printf "    ${C_YELLOW}!${C_RESET} %s\n" "$*"; }
die()  { printf "${C_RED}${C_BOLD}✗ %s${C_RESET}\n" "$*" >&2; exit 1; }

# Install uv on a bare system, then make it usable in THIS shell. uv is the
# fastest path from "nothing installed" to a working environment: it fetches a
# managed Python 3.12 for us and adds itself to PATH for future shells.
bootstrap_uv() {
    step "No Python ${REQUIRED_PY} and no uv found — bootstrapping uv"
    info "Installing uv from https://astral.sh/uv (it will fetch Python ${REQUIRED_PY})"
    if command -v curl >/dev/null 2>&1; then
        curl -LsSf https://astral.sh/uv/install.sh | sh || return 1
    elif command -v wget >/dev/null 2>&1; then
        wget -qO- https://astral.sh/uv/install.sh | sh || return 1
    else
        die "Need curl or wget to bootstrap uv. Install one (or install Python ${REQUIRED_PY} yourself), then re-run."
    fi
    # uv installs to $XDG_BIN_HOME or ~/.local/bin (older builds: ~/.cargo/bin).
    # Put those on PATH now so the rest of this run can call uv.
    export PATH="${XDG_BIN_HOME:-$HOME/.local/bin}:$HOME/.cargo/bin:$PATH"
    command -v uv >/dev/null 2>&1 || die "uv installed but not on PATH — open a new terminal and re-run ./install.sh"
    ok "uv $(uv --version 2>/dev/null | awk '{print $2}') ready"
    return 0
}

# Reverse an install: always remove the virtualenv; with --purge also delete the
# generated .env and the LOCAL database / salt / logs. Never touches the source
# tree or an external Postgres database.
do_uninstall() {
    printf "${C_BOLD}MerCury uninstaller${C_RESET} ${C_DIM}(macOS / Linux)${C_RESET}\n\n"

    # Where .env lives (same rule the installer uses).
    local install_dir
    if [ -f "$SCRIPT_DIR/pyproject.toml" ] && grep -q '^name = "mercury"' "$SCRIPT_DIR/pyproject.toml" 2>/dev/null; then
        install_dir="$SCRIPT_DIR"
    else
        install_dir="$(pwd)"
    fi
    local env_file="$install_dir/.env"
    local venv_py="$VENV_DIR/bin/python"

    # Discover data/log/db paths from the venv BEFORE it's deleted (for --purge).
    local data_dir="" log_dir="" db_path=""
    if [ "$PURGE" -eq 1 ] && [ -x "$venv_py" ]; then
        [ -f "$env_file" ] && { set -a; . "$env_file"; set +a; }   # reflect DATABASE_URL
        data_dir="$("$venv_py" -c 'from mercury.utils import app_dirs as a; print(a.get_data_dir())' 2>/dev/null || true)"
        log_dir="$("$venv_py" -c 'from mercury.utils import app_dirs as a; print(a.get_log_dir())' 2>/dev/null || true)"
        db_path="$("$venv_py" -c 'from mercury.utils import app_dirs as a; print(a.get_db_path())' 2>/dev/null || true)"
    fi

    step "Will remove"
    [ -d "$VENV_DIR" ] && info "• virtualenv:  $VENV_DIR" || info "• virtualenv:  (none at $VENV_DIR)"
    if [ "$PURGE" -eq 1 ]; then
        [ -f "$env_file" ] && info "• .env:        $env_file"
        case "$db_path" in
            sqlite:*) info "• database:    ${db_path#sqlite:///}" ;;
            "")       : ;;
            *)        warn "database is external ($db_path) — NOT removed" ;;
        esac
        [ -n "$data_dir" ] && info "• data dir:    $data_dir  (DB + encryption salt)"
        [ -n "$log_dir" ]  && info "• log dir:     $log_dir"
    else
        info "(keeping .env + database — pass --purge to remove them too)"
    fi

    if [ "$ASSUME_YES" -ne 1 ]; then
        printf "\n${C_YELLOW}Proceed with removal? [y/N] ${C_RESET}"
        read -r _reply || _reply=""
        case "$_reply" in [yY]*) ;; *) info "Aborted — nothing removed."; exit 0 ;; esac
    fi

    step "Removing"
    if [ -d "$VENV_DIR" ]; then rm -rf "$VENV_DIR" && ok "virtualenv"; fi
    if [ "$PURGE" -eq 1 ]; then
        [ -f "$env_file" ] && { rm -f "$env_file"; ok ".env"; }
        [ -n "$data_dir" ] && [ -d "$data_dir" ] && { rm -rf "$data_dir"; ok "data dir"; }
        [ -n "$log_dir" ]  && [ -d "$log_dir" ]  && { rm -rf "$log_dir"; ok "log dir"; }
    fi
    printf "\n${C_GREEN}${C_BOLD}✓ MerCury uninstalled.${C_RESET}\n"
    exit 0
}

usage() {
    cat <<'EOF'
MerCury installer (macOS / Linux)

USAGE:
    ./install.sh [options]

OPTIONS:
    --venv DIR         Virtualenv location (default: .venv)
    --python PATH      Use this interpreter instead of auto-detecting 3.12
    --extras LIST      Comma-separated optional deps to install. Any of:
                         postgres, redis, worker, observability, pdf, geo, all
                       e.g. --extras postgres,redis,worker
    --dev              Editable install (pip install -e) + the [dev] extra
    --recreate         Delete and rebuild the virtualenv from scratch
    --no-uv            Force stdlib `python -m venv` + pip (ignore uv)
    --no-bootstrap     On a bare system (no Python + no uv), fail instead of
                       auto-installing uv
    --no-db            Skip database migration (`mercury db migrate`)
    --no-env           Do not generate a starter .env
    --uninstall        Uninstall: remove the virtualenv (keeps .env + database)
    --purge            With --uninstall: also delete .env + the local database
    -y, --yes          Non-interactive; assume yes and never prompt
    -h, --help         Show this help and exit

EXAMPLES:
    ./install.sh                              # core install, SQLite, login-ready
    ./install.sh --extras postgres,redis      # add the Postgres + Redis drivers
    ./install.sh --dev                        # contributor setup (editable + dev)
    ./install.sh --venv /opt/mercury/venv -y  # scripted install to a fixed path
    ./install.sh --uninstall                  # remove the venv (keeps .env + DB)
    ./install.sh --uninstall --purge -y       # remove everything, no prompt
EOF
}

# -----------------------------------------------------------------------------
# Argument parsing
# -----------------------------------------------------------------------------
while [ $# -gt 0 ]; do
    case "$1" in
        --venv)     VENV_DIR="${2:?--venv needs a path}"; shift 2 ;;
        --python)   PYTHON_BIN="${2:?--python needs a path}"; shift 2 ;;
        --extras)   EXTRAS="${2:?--extras needs a list}"; shift 2 ;;
        --dev)      DEV=1; shift ;;
        --recreate) RECREATE=1; shift ;;
        --no-uv)    NO_UV=1; shift ;;
        --no-bootstrap) BOOTSTRAP=0; shift ;;
        --uninstall) UNINSTALL=1; shift ;;
        --purge)    PURGE=1; shift ;;
        --no-db)    DO_DB=0; shift ;;
        --no-env)   DO_ENV=0; shift ;;
        -y|--yes)   ASSUME_YES=1; shift ;;
        -h|--help)  usage; exit 0 ;;
        *)          die "Unknown option: $1  (try --help)" ;;
    esac
done

# Uninstall short-circuits the whole install flow.
if [ "$UNINSTALL" -eq 1 ]; then do_uninstall; fi

printf "${C_BOLD}MerCury installer${C_RESET} ${C_DIM}(macOS / Linux)${C_RESET}\n\n"

# -----------------------------------------------------------------------------
# 1. Locate a Python 3.12 interpreter
#    requires-python is ">=3.12,<3.13": a 3.11 or 3.13 interpreter would make
#    `pip install` fail with an opaque resolver error, so we validate up front.
#    PY stays empty if none is found on PATH — uv can still provide one below.
# -----------------------------------------------------------------------------
step "Locating Python ${REQUIRED_PY}"

py_minor() { "$1" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || true; }

PY=""
if [ -n "$PYTHON_BIN" ]; then
    command -v "$PYTHON_BIN" >/dev/null 2>&1 || die "Interpreter not found: $PYTHON_BIN"
    [ "$(py_minor "$PYTHON_BIN")" = "$REQUIRED_PY" ] \
        || die "$PYTHON_BIN is Python $(py_minor "$PYTHON_BIN"); MerCury needs exactly ${REQUIRED_PY}."
    PY="$PYTHON_BIN"
else
    for cand in python3.12 python3 python; do
        command -v "$cand" >/dev/null 2>&1 || continue
        if [ "$(py_minor "$cand")" = "$REQUIRED_PY" ]; then PY="$cand"; break; fi
    done
fi

# -----------------------------------------------------------------------------
# 2. Pick the virtualenv backend (uv preferred) and settle the interpreter
# -----------------------------------------------------------------------------
USE_UV=0
if [ "$NO_UV" -eq 0 ] && command -v uv >/dev/null 2>&1; then USE_UV=1; fi

# Truly fresh machine: no Python 3.12 on PATH and no uv. Auto-install uv (unless
# opted out with --no-bootstrap/--no-uv); it then downloads a managed Python
# 3.12 and handles PATH — the "from nothing" path.
if [ -z "$PY" ] && [ "$USE_UV" -eq 0 ] && [ "$NO_UV" -eq 0 ] && [ "$BOOTSTRAP" -eq 1 ]; then
    bootstrap_uv && USE_UV=1
fi

# PY_SPEC is what we hand the backend: a concrete interpreter path when we found
# one, otherwise the bare version so uv can fetch/select a managed 3.12.
PY_SPEC="$PY"
if [ -z "$PY" ]; then
    if [ "$USE_UV" -eq 1 ]; then
        PY_SPEC="$REQUIRED_PY"
        ok "No system Python ${REQUIRED_PY} on PATH — uv will provide a managed ${REQUIRED_PY}"
    else
        printf "${C_RED}${C_BOLD}✗ No Python ${REQUIRED_PY} interpreter found.${C_RESET}\n" >&2
        cat >&2 <<EOF

    MerCury requires Python ${REQUIRED_PY} (not 3.11, not 3.13). Either install it:
      macOS (Homebrew):   brew install python@3.12
      pyenv:              pyenv install 3.12 && pyenv shell 3.12
      Debian/Ubuntu:      sudo apt install python3.12 python3.12-venv
    …or install uv (which can fetch 3.12 for you):
      curl -LsSf https://astral.sh/uv/install.sh | sh
    Then re-run:  ./install.sh
EOF
        exit 1
    fi
else
    ok "Using $(command -v "$PY")  ($("$PY" --version 2>&1))"
fi
[ "$USE_UV" -eq 1 ] && info "Backend: uv $(uv --version 2>/dev/null | awk '{print $2}')" \
                    || info "Backend: python -m venv + pip"

# -----------------------------------------------------------------------------
# 3. Decide install source: SOURCE (repo checkout) vs PACKAGE (PyPI)
# -----------------------------------------------------------------------------
step "Selecting install source"
INSTALL_MODE="package"
INSTALL_DIR="$(pwd)"
if [ -f "$SCRIPT_DIR/pyproject.toml" ] && grep -q '^name = "mercury"' "$SCRIPT_DIR/pyproject.toml" 2>/dev/null; then
    INSTALL_MODE="source"
    INSTALL_DIR="$SCRIPT_DIR"
    ok "Source checkout detected — installing from $INSTALL_DIR"
else
    ok "No checkout here — installing the released 'mercury' package from PyPI"
fi

# -----------------------------------------------------------------------------
# 4. Create (or reuse) the virtualenv
# -----------------------------------------------------------------------------
step "Preparing virtualenv: $VENV_DIR"
if [ -d "$VENV_DIR" ] && [ "$RECREATE" -eq 1 ]; then
    warn "Removing existing virtualenv (--recreate)"
    rm -rf "$VENV_DIR"
fi
if [ -d "$VENV_DIR" ]; then
    ok "Reusing existing virtualenv (pass --recreate to rebuild)"
else
    if [ "$USE_UV" -eq 1 ]; then
        # --seed puts pip/setuptools in the venv so it behaves like a normal one
        # afterwards; --python accepts a path or a bare version to fetch.
        uv venv --seed --python "$PY_SPEC" "$VENV_DIR" || die "uv venv failed"
    else
        "$PY" -m venv "$VENV_DIR" || die "Failed to create virtualenv at $VENV_DIR"
    fi
    ok "Created virtualenv"
fi

# Use the venv's executables directly — no need to 'activate' in a script.
VENV_PY="$VENV_DIR/bin/python"
VENV_MERCURY="$VENV_DIR/bin/mercury"
[ -x "$VENV_PY" ] || die "Virtualenv looks broken: $VENV_PY missing"

# -----------------------------------------------------------------------------
# 5. Install MerCury
# -----------------------------------------------------------------------------
step "Installing MerCury and dependencies"

# Assemble the extras spec. --dev implies the [dev] extra as well.
_extras="$EXTRAS"
if [ "$DEV" -eq 1 ]; then
    case ",$_extras," in *",dev,"*) : ;; *) _extras="${_extras:+$_extras,}dev" ;; esac
fi
_bracket=""
[ -n "$_extras" ] && _bracket="[$_extras]"

# Build the pip target: a local path (source) or the PyPI name (package).
if [ "$INSTALL_MODE" = "source" ]; then
    _target="$INSTALL_DIR$_bracket"
    [ "$DEV" -eq 1 ] && _editable="-e" || _editable=""
else
    _target="mercury$_bracket"
    _editable=""
fi

if [ "$USE_UV" -eq 1 ]; then
    info "uv pip install ${_editable:+$_editable }\"$_target\""
    # shellcheck disable=SC2086
    uv pip install --python "$VENV_PY" $_editable "$_target" \
        || die "Install failed. If MerCury isn't on PyPI yet, run this from a repo checkout."
else
    info "Upgrading pip toolchain…"
    "$VENV_PY" -m pip install --quiet --upgrade pip setuptools wheel || die "pip bootstrap failed"
    info "pip install ${_editable:+$_editable }\"$_target\""
    # shellcheck disable=SC2086
    "$VENV_PY" -m pip install $_editable "$_target" \
        || die "Install failed. If MerCury isn't on PyPI yet, run this from a repo checkout."
fi
ok "Installed $("$VENV_MERCURY" --version 2>/dev/null || echo mercury)"

# -----------------------------------------------------------------------------
# 6. Generate a starter .env (only if absent — never clobber existing secrets)
#
#    The app creates the admin user on its first boot ONLY when ADMIN_USERNAME,
#    ADMIN_PASSWORD and ADMIN_EMAIL are all present (security/auth.py). We write
#    all three plus a strong SECRET_KEY so the instance is login-ready.
# -----------------------------------------------------------------------------
ENV_FILE="$INSTALL_DIR/.env"
GENERATED_ENV=0
ADMIN_USER="admin"
ADMIN_PASS=""
if [ "$DO_ENV" -eq 1 ]; then
    step "Configuring environment (.env)"
    if [ -f "$ENV_FILE" ]; then
        ok "Keeping existing .env (not overwritten)"
    else
        # Use the venv interpreter we just built for crypto-strength randomness.
        SECRET_KEY="$("$VENV_PY" -c 'import secrets; print(secrets.token_urlsafe(48))')"
        ADMIN_PASS="$("$VENV_PY" -c 'import secrets; print(secrets.token_urlsafe(18))')"
        cat > "$ENV_FILE" <<EOF
# MerCury local configuration — generated by install.sh
# FLASK_ENV=development keeps the production preflight (which requires Postgres,
# a real SECRET_KEY, etc.) from blocking a local SQLite run.
FLASK_ENV=development

# Session signing / token secret. Regenerate for a new install.
SECRET_KEY=$SECRET_KEY

# Admin bootstrap — the app creates this user on first boot when all three are
# set. Change the password after first login.
ADMIN_USERNAME=$ADMIN_USER
ADMIN_PASSWORD=$ADMIN_PASS
ADMIN_EMAIL=admin@localhost

# Database — unset means SQLite in your OS user-data dir. For Postgres, install
# with --extras postgres and set e.g.:
# DATABASE_URL=postgresql://mercury:mercury@localhost:5432/mercury
EOF
        chmod 600 "$ENV_FILE" 2>/dev/null || true
        GENERATED_ENV=1
        ok "Wrote $ENV_FILE (permissions 600)"
    fi
fi

# -----------------------------------------------------------------------------
# 7. Initialise the database (Alembic upgrade head via `mercury db migrate`)
#
#    `mercury` does NOT auto-load .env (only run.py does), so export the vars
#    for this process ourselves before migrating.
# -----------------------------------------------------------------------------
if [ "$DO_DB" -eq 1 ]; then
    step "Initialising the database"
    if [ -f "$ENV_FILE" ]; then
        set -a; . "$ENV_FILE"; set +a
    fi
    if "$VENV_MERCURY" db migrate; then
        ok "Schema is at head"
    else
        warn "Migration did not complete. If you chose Postgres, is the server up"
        warn "and DATABASE_URL set? You can re-run:  mercury db migrate"
    fi
fi

# -----------------------------------------------------------------------------
# 8. Done — print next steps tailored to what we installed
# -----------------------------------------------------------------------------
printf "\n${C_GREEN}${C_BOLD}✓ MerCury is installed.${C_RESET}\n\n"

printf "${C_BOLD}Start it${C_RESET}\n"
if [ "$INSTALL_MODE" = "source" ] && [ -f "$INSTALL_DIR/run.py" ]; then
    cat <<EOF
    # Production-style launcher (loads .env, gunicorn + eventlet, 1 worker):
    source $VENV_DIR/bin/activate
    python run.py

    # …or the lightweight dev runner (does NOT read .env — export it first):
    set -a; source .env; set +a
    mercury start server            # → http://127.0.0.1:5000
EOF
else
    cat <<EOF
    source $VENV_DIR/bin/activate
    set -a; source .env; set +a     # mercury CLI does not auto-read .env
    mercury start server            # → http://127.0.0.1:5000
EOF
fi

printf "\n${C_BOLD}Log in${C_RESET}\n"
if [ "$GENERATED_ENV" -eq 1 ]; then
    printf "    username: ${C_BOLD}%s${C_RESET}\n" "$ADMIN_USER"
    printf "    password: ${C_BOLD}%s${C_RESET}   ${C_DIM}(saved in .env — change after first login)${C_RESET}\n" "$ADMIN_PASS"
else
    info "Use the ADMIN_USERNAME / ADMIN_PASSWORD from your .env"
fi

printf "\n${C_DIM}Other commands:  mercury --help   |   mercury db current   |   mercury check <config>${C_RESET}\n"
