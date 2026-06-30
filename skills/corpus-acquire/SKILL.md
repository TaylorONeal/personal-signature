---
name: corpus-acquire
description: Request your personal-data exports from the platforms you use (Google Takeout, Instagram, Facebook, X/Twitter, Reddit, Slack, Spotify, and local sources like iMessage and browser bookmarks). Use when the user wants to "pull my data", "request my exports", "get my Instagram/Gmail/etc data", or start building a personal corpus. Drives the request UIs in the browser where possible and hands off password/2FA steps to the user. Covers the exact settings that keep exports small and parseable, and the traps that silently bloat them.
---

# corpus-acquire

Goal: get the user's data OUT of each platform and onto disk, configured so it's small and parseable. You don't need every source. Pick what the user has; partial is fine (the rest of the pipeline adapts).

## Before you start
- Confirm an `exports/` folder exists for drop-off, and an `identity.json` (copy from `identity.example.json`). The user fills in their handles so parsers know what's "theirs."
- **Never enter the user's password, 2FA code, or payment info.** Drive the UI up to the auth/confirm step, then hand off: "Enter your password and click Continue." This is a hard rule.
- Exports generate asynchronously (minutes to ~24h). Fire them all, then let `corpus-collect` pull them in as they're ready.

## Per-source playbook (do the ones the user has)

### Google Takeout (Gmail Sent, Google Chat, Google Voice, YouTube)
URL: `takeout.google.com/settings/takeout`. One export can bundle multiple products, but **keep products separate** so one giant product doesn't delay the rest.
- **Gmail Sent:** Mail product only -> open the labels/"All Mail data included" control -> the dialog defaults to **"Include all messages in Mail" ON**, which exports the ENTIRE mailbox. Turn that OFF, then tick **only "Sent"**. Verify the chip reads one label. (This picker is finicky under automation; if the OK won't commit, have the user tick "Sent" themselves.)
- **Google Chat:** select Google Chat. Yields `Groups/*/messages.json` (DMs + Spaces).
- **Google Voice:** select Voice. Yields `Calls/*.html` (Text + Voicemail records).
- **YouTube:** select YouTube and YouTube Music -> in its options keep comments, playlists, subscriptions, history; drop video files.
- Delivery: "Send download link via email", Export once, .zip, 50GB. Then **Create export**.

### Instagram DMs
`accountscenter.instagram.com` -> Your information and permissions -> Export your information -> Create export -> profile -> Export to device.
- **Customize information has ~7 separate sections (Activity, Personal info, Security, Apps, Preferences, Ads, Connections), EACH with its own "Clear all".** The top "Clear all" only clears the first section, so "Messages only" silently balloons to ~13 categories. Clear EVERY section, then check only **Messages**. Verify the review screen reads exactly "Messages".
- Format **JSON**, Date range **All time**, Media quality **Lower**. Then Start export (hands off to password).

### Facebook Messenger
`facebook.com` -> Settings -> Download your information. Same multi-section trap as Instagram: clear all sections, select **Messages** only, **JSON**, **All time**, low media.

### X / Twitter
`x.com` -> Settings -> Your account -> Download an archive of your data. **Takes ~24h.** One archive per account if the user had multiple handles. Drop the whole zip in `exports/twitter/`.

### Reddit
`reddit.com/settings/data-request` -> GDPR export. Returns CSVs (posts, comments, saved). Drop zip in `exports/reddit/`.

### Slack
Workspace export (admin) or per-DM. Drop the export folder/zip in `exports/slack/`.

### Spotify
Fastest: `exportify` (open-source, OAuth, instant CSV of liked songs + playlists). Or Spotify's official "Download your data" (slower). Drop CSV in `exports/`.

### Local (no request needed - just copy)
- **iMessage:** `~/Library/Messages/chat.db` -> copy into `exports/`. (Read in place; do not try to open it on a network/FUSE mount.)
- **Browser bookmarks:** export HTML from the browser -> `exports/`.

## Output
Tell the user which exports were fired, their rough ETAs, and that `corpus-collect` will watch for the "ready" emails. Record what was requested so collect knows what to expect.
