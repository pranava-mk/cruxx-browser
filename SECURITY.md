# Security

## Threat model

- Web pages are not trusted. They can run hostile JavaScript.
- Downloaded file names are not trusted.
- Data files on disk can be corrupt or changed.
- Page text and user text must never become code.
- Other users on the same computer must not read browser data.

Out of scope: a hostile local user with your account, and bugs in WebKit itself.
Update `webkit2gtk-4.1` often.

## Hardening

- The WebKit sandbox is on. It uses bubblewrap and xdg-dbus-proxy. The code sets it before any view exists.
- ITP is on. The browser blocks third-party cookies.
- Each WebView gets a fixed set of WebKit settings. File access from file URLs is off. Automatic popups are off. Clipboard access from JavaScript is off. DNS prefetch and hyperlink auditing are off.
- Navigation uses an allowlist of schemes: `http`, `https`, `about:blank`, `blob`, and `data` in subframes only.
- The browser blocks `file:`. Other schemes ask the user before they open an external app.
- Download names lose path parts, control characters, and leading dots and dashes. Names are limited to 200 bytes.
- The browser never opens a downloaded file by itself.
- Data directories have mode 0700. Data files have mode 0600. Writes are atomic.
- Corrupt data files are renamed to `<name>.corrupt-<timestamp>`. The app starts with empty data.
- The code does not use `shell=True`, `os.system`, `eval`, or `exec`.
- Data goes into JavaScript only through `json.dumps`.
- Hidden-element selectors are checked for type, length, and forbidden characters.
- Permission requests default to deny.
- TLS errors show an error page. There is no bypass button.
- Popups need a user gesture.
- The app makes no network requests by itself. It has no telemetry.
- The code never logs full URLs at INFO level or above.

## Passwords

- Where: passwords are stored in the system keyring (Secret Service, through libsecret). The schema is `dev.cruxx.Browser.Password`. The attributes are `origin` and `username`. The browser never writes a password to a file. `settings.json` holds only the switch `passwords_enabled` and the list `password_never` (origins).
- If the keyring is not available, or it stays locked, the feature turns off. The app does not crash.
- The browser never logs user names, passwords, or full URLs.
- Origin: the browser computes the origin in Python, from the address of the top-level page of the tab. It never trusts an origin, URL, or host that a page script sends.
- Only `https` origins and `http` on `localhost`, `127.0.0.1`, and `[::1]` can save or fill. A fill needs an exact origin match: scheme, host, and port. Sub domains do not match.
- Top frame only: the form script runs in the isolated world "cruxx" in the top frame. Frames and iframes cannot capture or receive a password. The message handler `cruxxForms` exists only in that world. A page cannot call it. The script ignores events that the page itself made (`isTrusted`).
- The browser checks every message: types, lengths (user name 512, password 4096), and no NUL characters.
- Save: the browser keeps a sign-in in memory for 60 seconds, for one tab. It asks to save only after the next page finished loading on the same site and that page has no visible password field. You can choose Save, Never for this site, or Not now.
- Never auto-fill: the browser puts a value in a field only after you click an account in the list. The browser sends the values to the page with `json.dumps`. The script sets the value and sends `input` and `change` events.
- Private tabs: a private tab never offers to save and never writes. It can fill, read only.
- Copy: a copied password leaves the clipboard after 45 seconds, only if the clipboard still holds it. The Show button hides the password again after 10 seconds.

## Report a problem

Use GitHub private vulnerability reporting on this repository:
https://github.com/pranava-mk/cruxx-browser/security/advisories/new

Do not open a public issue for a security problem.
Include the version, the steps to repeat the problem, and the effect.
