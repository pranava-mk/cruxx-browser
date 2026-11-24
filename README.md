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
- Tabs in a vertical list or a top bar. Pinned tabs show as small square tiles. The close button shows when the pointer is on a row. A faded "New tab" row ends the list. The settings button (menu) is at the bottom of the list. Its first item is "Settings…".
- Status line: the address of a link under the pointer shows at the bottom-left of the page. Restored tabs load only when you select them.
- Settings window (Ctrl+comma, or "Settings…" in the menu). A list of sections is on the left. The content is on the right. A change applies at once and the app saves it with an atomic write. The sections are:
  - General: search engine, restore last session (`restore_session`, on by default), and tabs side (left or top).
  - Tabs: sleep time (never, 15, 30, 60 or 120 minutes), sleep for pinned tabs, the keep-awake offer, and Split View.
  - Privacy: the global ad and tracker shield (`shield_enabled`, on by default), the sites where the shield is paused, the remembered permissions (each has a Remove button), and buttons to clear history, cookies and site data (the app asks first), and hidden-element rules. When the shield is off, no page uses the filter.
  - Shortcuts: a read-only table. The app builds it from the real shortcut table in `shortcuts.py`.
  - About: version, credit, data folders, and the no-telemetry statement.
  Press Ctrl+1 to Ctrl+5 in the window to go to a section. Esc closes it. The menu keeps only the page actions (reading mode, hide element, hidden list, reload from origin, keep awake, pause shield on this site, split current page, new space).
- Site card. Click the site mark of the selected tab row, or press Ctrl+I. A popover shows the host, the connection (https or not secure, with the certificate subject and issuer when WebKit gives them), a shield switch for this site, a keep-awake switch (when the offer is on), the zoom level (minus, reset, plus), the permissions that the app remembers for this site (each has a Revoke button), the number of hidden elements with "Show hidden list", "Clear cookies for this site", and the number of blocked popups. The zoom level is saved for each host in `zoom_by_host` and applies when the page loads. In a private tab, all changes stay in memory.
- Ad and tracker blocker. You can pause it for one site, or turn it off in Settings.
- Reading mode.
- Hide any element on a page. The browser remembers it for that site. Ctrl+Shift+U opens a list of the hidden selectors for the site. Each row has a Remove button, and "Unhide all" removes all rules. The page reloads to show the change.
- Private tabs. The browser saves no data from them.
- History, bookmarks, and downloads panels.
- Session restore.
- Live Omarchy theme.
- Permission requests with Allow and Deny. The default is deny.
- Error page for TLS errors. No bypass button.
- Popup blocking. A popup opens only after a user gesture.
- Tab sleep. A background tab that you did not use for 30 minutes frees its web process. The tab row stays. When you select the tab, it loads its page again. The setting `sleep_after_min` in `settings.json` sets the time (0 = never). A selected tab, a tab that plays sound, a tab with a download, and a pinned tab do not sleep. Set `sleep_pinned` to `true` to let pinned tabs sleep.
- Keep an important site awake. Set `keep_awake_enabled` to `true`, or use "Offer keep-awake for sites" in Settings. Then the settings menu and the tab context menu (right-click) show "Keep This Site Awake". The site is saved in `keep_awake_hosts`. For a private tab the choice stays in memory only. A tab of a site that is kept awake never sleeps.
- Memory limit. If WebKit supports it, the app sets a memory limit for the web processes (25% of RAM, from 512 MB to 4 GB). WebKit then frees memory early when the limit is near.
- Clean links. When you type or paste an address, or open a link in a new tab, the app removes tracking parameters (utm_*, fbclid, gclid, msclkid, and others). Other parameters and the part after # stay. Links that the page itself opens are not changed.
- Rename a tab. Double-click the tab title, or right-click and choose "Rename tab". Enter saves, Esc cancels, an empty name resets the title. The name is saved in the session. A private tab does not save it.
- Drag tabs to change their order, in the tab column and in the top strip. Drop a tab on the pinned tiles to pin it. Drag a pinned tile into the list to unpin it. The order is saved in the session.
- Split View. It is off by default. Turn it on with "Split View" in Settings (`split_enabled` in `settings.json`). Press Ctrl+Alt+N, or use "Split current page" in the settings menu. The browser pairs the current tab with the next tab. If there is no other tab, it opens a new blank tab and shows the address field. You can also drag a tab from the list onto the page. Drag the divider to change the width of the panes. The pane with the outline gets all page commands (address field, find, reading mode, hide element, zoom, reload, back, forward). Click a pane, or press Ctrl+Alt+Left or Ctrl+Alt+Right, to move the focus. Ctrl+W closes the focused tab. The other pane then takes the whole area. A pair shows as two rows with a bar on the left side. Click one row to select the pair with that pane in focus. "Separate split tabs" (settings menu, tab menu) makes the two tabs normal again. A pinned tab cannot be in a pair. Pairs and the divider position are saved in the session. A pair that has a private tab is not saved. Tab sleep never puts a visible pane to sleep. If you turn Split View off, all pairs end.
- Spaces. A space is a separate set of tabs and pins. It has a name, an icon (a letter or an emoji), its own split pairs, and its own selected tab. The first space is "Home". Small round marks at the bottom of the tab list show the spaces. Click a mark to switch. Right-click a mark to rename or delete the space, or to add a new space. "New space" is also in the settings menu. The browser asks before it deletes a space that has tabs. A switch does not close the pages of the other spaces. They can sleep as usual. A private tab belongs to the current space. The browser does not save it. The session keeps all spaces. Old session files load into the space "Home". You can have up to 9 spaces.
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
| Ctrl+Alt+N | Split the current page (Split View must be on) |
| Ctrl+Alt+Left, Ctrl+Alt+Right | Move the focus to the left or right pane |
| Alt+1 to Alt+9 | Go to space 1 to 9 |
| Ctrl+Alt+Page Up, Ctrl+Alt+Page Down | Previous, next space |
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
| Ctrl+Shift+U | Hidden elements on this site (list) |
| Ctrl+I | Site card |
| Ctrl+comma | Settings |
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
