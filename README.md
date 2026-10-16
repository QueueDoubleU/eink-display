# Xteink dashboard

Shows today's Google Tasks and the weather on an Xteink X3. Free: GitHub builds the
screen every 15 minutes and hosts it; the device wakes around 4:00 and 12:00, grabs
the latest screen, and sleeps again.

It speaks the TRMNL device protocol, so it works with:
- **TRMNL firmware** (dashboard only, wakes on schedule), or
- **cross-trmnl** (CrossPoint reader + dashboard, refreshes when the device sleeps).

## 1. Google Tasks access (one time, ~10 min)

1. Sign in to <https://console.cloud.google.com> with the shared books Gmail and create a project.
2. **APIs & Services → Library →** enable **Google Tasks API**.
3. **OAuth consent screen:** External, fill in the app name and your email. Then click
   **Publish app** (set it to "In production"). In Testing mode Google expires the
   token every 7 days. You'll see an "unverified app" warning when you sign in; that's
   expected for a personal app. Click Advanced → continue.
4. **Credentials → Create credentials → OAuth client ID → Desktop app.** Download the JSON.
5. On your Mac, in this folder:
   ```
   python3 -m venv .venv && .venv/bin/pip install google-auth-oauthlib
   .venv/bin/python dashboard/get_token.py ~/Downloads/client_secret_XXXX.json
   ```
   Sign in with the books Gmail. It prints three values.

## 2. GitHub repo

1. Create a **public** repository (free GitHub Pages needs public) and upload these files,
   keeping the `.github/workflows` folder.
2. **Settings → Secrets and variables → Actions → Secrets**, add:
   - `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REFRESH_TOKEN` (from step 1)
   - `SITE_SECRET`: a long random string, e.g. the output of `openssl rand -hex 12`.
     The screen is published at a public URL; this keeps the address unguessable.
3. Optional **Variables** (same page, Variables tab):
   - `TASKLIST_NAME`: which Google Tasks list to show (default: the first one, "My Tasks")
   - `SHOW_UNDATED`: `1` to also show tasks with no due date
   - `LAT` / `LON`: weather location (default Cambridge, MA)
   - `WIDTH` / `HEIGHT`: `800` / `480` for an X4 (default is the X3's 792 × 528)
4. **Settings → Pages → Source: GitHub Actions.**
5. **Actions tab → Build Xteink dashboard → Run workflow.** When it's green, check
   `https://<your-username>.github.io/<repo>/<SITE_SECRET>/preview.png`.

Your server URL is `https://<your-username>.github.io/<repo>/<SITE_SECRET>`.

## 3. The device

**TRMNL firmware (dashboard only):** flash it from <https://trmnl.com/flash> (choose the
X3). During Wi-Fi setup, choose a custom/self-hosted server and enter the server URL above.

**cross-trmnl (keep the reader):** build and flash per its README, then set its TRMNL
server URL to the server URL above and choose a Dashboard sleep screen.

## Notes

- Tasks shown: incomplete tasks due today or earlier (late ones are marked). Recurring
  tasks show up on the days they're due.
- Wake times are approximate (usually within ~10 minutes); GitHub's scheduler can run late.
- Change wake times with a `SLOTS` variable, e.g. `05:00,13:00`. Or set
  `INTERVAL_HOURS` (e.g. `8`) to wake every N hours instead; it overrides `SLOTS`.
- Changes take effect at the device's next wake (it learns its next sleep length each time).

## Adding tasks with Muse

In Muse: Settings → Connectors → connect **Google Tasks** with the shared books Gmail.
Then just tell Muse "add *water the plants* to my tasks, due today" or "every Monday".
Anything due today or earlier shows up at the next refresh. If you use a list other
than the default, tell Muse which list, and set `TASKLIST_NAME` to match.
