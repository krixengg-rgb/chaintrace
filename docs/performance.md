# First-load performance on the Render free plan (v34)

## What changed
- **One app bundle instead of 25 script files (not minified, see below).** At start-up `assets.py` joins the app's own scripts (in page order) into
  `/static/b/app.<hash>.js`, and serves it brotli or gzip compressed. (Minifying with `rjsmin` is off: it mangled spaces inside JavaScript template literals; it only saved ~4% before compression.) Cytoscape is served as `/static/b/cytoscape.<hash>.js`.
  `render.yaml` runs `python3 assets.py` in the build step, so the best compression (brotli 11 / gzip 9) is done once at deploy
  time and a cold start only reads the files (`static/b/`, gitignored).
- **Cache headers.** Hashed bundles: `Cache-Control: public, max-age=31536000, immutable` (a new deploy changes the hash).
  `index.html` and every un-hashed `/static` file: `no-cache` + ETag, so a deploy is never served stale and an unchanged file costs a 304.
- **Render-blocking script moved.** Cytoscape used to load in `<head>`; it now loads just before the app script, so the page paints first.
- **Splash.** `index.html` shows a lightweight inline "waking up" screen while the scripts download and parses, polling `/healthz`
  to say when the server is still loading labels / the exchange-deposit store. It disappears on `load`.
- **`/healthz`.** No auth, no database query: `{ok, labels_db, warm, up_s}` with `Cache-Control: no-store`.
- **Deferred warm-up.** The label / deposit-store / price warm-up now starts 3 s after boot (`CHAINTRACE_WARM_DELAY`), so on a 0.1-CPU
  instance the first page and bundle are served before it; a lookup that arrives earlier starts it immediately.
- **`docs/wake.html`.** A static page (host it on GitHub Pages or open it locally) that polls `/healthz` and opens the app once the
  Render instance has woken. While the instance itself is starting (about a minute, per Render), Render shows its own loading page; our splash can only appear once the instance answers.
- `CHAINTRACE_BUNDLE=0` serves the original un-bundled files (debugging).

## Optional keep-warm
`.github/workflows/keep-warm.yml` pings `/healthz` every 14 minutes between 07:00 and 22:59 UK time. It does nothing until you set
the repository variable `KEEPWARM_URL` (Settings → Secrets and variables → Actions → Variables), e.g. `https://chaintrace-d4fv.onrender.com`.

**Render free-plan limit:** free web services in a workspace share **750 instance hours per calendar month**; when they run out,
free services are suspended until the next month. Keep-warm during UK daytime uses about 16 h × 31 = **~496 h/month** for this
service. Do not run it alongside another 24/7 pinger (the `watch-alerts` workflow, if enabled, wakes the service every 20 minutes
around the clock, about 744 h/month on its own). GitHub also disables scheduled workflows in repositories with no activity for 60 days.

Source for the limits (checked 24 Nov 2026): https://render.com/docs/free (spin-down after 15 minutes without inbound traffic, ~1 minute spin-up, 750 free instance hours per workspace per month, 0.1 CPU / 512 MB).

## Measurements
See the v34 report for the before/after numbers (local server with and without throttling, and the live Render service warm and cold).
