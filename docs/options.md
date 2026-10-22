# Options for finding remote mobile jobs from Egypt (researched 2026-10-18)

The goal: senior Android / mobile lead roles at US-based companies, worked remotely from Egypt. The search must check four things for each listing:

- Can someone in Egypt take it?
- Do its hours fit Cairo time?
- Is the role Android-first?
- Does the pay meet the minimum?

## Bottom line

- **No existing product does the whole job.**
  - The tools that cover LinkedIn ignore whether you can work from Egypt: LinkedIn itself, LoopCV, the auto-appliers.
  - The tools that understand eligibility don't cover LinkedIn: Himalayas, Jobgether, Wellfound, the Arc.dev board.
  - None turns "must work PST hours" into Cairo hours.
- **Even structured eligibility tags are often wrong.**
  - Himalayas tagged a US-only role as worldwide.
  - We Work Remotely's RSS says "Anywhere" on US-only jobs.
  - So each listing still needs reading.
- **The plan:** use a few existing tools as extra channels, and run the custom tool in this repo (Job Radar) to cover LinkedIn plus feeds and score everything against the CV.

## Use these alongside Job Radar

1. **Himalayas** (free). Set the country to Egypt and the timezone to UTC+2/+3. Paid alerts are $9/mo.
   - Its free API is already one of Job Radar's sources.
2. **Jobgether** (free tier). Has the best "remote from Africa / Egypt" labels and matches against your CV.
   - It has no API, so use the website directly.
3. **Wellfound and HN "Who is hiring"** (monthly). US startups state there that they hire remotely from anywhere, and what hours they need.
4. **Talent marketplaces** run in parallel:
   - **Toptal:** best rate and title fit. Confirm Egypt with them first.
   - **Andela:** officially accepts Egypt.
   - **Arc.dev:** free profile.
   - **Lemon.io:** pays a senior Android median of about $50–71/hr. Ask them whether Egypt is OK.
5. **LinkedIn itself**:
   - Set "Open to: remote EMEA".
   - Use Job Match to triage by hand.
   - **Don't use auto-apply or LinkedIn-login automation tools.** LinkedIn sues scrapers and bans accounts.

## AI matchers and auto-appliers

| Product | LinkedIn? | CV scoring | Egypt / timezone | Price | Verdict |
|---|---|---|---|---|---|
| Jobright.ai | Aggregates US jobs | Yes | US-only | ~$40/mo | Not useful from Egypt |
| LoopCV | **Yes** (LinkedIn, Indeed, Glassdoor…) | Yes | Keyword rules only | from €9.99/mo | Has a REST API and webhooks; turn auto-apply off |
| Jobgether | No | % match | **Per-job Egypt/Africa labels** | Free / ~$29/mo | Strong |
| Simplify, Teal, Huntr, Careerflow | No | Keyword match | No | $24–40/mo | CV tailoring only |
| JobCopilot, Wobo, AIApply, LazyApply | Partly | Yes | No | $29–99+ | Avoid: they spray applications at US-only roles, and LinkedIn bans have been reported |
| LinkedIn Premium | Yes | Profile match | No eligibility check | $39.99/mo | Optional |
| [career-ops](https://github.com/career-ops-hq/career-ops) (open source, 75k★) | No | 1–5 score in Claude Code | Has a work-authorization blocker signal | Free | Good for tailoring CVs and cover letters; no LinkedIn search and no email |

## Remote boards that tag eligibility

| Board | Egypt filter | Timezone | Feed |
|---|---|---|---|
| **Himalayas** | `country=Egypt` | UTC-offset list per job | Free JSON API (credit and link back) |
| Jobgether | Best labels | No | None |
| Wellfound | "Hires remotely from" | Stated overlap | None |
| Arc.dev | `requiredCountries` | `overlapHours` | Page JSON. No Android jobs open to Egypt on the day checked |
| Remote Rocketship | Country pages (3–4 mobile jobs open to Egypt) | No | Paid API ($29/mo) |
| Jobicy, 4dayweek, WWR, Remote First Jobs | Regions only | Rarely | Free APIs / RSS |
| RemoteOK, Remotive | Weak | No | Too small or noisy to be worth it |

## LinkedIn: what's possible

- **"Sign in with LinkedIn" only gives your name and email.** There's no job-search API for individuals, so a "LinkedIn login" feature can't search jobs.
- **Searching LinkedIn without logging in works** and never touches your account. Its terms still forbid automation, even logged out.
  - For personal, low-volume use the practical effect is temporary slow-downs (HTTP 429).
  - It's not OK to run it as a service for other people.
- **Most search filters are ignored when logged out** (since Sep 2026): remote, experience level, job type and sort order. The time window and US salary filters still work. That's why Claude decides "remote" and "who can apply" from the listing text.
- **The fully allowed route:** LinkedIn's own job-alert emails (up to 20 alerts, daily). A future Job Radar source could read them from Gmail.

## Where to run it

| Option | Every 30 min? | Cost | LinkedIn reliability |
|---|---|---|---|
| **Your Mac, background service** (chosen) | Yes, while the Mac is awake | Free on your Claude subscription | Best (home IP) |
| GitHub Actions + Anthropic API key | Yes (cron can be delayed) | Free tier gets used up; plus API costs of a few $/mo | Datacenter IP, so blocked more often |
| Claude Code cloud routines | At most hourly | Uses your subscription | Datacenter IP; network allowlist needed |
| Small VPS (~€6/mo) + API key | Yes | ~€6/mo + API | Datacenter IP |

Turning Job Radar into a white-label site for other people would need an Anthropic API key, not your subscription. That costs about $3/mo per 150 jobs/day with Haiku 5.5, or about $15/mo if Sonnet re-scores the top 20%.

## Head-to-head test (2026-10-18)

Every source's mobile jobs from the past week were put through Job Radar's own checks: Egypt eligibility, hours, pay, industry, main stack and CV fit.

| Source | Good jobs for Yahia this week | Notes |
|---|---|---|
| **Job Radar: LinkedIn** | Rounds Android Developer (80), ServiceTitan Principal Mobile (62), Fuse Energy (62), Henkel, Property Finder | None of the other sources showed these. 128 listings read; most are US-only or on-site |
| **Job Radar: Himalayas** | Deed (82, blocked as a likely scam), Tether (crypto) | Its "worldwide" tags need checking |
| **Hacker News "Who is hiring"** | **Flexibits Android (80)**: remote, welcomes anyone worldwide | Missed by Job Radar. Free Algolia API, new thread monthly |
| **Remote Rocketship** | **Lumiform Android (74)**: worldwide remote | Missed. The full list needs an account; the API is $29/mo |
| **Wellfound** | **Fingerprint Senior Android, EMEA, $178–205k (74)** | Missed. The listing is 5 months old. Other "Everywhere" jobs pay $14–70k |
| **Jobgether** | Speechify Android Team Lead (76) | Missed, but pays up to $110k (below $120k). Labels are unreliable ("Anywhere" on a job based in Spain; the same job listed under two companies) |
| Arc.dev | None | Worldwide mobile jobs are freelance and 1–3 months old; this week's are locked to one country |
| Jobicy, RemoteOK, Remotive, Working Nomads, Remote First Jobs, 4dayweek | None new | Mobile jobs were US/Canada-only, on-site, or already in Job Radar |
| We Work Remotely | None | Its Mobile category was removed; "Anywhere" posts can carry a list of countries that excludes Egypt |
| Jobright.ai | None | US jobs only |
| DailyRemote | Unknown | Unreachable (blocked) |

**What this shows**

- Job Radar's checks are the part no service offers. Every board's eligibility labels were wrong at least once.
- LinkedIn alone misses good jobs that are posted only on Hacker News, company career pages, Wellfound or Jobgether.
- The best setup is Job Radar's checks with more sources feeding in:
  - Hacker News (free);
  - a "score this job link" box for jobs found on any site;
  - optionally the Remote Rocketship API.
