#!/usr/bin/env bash
# Installs the Pomodoro top bar extension and app for the current user (symlinked, so edits apply live).
set -euo pipefail
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UUID=pomodoro@joran.dev
DATA="${XDG_DATA_HOME:-$HOME/.local/share}"

glib-compile-schemas "$SRC/extension/schemas"

mkdir -p "$DATA/gnome-shell/extensions" "$HOME/.local/bin" "$DATA/applications" "$DATA/icons/hicolor/scalable/apps"
ln -sfn "$SRC/extension" "$DATA/gnome-shell/extensions/$UUID"
ln -sf "$SRC/app/pomodoro.py" "$HOME/.local/bin/pomodoro"
chmod +x "$SRC/app/pomodoro.py"
cp "$SRC/data/dev.joran.Pomodoro.desktop" "$DATA/applications/"
cp "$SRC/data/dev.joran.Pomodoro.svg" "$DATA/icons/hicolor/scalable/apps/"
gtk-update-icon-cache -q -t "$DATA/icons/hicolor" 2>/dev/null || true
update-desktop-database -q "$DATA/applications" 2>/dev/null || true

gnome-extensions enable "$UUID" 2>/dev/null || \
  gsettings set org.gnome.shell enabled-extensions "$(python3 -c "
import ast,subprocess
v=ast.literal_eval(subprocess.check_output(['gsettings','get','org.gnome.shell','enabled-extensions'],text=True).replace('@as ',''))
print(v+['$UUID'] if '$UUID' not in v else v)")"
echo "Installed. On Wayland, log out and back in once so GNOME Shell loads the new extension."
