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

## Report a problem

Use GitHub private vulnerability reporting on this repository:
https://github.com/pranava-mk/cruxx-browser/security/advisories/new

Do not open a public issue for a security problem.
Include the version, the steps to repeat the problem, and the effect.
