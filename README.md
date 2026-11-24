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

- One field (omnibox) for URLs and searches. There is no toolbar. The field shows in the middle of the page when you press Ctrl+L or open a new tab. It shows the current address. Esc hides it.
- Suggestions come from local history and bookmarks only. The first row is the search or the address you typed. Use Up, Down, and Enter. Nothing is sent to the network before Enter.
- Tabs in a vertical list or a top bar. Pinned tabs show as small square tiles. The close button shows when the pointer is on a row. A faded "New tab" row ends the list. The settings button (menu) is at the bottom of the list.
- Status line: the address of a link under the pointer shows at the bottom-left of the page. Restored tabs load only when you select them.
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
- Tab sleep. A background tab that you did not use for 30 minutes frees its web process. The tab row stays. When you select the tab, it loads its page again. The setting `sleep_after_min` in `settings.json` sets the time (0 = never). A selected tab, a tab that plays sound, a tab with a download, and a pinned tab do not sleep. Set `sleep_pinned` to `true` to let pinned tabs sleep.
- Keep an important site awake. Set `keep_awake_enabled` to `true`, or use "Offer keep-awake for sites" in the settings menu. Then the settings menu and the tab context menu (right-click) show "Keep This Site Awake". The site is saved in `keep_awake_hosts`. For a private tab the choice stays in memory only. A tab of a site that is kept awake never sleeps.
- Memory limit. If WebKit supports it, the app sets a memory limit for the web processes (25% of RAM, from 512 MB to 4 GB). WebKit then frees memory early when the limit is near.
- Clean links. When you type or paste an address, or open a link in a new tab, the app removes tracking parameters (utm_*, fbclid, gclid, msclkid, and others). Other parameters and the part after # stay. Links that the page itself opens are not changed.
- Rename a tab. Double-click the tab title, or right-click and choose "Rename tab". Enter saves, Esc cancels, an empty name resets the title. The name is saved in the session. A private tab does not save it.
- Drag tabs to change their order, in the tab column and in the top strip. Drop a tab on the pinned tiles to pin it. Drag a pinned tile into the list to unpin it. The order is saved in the session.
- Find in page, zoom, fullscreen, and a tab switcher (Ctrl+K, a floating list with fuzzy match on title and address).

## Keyboard

| Key | Action |
| --- | --- |
| Ctrl+T | New tab |
| Ctrl+W | Close tab |
| Ctrl+Shift+T | Reopen closed tab |
| Ctrl+L | Show the address field |
| Ctrl+K | Tab switcher (type to filter, Up, Down, Enter) |
| Ctrl+R, F5 | Reload |
| Ctrl+Alt+R | Reload from the origin (ignore the cache) |
| Ctrl+Shift+R | Reading mode |
| Ctrl+[, Alt+Left | Back |
| Ctrl+], Alt+Right | Forward |
| Ctrl+Tab, Ctrl+Shift+Tab | Next, previous tab |
| Ctrl+Shift+], Ctrl+Shift+[ | Next, previous tab |
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
| Esc | Close address field, switcher, panel, find bar, or picker |
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
