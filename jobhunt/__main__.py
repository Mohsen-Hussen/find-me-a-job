"""Command line: uv run python -m jobhunt <command>"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import plistlib
import subprocess
import sys
from pathlib import Path

from . import settings as settings_mod

LABEL = "com.yahia.jobhunt"
PLIST = Path.home() / "Library/LaunchAgents" / f"{LABEL}.plist"


def cmd_run(args) -> None:
    from . import pipeline

    stages = tuple(args.stages.split(",")) if args.stages else ("fetch", "screen", "assess", "notify")
    print(json.dumps(pipeline.run(stages=stages), indent=2))


def cmd_serve(args) -> None:
    from . import web

    web.serve(port=args.port, scheduler=not args.no_schedule)


def cmd_cv(args) -> None:
    text = settings_mod.save_cv_pdf(Path(args.pdf).expanduser().read_bytes())
    print(f"Saved CV ({len(text)} characters of text) to {settings_mod.CV_TEXT_FILE}")


def cmd_email_setup(args) -> None:
    from . import notify

    s = settings_mod.load()
    user = input(f"Gmail address to send from [{s['email']['smtp_user'] or 'you@gmail.com'}]: ").strip() or s["email"]["smtp_user"]
    to = input(f"Send alerts to [{s['email']['to'] or user}]: ").strip() or s["email"]["to"] or user
    print("Create an app password at https://myaccount.google.com/apppasswords (needs 2-Step Verification).")
    password = getpass.getpass("Paste the 16-character app password (hidden): ").replace(" ", "")
    notify.store_password(user, password)
    s["email"].update(smtp_user=user, to=to)
    settings_mod.save(s)
    print("Saved. The password is in your macOS Keychain (service 'jobhunt-smtp'), not in any file.")


def cmd_install(args) -> None:
    uv = subprocess.run(["which", "uv"], capture_output=True, text=True).stdout.strip() or "/opt/homebrew/bin/uv"
    root = settings_mod.ROOT
    PLIST.parent.mkdir(parents=True, exist_ok=True)
    path = ":".join(
        [str(Path.home() / ".local/bin"), "/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin", "/usr/sbin", "/sbin"]
    )
    plist = {
        "Label": LABEL,
        "ProgramArguments": [uv, "run", "--project", str(root), "python", "-m", "jobhunt", "serve"],
        "WorkingDirectory": str(root),
        "RunAtLoad": True,
        "KeepAlive": True,
        "EnvironmentVariables": {"PATH": path, "HOME": str(Path.home())},
        "StandardOutPath": str(settings_mod.DATA / "server.log"),
        "StandardErrorPath": str(settings_mod.DATA / "server.log"),
    }
    with open(PLIST, "wb") as fh:
        plistlib.dump(plist, fh)
    subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}", str(PLIST)], capture_output=True)
    subprocess.run(["launchctl", "bootstrap", f"gui/{os.getuid()}", str(PLIST)], check=True)
    print(f"Installed {PLIST}. Dashboard: http://localhost:8765 (starts at login, searches on schedule).")


def cmd_uninstall(args) -> None:
    subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}", str(PLIST)], capture_output=True)
    PLIST.unlink(missing_ok=True)
    print("Removed the background service.")


def main() -> None:
    parser = argparse.ArgumentParser(prog="jobhunt")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("run", help="run one search + scoring pass now")
    p.add_argument("--stages", help="comma list of fetch,screen,assess,notify")
    p.set_defaults(func=cmd_run)
    p = sub.add_parser("serve", help="dashboard + scheduler on http://localhost:8765")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--no-schedule", action="store_true")
    p.set_defaults(func=cmd_serve)
    p = sub.add_parser("cv", help="load a CV PDF")
    p.add_argument("pdf")
    p.set_defaults(func=cmd_cv)
    sub.add_parser("email-setup", help="store Gmail app password in the Keychain").set_defaults(func=cmd_email_setup)
    sub.add_parser("install", help="run dashboard + scheduler in the background at login").set_defaults(func=cmd_install)
    sub.add_parser("uninstall", help="remove the background service").set_defaults(func=cmd_uninstall)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    sys.exit(main())
