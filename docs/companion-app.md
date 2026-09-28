# AzerothGPS Uploader: companion app plan

A small, optional desktop app that sends a player's opt-in road and trip data to us, so
we can evaluate it and build the good parts into the next road network. The addon keeps
working fully without it.

## Why an app

WoW addons can't use the network. The addon already keeps opt-in data in its saved
variables (`AzerothGPSDB.feedback`: drawn roads and faster trips, no character or
realm names). The game writes that file on logout and `/reload`. An app outside the game
can read it and send it.

## Policy and ToS

- **The app only reads a file on disk.** It doesn't touch the game process: no injection,
  no memory reading, no automation, and it doesn't send input to the game. This is the
  same pattern as widely used companion apps that read SavedVariables or logs (e.g. the
  TSM desktop app, Warcraft Logs uploader, Raider.IO client).
- **The addon doesn't depend on it.** Everything works without the app. Nothing in game
  asks the player to install it beyond an info link in "Help improve".
- **It's opt-in twice.** The sharing options in game are off by default, and the app asks
  for consent on first run before sending anything.
- **It sends only feedback data:** coordinates, times, the addon version and the game
  build. It never sends character, realm or account names, chat, or anything else from
  the file.
- **It doesn't write to the addon's saved variables.** The game overwrites them on logout.
  The app keeps its own record of what it has sent.

## How it works

```
 WoW (addon)                    Uploader (tray app)                 API
 ───────────                    ───────────────────                 ───
 records opt-in roads/trips  →  watches WTF\...\AzerothGPS.lua
 writes on logout / /reload     parses as data (never executes)
                                keeps only feedback records
                                drops anything identifying
                                de-duplicates (hash per record)  →  POST /v1/submissions
                                remembers what it sent              validates, rate-limits,
                                                                    stores for review
                                                        ←           202 Accepted + receipt
```

### 1. Addon changes (small)

- **Versioned records:** add `format = 2` and a random, anonymous `install` id created
  once. Its only uses are rate limiting and "delete my data" requests; it's never linked
  to a character.
- **Enough context to evaluate a trip:** the start, the stop, the estimate, the actual
  time, mounted or not, and whether off-road or flights were used.
- **A "How to share" page** explaining the app, replacing the "Coming soon" text.

### 2. The uploader app

- **What it is:** a small tray app for Windows first (macOS later if players ask).
- **Built from:** the existing Python tooling's `savedvars/parser.py` (a tokenizer, no
  execution) and `watcher.py`, packaged with PyInstaller. Aim for well under 20 MB.
  - The alternative is a Go or Rust rewrite for a ~5 MB binary. Only worth it if size or
    antivirus false positives become a problem.
- **First run:**
  - Find the WoW Forever folder.
  - Show exactly what will be sent.
  - Ask for consent, with two choices: **send automatically**, or **review each batch**.
- **While running:** watch `WTF\Account\*\SavedVariables\AzerothGPS.lua`. After it changes
  (logout or `/reload`), read `feedback` only and hash each record. Skip already-sent
  ones, and send the new ones in one batch. If sending fails, retry with a delay.
- **Tray menu:**
  - Pending count and last upload
  - Pause
  - Review / send now
  - View what was sent
  - Request deletion
  - Quit
- **Safety:**
  - HTTPS only, to one fixed endpoint.
  - Request size capped; nothing but feedback records ever read or sent.
  - Keep the code readable, and sign releases if possible (unsigned builds trigger
    SmartScreen warnings).

### 3. The API

- **Hosting:** keep it tiny and cheap. For example, Cloudflare Workers with D1 for the
  records and R2 for raw batches (a free tier covers early use). A small FastAPI service
  on Fly.io or Render would also work.
- **Endpoint:** `POST /v1/submissions` with `{ format, install, addon, build, roads[], trips[] }`.
- **On the server:**
  - A strict schema, with limits on:
    - batch size (e.g. ≤ 1 MB)
    - points per road or trip
    - coordinate ranges
  - Unknown fields rejected.
  - Rate limits per install id and per IP.
  - Everything stored as data and never executed.
- **Privacy:**
  - No accounts.
  - IPs used for rate limiting only, not stored with the data.
  - A published retention period.
  - `DELETE /v1/installs/{id}` for deletion requests.
  - A privacy notice on the CurseForge page and in the app.
- **For us:** an authenticated `GET /v1/submissions?since=…` so the review tool can pull
  new data.

### 4. Review before anything ships

`agps review` (developer tool) pulls submissions and, for each one:

1. **Checks** it: inside continent bounds, plausible speeds (no teleports), point spacing,
   and mostly over walkable ground (the terrain data).
2. **Groups** the same shortcut from different installs. Two or more independent ones are
   much stronger evidence.
3. **Compares** the route with and without it, using the addon's own routing (the Lua
   under lupa, as the tests do), and reports the time saved.
4. **Renders** a preview image: the submission over the map, our route and the road
   network.
5. **On approval,** writes the road into `overrides/`. `agps roads` / `gen-addon-data`
   bring it into the next release.

Players only ever get new road data through normal addon releases, never directly from
other players.

## Phases

1. **Addon format 2:** install id, trip context and the "How to share" text. Local tests.
2. **API:** schema, validation, rate limits, storage, deletion; deployed on a test
   domain.
3. **Uploader app:**
   - Consent, watcher, de-duplication, batching and the tray menu.
   - Packaged exe, released on GitHub.
4. **Review tool:** pull, validate, group, compare and preview; the path into
   `overrides/`.
5. **Launch:**
   - Privacy notice.
   - A CurseForge description section.
   - A link from the addon's "How to share" page.

A manual fallback stays: the "Export for submission" string pasted into a GitHub issue,
for players who don't want an app.

## Decisions needed

- **Hosting:** Cloudflare Workers + D1 (cheap, simple), or a small Python service (same
  language as our tools)?
- **App code:** open-source the uploader (builds trust, and it's only a file reader and
  uploader) while the addon stays All Rights Reserved? Or keep it private?
- **Default upload mode after consent:** automatic, or review each batch?
- **Domain name** for the API and privacy notice.
