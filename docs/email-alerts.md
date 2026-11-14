# Server-side email alerts (no browser needed)

Watched addresses are checked every ~20 minutes by a GitHub Actions cron that wakes the Render service and calls
`POST /api/alerts/run` with a bearer token. New activity is emailed as one digest (amount + asset, counterparty + label,
sanctions / risk flags, UK time + UTC, links back to ChainTrace). Suggested labels and heuristics in alerts are leads, not evidence.

## Where things live
| What | Where | Public? |
|---|---|---|
| Watchlist (case data) | Render env var `ALERTS_WATCHLIST` (sealed `enc:…` value) | no |
| Email API key / SMTP password | Render env vars | no |
| Scheduler token | Render env var `ALERTS_TOKEN` **and** GitHub Actions secret `ALERTS_TOKEN` (same value) | no |
| Cursors, mutes, sent ids | Render disk + encrypted blob in the GitHub Actions cache (Fernet, key from `ALERTS_KEY`) | encrypted |
| Actions logs | counts only | yes (public repo) |

## Setup
1. Generate two random values (run locally; do not paste them anywhere public):
   `python3 -c "import secrets;print(secrets.token_urlsafe(32))"` (twice).
2. Render › chaintrace › Environment, add:
   - `ALERTS_TOKEN` = first value
   - `ALERTS_KEY` = second value (changing it later makes stored state unreadable → silent re-baseline)
   - `ALERT_EMAIL_TO` = your address (comma-separated for several)
   - `RESEND_API_KEY` = your Resend API key. Default sender `onboarding@resend.dev` only delivers to your Resend account's own email;
     after verifying a domain in Resend, also set `ALERT_EMAIL_FROM` (e.g. `ChainTrace <alerts@yourdomain>`).
   - Or SMTP instead: `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS` (+ `ALERT_EMAIL_FROM`). Render free instances block ports 25/465/587, so use a provider on port 2525.
   - Save (Render redeploys).
3. Open the site › 👁 Watch › ✉ Email › **Create sealed value**, copy it, add Render env var `ALERTS_WATCHLIST` = that value, save.
   Repeat whenever the watchlist changes.
4. GitHub › repo › Settings › Secrets and variables › Actions › New repository secret `ALERTS_TOKEN` = same value as on Render.
   (Optional variable `CHAINTRACE_URL` if the site URL changes.)
5. GitHub › Actions › watch-alerts › Run workflow (first run baselines silently). Then ✉ Email › **Send test email**.

Optional: `ALERTS_MIN_SEVERITY` (low|medium|high, default low), `ALERTS_BUDGET` (seconds per round, default 45),
`CHAINTRACE_PUBLIC_URL` (link base), `ALERTS_SENDER` (force resend|smtp|mock).
Per-address mute: ✉ Email panel toggle (saved on the server and in the encrypted state from the next run), or `"muted": true` on the item.
