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

    tag_groups = group_by_tag(uploads)
    created, updated, stale_cleaned = 0, 0, 0
    now = datetime.utcnow()
    expires_dt = now + timedelta(days=AD_DURATION_DAYS)
    active_titles = set()

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

    # --- Clean stale variant ads ---
    # When a tag drops from multi-variant to fewer variants (or disappears),
    # expire old ads that are no longer in the active set.
    for a in existing_ads or []:
        if not isinstance(a, dict):
            continue
        t = a.get("title", "")
        if t.startswith(TITLE_PREFIX) and t not in active_titles:
            aid = a.get("id")
            if aid:
                print(("[dry-run] " if DRY_RUN else "") + f"[cleanup] expiring stale ad: {t}")
                expire_payload = {"id": aid, end_key: to_iso8601(now)}
                send_payload("admin/ad/update", expire_payload)
                stale_cleaned += 1

    Path("ads_created.json").write_text(
        json.dumps({"created": created, "updated": updated, "stale_cleaned": stale_cleaned},
                   ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    print(f"\n[done] ads created={created}, updated={updated}, stale_cleaned={stale_cleaned}. Wrote ads_created.json.")

if __name__ == "__main__":
    main()
