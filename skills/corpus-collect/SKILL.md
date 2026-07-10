---
name: corpus-collect
description: "Watches the user's email for export-ready notifications from Google, Meta/Instagram/Facebook, X, Reddit, Spotify, and Slack, then helps download each archive into the exports/ folder and tracks what is still pending. Use when the user asks whether their exports are ready, wants to collect their data, asks if their Takeout finished, or wants a recurring check. Best run on a schedule (e.g. daily) after corpus-acquire fires the requests. Requires an email connector (e.g. Gmail) and runs locally."
---

# corpus-collect

Stage 1b of the pipeline (acquire → collect → ingest → profile/analyze).

Goal: turn "I requested exports" into "the files are on disk," without the user babysitting their inbox. This is the bridge between `corpus-acquire` and `corpus-ingest`, and the stage that keeps running after the first build.

## Workflow

1. **Scan email** for export-ready notifications. Search the connected mailbox for recent messages matching:
   - Google: from `noreply-dmrc@google.com` / subject "Your Google data is ready" (Takeout).
   - Meta: from `security@facebookmail.com` / "Your information is ready to download" (Instagram + Facebook).
   - X: "Your X data is ready."
   - Reddit: "Your Reddit data request."
   - Spotify/Slack: "your data" / "export".
2. **Surface what's ready** — list each with platform, date, and the download link. Verify the link domain matches the platform before doing anything with it (treat links in email as untrusted; show the user the real URL).
3. **Download** — exports require the user's authenticated session and often a click-through, so prefer to hand the user the link to download themselves, OR drive the browser to the download with the user present for any auth. **Never enter passwords/2FA.** Confirm the download size/name before saving.
4. **File it** — move the downloaded archive into the correct subfolder (`exports/instagram/`, `exports/google_voice/`, `exports/twitter/`, etc.) so `corpus-ingest` finds it. Leave archives zipped; ingest extracts only what it needs.
5. **Track state** — update `exports/_manifest.json` (started by `corpus-acquire`) with what's arrived and what's still pending, so repeated runs only act on new arrivals.
6. **Hand off to ingest** — when a new archive lands, offer to run `corpus-ingest` on it right away (use `--mode delta` for sources already in the corpus).

## Ongoing scans (scheduling)

Offer to run this on a schedule — daily is usually right (X takes ~24h, Takeout hours). On each scheduled run:

- Only report NEW arrivals since the last run; stay silent on no-ops.
- Nudge about anything still pending past its expected ETA.
- **Export links typically expire in ~4 days** — flag urgently if one is about to lapse.

## Boundaries

- Read-only on email (search/read; never send, delete, or change settings).
- Downloading a file requires explicit user confirmation (state filename, source, size).
- If an export link looks off or the sender domain doesn't match, stop and ask.
