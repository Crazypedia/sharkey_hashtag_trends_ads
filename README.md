# fedibuzz_to_sharkey

Tools to surface **bubble-wide trending tags** and turn them into **Sharkey/Misskey advertisements** that link to your local tag pages.

## What it does

- **Discover trending hashtags** across the servers you trust (your “bubble”).  
- For each chosen tag, **pick a representative safe image** (consensus across servers first, otherwise the most‑engaged post).
- **Deduplicate** downloads by SHA‑256 to save Drive space.
- **Upload** the image to your server’s **Drive › Advertisements** folder.
- **Create/Update an Advertisement** that links to `https://<your-instance>/tags/<tag>`.
- **Promote the underdogs:** ad `ratio` is computed **inverse to popularity** (less popular → bigger ratio).
- **Idempotent:** one ad per tag (`[TagAd] #<tag> — featured`). If it exists, the image is updated only when newer, and the run window is extended.
- **Fork‑friendly:** the ad creator adapts to different field requirements (e.g., `place`, `startsAt`, `expiresAt`, `dayOfWeek`, integer `ratio`, string `priority`).

> ℹ️ This project was assisted by AI. Review before production, and pin settings to match your instance’s schema.

---

## Quick start

> Tested with **Python 3.10+**. Earlier versions may work but aren’t supported here.

```bash
python -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt
cp .env.example .env
# edit .env and set SHARKEY_BASE + SHARKEY_TOKEN
```

1) **Pick bubble sources** (public servers you trust).  
   Edit `bubble_domains.txt` (one per line). This repo ships a minimal default:
   ```
   mastodon.social
   mastodon.art
   ```

2) **Aggregate trends and choose tags** (writes `bubble_trends.json` + `selected_tags.txt`):
   ```bash
   python3 _1_bubble_trends.py --select 10
   # Or interactively:
   python3 _1_bubble_trends.py --interactive
   ```

3) **Fetch images & upload to Drive › Advertisements** (writes `ads_uploads_manifest.json`):
   ```bash
   python3 _2_ads_stage_uploads.py
   ```

4) **Create/Update ads** (writes `ads_created.json`):
   ```bash
   DRY_RUN=1 python3 _3_ad_stage_create_ad.py  # preview payloads only
# or
python3 _3_ad_stage_create_ad.py
   ```

5) **(Optional) Clean the Ads folder** (for fresh runs):
   ```bash
   python3 clean_ads_folder.py --yes
   ```

---

## Scripts & switches

### 1) `_1_bubble_trends.py`
Merges trending tags across your bubble and lets you pick a subset.

**CLI**
- `--domains-file PATH`  (default: `bubble_domains.txt`)  
- `--limit-per-domain N` (default: `40`)  
- `--select N`           (default: `10`) — choose top N automatically  
- `--interactive`        — choose by index ranges (e.g., `1-5,8,12`)

**Outputs**
- `bubble_trends.json` — raw + merged trends
- `selected_tags.txt`  — one tag per line (feeds stage 2)

---

### 2) `_2_ads_stage_uploads.py`
Finds a good post with media for each selected tag, filters sensitive content, dedupes by SHA‑256, and uploads the file to **Drive › Advertisements**.

**Inputs**
- `selected_tags.txt` — from stage 1
- `bubble_domains.txt` — the bubble

**Environment (.env)**
- `SHARKEY_BASE` — e.g., `https://mypocketpals.online`
- `SHARKEY_TOKEN` — **ADMIN token** with Drive + Advertisement write scopes
- `AD_FOLDER` — Drive folder name (default `Advertisements`)
- `STATUS_SCAN_LIMIT` — posts per server/tag to consider (default `60`)
- `HTTP_TIMEOUT` — per request seconds (default `25`)
- `USER_AGENT` — http UA string
- `DEDUP_MODE` — `reuse` (default) or `rename`  
  - `reuse`: move an existing matching file into the folder and keep its name  
  - `rename`: also rename it to the new run’s filename

**Outputs**
- `ads_uploads_manifest.json` — per‑tag chosen file & Drive URL
- `ads_dedupe_index.json` — persistent hash→file map

---

### 3) `_3_ad_stage_create_ad.py`
Creates/updates one Advertisement per tag, linking to your local tag page. It tries to adapt to your instance’s schema:

- Always sends: `title`, `memo`, `imageUrl`, `url`, `place`, `priority` *(string)*.
- Dates: uses `startsAt` (now) and `expiresAt` (now + `AD_DURATION_DAYS`).  
  Falls back between ISO‑8601 and epoch‑ms if needed.
- Days: sends `dayOfWeek` as an **integer bitmask** (`127` = every day) and retries other encodings if your server requires them.
- Ratio: computed **inverse to popularity** and sent as **integer** (scaled; see below).

**Environment (.env)**
- `AD_DEFAULT_PRIORITY` — default priority (stored as **string**) (default `50`)
- `AD_DURATION_DAYS` — run length (default `7`)
- `AD_TITLE_PREFIX` — default `[TagAd] #`
- `AD_PLACE` — e.g., `horizontal-big` (required on many builds)
- `AD_RATIO_MIN` / `AD_RATIO_MAX` — float range used for internal scaling (defaults `0.40`..`1.00`)
- `AD_RATIO_SCALE` — integer scale for the server (default `100`; send 40..100 by default)

**Outputs**
- `ads_created.json` — counts of created/updated

---

## Configuration

Create `.env` from the example and fill in your values:

```bash
cp .env.example .env
$EDITOR .env
```

`.env.example` includes:

```dotenv
# Server + admin token
SHARKEY_BASE=https://mypocketpals.online
SHARKEY_TOKEN=YOUR_ADMIN_API_TOKEN_HERE

# Drive & fetch
AD_FOLDER=Advertisements
STATUS_SCAN_LIMIT=60
HTTP_TIMEOUT=25
USER_AGENT=BubbleAdUploader/1.3 (+https://your-domain)

# Dedupe behaviour: reuse | rename
DEDUP_MODE=reuse

# Ad creator
AD_DEFAULT_PRIORITY=50
AD_DURATION_DAYS=7
AD_TITLE_PREFIX=[TagAd] #
AD_PLACE=horizontal-big

# Popularity → ratio controls
AD_RATIO_MIN=0.40
AD_RATIO_MAX=1.00
AD_RATIO_SCALE=100
```

Permissions the token needs (typical for Sharkey/Misskey forks):
- Drive: `read`, `write`
- Advertisements: `read`, `write`
- Admin scope if required by your build for `/api/admin/ad/*`

---

## File overview

- `_1_bubble_trends.py` — discover & select tags  
- `_2_ads_stage_uploads.py` — fetch safe images, dedupe, upload to Drive  
- `_3_ad_stage_create_ad.py` — create/update advertisements  
- `clean_ads_folder.py` — wipe the `Advertisements` folder (careful)  
- `bubble_domains.txt` — your bubble (one domain per line)  
- `selected_tags.txt` — chosen tags (produced by stage 1)  
- `requirements.txt` — `python-dotenv`, `requests`

---


---

## Admin considerations

- **Attribution & provenance:** Images are sourced from public posts on other servers. Consider adding attribution (origin domain + post URL) to the ad memo or Drive file description if your policies require it.
- **NSFW is best-effort:** The filters avoid obvious NSFW via content warnings, tags, and common terms. They are not perfect. Review before publishing in sensitive contexts.
- **Rate limits & neighborly use:** Add small delays between requests if you expand your bubble; some servers rate limit aggressively.
- **Timezones:** `startsAt`/`expiresAt` are sent in UTC; your UI may show local time.
- **Production hygiene:** Prefer updating/rotating ads over deleting Drive media. Deleting files breaks ads that reference them.


## Troubleshooting

- `INVALID_PARAM … must have required property 'place'`  
  → Set `AD_PLACE` in `.env` (e.g., `horizontal-big`).

- `… 'startsAt' / 'expiresAt'` required  
  → The creator sends both; if your fork wants epoch numbers, it auto‑retries. Pin your build’s expected keys if you’ve customized them.

- `… 'priority' type must be string`  
  → This build stores priority as string; the creator already sends it as such.

- `… 'ratio' type must be integer`  
  → Set by the creator using `AD_RATIO_SCALE`. Adjust scale if your UI expects a different range.

- Day‑of‑week complaints  
  → The creator tries an integer bitmask (`127`) first, then known fallbacks. If your build uses a different encoding, update `_3_ad_stage_create_ad.py` accordingly.

If you still get a 400, copy the exact response and compare to the payload in `_3_ad_stage_create_ad.py`—forks vary in small but important ways.

---

## License / Credit

This repository contains scripts authored with the assistance of AI. You are responsible for reviewing and operating them within your server’s policies and applicable laws.


\1
> **⚠️ Important production warning**  
> Deleting images from Drive will break existing advertisements that reference those files.  
> Use the cleaner only in test/dev runs. In production, prefer rotating ads (update dates) instead of deleting media.

---

## Developer experience

- **Makefile:** `make install`, `make run-trends`, `make run-uploads`, `make run-ads`, `make clean-ads`.
- **Pinned deps:** See `requirements.txt` for exact versions.
- **.gitignore:** Excludes secrets and generated artifacts by default.
- **Contributing:** If your fork expects different ad field names or types, open an issue with a sample of the 400 error JSON and the payload that works on your instance so we can add a shim.
