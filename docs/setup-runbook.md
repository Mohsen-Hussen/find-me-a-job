# Runbook: set up Job Radar for a new person

This runbook is for Claude Code, working for someone who wants their own copy of Job Radar. Follow the steps in order.

Job Radar searches LinkedIn (logged out) and Himalayas for jobs and has Claude read every listing through `claude -p`. It then applies hard rules in code (eligibility, time zone, pay, engagement, industry), scores the matches against a CV, and shows them on a local dashboard. The dashboard runs a search every 30 minutes and can send email alerts.

It was built for Yahia Ragae: an Android engineer living in Egypt who wants remote work with US companies, on a Mac. Your user is someone else, probably in a different country and possibly not on a Mac. Make the tool fit them.

## 1. Set up

- **Don't push to `YahiaRagae/find-me-a-job`.**
  1. Create a private repo under the user's own GitHub account.
  2. Rename the current remote to `upstream`.
  3. Make the user's new repo `origin`.
- Tell the user which OS you detect.
- Install anything missing: git, uv (it provides Python 3.13), and check that `claude --version` works.
- Read README.md and docs/options.md, and skim the `jobhunt/` package, before you change anything.

## 2. Interview the user before coding

Ask in small batches, with options where possible:

- where they live, their time zone, their citizenship and any work permits;
- target job titles and seniority;
- their main skills, secondary skills, and skills they're rusty in;
- remote only, or hybrid/onsite OK; companies from which countries;
- full-time, contract or part-time;
- the working hours they'll accept, and their minimum pay and its currency;
- industries or companies to avoid;
- which countries or regions to search on LinkedIn, and whether Himalayas is useful for their country;
- whether they want email alerts.

Also ask for the path to their CV PDF.

## 3. Make it generic, not just re-filled with their details

These are hard-coded for Yahia today:

- **Egypt and Cairo:**
  - the `CAIRO` zone in jobhunt/rules.py;
  - "EGYPT" in the screening prompt in jobhunt/scoring.py;
  - the `egypt_eligible` field;
  - the Himalayas country fallback in jobhunt/pipeline.py;
  - labels such as "Open to Egypt" and "Cairo time" in jobhunt/static/index.html.

  Turn these into settings (home country, IANA time zone) that the prompts, rules and dashboard all read.
- **Yahia's profile and preferences** are the defaults in jobhunt/settings.py: profile, search terms, the blocked company "Deed", excluded industries, role focus. Put neutral defaults in code, and the user's answers in data/settings.json (git-ignored).
- **Yahia's name:** in README.md and docs/options.md, and in the service label `com.yahia.jobhunt` in jobhunt/__main__.py.

## 4. Make it work on the user's OS, and keep Mac support

These parts are macOS-only:

- **File locks:** `fcntl` in jobhunt/pipeline.py and jobhunt/web.py doesn't exist on Windows.
- **Email password:** it's stored with the macOS `security` command (Keychain) in jobhunt/notify.py and jobhunt/__main__.py. Switch to the cross-platform `keyring` package.
- **Desktop notifications:** they use `osascript` in jobhunt/notify.py. Use the OS's own method, or skip them.
- **Background service:** `install` and `uninstall` write a macOS LaunchAgent. On Linux use a systemd user service; on Windows use Task Scheduler. Either way it should start at login and restart if it crashes.
- **Time zones on Windows:** add the `tzdata` package so `zoneinfo` works.

## 5. Keep the safety rules

- Keep LinkedIn logged out and polite. Don't shorten the 4–7 s pacing between requests or the back-off on HTTP 429, and don't add LinkedIn login or auto-apply.
- Scoring uses the user's own Claude Code login through `claude -p`. Check that the flags it passes (`--safe-mode`, `--strict-mcp-config`, `--json-schema`, `--output-format json` and the others) work on their version.
- Never type passwords for the user. They run `email-setup` themselves; Gmail needs an app password.
- The dashboard must stay bound to 127.0.0.1.

## 6. Test, then do a first run

- Run the tests (`uv run python -m unittest tests.test_rules tests.test_linkedin`) and add tests for what you change.
- Load the CV with `uv run python -m jobhunt cv <path>`.
- Do a small first run before the full one: a few places, with `first_run_days` set to 2, so the user can check the results. LinkedIn allows only about 10 requests a minute, so a big search takes a while.
- Start the dashboard. Install it as a background service only once the user is happy with it.

Commit to the user's repo as you go. At the end, tell them what you changed and how to run it.
