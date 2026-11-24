"""Command-line entry point for cruxx browser."""

import argparse
import logging
import sys


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError(message)


def build_parser():
    parser = _Parser(prog="cruxx-browser", add_help=False,
                     description="A small, fast, quiet WebKit browser.")
    parser.add_argument("urls", nargs="*", help="addresses to open as tabs")
    parser.add_argument("--dev", action="store_true", help="enable the web inspector")
    parser.add_argument("--verbose", action="store_true", help="debug logging")
    # Omarchy's omarchy-launch-browser sends --incognito to most browsers.
    parser.add_argument("--private", "--incognito", "--private-window",
                        dest="private", action="store_true", help="open a private tab")
    parser.add_argument("--test-url", help=argparse.SUPPRESS)
    parser.add_argument("--test-sleep", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--test-action", choices=("wall", "peek", "peek-adopt", "float",
                                                  "float-back", "settings"), help=argparse.SUPPRESS)
    parser.add_argument("--test-hold", type=int, default=6, help=argparse.SUPPRESS)
    parser.add_argument("--test-exit-after-load", action="store_true",
                        help=argparse.SUPPRESS)
    return parser


def parse_args(argv):
    """Parse ARGV (without the program name). Raise ValueError if bad."""
    return build_parser().parse_args(list(argv))


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    if "-h" in argv or "--help" in argv:
        print(build_parser().format_help())
        return 0
    try:
        opts = parse_args(argv)
    except ValueError as exc:
        print("cruxx-browser: %s" % exc, file=sys.stderr)
        return 2
    logging.basicConfig(
        level=logging.DEBUG if opts.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s")
    from .app import CruxxApp
    app = CruxxApp(parse_args, unique=opts.test_url is None)
    status = app.run(["cruxx-browser"] + argv)
    return app.exit_code or status


if __name__ == "__main__":
    sys.exit(main())
