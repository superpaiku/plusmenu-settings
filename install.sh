#!/bin/bash
# Installs Plusmenu-Settings for this user: the plusmenu-settings command, a menu entry, and the
# systemd user units that run "plusmenu-settings sync" whenever an applications folder changes,
# a minute after login and every hour (Flatpak updates only change where its links point).
#   ./install.sh            install
#   ./install.sh --remove   uninstall (apps hidden with it stay hidden; run
#                           "plusmenu-settings list --hidden" and "plusmenu-settings show ..." first to undo)
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
bin=~/.local/bin/plusmenu-settings
entry=~/.local/share/applications/plusmenu-settings.desktop
units=~/.config/systemd/user  # not XDG_CONFIG_HOME: the Frametop session points it elsewhere
unit=plusmenu-settings-sync
# The Frametop session has its own XDG_RUNTIME_DIR and D-Bus; talk to the login's systemd
systemctl() { XDG_RUNTIME_DIR=/run/user/$(id -u) DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$(id -u)/bus command systemctl "$@"; }

if [[ ${1:-} == --remove ]]; then
  systemctl --user disable --now $unit.path $unit.timer 2>/dev/null || true
  rm -f "$units/$unit.service" "$units/$unit.path" "$units/$unit.timer"
  systemctl --user daemon-reload 2>/dev/null || true
  rm -f "$bin" "$entry"
  update-desktop-database -q ~/.local/share/applications 2>/dev/null || true
  echo "Plusmenu-Settings removed"
  exit 0
fi

chmod +x "$here/plusmenu_settings.py"
mkdir -p ~/.local/bin ~/.local/share/applications "$units"
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

cat > "$units/$unit.service" <<'EOF'
[Unit]
Description=Plusmenu-Settings: keep the apps hidden from the Steam Frame + menu hidden

[Service]
Type=oneshot
# Let an install or update finish writing its files
ExecStartPre=/usr/bin/sleep 3
ExecStart=%h/.local/bin/plusmenu-settings sync
EOF
cat > "$units/$unit.path" <<'EOF'
[Unit]
Description=Plusmenu-Settings: watch the applications folders

[Path]
PathModified=%h/.local/share/applications
PathModified=%h/.local/share/flatpak/exports/share/applications
PathModified=/var/lib/flatpak/exports/share/applications
PathModified=/usr/local/share/applications
PathModified=/usr/share/applications
Unit=plusmenu-settings-sync.service

[Install]
WantedBy=default.target
EOF
cat > "$units/$unit.timer" <<'EOF'
[Unit]
Description=Plusmenu-Settings: check the hidden apps after login and every hour

[Timer]
OnStartupSec=1min
OnUnitActiveSec=1h
Unit=plusmenu-settings-sync.service

[Install]
WantedBy=timers.target
EOF
systemctl --user daemon-reload
systemctl --user enable --now $unit.path $unit.timer
echo "Installed: $bin, $entry and the $unit units"
