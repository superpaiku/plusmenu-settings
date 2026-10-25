# Plusmenu-Settings

Hides apps from the Steam Frame dashboard's + menu without uninstalling them. Desktop Mode and the Frametop desktop still list them.

## How it works

The + menu's "Launch Program" section comes from `SteamClient.Apps.ScanForInstalledNonSteamApps()`, the same scan "Add a Non-Steam Game" uses. Steam runs it with `XDG_CURRENT_DESKTOP=gamescope` over the `.desktop` files in `~/.local/share/applications`, the Flatpak exports, `/usr/local/share` and `/usr/share`, the first file of a name winning.

- The scan leaves out `NotShowIn`/`OnlyShowIn` (for `gamescope`), `NoDisplay`, `Hidden`, a missing `TryExec` program, `Terminal=true`, and `steam://` shortcuts (games are in the library).
- The dashboard then drops apps whose executable is `steam` or `vrurlhandler`, and, unless Steam's developer mode is on, `firewall-config, vlc, dolphin, cmake-gui, plasma-discover, konsole, systemsettings, qrenderdoc, sh, lxterminal`. "Install Chromium" always stays.

When it can, the app reads the developer mode setting through Steam's local CEF debugging port (127.0.0.1:8080). Entries the menu never shows are only listed through "List entries the menu never shows" and can't be switched.

Hiding an app adds `NotShowIn=gamescope;` without touching system files:

- **File already in `~/.local/share/applications`**: the key goes in that file, with the mark `X-PlusmenuSettings-Added=true`. Showing the app again takes both out.
- **Any other app**: a copy goes there with `NotShowIn=gamescope;` and `X-PlusmenuSettings-Copy=true`. Showing the app again deletes it. When there's a Frametop copy (`~/.local/share/frametop/apps`), the new copy is made from that one, so the app keeps "Launch as Standalone" in the Frametop desktop.

Reopen the + menu to see changes.

## Usage

```
./install.sh                          # plusmenu-settings command + "Plusmenu-Settings" menu entry
plusmenu-settings                     # open the window
plusmenu-settings list [--hidden]
plusmenu-settings hide vlc.desktop
plusmenu-settings show vlc.desktop
./install.sh --remove
```

## Requirements

SteamOS on the Steam Frame, with Python 3, GTK 4 and libadwaita (all preinstalled). No root access needed: everything lives in your home folder.

## Known limits

- A hidden app's copy keeps the desktop file as it was when it was hidden (name, icon, Exec). After an update, show and hide it once.
- Reinstalling Frametop or another app that writes its own entry to `~/.local/share/applications` replaces that entry, so it shows up in the + menu again until you hide it again.
- The menu's rules come from Steam's current client code and may change with a Steam update.

## License

MIT, see [LICENSE](LICENSE). Not affiliated with or endorsed by Valve.
