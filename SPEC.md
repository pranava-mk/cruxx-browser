# cruxx browser — build specification

A small, fast, quiet WebKit browser for Omarchy (Arch Linux + Hyprland).
A Linux re-creation of the design of "Search" by Office Commun
(https://github.com/driceroland/Search, MIT). The upstream code is macOS-only
Swift and is NOT ported. Only the design idea and two data lists are reused
(see "Reuse from upstream").

## Stack (fixed, do not change)

- Python 3.14, PyGObject.
- `gi.require_version("Gtk", "3.0")`, `gi.require_version("WebKit2", "4.1")`.
  Installed package: `webkit2gtk-4.1` 2.54. Do NOT use GTK4 or WebKit 6.0.
- Standard library only. No pip packages. Tests use `unittest` (no pytest).
- Package import name: `cruxx_browser`. Command: `cruxx-browser`.
- D-Bus app ID: `dev.cruxx.Browser`. Wayland app_id, desktop file and icon name: `cruxx-browser`. Display name: `cruxx browser` (lowercase).

## Layout

```
cruxx_browser/
  __init__.py      __version__ = "0.1.0"
  __main__.py      main(): parse args, run app
  app.py           Gtk.Application (single instance, HANDLES_COMMAND_LINE; extra launches open URL as new tab in running window)
  window.py        main window: tab strip + stack of WebViews + omnibox
  tab.py           one Tab = WebKit2.WebView + title/favicon/state
  omnibox.py       PURE logic: classify input -> URL or search URL; history completion ranking
  store.py         PURE logic: XDG paths, atomic JSON read/write, history, bookmarks, session, settings, hidden rules
  shield.py        ad/tracker blocker: build WebKit content-filter JSON, compile with UserContentFilterStore
  security.py      PURE logic: URL scheme allowlist, download filename sanitizing, WebKit settings table
  theme.py         PURE logic: parse Omarchy colors.toml -> CSS; watcher for live reload
  resources/reader.js   reading mode (article extract, rebuild document)
  resources/hide.js     element picker: hover outline, click -> return a CSS selector
  resources/hidden.js   apply saved selectors at document-start (style tag, display:none !important)
tests/
  test_omnibox.py test_store.py test_shield.py test_security.py test_theme.py
  test_smoke.py   launches real app against a local http.server; skip if no WAYLAND_DISPLAY/DISPLAY
```

"PURE logic" modules must not import Gtk/WebKit, so they unit test without a display.

## Features (scope — build these, nothing more)

1. **One field (omnibox).** `Gtk.Entry` at top of tab strip. Ctrl+L focuses.
   - Input classification (`omnibox.classify(text) -> str`):
     - Has scheme `http://` or `https://` -> keep as is.
     - `localhost`, `localhost:port`, IPv4, `[IPv6]`, or `host.tld[/...]` with no spaces and a dot and a TLD of 2+ letters -> prefix `https://` (for localhost and IP literals use `http://`).
     - `about:blank` allowed.
     - Anything else (spaces, no dot, `javascript:`, `file:`, `data:`, other schemes) -> search URL. Default engine DuckDuckGo `https://duckduckgo.com/?q={q}`, URL-encode with `urllib.parse.quote_plus`. Engine is a setting (duckduckgo, google, brave, startpage, kagi).
   - Completion from local history only (`Gtk.EntryCompletion` with a ListStore, rank by prefix match of host then visit count then recency). Nothing typed is sent to the network before Enter.
2. **Tabs.** Vertical list on the left by default (`Gtk.ListBox` in a `Gtk.ScrolledWindow`, width 220). Ctrl+Shift+S toggles left/top (top = horizontal `Gtk.Box` of buttons in a scrolled window). Ctrl+S hides/shows the strip. Show favicon (if any) + title, ellipsized. Middle-click closes. Pinned tabs (Ctrl+Shift+D toggles pin) are at the top, shown icon/first-letter only.
   Restored session tabs are lazy: WebView created on first select.
3. **Keyboard** (Ctrl in place of ⌘): Ctrl+T new tab (focus omnibox), Ctrl+W close, Ctrl+Shift+T reopen closed (stack of 25), Ctrl+L field, Ctrl+K tab switcher (popover with search entry filtering open tabs by title/URL), Ctrl+R / F5 reload, Ctrl+Shift+R reading mode, Ctrl+[ / Alt+Left back, Ctrl+] / Alt+Right forward, Ctrl+Tab / Ctrl+Shift+Tab next/prev tab, Ctrl+1..8 jump, Ctrl+9 last, Ctrl+F find bar (WebKit FindController, Enter next, Shift+Enter prev, Esc close), Ctrl+D duplicate tab, Ctrl+Shift+C copy URL, Ctrl+Shift+V paste and go, Ctrl+Shift+B bookmark page, Ctrl+B bookmarks panel, Ctrl+Y history panel, Ctrl+Shift+J downloads panel, Ctrl+Shift+N private tab, Ctrl+Shift+H hide element, Ctrl+Shift+U un-hide all on this site, Ctrl+plus/minus/0 zoom, F11 fullscreen, Esc closes any open panel/find/picker, F12 web inspector ONLY if `--dev` flag given.
4. **Ad/tracker blocker** (`shield.py`). Build Safari-content-blocker JSON (same format WebKitGTK `UserContentFilterStore` accepts). Rules: block each domain in the upstream `unwanted` list with `url-filter` from upstream `networkFilter(for:)` and `load-type: ["third-party"]` exactly as upstream; css-display-none rule for upstream `slots` selectors and per-site `slotsBySite` with `if-domain`. Compile once into `$XDG_CACHE_HOME/cruxx-browser/filters/`, identifier includes a SHA-256 of the JSON so changes recompile. Apply to every normal and private WebView's UserContentManager. On by default. Per-site pause (setting `shield_paused_hosts`), toggled from a menu item; paused host -> remove filter for that view and reload.
5. **Reading mode** Ctrl+Shift+R: inject `reader.js` with `run_javascript`; it picks the largest-text `article`/`main`/block, strips scripts/iframes/forms, rebuilds a clean document with readable CSS (max-width 70ch, theme colors passed in). Toggle again reloads the page.
6. **Hide anything** Ctrl+Shift+H: inject `hide.js` (picker). Clicked element -> selector sent back through a `UserContentManager` script message handler named `cruxxHide` (register with `register_script_message_handler`). Validate selector in Python: str, length <= 512, no `{`, `}`, `<`, `;`, `@`, `\` characters. Save per registrable host (`store.hidden[host]`, max 200 per host). On every load, a document-start `UserScript` (hidden.js template) injects saved selectors as a `<style>`. Pass selectors as a JSON literal via `json.dumps` — never string concat. Ctrl+Shift+U clears for host.
7. **Private tab** Ctrl+Shift+N: WebView with a separate `WebKit2.WebContext.new_ephemeral()` (one shared ephemeral context per window). Not saved in session, history, or closed-tab stack. Visual mark (italic title + "private" CSS class).
8. **History, bookmarks, downloads panels.** A `Gtk.Revealer` side panel with a search entry and a ListBox; click opens in current tab; Delete key removes item. History capped at 20000 entries (drop oldest). Clear history button. Downloads: `WebContext` `download-started`; destination `~/Downloads` (XDG download dir via `GLib.get_user_special_dir`), filename via `security.safe_download_name` with collision suffix ` (1)`, ` (2)`. Never auto-open downloaded files. Show progress + "open folder" (via `Gio.AppInfo.launch_default_for_uri` on the folder only).
9. **Session restore.** Save open non-private tabs (url, title, pinned) + active index + strip side on change (debounced 1 s with `GLib.timeout_add`) and on quit. Restore at start; if empty open one blank tab with omnibox focused.
10. **Omarchy theme.** `theme.py` reads `$XDG_STATE_HOME/omarchy/current/theme/colors.toml` (default `~/.local/state/omarchy/current/theme/colors.toml`) with `tomllib`. Keys used: mode, accent, selection, muted, background, dark_background, lighter_background, foreground, light_foreground, red. Validate each colour with regex `^#[0-9A-Fa-f]{6}$`; invalid/missing -> built-in dark fallback. Generate GTK CSS (CssProvider, priority APPLICATION). Watch `$XDG_STATE_HOME/omarchy/current/theme.name` AND the `theme` symlink dir with `Gio.FileMonitor`; on change reload CSS (debounce 300 ms). Set `Gtk.Settings` `gtk-application-prefer-dark-theme` from `mode`. WebView background colour = theme background (`set_background_color` with `Gdk.RGBA`) so blank tabs are not white.
11. **Permission requests** (geolocation, notifications, media, clipboard, etc.): `permission-request` signal -> show an in-window `Gtk.InfoBar` "site.com wants X — Allow / Deny"; default deny; remember per host per kind in settings only if user ticks "Remember". Pointer-lock / fullscreen requests allowed.
12. **TLS errors**: `load-failed-with-tls-errors` -> show an error page via `load_alternate_html` (escape all values with `html.escape`). No bypass button.
13. **New windows / popups**: `create` signal -> open as new tab in same window only if the navigation action is user-gesture (`navigation_action.is_user_gesture()`); else block and count blocked popups.
14. **Context menu**: keep WebKit default; add "Open link in new tab". Remove "Inspect element" unless `--dev`.

## Security and hardening (required)

- `WebContext.set_sandbox_enabled(True)` BEFORE any WebView is created (bubblewrap and xdg-dbus-proxy are installed). Also add the cache dir read-only? No — do not call `sandbox_add_path` at all.
- WebsiteDataManager: base data dir `$XDG_DATA_HOME/cruxx-browser/web`, cache `$XDG_CACHE_HOME/cruxx-browser/web`. Enable ITP (`set_itp_enabled(True)`). Cookie accept policy `NO_THIRD_PARTY`. Persistent cookies in SQLite under data dir.
- WebKit settings on every WebView (put in `security.WEBKIT_SETTINGS` dict, apply with `set_property` loop, and unit test the dict): `enable-developer-extras` = dev flag; `allow-file-access-from-file-urls` False; `allow-universal-access-from-file-urls` False; `javascript-can-open-windows-automatically` False; `javascript-can-access-clipboard` False; `enable-java` absent (removed in 4.1, do not set); `enable-write-console-messages-to-stdout` False; `enable-dns-prefetching` False; `enable-hyperlink-auditing` False; `enable-mediasource` True; `enable-smooth-scrolling` True; `hardware-acceleration-policy` default. Guard each `set_property` with `settings.find_property(name)` so an unknown name is skipped with a debug log, not a crash.
- Navigation policy (`decide-policy`, NAVIGATION_ACTION + NEW_WINDOW_ACTION): allow only schemes `http`, `https`, `about` (about:blank only), `blob`, `data` only for subframes (not main frame). Block `file:` main-frame navigations unless the user typed... no: block `file:` always. Other schemes (mailto:, tel:, magnet: etc.) -> do not navigate; ask with a dialog "Open in external app?" and, if yes, `Gio.AppInfo.launch_default_for_uri`. Unit test `security.scheme_decision(uri, is_main_frame) -> "allow" | "block" | "external"`.
- `security.safe_download_name(name)`: basename only; strip path separators, NUL, control chars, leading dots and dashes; collapse whitespace; max 200 bytes UTF-8 keeping extension; empty -> "download". Unit test path traversal (`../../.bashrc`), absolute paths, `\x00`, unicode, very long names.
- `store.py`: dirs created with mode 0o700; files written atomically (temp file in same dir via `tempfile.mkstemp`, `os.fchmod(fd, 0o600)`, write, `flush`, `os.fsync`, `os.replace`). Corrupt/invalid JSON -> rename to `<name>.corrupt-<timestamp>` and start empty (never crash). Validate loaded types (lists of dicts with str fields); drop bad entries. Never store private-tab data.
- Never use `shell=True`, `os.system`, `eval`, `exec`, or string-built JS with page/user data. Data into JS goes only via `json.dumps`.
- No network requests by the app itself (no update check, no telemetry, no favicon service; favicons come from WebKit's own `FaviconDatabase` via `website_data_manager`/`WebContext.set_favicon_database_directory` — whichever exists in 4.1; check with `hasattr`).
- Logging: `logging` module, default WARNING, `--verbose` -> DEBUG. Never log full URLs at INFO or above.

## Performance

- Lazy restored tabs (no WebView until selected).
- `WebContext.set_process_model(MULTIPLE_SECONDARY_PROCESSES)`; cache model `WEB_BROWSER`.
- Debounced session/history writes (history flush every 5 s max, and on quit).
- Content filter compiled once and cached on disk.
- Start-up: window shown before session WebViews load.

## Reuse from upstream

Upstream source (read-only reference): https://github.com/driceroland/Search
- `Sources/Search/Shield.swift`: copy the `unwanted` domain list, `slots`, `slotsBySite`, `reddit` lists and the `networkFilter(for:)` regex logic into `shield.py` verbatim (data only).
- `Sources/Search/Reader.swift` and `Sources/Search/Hidden.swift`: read for behaviour ideas only.
Keep the MIT credit: file header comment in `shield.py`: "Domain and selector lists adapted from Search by Office Commun (MIT), https://github.com/driceroland/Search".

## Tests (unittest, stdlib)

Run: `python3 -m unittest discover -s tests -v` from repo root. All must pass.
- omnibox: 25+ cases incl. `example.com`, `example.com/path?q=1`, `localhost:8080`, `127.0.0.1`, `[::1]:3000`, `hello world`, `javascript:alert(1)`, `file:///etc/passwd`, `data:text/html,x`, `what is 2+2`, `a.b` (1-letter TLD -> search), unicode query, empty/whitespace string (-> None, do nothing), completion ranking.
- store: atomic write, perms 0600/0700, corrupt file recovery, bad types dropped, history cap, hidden-rule cap and validation.
- shield: JSON is valid, every rule has trigger+action, url-filter regexes compile with `re` (WebKit regex is a subset; also assert no unsupported tokens like `{`, `|` inside url-filter, matching what upstream produces), identifier changes when rules change.
- security: scheme_decision table, safe_download_name cases, WEBKIT_SETTINGS has required keys/values.
- theme: valid file, missing file, invalid colours, CSS contains accent, injection attempt in a colour value (`"#fff; } * { color: red"`) rejected.
- smoke (`test_smoke.py`): skip unless display env set. Start `http.server` on 127.0.0.1 random port serving a temp dir with a page; run `python3 -m cruxx_browser --test-url http://127.0.0.1:PORT/ --test-exit-after-load` with isolated `XDG_*_HOME` env vars pointing to temp dirs; assert exit code 0 within 30 s, and assert session.json created with mode 0600. Implement `--test-url` and `--test-exit-after-load` (hidden argparse flags: load URL in one tab, quit with code 0 on `load-changed` FINISHED, code 2 on load-failed, code 3 on 25 s timeout).

## Do not

- No features beyond this list (no sync, extensions, passwords, AI, split view, spaces).
- No network access from the app itself.
- Do not edit anything outside this repository.
