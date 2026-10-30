# Job Radar

Searches LinkedIn and Himalayas for your target roles, has Claude read every listing, and shows the ones you can actually take from Egypt: remote, open to your country, workable hours, acceptable pay and engagement type, scored against your CV. New strong matches arrive by email or Mac notification.

## Use it

```sh
uv run python -m jobhunt serve     # dashboard + 30-minute schedule on http://localhost:8765
uv run python -m jobhunt run       # one search now, in the terminal
uv run python -m jobhunt install   # keep the dashboard + schedule running in the background, from login
uv run python -m jobhunt uninstall
uv run python -m jobhunt cv ~/Downloads/new-cv.pdf
uv run python -m jobhunt email-setup   # Gmail app password → OS credential store
```

Everything else (titles, places, hours, pay, engagement, schedule, models) is in the dashboard's **Settings** tab.

Runs on macOS, Windows and Linux (`install`/`uninstall` use a LaunchAgent, a Task Scheduler logon task, or a systemd user service respectively). On Windows, open a fresh terminal after installing `uv` so it's on your PATH.

**Setting it up for yourself?** It's currently configured for one person (a frontend / full-stack engineer in Egypt). Ask Claude Code to follow [docs/setup-runbook.md](docs/setup-runbook.md): it interviews you, makes the code fit you, and gets it running on your OS.

## How a run works

1. **Search.** LinkedIn's logged-out job search covers every title × place. It searches back to the last run plus an hour of overlap; the first run searches back 7 days. Himalayas' free API returns remote jobs open to Egypt. No LinkedIn login is used, so your account is never involved.
2. **Skip by title.** Titles that don't match your roles are skipped before any request or Claude call. So are titles in your exclude list.
3. **Read** (Claude Haiku, low effort). Claude reads every remaining listing and extracts facts:
   - whether someone in Egypt can take it (`yes / likely / unclear / unlikely / no`), quoting its evidence;
   - remote, hybrid or onsite;
   - required hours and time zone;
   - full-time, part-time or contract;
   - pay;
   - role focus (frontend, full-stack, backend, mobile…);
   - seniority.
4. **Rules** (plain code, `jobhunt/rules.py`). Your settings are compared with those facts:
   - Required hours are converted to Cairo time and checked against your working window.
   - Changing a rule takes effect immediately, with no re-reading.
5. **Score** (Claude Sonnet, medium effort). Only jobs that pass the rules are scored 0–100 against your CV. Each score comes with matched skills, gaps, red flags, interview risk and an application tip.
6. **Alert.** Matches at or above your email threshold that you haven't been sent yet go out by email, or as a desktop notification until email is set up.

Claude runs through `claude -p` on your Claude subscription, so there's no API key and no extra cost.

## Files

- `data/` (git-ignored) holds `jobs.db`, `settings.json`, `cv.txt`/`cv.pdf` and the logs.
- `jobhunt/linkedin.py`: LinkedIn guest endpoints, paced at 4–7 s per request with back-off on HTTP 429.
- `jobhunt/himalayas.py`: Himalayas API. Their terms ask you to credit Himalayas and link back to each listing.
- `jobhunt/scoring.py`: Claude prompts and JSON schemas.
- `jobhunt/rules.py`: eligibility, time zone, pay and engagement rules.
- `jobhunt/web.py` and `jobhunt/static/index.html`: the dashboard. It only listens on 127.0.0.1.

## Caveats

- LinkedIn's terms forbid automated access, even logged out. Keep volume personal-scale; LinkedIn answers too many requests with HTTP 429 for a while. Don't turn this into a service for other people: that also isn't allowed on a personal Claude subscription and would need API keys.
- LinkedIn ignores its remote, experience and job-type filters for logged-out searches, so Claude decides those from each listing's text.
- Eligibility tags, even Himalayas' own, are sometimes wrong. Check the "Who can apply" quote before you apply.
