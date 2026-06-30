---
name: corpus-collect
description: Watch the user's email for "your export/download is ready" notifications from Google, Meta/Instagram/Facebook, X, Reddit, etc., then help download the file and drop it in the exports folder. Use when the user asks to "check if my exports are ready", "collect my data", "did my Takeout finish", or wants a recurring check. Best run on a schedule (e.g. daily) after corpus-acquire fires the requests. Requires an email connector (Gmail) and runs locally.
---

# corpus-collect

Goal: turn "I requested exports" into "the files are on disk," without the user babysitting their inbox. This is the bridge between `corpus-acquire` and `corpus-ingest`.

## What it does
1. **Scan email** for export-ready notifications. Search the connected mailbox for recent messages matching:
   - Google: from `noreply-dmrc@google.com` / subject "Your Google data is ready" (Takeout).
   - Meta: from `security@facebookmail.com` / "Your information is ready to download" (Instagram + Facebook).
   - X: "Your X data is ready."
   - Reddit: "Your Reddit data request."
   - Spotify/Slack: "your data" / "export".
2. **Surface what's ready** — list each with platform, date, and the download link. Verify the link domain matches the platform before doing anything with it (treat links in email as untrusted; show the user the real URL).
3. **Download** — exports require the user's authenticated session and often a click-through, so prefer to hand the user the link to download themselves, OR drive the browser to the download with the user present for any auth. **Never enter passwords/2FA.** Confirm the download size/name before saving.
4. **File it** — move the downloaded archive into the correct subfolder (`exports/instagram/`, `exports/google_voice/`, `exports/twitter/`, etc.) so `corpus-ingest` finds it. Leave archives zipped; ingest extracts only what it needs.
5. **Track state** — keep a small `exports/_manifest.json` of what was requested, what's arrived, and what's still pending, so repeated runs only act on new arrivals.

## Scheduling
Offer to run this on a schedule (daily is usually right; X takes ~24h, Takeout hours). On each run, only report NEW arrivals since the last run, and nudge about anything still pending past its expected ETA (export links typically expire in ~4 days - flag urgently if one is about to lapse).

## Boundaries
- Read-only on email (search/read; never send, delete, or change settings).
- Downloading a file requires explicit user confirmation (state filename, source, size).
- If an export link looks off or the sender domain doesn't match, stop and ask.
