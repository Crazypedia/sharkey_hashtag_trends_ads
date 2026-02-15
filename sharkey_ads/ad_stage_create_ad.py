# ad_stage_create_ad.py
# Create/update Advertisements per selected tag using Drive images from ads_uploads_manifest.json.
# - Supports multi-variant ads: tags with enough images get multiple concurrent ads
#   with the ratio budget split evenly so they don't crowd out single-image tags.
# - Handles schema quirks across Sharkey/Misskey forks (place, startsAt/expiresAt, dayOfWeek, ratio int, priority string)
# - Automatically expires stale variant ads when a tag's image count drops.
# - Supports DRY_RUN=1 to preview payloads without modifying the server.

import os, sys, json
from datetime import datetime, timedelta, timezone
from collections import Counter
from pathlib import Path
import requests
from dotenv import load_dotenv

# Load .env from project root
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

# ===== Config / ENV =====
SHARKEY_BASE  = (os.getenv("SHARKEY_BASE") or "").rstrip("/")
SHARKEY_TOKEN = (os.getenv("SHARKEY_TOKEN") or "").strip()

AD_DEFAULT_PRIORITY = int(os.getenv("AD_DEFAULT_PRIORITY", "50"))
AD_RATIO_MIN = float(os.getenv("AD_RATIO_MIN", "0.40"))   # internal float space 0..1
AD_RATIO_MAX = float(os.getenv("AD_RATIO_MAX", "1.00"))
AD_RATIO_SCALE = int(os.getenv("AD_RATIO_SCALE", "100"))  # server integer space (default 1..100)
AD_DURATION_DAYS = int(os.getenv("AD_DURATION_DAYS", "7"))
TITLE_PREFIX = os.getenv("AD_TITLE_PREFIX", "[TagAd] #")
AD_PLACE_ENV = os.getenv("AD_PLACE", "").strip()          # e.g., "horizontal-big", "timeline"

# Weekday "always on" ads
WEEKDAY_TITLE_PREFIX = os.getenv("WEEKDAY_TITLE_PREFIX", "[WeekdayAd] #")
WEEKDAY_AD_RATIO = int(os.getenv("WEEKDAY_AD_RATIO", "50"))
WEEKDAY_AD_PRIORITY = int(os.getenv("WEEKDAY_AD_PRIORITY", "50"))

# Bitmask per day (Sunday = bit 0)
DAY_BITMASK = {
    "sunday":    1,   # 2^0
    "monday":    2,   # 2^1
    "tuesday":   4,   # 2^2
    "wednesday": 8,   # 2^3
    "thursday":  16,  # 2^4
    "friday":    32,  # 2^5
    "saturday":  64,  # 2^6
}
DAY_INDEX_0 = {  # 0-based (Sunday = 0)
    "sunday": 0, "monday": 1, "tuesday": 2, "wednesday": 3,
    "thursday": 4, "friday": 5, "saturday": 6,
}
DAY_INDEX_1 = {  # 1-based (Sunday = 1)
    "sunday": 1, "monday": 2, "tuesday": 3, "wednesday": 4,
    "thursday": 5, "friday": 6, "saturday": 7,
}

# New: dry-run support
DRY_RUN = os.getenv("DRY_RUN", "0") == "1"

USER_AGENT = "SharkeyAdCreator/1.7 (+MyPocketPals)"
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": USER_AGENT})
TIMEOUT = 30

MANIFEST_PATH = Path("ads_uploads_manifest.json")
TRENDS_PATH   = Path("bubble_trends.json")
OVERRIDES     = Path("ad_overrides.json")

# ===== Helpers =====
def die(msg: str, code=1):
    print(f"[fatal] {msg}", file=sys.stderr); sys.exit(code)

def post_api_soft(path: str, payload: dict, expect_json=True):
    """Return (ok, data_or_text, status)."""
    if not SHARKEY_BASE or not SHARKEY_TOKEN:
        return False, "missing SHARKEY_BASE/SHARKEY_TOKEN", 0
    url = f"{SHARKEY_BASE}/api/{path.lstrip('/')}"
    data = dict(payload or {}); data["i"] = SHARKEY_TOKEN
    r = SESSION.post(url, json=data, timeout=TIMEOUT)
    if 200 <= r.status_code < 300:
        if expect_json:
            try: return True, r.json(), r.status_code
            except Exception: return True, {}, r.status_code
        return True, {}, r.status_code
    else:
        return False, (r.text or ""), r.status_code

def post_api(path: str, payload: dict, expect_json=True):
    ok, data, _ = post_api_soft(path, payload, expect_json)
    if not ok:
        die(f"{path} failed: {data}")
    return data

def send_payload(op_path: str, payload: dict):
    """Respects DRY_RUN. Returns (ok, data_or_text, status)."""
    if DRY_RUN:
        # Print a compact payload snippet for sanity
        preview = {k: payload.get(k) for k in ("title","place","url","imageUrl","priority","ratio","startsAt","expiresAt","dayOfWeek","id") if k in payload}
        print("[dry-run]", op_path, json.dumps(preview, ensure_ascii=False))
        return True, {"dry_run": True}, 200
    return post_api_soft(op_path, payload, expect_json=True)

def load_json_file(path: Path):
    if not path.exists(): return {}
    return json.loads(path.read_text(encoding="utf-8"))

def detect_schema_and_defaults():
    """Probe existing ads to learn optional fields and a default 'place'."""
    ads = post_api("admin/ad/list", {})
    schema = {"ratio": False, "place": False, "start_key": None, "end_key": None, "default_place": None}
    places = []
    if isinstance(ads, list):
        for a in ads:
            if not isinstance(a, dict): continue
            if "ratio" in a: schema["ratio"] = True
            if "place" in a:
                schema["place"] = True
                v = a.get("place")
                if v is not None: places.append(str(v))
            for k in a.keys():
                lk = k.lower()
                if schema["start_key"] is None and lk in ("start", "startat", "startsat", "startdate"):
                    schema["start_key"] = k
                if schema["end_key"]   is None and lk in ("end", "endat", "enddate", "expiresat"):
                    schema["end_key"] = k
    if AD_PLACE_ENV:
        schema["default_place"] = AD_PLACE_ENV
    elif places:
        schema["default_place"] = Counter(places).most_common(1)[0][0]
    else:
        schema["default_place"] = "timeline"
        schema["place"] = True
    return schema, ads

def build_ratio_inverse_float(pop_scores: dict, tag: str) -> float:
    vals = [v for v in pop_scores.values() if isinstance(v, (int,float))]
    if not vals: return (AD_RATIO_MIN + AD_RATIO_MAX)/2.0
    smin, smax = min(vals), max(vals); s = pop_scores.get(tag, smin)
    t = 0.5 if smax == smin else (s - smin) / (smax - smin)
    inv = 1.0 - max(0.0, min(1.0, t))
    ratio = AD_RATIO_MIN + inv * (AD_RATIO_MAX - AD_RATIO_MIN)
    return max(AD_RATIO_MIN, min(AD_RATIO_MAX, ratio))

def to_iso8601(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()

def to_epoch_ms(dt: datetime) -> int:
    return int(dt.replace(tzinfo=timezone.utc).timestamp() * 1000)

VARIANT_LABELS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

def newest_per_tag(uploads_list):
    latest = {}
    for r in uploads_list:
        tag = (r.get("tag") or "").lstrip("#").lower()
        fn = r.get("filename") or ""
        date_prefix = fn.split("_", 1)[0] if "_" in fn else ""
        try:
            d = datetime.strptime(date_prefix, "%Y-%m-%d")
        except Exception:
            d = datetime.utcnow()
        prev = latest.get(tag)
        if (prev is None) or (d > prev["dt"]):
            latest[tag] = {**r, "dt": d}
    return latest

def group_by_tag(uploads_list):
    """Group uploads by tag, returning {tag: [uploads sorted by variant_rank]}.
    Each tag may have multiple variants (images) from the upload stage."""
    groups = {}
    for r in uploads_list:
        tag = (r.get("tag") or "").lstrip("#").lower()
        if not tag:
            continue
        groups.setdefault(tag, []).append(r)
    # Sort each group by variant_rank (upload stage assigns these)
    for tag in groups:
        groups[tag].sort(key=lambda r: r.get("variant_rank", 0))
    return groups

def find_existing_by_title(ads: list, title: str):
    for a in ads or []:
        if isinstance(a, dict) and a.get("title") == title:
            return a
    return None

def needs_epoch_retry(err: str) -> bool:
    t = (err or "").lower()
    return any(k in t for k in ["format", "invalid date", "not a valid", "string is not", "must be integer", "must be number"])

def dayofweek_candidates():
    """Try formats in this order (most common first)."""
    return [
        127,                          # integer bitmask, all days
        0,                            # seen on some forks as "every day"
        list(range(0,7)),             # [0..6]
        list(range(1,8)),             # [1..7]
        ["sunday","monday","tuesday","wednesday","thursday","friday","saturday"],
    ]

def weekday_dayofweek_candidates(day_name: str):
    """Day-of-week candidates restricted to a single named day."""
    day = day_name.strip().lower()
    return [
        DAY_BITMASK[day],             # integer bitmask for one day
        [DAY_INDEX_0[day]],           # array [0..6]
        [DAY_INDEX_1[day]],           # array [1..7]
        [day],                        # string array
    ]

# ===== Main =====
def main():
    manifest = load_json_file(MANIFEST_PATH)
    if not manifest or "results" not in manifest:
        die("ads_uploads_manifest.json not found or empty. Run the upload stage first.")
    uploads = manifest["results"]

    trends = load_json_file(TRENDS_PATH)
    merged_scores = {}
    for item in trends.get("merged", []):
        tag = (item.get("tag") or "").lstrip("#").lower()
        try: score = int(item.get("score", 0))
        except Exception: score = 0
        if tag: merged_scores[tag] = score

    overrides = load_json_file(OVERRIDES) if OVERRIDES.exists() else {}

    schema, existing_ads = detect_schema_and_defaults()
    print(f"[info] ad schema → ratio={schema['ratio']} place={schema['place']} "
          f"start={schema['start_key']} end={schema['end_key']} default_place={schema['default_place']}")

    # Keys: respect discovered names; otherwise use common ones
    start_key = schema["start_key"] or "startsAt"
    end_key   = schema["end_key"]   or "expiresAt"

    # Separate trending uploads from weekday "always on" uploads
    trending_uploads = [r for r in uploads if not r.get("weekday")]
    weekday_uploads  = [r for r in uploads if r.get("weekday")]

    tag_groups = group_by_tag(trending_uploads)
    weekday_groups = group_by_tag(weekday_uploads)

    created, updated, stale_cleaned = 0, 0, 0
    now = datetime.utcnow()
    expires_dt = now + timedelta(days=AD_DURATION_DAYS)
    active_titles = set()

    # ===== Trending ads (normal behaviour) =====
    for tag, variants in tag_groups.items():
        is_multi = len(variants) > 1
        url = f"{SHARKEY_BASE}/tags/{tag}"

        # Compute ratio budget for the whole tag
        ratio_f = build_ratio_inverse_float(merged_scores, tag) if schema["ratio"] else None

        # Per-tag overrides
        priority_val = AD_DEFAULT_PRIORITY
        ov = overrides.get(tag) if isinstance(overrides, dict) else None
        if ov:
            try: priority_val = int(ov.get("priority", priority_val))
            except Exception: pass
            url = ov.get("targetUrl", url)

        if is_multi:
            print(f"[info] #{tag}: {len(variants)} variant(s), splitting ratio budget")

        for vi, r in enumerate(variants):
            # --- Title: bare for single, labelled for multi ---
            if is_multi:
                label = VARIANT_LABELS[vi]
                title = f"{TITLE_PREFIX}{tag} — featured ({label})"
            else:
                title = f"{TITLE_PREFIX}{tag} — featured"
            active_titles.add(title)

            # --- Split ratio across variants ---
            ratio_int = None
            if ratio_f is not None:
                variant_ratio = ratio_f / len(variants)
                scaled = variant_ratio * AD_RATIO_SCALE
                scaled = max(1, min(AD_RATIO_SCALE, scaled))
                ratio_int = int(round(scaled))

            # --- Memo ---
            variant_note = f"variant={VARIANT_LABELS[vi]}/{len(variants)}" if is_multi else "single"
            memo = " • ".join([
                f"Auto {now.date().isoformat()}",
                f"consensus={r.get('appearances', 1)}",
                f"score={r.get('score', 0)}",
                f"duration={AD_DURATION_DAYS}d",
                variant_note
            ])

            base = {
                "title": title,
                "memo": memo,
                "imageUrl": r.get("drive_url"),
                "url": url,
                "priority": str(priority_val),
                "place": schema["default_place"],
            }
            if schema["ratio"] and ratio_int is not None:
                base["ratio"] = ratio_int

            iso_dates = { start_key: to_iso8601(now),     end_key: to_iso8601(expires_dt) }
            epoch_dates = { start_key: to_epoch_ms(now),  end_key: to_epoch_ms(expires_dt) }

            existing = find_existing_by_title(existing_ads, title)
            op_path = "admin/ad/update" if existing else "admin/ad/create"

            core = dict(base)
            if existing:
                core["id"] = existing.get("id")

            success = False
            last_err = None

            # Try ISO-date attempts with several dayOfWeek encodings
            for dv in dayofweek_candidates():
                payload = dict(core); payload.update(iso_dates); payload["dayOfWeek"] = dv
                ok, data, _ = send_payload(op_path, payload)
                if ok:
                    success = True; break
                last_err = data
                if needs_epoch_retry(str(data)):
                    break

            # If still not ok, try epoch-ms attempts
            if not success:
                for dv in dayofweek_candidates():
                    payload = dict(core); payload.update(epoch_dates); payload["dayOfWeek"] = dv
                    ok, data, _ = send_payload(op_path, payload)
                    if ok:
                        success = True; break
                    last_err = data

            if not success:
                die(f"{op_path} failed: {last_err}")

            if existing:
                updated += 1
                print(("[dry-run] " if DRY_RUN else "") + f"[update] {title} place={base['place']} ratio={base.get('ratio')} priority={base['priority']}")
            else:
                created += 1
                print(("[dry-run] " if DRY_RUN else "") + f"[create] {title} place={base['place']} ratio={base.get('ratio')} priority={base['priority']}")

    # ===== Weekday "always on" ads =====
    # These get: day-specific dayOfWeek, no expiration, fixed ratio, image refresh only.
    weekday_created, weekday_updated = 0, 0
    # Use a far-future expiry (10 years) since weekday ads should never expire.
    far_future = now + timedelta(days=3650)

    for tag, variants in weekday_groups.items():
        day_name = variants[0].get("weekday", "").lower()
        if day_name not in DAY_BITMASK:
            print(f"[warn] weekday tag #{tag} has unknown day '{day_name}', skipping")
            continue

        url = f"{SHARKEY_BASE}/tags/{tag}"

        # Per-tag overrides (same mechanism as trending)
        priority_val = WEEKDAY_AD_PRIORITY
        ov = overrides.get(tag) if isinstance(overrides, dict) else None
        if ov:
            try: priority_val = int(ov.get("priority", priority_val))
            except Exception: pass
            url = ov.get("targetUrl", url)

        # Take only the first variant for weekday ads (single image per tag)
        r = variants[0]
        title = f"{WEEKDAY_TITLE_PREFIX}{tag} — {day_name}"
        active_titles.add(title)

        memo = " • ".join([
            f"Auto {now.date().isoformat()}",
            f"weekday={day_name}",
            "always-on",
        ])

        base = {
            "title": title,
            "memo": memo,
            "imageUrl": r.get("drive_url"),
            "url": url,
            "priority": str(priority_val),
            "place": schema["default_place"],
        }
        if schema["ratio"]:
            base["ratio"] = WEEKDAY_AD_RATIO

        # Weekday ads: start now, never expire (far future).
        # Only update the image and start date — preserve the always-on nature.
        iso_dates  = { start_key: to_iso8601(now), end_key: to_iso8601(far_future) }
        epoch_dates = { start_key: to_epoch_ms(now), end_key: to_epoch_ms(far_future) }

        existing = find_existing_by_title(existing_ads, title)
        op_path = "admin/ad/update" if existing else "admin/ad/create"

        core = dict(base)
        if existing:
            core["id"] = existing.get("id")
            # When updating an existing weekday ad, only refresh the image —
            # do not overwrite the expiry or ratio that may have been tuned.
            core.pop("ratio", None)

        success = False
        last_err = None

        # Try ISO-date attempts with day-specific dayOfWeek
        dow_candidates = weekday_dayofweek_candidates(day_name)
        for dv in dow_candidates:
            payload = dict(core)
            payload.update(iso_dates)
            # On updates, don't send new dates (preserve always-on window)
            if existing:
                payload.pop(start_key, None)
                payload.pop(end_key, None)
            payload["dayOfWeek"] = dv
            ok, data, _ = send_payload(op_path, payload)
            if ok:
                success = True; break
            last_err = data
            if needs_epoch_retry(str(data)):
                break

        # Epoch-ms fallback
        if not success:
            for dv in dow_candidates:
                payload = dict(core)
                payload.update(epoch_dates)
                if existing:
                    payload.pop(start_key, None)
                    payload.pop(end_key, None)
                payload["dayOfWeek"] = dv
                ok, data, _ = send_payload(op_path, payload)
                if ok:
                    success = True; break
                last_err = data

        if not success:
            print(f"[warn] weekday ad #{tag} ({day_name}) failed: {last_err}")
            continue

        prefix = "[dry-run] " if DRY_RUN else ""
        if existing:
            weekday_updated += 1
            print(f"{prefix}[weekday-update] {title} day={day_name} place={base['place']} priority={base['priority']}")
        else:
            weekday_created += 1
            print(f"{prefix}[weekday-create] {title} day={day_name} place={base['place']} ratio={base.get('ratio')} priority={base['priority']}")

    # ===== Clean stale ads =====
    # Expire old trending or weekday ads that are no longer in the active set.
    managed_prefixes = (TITLE_PREFIX, WEEKDAY_TITLE_PREFIX)
    for a in existing_ads or []:
        if not isinstance(a, dict):
            continue
        t = a.get("title", "")
        if any(t.startswith(p) for p in managed_prefixes) and t not in active_titles:
            aid = a.get("id")
            if aid:
                print(("[dry-run] " if DRY_RUN else "") + f"[cleanup] expiring stale ad: {t}")
                expire_payload = {"id": aid, end_key: to_iso8601(now)}
                send_payload("admin/ad/update", expire_payload)
                stale_cleaned += 1

    total_created = created + weekday_created
    total_updated = updated + weekday_updated
    Path("ads_created.json").write_text(
        json.dumps({
            "created": created, "updated": updated,
            "weekday_created": weekday_created, "weekday_updated": weekday_updated,
            "stale_cleaned": stale_cleaned
        }, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    print(f"\n[done] trending: created={created} updated={updated} | "
          f"weekday: created={weekday_created} updated={weekday_updated} | "
          f"stale_cleaned={stale_cleaned}. Wrote ads_created.json.")

if __name__ == "__main__":
    main()
