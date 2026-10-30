"""Alerts: email (Gmail SMTP, app password kept in the OS credential store) + desktop notification.

The password is stored with `keyring`, which maps to the Windows Credential
Manager, the macOS Keychain, or the Secret Service on Linux.
"""

from __future__ import annotations

import html
import smtplib
import subprocess
import sys
from email.message import EmailMessage

import keyring

KEYCHAIN_SERVICE = "jobhunt-smtp"


def keychain_password(account: str) -> str | None:
    if not account:
        return None
    try:
        return keyring.get_password(KEYCHAIN_SERVICE, account)
    except Exception:
        return None


def store_password(account: str, password: str) -> None:
    keyring.set_password(KEYCHAIN_SERVICE, account, password)


def email_ready(settings: dict) -> bool:
    e = settings["email"]
    return bool(e.get("to") and e.get("smtp_user") and keychain_password(e["smtp_user"]))


def _job_html(job: dict) -> str:
    a, s, ev = job["assess"], job["screen"], job["eval"]
    esc = html.escape
    chips = [f"Egypt: {s['egypt_eligible']}", f"{s['engagement']}", f"focus: {s['role_focus']}"]
    if s.get("pay_text"):
        chips.append(s["pay_text"])
    if ev.get("tz"):
        chips.append(ev["tz"][1])
    gaps = "".join(f"<li>{esc(g)}</li>" for g in a.get("gaps", [])[:3])
    return f"""
<div style="border:1px solid #ddd;border-radius:8px;padding:12px 14px;margin:0 0 12px">
  <div style="font-size:13px;color:#555">{esc(job['company'])} · {esc(job.get('detail_location') or job['location'])}</div>
  <div style="font-size:16px;font-weight:600;margin:2px 0">
    <span style="background:#0a7d4f;color:#fff;border-radius:4px;padding:1px 6px;margin-right:6px">{a['fit_score']}</span>
    <a href="{esc(job['url'])}">{esc(job['title'])}</a></div>
  <div style="font-size:13px;margin:4px 0"><b>{esc(a['headline'])}</b></div>
  <div style="font-size:12px;color:#444">{esc(' · '.join(chips))}</div>
  <div style="font-size:13px;margin-top:6px">{esc(a['summary'])}</div>
  {f'<div style="font-size:12px;margin-top:4px">Gaps:<ul style="margin:2px 0">{gaps}</ul></div>' if gaps else ''}
  <div style="font-size:12px;color:#333;margin-top:4px">Tip: {esc(a.get('apply_tip', ''))}</div>
</div>"""


def send_digest(settings: dict, jobs: list[dict], dashboard_url: str) -> None:
    e = settings["email"]
    password = keychain_password(e["smtp_user"])
    if not password:
        raise RuntimeError("No SMTP app password in the Keychain. Run: uv run python -m jobhunt email-setup")
    msg = EmailMessage()
    top = jobs[0]
    msg["Subject"] = f"{len(jobs)} new job match{'es' if len(jobs) != 1 else ''}: {top['title']} at {top['company']} ({top['assess']['fit_score']})"
    msg["From"] = e["smtp_user"]
    msg["To"] = e["to"]
    text = "\n\n".join(
        f"[{j['assess']['fit_score']}] {j['title']} — {j['company']}\n{j['assess']['headline']}\n{j['url']}" for j in jobs
    )
    msg.set_content(text + f"\n\nDashboard: {dashboard_url}")
    body = "".join(_job_html(j) for j in jobs)
    msg.add_alternative(
        f"""<div style="font-family:-apple-system,Segoe UI,sans-serif;max-width:680px">
<p style="font-size:14px">New jobs that pass your filters, best first. <a href="{dashboard_url}">Open dashboard</a></p>
{body}</div>""",
        subtype="html",
    )
    with smtplib.SMTP_SSL(e["smtp_host"], int(e["smtp_port"]), timeout=30) as smtp:
        smtp.login(e["smtp_user"], password)
        smtp.send_message(msg)


def send_test(settings: dict, dashboard_url: str) -> None:
    e = settings["email"]
    password = keychain_password(e.get("smtp_user", ""))
    if not (e.get("to") and e.get("smtp_user") and password):
        raise RuntimeError("Email isn't set up yet. Run: uv run python -m jobhunt email-setup")
    msg = EmailMessage()
    msg["Subject"] = "Job Radar test email"
    msg["From"] = e["smtp_user"]
    msg["To"] = e["to"]
    msg.set_content(f"Email alerts work. New matches will arrive here.\n\nDashboard: {dashboard_url}")
    with smtplib.SMTP_SSL(e["smtp_host"], int(e["smtp_port"]), timeout=30) as smtp:
        smtp.login(e["smtp_user"], password)
        smtp.send_message(msg)


def desktop_notification(title: str, message: str) -> None:
    """Best-effort OS notification. Never raises if the platform tool is missing."""
    try:
        if sys.platform == "darwin":
            script = f"display notification {_as(message)} with title {_as(title)} sound name \"Glass\""
            subprocess.run(["osascript", "-e", script], capture_output=True)
        elif sys.platform == "win32":
            try:
                from winotify import Notification

                Notification(app_id="Job Radar", title=title, msg=message).show()
            except Exception:
                pass
        else:
            subprocess.run(["notify-send", title, message], capture_output=True)
    except Exception:
        pass


# Backwards-compatible alias (older code / docs call this "mac_notification").
mac_notification = desktop_notification


def _as(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
