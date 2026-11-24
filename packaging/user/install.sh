#!/bin/sh
# Install cruxx browser for the current user only. No root access is needed.
# Usage: packaging/user/install.sh [install|uninstall]
set -eu

root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
data="${XDG_DATA_HOME:-$HOME/.local/share}"
lib="$HOME/.local/lib/cruxx-browser"
bin="$HOME/.local/bin/cruxx-browser"
apps="$data/applications"
icon="$data/icons/hicolor/scalable/apps/cruxx-browser.svg"

refresh() {
  command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database -q "$apps" || true
  command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -q -t "$data/icons/hicolor" || true
}

case "${1:-install}" in
install)
  # Copy the package into a new directory, then swap it in.
  rm -rf "$lib.new"
  mkdir -p "$lib.new"
  (cd "$root" && find cruxx_browser -type f \( -name '*.py' -o -path 'cruxx_browser/resources/*' \) \
     -not -path '*/__pycache__/*' -exec install -Dm644 {} "$lib.new/{}" \;)
  python3 -m compileall -q "$lib.new"
  rm -rf "$lib"
  mv "$lib.new" "$lib"

  # Launcher. -I (isolated mode) keeps the current directory off sys.path.
  mkdir -p "$(dirname "$bin")"
  cat > "$bin.new" <<LAUNCHER
#!/bin/sh
exec /usr/bin/python3 -I -c 'import sys; sys.path.insert(0, "$lib"); from cruxx_browser.__main__ import main; sys.exit(main())' "\$@"
LAUNCHER
  chmod 755 "$bin.new"
  mv "$bin.new" "$bin"

  # Desktop file with the absolute launcher path, and the icon.
  mkdir -p "$apps"
  sed "s|^Exec=cruxx-browser|Exec=$bin|" "$root/packaging/cruxx-browser.desktop" > "$apps/cruxx-browser.desktop"
  chmod 644 "$apps/cruxx-browser.desktop"
  install -Dm644 "$root/packaging/cruxx-browser.svg" "$icon"
  refresh
  echo "Installed. Launcher: $bin"
  ;;
uninstall)
  rm -rf "$lib" "$bin" "$apps/cruxx-browser.desktop" "$icon"
  refresh
  echo "Removed. Browser data in ~/.local/share/cruxx-browser is kept."
  ;;
*)
  echo "usage: $0 [install|uninstall]" >&2
  exit 2
  ;;
esac
