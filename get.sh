#!/bin/bash
# Downloads the latest release of Plusmenu-Settings and installs it for this user:
#   curl -fsSL https://raw.githubusercontent.com/superpaiku/plusmenu-settings/main/get.sh | bash
# Uninstall (apps hidden with it stay hidden; show them again in the app first to undo):
#   curl -fsSL https://raw.githubusercontent.com/superpaiku/plusmenu-settings/main/get.sh | bash -s -- --remove
set -euo pipefail

main() {  # all in a function, so a download cut short runs nothing
  local repo=superpaiku/plusmenu-settings
  local dest="$HOME/.local/share/plusmenu-settings"
  local url="https://github.com/$repo/releases/latest/download"

  if [[ ${1:-} == --remove ]]; then
    [[ -x $dest/install.sh ]] && "$dest/install.sh" --remove
    rm -rf "$dest"
    return
  fi

  tmp=$(mktemp -d)  # global: the EXIT trap runs after main has returned
  trap 'rm -rf "$tmp"' EXIT
  echo "Downloading Plusmenu-Settings..."
  curl -fsSL "$url/plusmenu-settings.tar.gz" -o "$tmp/plusmenu-settings.tar.gz"
  curl -fsSL "$url/plusmenu-settings.tar.gz.sha256" -o "$tmp/plusmenu-settings.tar.gz.sha256"
  (cd "$tmp" && sha256sum -c --quiet plusmenu-settings.tar.gz.sha256)
  tar -xzf "$tmp/plusmenu-settings.tar.gz" -C "$tmp"
  mkdir -p "$dest"
  cp -f "$tmp"/plusmenu-settings/* "$dest"/
  "$dest/install.sh"
}

main "$@"
