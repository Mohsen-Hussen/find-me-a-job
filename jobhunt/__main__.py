"""Command line: uv run python -m jobhunt <command>"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import settings as settings_mod

# Background-service identifiers per OS.
MAC_LABEL = "com.jobhunt.radar"
MAC_PLIST = Path.home() / "Library/LaunchAgents" / f"{MAC_LABEL}.plist"
WIN_TASK = "JobRadar"
LINUX_UNIT = "jobhunt.service"
LINUX_UNIT_PATH = Path.home() / ".config/systemd/user" / LINUX_UNIT


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
    print("Saved. The password is in your OS credential store (service 'jobhunt-smtp'), not in any file.")


def cmd_set_token(args) -> None:
    import keyring

    from .scoring import TOKEN_SERVICE

    print("Create a long-lived token first with:  claude setup-token")
    token = getpass.getpass("Paste your Claude token (hidden): ").strip()
    if not token:
        print("No token entered; nothing changed.")
        return
    keyring.set_password(TOKEN_SERVICE, "oauth_token", token)
    print("Stored the token in your OS credential store. Restart the dashboard (serve) to use it.")


def _uv_path() -> str:
    found = shutil.which("uv")
    if found:
        return found
    name = "uv.exe" if sys.platform == "win32" else "uv"
    local = Path.home() / ".local" / "bin" / name
    if local.exists():
        return str(local)
    return "uv"  # assume it's on PATH at service-start time


# ---------- background service: install / uninstall per OS ----------

def _install_mac(uv: str, root: Path) -> None:
    import plistlib

    MAC_PLIST.parent.mkdir(parents=True, exist_ok=True)
    path = ":".join(
        [str(Path.home() / ".local/bin"), "/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin", "/usr/sbin", "/sbin"]
    )
    plist = {
        "Label": MAC_LABEL,
        "ProgramArguments": [uv, "run", "--project", str(root), "python", "-m", "jobhunt", "serve"],
        "WorkingDirectory": str(root),
        "RunAtLoad": True,
        "KeepAlive": True,
        "EnvironmentVariables": {"PATH": path, "HOME": str(Path.home())},
        "StandardOutPath": str(settings_mod.DATA / "server.log"),
        "StandardErrorPath": str(settings_mod.DATA / "server.log"),
    }
    with open(MAC_PLIST, "wb") as fh:
        plistlib.dump(plist, fh)
    subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}", str(MAC_PLIST)], capture_output=True)
    subprocess.run(["launchctl", "bootstrap", f"gui/{os.getuid()}", str(MAC_PLIST)], check=True)
    print(f"Installed {MAC_PLIST}. Dashboard: http://localhost:8765 (starts at login, searches on schedule).")


def _win_startup_dir() -> Path:
    return Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def _install_windows(uv: str, root: Path) -> None:
    data = settings_mod.DATA
    data.mkdir(exist_ok=True)
    log = data / "server.log"
    # A .bat runs the server; a .vbs launches it with no console window.
    bat = data / "serve.bat"
    bat.write_text(
        "@echo off\r\n"
        f'cd /d "{root}"\r\n'
        f'"{uv}" run python -m jobhunt serve >> "{log}" 2>&1\r\n'
    )
    vbs = data / "serve.vbs"
    vbs.write_text(f'CreateObject("Wscript.Shell").Run "cmd /c ""{bat}""", 0, False\r\n')
    # A Startup-folder entry runs it at login without admin rights (Task
    # Scheduler registration needs elevation). The dashboard's own scheduler
    # then runs a search every 30 minutes.
    startup = _win_startup_dir()
    startup.mkdir(parents=True, exist_ok=True)
    (startup / "JobRadar.vbs").write_text(
        f'CreateObject("Wscript.Shell").Run "wscript ""{vbs}""", 0, False\r\n'
    )
    subprocess.Popen(["wscript", str(vbs)], cwd=str(root))  # start it now
    print(f"Added Job Radar to your Startup folder ({startup / 'JobRadar.vbs'}) and started it now.")
    print("It starts automatically at login. Dashboard: http://localhost:8765")


def _install_linux(uv: str, root: Path) -> None:
    LINUX_UNIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    LINUX_UNIT_PATH.write_text(
        "[Unit]\n"
        "Description=Job Radar dashboard and scheduler\n\n"
        "[Service]\n"
        f"WorkingDirectory={root}\n"
        f"ExecStart={uv} run python -m jobhunt serve\n"
        "Restart=always\n"
        f"StandardOutput=append:{settings_mod.DATA / 'server.log'}\n"
        f"StandardError=append:{settings_mod.DATA / 'server.log'}\n\n"
        "[Install]\n"
        "WantedBy=default.target\n"
    )
    subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True)
    subprocess.run(["systemctl", "--user", "enable", "--now", LINUX_UNIT], check=True)
    print(f"Installed {LINUX_UNIT_PATH} (starts at login, restarts on crash). Dashboard: http://localhost:8765")
    print("Tip: `loginctl enable-linger $USER` keeps it running when you're logged out.")


def cmd_install(args) -> None:
    uv, root = _uv_path(), settings_mod.ROOT
    if sys.platform == "darwin":
        _install_mac(uv, root)
    elif sys.platform == "win32":
        _install_windows(uv, root)
    else:
        _install_linux(uv, root)


def _uninstall_mac() -> None:
    subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}", str(MAC_PLIST)], capture_output=True)
    MAC_PLIST.unlink(missing_ok=True)


def _uninstall_windows() -> None:
    (_win_startup_dir() / "JobRadar.vbs").unlink(missing_ok=True)
    for leftover in ("serve.bat", "serve.vbs", "jobradar_task.xml"):
        (settings_mod.DATA / leftover).unlink(missing_ok=True)
    print("Note: a dashboard already running stays up until you close it or sign out.")


def _uninstall_linux() -> None:
    subprocess.run(["systemctl", "--user", "disable", "--now", LINUX_UNIT], capture_output=True)
    LINUX_UNIT_PATH.unlink(missing_ok=True)
    subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True)


def cmd_uninstall(args) -> None:
    if sys.platform == "darwin":
        _uninstall_mac()
    elif sys.platform == "win32":
        _uninstall_windows()
    else:
        _uninstall_linux()
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
    sub.add_parser("email-setup", help="store Gmail app password in the OS credential store").set_defaults(func=cmd_email_setup)
    sub.add_parser("set-token", help="store a Claude long-lived token (claude setup-token)").set_defaults(func=cmd_set_token)
    sub.add_parser("install", help="run dashboard + scheduler in the background at login").set_defaults(func=cmd_install)
    sub.add_parser("uninstall", help="remove the background service").set_defaults(func=cmd_uninstall)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    sys.exit(main())
