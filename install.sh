#!/bin/sh
# deerctl installer for Linux and macOS.
#
#   curl -fsSL https://raw.githubusercontent.com/xuckless/deerctl/main/install.sh | sh
#
# Installs deerctl into its own Python environment in ~/.local/share/deerctl
# and links the `deerctl` command into ~/.local/bin. Nothing outside your home
# directory is touched, except (Linux) the udev rule that `deerctl setup`
# installs with sudo at the end. Re-run to update. Remove with `deerctl uninstall`.
#
# Environment overrides:
#   DEERCTL_HOME      install directory    (default ~/.local/share/deerctl)
#   DEERCTL_BIN_DIR   where to link deerctl (default ~/.local/bin)
#   DEERCTL_REF       git branch or tag     (default main)
#   DEERCTL_SRC       pip source to install from (path or URL; overrides DEERCTL_REF)
#   DEERCTL_NO_SETUP  set to 1 to skip `deerctl setup`
set -eu

REPO="xuckless/deerctl"
REF="${DEERCTL_REF:-main}"
SRC="${DEERCTL_SRC:-https://github.com/$REPO/archive/$REF.tar.gz}"
DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
PREFIX="${DEERCTL_HOME:-$DATA_HOME/deerctl}"
BIN_DIR="${DEERCTL_BIN_DIR:-$HOME/.local/bin}"
VENV="$PREFIX/venv"
LINK="$BIN_DIR/deerctl"

if [ -t 1 ]; then B="$(printf '\033[1m')"; G="$(printf '\033[32m')"; R="$(printf '\033[31m')"; N="$(printf '\033[0m')"; else B=""; G=""; R=""; N=""; fi
info() { printf '%s==>%s %s\n' "$B" "$N" "$*"; }
ok()   { printf '%s✓%s %s\n' "$G" "$N" "$*"; }
die()  { printf '%serror:%s %s\n' "$R" "$N" "$*" >&2; exit 1; }

case "$(uname -s)" in
  Linux)  OS=linux ;;
  Darwin) OS=macos ;;
  *)      die "deerctl supports Linux and macOS only." ;;
esac

# --- find Python 3.9+ ---------------------------------------------------------
PY=""
for c in python3 python3.14 python3.13 python3.12 python3.11 python3.10 python3.9; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(sys.version_info < (3, 9))' 2>/dev/null; then
    PY="$(command -v "$c")"; break
  fi
done
if [ -z "$PY" ]; then
  if [ "$OS" = macos ]; then
    die "Python 3.9+ is required. Install it with:  xcode-select --install   (or: brew install python)"
  else
    die "Python 3.9+ is required. Install python3 with your package manager (e.g. sudo apt install python3 python3-venv)."
  fi
fi
info "Using $("$PY" -V 2>&1) ($PY)"

# --- don't clobber something that isn't ours -----------------------------------
if [ -e "$LINK" ] && [ ! -L "$LINK" ]; then
  die "$LINK already exists and isn't a symlink; move it away and re-run."
fi

# --- create / update the environment ------------------------------------------
if [ -x "$VENV/bin/python" ] && "$VENV/bin/python" -c 'import sys' 2>/dev/null; then
  info "Updating deerctl in $PREFIX"
else
  info "Installing deerctl into $PREFIX"
  rm -rf "$VENV"
  mkdir -p "$PREFIX"
  if ! "$PY" -m venv "$VENV" >/dev/null 2>&1; then
    rm -rf "$VENV"
    die "Couldn't create a Python virtual environment. On Debian/Ubuntu: sudo apt install python3-venv"
  fi
fi
"$VENV/bin/python" -m pip install --quiet --disable-pip-version-check --upgrade pip >/dev/null 2>&1 || true
"$VENV/bin/python" -m pip install --quiet --disable-pip-version-check --upgrade --force-reinstall "$SRC" \
  || die "pip install failed (source: $SRC)"

mkdir -p "$BIN_DIR"
ln -sfn "$VENV/bin/deerctl" "$LINK"
printf '%s\n' "$LINK" > "$PREFIX/.deerctl-install"
ok "Installed $("$LINK" --version 2>/dev/null | sed 's/^/deerctl /') → $LINK"

# --- PATH hint ----------------------------------------------------------------
case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *)
    shell_rc="~/.profile"
    case "${SHELL:-}" in
      */zsh)  shell_rc="~/.zshrc" ;;
      */bash) shell_rc="~/.bashrc" ;;
      */fish) shell_rc="~/.config/fish/config.fish" ;;
    esac
    printf '\n%s is not on your PATH. Add this line to %s:\n' "$BIN_DIR" "$shell_rc"
    case "${SHELL:-}" in
      */fish) printf '    fish_add_path %s\n\n' "$BIN_DIR" ;;
      *)      printf '    export PATH="%s:$PATH"\n\n' "$BIN_DIR" ;;
    esac
    ;;
esac

# --- one-time setup (Linux udev rule) -----------------------------------------
if [ "${DEERCTL_NO_SETUP:-0}" != 1 ]; then
  if [ "$OS" = linux ]; then
    if [ -r /dev/tty ] && { : < /dev/tty; } 2>/dev/null; then
      info "Running one-time setup (installs a udev rule; asks for your sudo password)"
      "$LINK" setup < /dev/tty || printf '\nSetup did not finish. Run it later with:  deerctl setup\n'
    else
      printf '\nFinish with the one-time setup:  deerctl setup\n'
    fi
  else
    "$LINK" setup || true
  fi
fi

printf '\n%sDone.%s  deerctl gui   (graphical editor)\n       deerctl --help\n       deerctl uninstall   (removes everything)\n' "$B" "$N"
