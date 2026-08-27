#!/usr/bin/env bash
#
# loraai installer.
#
# Creates an isolated virtual environment, installs loraai into it, links the
# `loraai` command onto your PATH, and verifies the result actually works.
#
#   curl -fsSL <url>/install.sh | bash
#   ./install.sh --dev            # editable install from this checkout
#   ./install.sh --prefix ~/opt   # choose where the venv lives
#   ./install.sh --uninstall
#
set -euo pipefail

readonly APP="loraai"
readonly MIN_PYTHON_MAJOR=3
readonly MIN_PYTHON_MINOR=10

PREFIX="${LORAAI_PREFIX:-${XDG_DATA_HOME:-$HOME/.local/share}/$APP}"
BIN_DIR="${LORAAI_BIN_DIR:-$HOME/.local/bin}"
DEV_MODE=0
UNINSTALL=0
QUIET=0

# ---------------------------------------------------------------- presentation

if [ -t 1 ] && [ -z "${NO_COLOR:-}" ] && command -v tput >/dev/null 2>&1 &&
   [ "$(tput colors 2>/dev/null || echo 0)" -ge 8 ]; then
    C_RESET=$'\033[0m';  C_BOLD=$'\033[1m';   C_DIM=$'\033[2m'
    C_BRAND=$'\033[38;5;141m'; C_ACCENT=$'\033[38;5;80m'
    C_OK=$'\033[38;5;79m';     C_WARN=$'\033[38;5;221m'; C_ERR=$'\033[38;5;210m'
else
    C_RESET=''; C_BOLD=''; C_DIM=''
    C_BRAND=''; C_ACCENT=''; C_OK=''; C_WARN=''; C_ERR=''
fi

banner() {
    [ "$QUIET" -eq 1 ] && return 0
    printf '%s\n' ""
    printf '%s ██╗      ██████╗ ██████╗  █████╗      █████╗ ██╗%s\n' "$C_BRAND" "$C_RESET"
    printf '%s ██║     ██╔═══██╗██╔══██╗██╔══██╗    ██╔══██╗██║%s\n' "$C_BRAND" "$C_RESET"
    printf '%s ██║     ██║   ██║██████╔╝███████║    ███████║██║%s\n' "$C_BRAND" "$C_RESET"
    printf '%s ██║     ██║   ██║██╔══██╗██╔══██║    ██╔══██║██║%s\n' "$C_BRAND" "$C_RESET"
    printf '%s ███████╗╚██████╔╝██║  ██║██║  ██║    ██║  ██║██║%s\n' "$C_ACCENT" "$C_RESET"
    printf '%s ╚══════╝ ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═╝    ╚═╝  ╚═╝╚═╝%s\n' "$C_ACCENT" "$C_RESET"
    printf '%s\n' ""
    printf '  %stext forensics · hidden unicode · writing analysis · humanizer%s\n' \
        "$C_DIM" "$C_RESET"
    printf '%s\n' ""
}

step()  { [ "$QUIET" -eq 1 ] || printf '  %s▸%s %s\n' "$C_ACCENT" "$C_RESET" "$1"; }
ok()    { [ "$QUIET" -eq 1 ] || printf '  %s✓%s %s\n' "$C_OK" "$C_RESET" "$1"; }
warn()  { printf '  %s!%s %s\n' "$C_WARN" "$C_RESET" "$1" >&2; }
die()   { printf '\n  %s✗ %s%s\n\n' "$C_ERR" "$1" "$C_RESET" >&2; exit "${2:-1}"; }

# ---------------------------------------------------------------------- args

usage() {
    cat <<USAGE
${C_BOLD}loraai installer${C_RESET}

  ./install.sh [options]

${C_BOLD}Options${C_RESET}
  --dev              Editable install from this source checkout.
  --prefix PATH      Where the virtual environment lives.
                     (default: ${PREFIX})
  --bin-dir PATH     Where the launcher is linked.
                     (default: ${BIN_DIR})
  --uninstall        Remove a previous installation.
  --quiet            Only print errors.
  -h, --help         This message.

${C_BOLD}Environment${C_RESET}
  LORAAI_PREFIX      Same as --prefix.
  LORAAI_BIN_DIR     Same as --bin-dir.
  NO_COLOR           Disable colour.
USAGE
}

while [ $# -gt 0 ]; do
    case "$1" in
        --dev)       DEV_MODE=1; shift ;;
        --uninstall) UNINSTALL=1; shift ;;
        --quiet)     QUIET=1; shift ;;
        --prefix)    [ $# -ge 2 ] || die "--prefix needs a path"; PREFIX="$2"; shift 2 ;;
        --bin-dir)   [ $# -ge 2 ] || die "--bin-dir needs a path"; BIN_DIR="$2"; shift 2 ;;
        -h|--help)   usage; exit 0 ;;
        *)           die "Unknown option: $1 (try --help)" 2 ;;
    esac
done

VENV_DIR="$PREFIX/venv"
LAUNCHER="$BIN_DIR/$APP"

# ----------------------------------------------------------------- uninstall

if [ "$UNINSTALL" -eq 1 ]; then
    banner
    removed=0
    if [ -d "$PREFIX" ]; then
        rm -rf "$PREFIX"; ok "removed $PREFIX"; removed=1
    fi
    for link in "$LAUNCHER" "$BIN_DIR/lora"; do
        if [ -e "$link" ] || [ -L "$link" ]; then
            rm -f "$link"; ok "removed $link"; removed=1
        fi
    done
    [ "$removed" -eq 1 ] || warn "nothing found to remove at $PREFIX"
    printf '\n  %sUninstalled.%s Configuration in ~/.config/%s was left alone.\n\n' \
        "$C_BOLD" "$C_RESET" "$APP"
    exit 0
fi

# ------------------------------------------------------------ preflight checks
#
# Everything that can fail is checked BEFORE anything is written, so a machine
# that cannot support loraai is never left with a half-built install.

banner

case "$(uname -s 2>/dev/null || echo unknown)" in
    Linux*)   OS_NAME="Linux" ;;
    Darwin*)  OS_NAME="macOS" ;;
    FreeBSD*) OS_NAME="FreeBSD" ;;
    MINGW*|MSYS*|CYGWIN*)
        OS_NAME="Windows (POSIX layer)"
        warn "On native Windows, prefer: py -m pip install loraai-cli" ;;
    *)        OS_NAME="$(uname -s 2>/dev/null || echo unknown)" ;;
esac
ok "platform: $OS_NAME ($(uname -m 2>/dev/null || echo unknown))"

# Find a Python new enough for the dependency set.
PYTHON=""
for candidate in python3.14 python3.13 python3.12 python3.11 python3.10 python3 python; do
    command -v "$candidate" >/dev/null 2>&1 || continue
    if "$candidate" -c "import sys; raise SystemExit(0 if sys.version_info[:2] >= ($MIN_PYTHON_MAJOR, $MIN_PYTHON_MINOR) else 1)" 2>/dev/null; then
        PYTHON="$candidate"
        break
    fi
done

if [ -z "$PYTHON" ]; then
    newest="$(python3 -c 'import platform; print(platform.python_version())' 2>/dev/null || echo 'none found')"
    die "Python ${MIN_PYTHON_MAJOR}.${MIN_PYTHON_MINOR}+ is required (found: ${newest}).

  Install a newer Python, then run this script again:
    macOS          brew install python@3.12
    Debian/Ubuntu  sudo apt install python3.12 python3.12-venv
    Fedora         sudo dnf install python3.12
    Arch           sudo pacman -S python" 3
fi
ok "python: $($PYTHON -c 'import sys;print(sys.version.split()[0])') ($(command -v "$PYTHON"))"

# venv must be importable; Debian splits it into a separate package.
if ! "$PYTHON" -c "import venv" 2>/dev/null; then
    die "The 'venv' module is missing from $PYTHON.

  Debian/Ubuntu:  sudo apt install python3-venv
  Fedora:         sudo dnf install python3-libs" 4
fi
ok "venv module available"

if [ "$DEV_MODE" -eq 1 ]; then
    SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    [ -f "$SOURCE_DIR/pyproject.toml" ] ||
        die "--dev needs a source checkout; no pyproject.toml beside this script." 5
    ok "source: $SOURCE_DIR"
fi

for directory in "$PREFIX" "$BIN_DIR"; do
    parent="$(dirname "$directory")"
    mkdir -p "$parent" 2>/dev/null ||
        die "Cannot create $parent — check permissions." 6
    [ -w "$parent" ] || die "$parent is not writable. Try --prefix with a path you own." 6
done
ok "install paths writable"

# ------------------------------------------------------------------- install

if [ -d "$VENV_DIR" ]; then
    step "removing previous installation at $VENV_DIR"
    rm -rf "$VENV_DIR"
fi

step "creating virtual environment"
mkdir -p "$PREFIX"
"$PYTHON" -m venv "$VENV_DIR" || die "Could not create a virtual environment in $VENV_DIR" 7

VENV_PYTHON="$VENV_DIR/bin/python"
[ -x "$VENV_PYTHON" ] || VENV_PYTHON="$VENV_DIR/Scripts/python.exe"
[ -x "$VENV_PYTHON" ] || die "The virtual environment has no python interpreter." 7
ok "virtual environment ready"

step "upgrading pip"
"$VENV_PYTHON" -m pip install --quiet --upgrade pip setuptools wheel ||
    die "Could not upgrade pip inside the virtual environment." 8

step "installing $APP (this may take a moment)"
if [ "$DEV_MODE" -eq 1 ]; then
    "$VENV_PYTHON" -m pip install --quiet --editable "$SOURCE_DIR" ||
        die "Editable install failed. Run without --quiet for the full pip output." 9
else
    if [ -f "$(dirname "${BASH_SOURCE[0]}")/pyproject.toml" ]; then
        "$VENV_PYTHON" -m pip install --quiet "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)" ||
            die "Install from the local checkout failed." 9
    else
        "$VENV_PYTHON" -m pip install --quiet "$APP-cli" ||
            die "Install from PyPI failed. Check your network connection." 9
    fi
fi
ok "package installed"

# ------------------------------------------------------------------- linking

mkdir -p "$BIN_DIR"
for name in "$APP" lora; do
    target="$VENV_DIR/bin/$name"
    [ -x "$target" ] || target="$VENV_DIR/Scripts/$name.exe"
    if [ -x "$target" ]; then
        ln -sf "$target" "$BIN_DIR/$name"
    fi
done
[ -e "$LAUNCHER" ] || die "The launcher was not created at $LAUNCHER" 10
ok "linked $LAUNCHER"

# ---------------------------------------------------------------- verification
#
# An installer that reports success without checking has told you nothing.

step "verifying installation"

INSTALLED_VERSION="$("$LAUNCHER" --version 2>/dev/null || true)"
[ -n "$INSTALLED_VERSION" ] || die "The installed command does not run. Try: $VENV_PYTHON -m loraai --version" 11
ok "$INSTALLED_VERSION"

"$LAUNCHER" analyze -t "installation self check for the loraai command line tool" \
    --json >/dev/null 2>&1 ||
    die "The analysis engine failed on a trivial input. Please report this." 11
ok "analysis engine responds"

if "$LAUNCHER" --quiet doctor >/dev/null 2>&1; then
    ok "doctor reports a healthy environment"
else
    warn "doctor reported problems — run '$APP doctor' for the details"
fi

# --------------------------------------------------------------------- PATH

PATH_WARNING=0
case ":${PATH}:" in
    *":${BIN_DIR}:"*) ok "$BIN_DIR is on your PATH" ;;
    *) PATH_WARNING=1 ;;
esac

# ------------------------------------------------------------------- summary

[ "$QUIET" -eq 1 ] && exit 0

printf '\n  %s%sInstalled.%s\n\n' "$C_BOLD" "$C_OK" "$C_RESET"

if [ "$PATH_WARNING" -eq 1 ]; then
    shell_rc="$HOME/.bashrc"
    case "${SHELL:-}" in
        */zsh)  shell_rc="$HOME/.zshrc" ;;
        */fish) shell_rc="$HOME/.config/fish/config.fish" ;;
    esac
    printf '  %s%s is not on your PATH.%s Add it:\n\n' "$C_WARN" "$BIN_DIR" "$C_RESET"
    if [ "${shell_rc##*/}" = "config.fish" ]; then
        printf '    %sfish_add_path %s%s\n\n' "$C_DIM" "$BIN_DIR" "$C_RESET"
    else
        printf '    %secho '"'"'export PATH="%s:$PATH"'"'"' >> %s%s\n' \
            "$C_DIM" "$BIN_DIR" "$shell_rc" "$C_RESET"
        printf '    %ssource %s%s\n\n' "$C_DIM" "$shell_rc" "$C_RESET"
    fi
fi

cat <<SUMMARY
  ${C_BOLD}Getting started${C_RESET}

    ${C_ACCENT}${APP}${C_RESET}                              ${C_DIM}open the interactive TUI${C_RESET}
    ${C_ACCENT}${APP} analyze${C_RESET} -f article.md         ${C_DIM}full analysis of a file${C_RESET}
    ${C_ACCENT}${APP} analyze${C_RESET} -t "some text"        ${C_DIM}analyse text directly${C_RESET}
    ${C_ACCENT}${APP} inspect${C_RESET} -f doc.txt            ${C_DIM}hidden-character forensics${C_RESET}
    ${C_ACCENT}${APP} clean${C_RESET} -f doc.txt --in-place   ${C_DIM}strip invisible characters${C_RESET}
    ${C_ACCENT}${APP} humanize${C_RESET} -f draft.md          ${C_DIM}rewrite to read naturally${C_RESET}
    ${C_ACCENT}${APP} doctor${C_RESET}                        ${C_DIM}check the environment${C_RESET}
    ${C_ACCENT}${APP} --help${C_RESET}                        ${C_DIM}every command${C_RESET}

  ${C_DIM}Installed at ${VENV_DIR}
  Uninstall with: ./install.sh --uninstall${C_RESET}

SUMMARY
