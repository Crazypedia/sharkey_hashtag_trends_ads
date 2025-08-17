# ads_stage_create_ads.py
import os, sys, json
from datetime import datetime, timedelta, timezone
from collections import Counter
from pathlib import Path
import requests
from dotenv import load_dotenv

# Load .env
load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")

SHARKEY_BASE  = (os.getenv("SHARKEY_BASE") or "").rstrip("/")
SHARKEY_TOKEN = (os.getenv("SHARKEY_TOKEN") or "").strip()

AD_DEFAULT_PRIORITY = int(os.getenv("AD_DEFAULT_PRIORITY", "50"))
AD_RATIO_MIN = float(os.getenv("AD_RATIO_MIN", "0.40"))   # 0.0..1.0 (float space)
AD_RATIO_MAX = float(os.getenv("AD_RATIO_MAX", "1.00"))
AD_RATIO_SCALE = int(os.getenv("AD_RATIO_SCALE", "100"))  # server expects integer (e.g., 1..100)
AD_DURATION_DAYS = int(os.getenv("AD_DURATION_DAYS", "7"))
TITLE_PREFIX = os.getenv("AD_TITLE_PREFIX", "[TagAd] #")
AD_PLACE_ENV = os.getenv("AD_PLACE", "").strip()  # e.g. "horizontal-big", "timeline"

USER_AGENT = "SharkeyAdCreator/1.7 (+MyPocketPals)"
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": USER_AGENT})
TIMEOUT = 30

MANIFEST_PATH = Path("ads_uploads_manifest.json")
TRENDS_PATH   = Path("bubble_trends.json")
OVERRIDES     = Path("ad_overrides.json")

def die(msg: str, code=1):
    print(f"[fatal] {msg}", file=sys.stderr); sys.exit(code)

def post_api_soft(path: str, payload: dict, expect_json=True):
    url = f"{SHARKEY_BASE}/api/{path.lstrip('/')}"
    data = dict(payload or {}); data["i"] = SHARKEY_TOKEN
    r = SESSION.post(url, json=data, timeout=TIMEOUT)
    if 200 <= r.status_code < 300:
        if expect_json:
            try: return True, r.json(), r.status_code
            except Exception: return True, {}, r.status_code
        return True, {}, r.status_code
    return False, (r.text or ""), r.status_code

def post_api(path: str, payload: dict, expect_json=True):
    ok, data, _ = post_api_soft(path, payload, expect_json)
    if not ok:
        die(f"{path} failed: {data}")
    return data

def load_json(path: Path):
    if not path.exists(): return {}
    return json.loads(path.read_text(encoding="utf-8"))

def detect_schema_and_defaults():
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
    """Return 0..1 where lower popularity => larger value (inverse)."""
    vals = [v for v in pop_scores.values() if isinstance(v, (int,float))]
    if not vals: return (AD_RATIO_MIN + AD_RATIO_MAX)/2.0
    smin, smax = min(vals), max(vals); s = pop_scores.get(tag, smin)
    t = 0.5 if smax == smin else (s - smin) / (smax - smin)
    inv = 1.0 - max(0.0, min(1.0, t))
    ratio = AD_RATIO_MIN + inv * (AD_RATIO_MAX - AD_RATIO_MIN)
    # clamp
    if ratio < AD_RATIO_MIN: ratio = AD_RATIO_MIN
    if ratio > AD_RATIO_MAX: ratio = AD_RATIO_MAX
    return ratio

def to_iso8601(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()

def to_epoch_ms(dt: datetime) -> int:
    return int(dt.replace(tzinfo=timezone.utc).timestamp() * 1000)

def newest_per_tag(uploads_list):
    latest = {}
    for r in uploads_list:
        tag = (r.get("tag") or "").lstrip("#").lower()
        fn = r.get("filename") or ""
        date_prefix = fn.split("_", 1)[0] if "_" in fn else ""
        try: d = datetime.strptime(date_prefix, "%Y-%m-%d")
        except Exception: d = datetime.utcnow()
        prev = latest.get(tag)
        if (prev is None) or (d > prev["dt"]):
            latest[tag] = {**r, "dt": d}
    return latest

def find_existing_by_title(ads: list, title: str):
    for a in ads or []:
        if isinstance(a, dict) and a.get("title") == title:
            return a
    return None

def wants_dayofweek_error(err: str) -> bool:
    t = (err or "").lower()
    return "dayofweek" in t and ("required" in t or "invalid" in t or "must have" in t)

def needs_epoch_retry(err: str) -> bool:
    t = (err or "").lower()
    return any(k in t for k in ["format", "invalid date", "not a valid", "string is not", "must be integer", "must be number"])

def dayofweek_candidates():
    """
    Try formats in this order:
      1) integer bitmask (all days) -> 127  (1|2|4|8|16|32|64)
      2) integer 0 (seen on some forks as 'every day')
      3) arrays (0..6), (1..7), and strings (fallbacks)
    """
    return [
        127,
        0,
        list(range(0,7)),
        list(range(1,8)),
        ["sunday","monday","tuesday","wednesday","thursday","friday","saturday"],
    ]

def main():
    manifest = load_json(MANIFEST_PATH)
    if not manifest or "results" not in manifest:
        die("ads_uploads_manifest.json not found or empty. Run the upload stage first.")
    uploads = manifest["results"]

    trends = load_json(TRENDS_PATH)
    merged_scores = {}
    for item in trends.get("merged", []):
        tag = (item.get("tag") or "").lstrip("#").lower()
        try: score = int(item.get("score", 0))
        except Exception: score = 0
        if tag: merged_scores[tag] = score

    overrides = load_json(OVERRIDES) if OVERRIDES.exists() else {}

    schema, existing_ads = detect_schema_and_defaults()
    print(f"[info] ad schema → ratio={schema['ratio']} place={schema['place']} "
          f"start={schema['start_key']} end={schema['end_key']} default_place={schema['default_place']}")

    # Pin keys your instance expects if not discovered
    start_key = schema["start_key"] or "startsAt"
    end_key   = schema["end_key"]   or "expiresAt"

    uploads_by_tag = newest_per_tag(uploads)
    created, updated = 0, 0
    now = datetime.utcnow()
    expires_dt = now + timedelta(days=AD_DURATION_DAYS)

    for tag, r in uploads_by_tag.items():
        title = f"{TITLE_PREFIX}{tag} — featured"
        url = f"{SHARKEY_BASE}/tags/{tag}"

        # inverse popularity → float ratio, then convert to integer scale for server
        ratio_f = build_ratio_inverse_float(merged_scores, tag) if schema["ratio"] else None
        ratio_int = None
        if ratio_f is not None:
            scaled = ratio_f * AD_RATIO_SCALE
            if scaled < 1: scaled = 1
            if scaled > AD_RATIO_SCALE: scaled = AD_RATIO_SCALE
            ratio_int = int(round(scaled))

        priority_val = AD_DEFAULT_PRIORITY

        memo = " • ".join([
            f"Auto {now.date().isoformat()}",
            f"consensus={r.get('appearances', 1)}",
            f"score={r.get('score', 0)}",
            f"duration={AD_DURATION_DAYS}d"
        ])

        ov = overrides.get(tag) if isinstance(overrides, dict) else None
        if ov:
            priority_val = int(ov.get("priority", priority_val))
            url = ov.get("targetUrl", url)

        base = {
            "title": title,
            "memo": memo,
            "imageUrl": r.get("drive_url"),
            "url": url,
            "priority": str(priority_val),      # STRING per your instance
            "place": schema["default_place"],
        }
        if schema["ratio"] and ratio_int is not None:
            base["ratio"] = ratio_int          # INTEGER per your instance

        iso_dates = { start_key: to_iso8601(now),     end_key: to_iso8601(expires_dt) }
        epoch_dates = { start_key: to_epoch_ms(now),  end_key: to_epoch_ms(expires_dt) }

        existing = find_existing_by_title(existing_ads, title)
        op_path = "admin/ad/update" if existing else "admin/ad/create"

        core = dict(base)
        if existing:
            core["id"] = existing.get("id")

        success = False
        last_err = None

        # First try: ISO dates + integer bitmask dayOfWeek (then other variants)
        for dv in dayofweek_candidates():
            payload = dict(core); payload.update(iso_dates); payload["dayOfWeek"] = dv
            ok, data, _ = (True, {"dry_run": True}, 200) if DRY_RUN else post_api_soft(op_path, payload, expect_json=True)
            if ok:
                success = True; break
            last_err = data
            # If the error screams about date format, jump to epoch-ms attempts
            if needs_epoch_retry(str(data)):
                break

        # If still not ok, try epoch-ms dates with the same dayOfWeek variants
        if not success:
            for dv in dayofweek_candidates():
                payload = dict(core); payload.update(epoch_dates); payload["dayOfWeek"] = dv
                ok, data, _ = (True, {"dry_run": True}, 200) if DRY_RUN else post_api_soft(op_path, payload, expect_json=True)
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

    Path("ads_created.json").write_text(
        json.dumps({"created": created, "updated": updated}, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    print(f"\n[done] ads created={created}, updated={updated}. Wrote ads_created.json.")

if __name__ == "__main__":
    main()

