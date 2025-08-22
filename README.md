# sharkey_hashtag_trends_ads

Surface **bubble-wide trending tags** and turn them into **Sharkey/Misskey advertisements** that link to your local tag pages.

## What it does

- **Discover trending hashtags** across the servers you trust (your “bubble”).  
- For each tag you pick, **select a representative safe image** (consensus across servers first; otherwise the most‑engaged post).  
- **Deduplicate** by SHA‑256 so the same image isn’t uploaded twice.  
- **Upload** the image to your server’s **Drive › Advertisements** folder (creating it if missing).  
- **Create/Update an Advertisement** that links to `https://<your-instance>/tags/<tag>`.  
- **Boost the underdogs:** ad `ratio` is computed **inverse to popularity** (less popular → larger ratio).  
- **Idempotent:** one ad per tag (`[TagAd] #<tag> — featured`). If it exists, we update the image (when newer) and extend the run window.  
- **Schema‑adaptive:** handles forks that require `place`, `startsAt`/`expiresAt`, `dayOfWeek`, integer `ratio`, and string `priority`.

> This project was assisted by AI. Review before production; adjust settings to match your instance’s schema.

---

## Quick start

> Tested with **Python 3.10+**.

```bash
python -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt
cp .env.example .env
# edit .env and set SHARKEY_BASE + SHARKEY_TOKEN
```

1) **Choose your bubble** (trusted public servers).  
   Edit `bubble_domains.txt` (one per line). A minimal default is included:
   ```
   mastodon.social
   mastodon.art
   ```

2) **Aggregate trends & choose tags** (writes `bubble_trends.json` + `selected_tags.txt`):
```bash
python -m sharkey_ads.bubble_trends --select 10
# Or pick interactively:
python -m sharkey_ads.bubble_trends --interactive
```

3) **Fetch images & upload to Drive › Advertisements** (writes `ads_uploads_manifest.json`):
```bash
python -m sharkey_ads.ads_stage_uploads
```

4) **Create/Update ads** (writes `ads_created.json`):

```bash
# Preview (no writes)
DRY_RUN=1 python -m sharkey_ads.ad_stage_create_ad

# Create/update for real
python -m sharkey_ads.ad_stage_create_ad
```

5) **(Optional) Clean the Ads folder** (for fresh test runs):
```bash
python -m sharkey_ads.clean_ads_folder --yes
```
> **⚠️ Production warning:** Deleting images from Drive will **break existing advertisements** that reference those files. Use the cleaner only in test/dev runs. In production, prefer rotating ads (update dates) instead of deleting media.

---

## Scripts & switches

### 1) `bubble_trends`
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

### 2) `ads_stage_uploads`
Finds a good post with media for each selected tag, filters sensitive content, dedupes by SHA‑256, and uploads the file to **Drive › Advertisements**.

**Inputs**
- `selected_tags.txt` — from stage 1
- `bubble_domains.txt` — the bubble

**Environment (.env)**
- `SHARKEY_BASE` — e.g., `https://your.instance`
- `SHARKEY_TOKEN` — **ADMIN token** with Drive + Advertisement write scopes
- `AD_FOLDER` — Drive folder name used for storage (default `Advertisements`). Created automatically if missing.
- `STATUS_SCAN_LIMIT` — posts per server/tag to consider (default `60`)
- `HTTP_TIMEOUT` — per request seconds (default `25`)
- `USER_AGENT` — HTTP UA string
- `DEDUP_MODE` — `reuse` (default) or `rename`  
  - `reuse`: move an existing matching file into the folder and keep its name  
  - `rename`: also rename it to match the new run’s filename

**Outputs**
- `ads_uploads_manifest.json` — per‑tag chosen file & Drive URL
- `ads_dedupe_index.json` — persistent hash→file map

---

### 3) `ad_stage_create_ad`
Creates/updates one Advertisement per tag, linking to your local tag page. Adapts to schema differences across forks.

- Sends: `title`, `memo`, `imageUrl`, `url`, `place`, `priority` *(string)*.
- Dates: `startsAt` (now) and `expiresAt` (now + `AD_DURATION_DAYS`).  
  Falls back between ISO‑8601 and epoch‑ms automatically.
- Days: `dayOfWeek` defaults to an **integer bitmask** (`127` = every day); known fallbacks are tried if needed.
- Ratio: computed **inverse to popularity** and sent as **integer** (scaled; see below).

**Environment (.env)**
- `AD_DEFAULT_PRIORITY` — default priority (**string** is sent) (default `50`)
- `AD_DURATION_DAYS` — run length (default `7`)
- `AD_TITLE_PREFIX` — default `[TagAd] #`
- `AD_PLACE` — e.g., `horizontal-big` (required on many builds)
- `AD_RATIO_MIN` / `AD_RATIO_MAX` — float range used for internal scaling (defaults `0.40`..`1.00`)
- `AD_RATIO_SCALE` — integer scale sent to the server (default `100`; e.g., 40..100)
- `AD_DAY_MASK` *(optional)* — override day bitmask (default `127` if added to the script)
- `DRY_RUN` — `1` to preview payloads; `0` (default) to create/update

**Outputs**
- `ads_created.json` — counts of created/updated

---

### Optional: `ad_overrides.json`

Per‑tag tweaks without touching code. If present in the project root, the ad creator will read it.

Example:
```json
{
  "caturday":  { "priority": 90, "targetUrl": "https://your.instance/tags/caturday" },
  "photography": { "priority": 40 }
}
```

Supported fields:
- `priority` (number): overrides the default priority for that tag (the script will send it as a **string** to the API).
- `targetUrl` (string): override the click‑through URL (defaults to `https://<your-instance>/tags/<tag>`).

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
SHARKEY_BASE=https://your.instance
SHARKEY_TOKEN=YOUR_ADMIN_API_TOKEN_HERE

# Drive & fetch
AD_FOLDER=Advertisements  # storage folder; created automatically if missing
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

# Optional
# AD_DAY_MASK=127
# DRY_RUN=1
```

Required token scopes (typical for Sharkey/Misskey forks):
- Drive: `read`, `write`
- Advertisements: `read`, `write`
- Admin scope if required by your build for `/api/admin/ad/*`

---

## Admin considerations

- **Attribution & provenance:** Images are sourced from public posts on other servers. Consider adding attribution (origin domain + post URL) to the ad memo or Drive file description if your policies require it.
- **NSFW is best‑effort:** Filters avoid obvious NSFW via content warnings, tags, and common terms. They are not perfect. Review before publishing in sensitive contexts.
- **Neighborly rate limits:** Add small delays between requests if you expand your bubble; some servers rate limit aggressively.
- **Timezones:** `startsAt`/`expiresAt` are sent in UTC; your UI may show local time.
- **Production hygiene:** Prefer updating/rotating ads over deleting Drive media. Deleting files breaks ads that reference them.

---

## Troubleshooting

- `INVALID_PARAM … 'place' required` → Set `AD_PLACE` in `.env` (e.g., `horizontal-big`).  
- `… 'startsAt' / 'expiresAt' required` → Script sends both; if your fork wants epoch, it auto‑retries.  
- `… 'priority' type must be string` → Script already sends string.  
- `… 'ratio' type must be integer` → Script scales to int using `AD_RATIO_SCALE`.  
- `… 'dayOfWeek' issues` → Script tries multiple encodings (bitmask first).

If you still get a 400, copy the exact response and compare to the payload the script prints (use `DRY_RUN=1` first). Forks vary in small but important ways.

---

## Developer experience

- **Makefile:** `make install`, `make run-trends`, `make run-uploads`, `make run-ads`, `make clean-ads`.
- **Pinned deps:** See `requirements.txt` for exact versions.
- **.gitignore:** Excludes secrets and generated artifacts by default.
- **Contributing:** If your fork expects different ad field names or types, open an issue with a sample of the 400 error JSON and the payload that works on your instance so we can add a shim.
