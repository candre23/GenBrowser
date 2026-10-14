#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DESKTOP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
DESKTOP_FILE="$DESKTOP_DIR/genbrowser.desktop"

if ! command -v python3 >/dev/null 2>&1; then
  echo 'Python 3 is required. On Ubuntu: sudo apt install python3 python3-venv' >&2
  exit 1
fi
if [ ! -x "$APP_DIR/.venv/bin/python" ]; then
  python3 -m venv "$APP_DIR/.venv"
fi
"$APP_DIR/.venv/bin/python" -m pip install -r "$APP_DIR/requirements.txt"

mkdir -p "$DESKTOP_DIR"
# Desktop Entry Exec uses double-quoted arguments so installation paths can contain spaces.
escape_exec() {
  local value="$1"
  value="${value//\\/\\\\}"
  value="${value//\"/\\\"}"
  value="${value//\$/\\\$}"
  value="${value//\`/\\\`}"
  printf '"%s"' "$value"
}
PYTHON_CMD="$(escape_exec "$APP_DIR/.venv/bin/python")"
SCRIPT_ARG="$(escape_exec "$APP_DIR/genbrowser.py")"
cat > "$DESKTOP_FILE" <<DESKTOP
[Desktop Entry]
Type=Application
Name=GenBrowser
Comment=Browse images and AI generation metadata
Exec=$PYTHON_CMD $SCRIPT_ARG %f
Terminal=false
Categories=Graphics;Photography;
MimeType=image/png;image/jpeg;image/webp;image/bmp;image/gif;image/tiff;
StartupNotify=true
DESKTOP
chmod 644 "$DESKTOP_FILE"
if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$DESKTOP_DIR" || true
fi
printf 'GenBrowser installed. Open it from the application menu, or run:\n%s\n' "$APP_DIR/.venv/bin/python $APP_DIR/genbrowser.py"
