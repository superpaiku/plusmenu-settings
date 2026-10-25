#!/bin/bash
# Installs Plusmenu-Settings for this user: the plusmenu-settings command and a menu entry.
#   ./install.sh            install
#   ./install.sh --remove   uninstall (apps hidden with it stay hidden; run
#                           "plusmenu-settings list --hidden" and "plusmenu-settings show ..." first to undo)
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
bin=~/.local/bin/plusmenu-settings
entry=~/.local/share/applications/plusmenu-settings.desktop

if [[ ${1:-} == --remove ]]; then
  rm -f "$bin" "$entry"
  update-desktop-database -q ~/.local/share/applications 2>/dev/null || true
  echo "Plusmenu-Settings removed"
  exit 0
fi

chmod +x "$here/plusmenu_settings.py"
mkdir -p ~/.local/bin ~/.local/share/applications
ln -sf "$here/plusmenu_settings.py" "$bin"
cat > "$entry" <<EOF
[Desktop Entry]
Type=Application
Name=Plusmenu-Settings
Comment=Show or hide apps in the Steam Frame dashboard's + menu
Exec=$bin
Icon=view-list-symbolic
Categories=Settings;Utility;
Terminal=false
EOF
update-desktop-database -q ~/.local/share/applications 2>/dev/null || true
echo "Installed: $bin and $entry"
