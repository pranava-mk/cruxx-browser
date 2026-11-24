# cruxx browser

## What it is

cruxx browser is a small, fast, quiet web browser for Omarchy.
Omarchy is Arch Linux with Hyprland.
The browser uses Python, GTK3, and WebKit2GTK 4.1.

The design comes from Search by Office Commun
(https://github.com/driceroland/Search).
cruxx browser is a new Linux app. It is not a port of the Swift code.
It reuses only the design idea and two data lists (ad-blocker domains and selectors).

## Features

- One field (omnibox) for URLs and searches. Completion uses local history only.
- Tabs in a vertical list or a top bar. Pinned tabs. Restored tabs load only when you select them.
- Ad and tracker blocker. You can pause it for one site.
- Reading mode.
- Hide any element on a page. The browser remembers it for that site.
- Private tabs. The browser saves no data from them.
- History, bookmarks, and downloads panels.
- Session restore.
- Live Omarchy theme.
- Permission requests with Allow and Deny. The default is deny.
- Error page for TLS errors. No bypass button.
- Popup blocking. A popup opens only after a user gesture.
- Find in page, zoom, fullscreen, and a tab switcher.

## Keyboard

| Key | Action |
| --- | --- |
| Ctrl+T | New tab |
| Ctrl+W | Close tab |
| Ctrl+Shift+T | Reopen closed tab |
| Ctrl+L | Focus the omnibox |
| Ctrl+K | Tab switcher |
| Ctrl+R, F5 | Reload |
| Ctrl+Shift+R | Reading mode |
| Ctrl+[, Alt+Left | Back |
| Ctrl+], Alt+Right | Forward |
| Ctrl+Tab, Ctrl+Shift+Tab | Next, previous tab |
| Ctrl+1 to Ctrl+8 | Go to tab 1 to 8 |
| Ctrl+9 | Go to last tab |
| Ctrl+F | Find in page |
| Ctrl+D | Duplicate tab |
| Ctrl+Shift+C | Copy URL |
| Ctrl+Shift+V | Paste and go |
| Ctrl+Shift+B | Bookmark page |
| Ctrl+B | Bookmarks panel |
| Ctrl+Y | History panel |
| Ctrl+Shift+J | Downloads panel |
| Ctrl+Shift+N | Private tab |
| Ctrl+Shift+H | Hide element |
| Ctrl+Shift+U | Show all hidden elements on this site |
| Ctrl+Shift+D | Pin or unpin tab |
| Ctrl+Shift+S | Move tab strip left or top |
| Ctrl+S | Hide or show tab strip |
| Ctrl+plus, Ctrl+minus, Ctrl+0 | Zoom in, zoom out, reset zoom |
| F11 | Fullscreen |
| Esc | Close panel, find bar, or picker |
| F12 | Web inspector (only with `--dev`) |

## Install

Install from source on Arch Linux:

```
git clone https://github.com/pranava-mk/cruxx-browser
cd cruxx-browser
make install
```

`make install` runs `makepkg -fsi`. It builds the package from the local tree.
Pacman installs the dependencies:

```
sudo pacman -S python python-gobject gtk3 webkit2gtk-4.1 bubblewrap xdg-dbus-proxy hicolor-icon-theme
```

To build the package without installing it, run `make package`.

## Run from source

Install the dependencies with pacman first. Then run:

```
make run
```

Use `--dev` to enable the web inspector. Use `--verbose` for debug logs.

## Omarchy integration

**Theme.** The browser reads `colors.toml` from
`$XDG_STATE_HOME/omarchy/current/theme/`. The default is
`~/.local/state/omarchy/current/theme/colors.toml`.
It reloads the colors when you change the Omarchy theme.
If the file is missing or a color is not valid, the browser uses a built-in dark theme.

**Default browser.** Run this command:

```
xdg-settings set default-web-browser cruxx-browser.desktop
```

Then the Omarchy browser key opens cruxx browser.
Omarchy's private-browser command also works, because the app accepts `--incognito`.

**Keybind.** Omarchy uses a Lua Hyprland config.
Add a line to `~/.config/hypr/bindings.lua`.
See `packaging/hyprland-bindings.lua.example`.

```lua
o.bind("SUPER + SHIFT + B", "cruxx browser", "uwsm-app -- cruxx-browser")
```

**Window class.** The Wayland app ID is `cruxx-browser`.
Use it in Hyprland window rules.

## Privacy

- The browser has no telemetry.
- The app makes no network requests by itself. It has no update check.
- Only the web pages you open use the network.
- Typed text goes to the network only after you press Enter.
- The browser keeps data under the XDG directories.
- Directories have mode 0700. Files have mode 0600.
- Private tabs write nothing to history, session, or the closed-tab list.

## Security

- WebKit runs in a sandbox (bubblewrap and xdg-dbus-proxy).
- Intelligent Tracking Prevention (ITP) is on.
- The browser blocks third-party cookies.
- Only `http`, `https`, `about:blank`, and `blob` pages load. `data:` loads only in subframes.
- The browser never opens `file:` pages.
- Other schemes (for example `mailto:`) ask you before they open an external app.
- A popup opens only after a user gesture.
- The browser never opens a downloaded file by itself.

See `SECURITY.md` for more.

## Testing

Run all tests:

```
make test
```

Run only the tests that need no display:

```
make test-unit
```

The smoke test needs a display. It skips when none is found.
Run `make lint` to check the Python files.

## License

MIT. See `LICENSE`.
Ad-blocker domain and selector lists come from Search by Office Commun (MIT).
