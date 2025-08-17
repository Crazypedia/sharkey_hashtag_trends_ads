# ads_stage_uploads.py
import os, sys, re, json, mimetypes, hashlib
from datetime import date
from urllib.parse import urlparse, quote
from pathlib import Path
from io import BytesIO

import requests
from dotenv import load_dotenv

# --- load .env ---
load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")

# -------- config via env --------
SHARKEY_BASE = os.getenv("SHARKEY_BASE", "https://mypocketpals.online").rstrip("/")
SHARKEY_TOKEN = (os.getenv("SHARKEY_TOKEN") or "").strip()
AD_FOLDER = os.getenv("AD_FOLDER", "Advertisements")
STATUS_SCAN_LIMIT = int(os.getenv("STATUS_SCAN_LIMIT", "60"))
USER_AGENT = os.getenv("USER_AGENT", "BubbleAdUploader/1.3 (+https://mypocketpals.online)")
TIMEOUT = int(os.getenv("HTTP_TIMEOUT", "25"))
DEDUP_MODE = (os.getenv("DEDUP_MODE", "reuse") or "reuse").lower()  # reuse | rename

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": USER_AGENT})

SAFE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
INDEX_PATH = Path("ads_dedupe_index.json")
MANIFEST_PATH = Path("ads_uploads_manifest.json")

# ---------- helpers ----------
def die(msg, code=1):
    print(f"[fatal] {msg}", file=sys.stderr); sys.exit(code)

def read_lines(path):
    p = Path(path)
    if not p.exists():
        die(f"{path} not found")
    return [ln.strip() for ln in p.read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.strip().startswith("#")]

def load_index():
    if INDEX_PATH.exists():
        try:
            return json.loads(INDEX_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"by_hash": {}}

def save_index(idx):
    INDEX_PATH.write_text(json.dumps(idx, ensure_ascii=False, indent=2), encoding="utf-8")

def mk_api(path, payload):
    if not SHARKEY_TOKEN:
        die("SHARKEY_TOKEN missing (check your .env)")
    url = f"{SHARKEY_BASE}/api/{path.lstrip('/')}"
    data = dict(payload or {})
    data["i"] = SHARKEY_TOKEN
    r = SESSION.post(url, json=data, timeout=TIMEOUT)
    try:
        r.raise_for_status()
    except requests.HTTPError as e:
        snippet = (r.text or "")[:300].replace("\n", " ")
        raise RuntimeError(f"{path} HTTP {r.status_code}: {snippet}") from e
    ctype = (r.headers.get("Content-Type") or "").lower()
    try:
        return r.json()
    except json.JSONDecodeError:
        snippet = (r.text or "")[:300].replace("\n", " ")
        raise RuntimeError(f"{path} returned non-JSON (Content-Type={ctype}): {snippet}")

def ensure_folder(name):
    lst = mk_api("drive/folders", {})
    for f in lst or []:
        if f and f.get("name") == name:
            return f["id"]
    created = mk_api("drive/folders/create", {"name": name})
    if not created or "id" not in created:
        raise RuntimeError("Could not create/find folder")
    return created["id"]

def sanitize_tag_for_filename(tag):
    return re.sub(r"[^a-z0-9._-]+", "-", tag.lower())

def text_has_nsfw(text):
    if not text: return False
    return bool(re.search(r"(?<!\w)#?(nsfw|18\+|lewd|porn|adult)\b", text, re.I))

def is_nsfw_tag(tagname):
    t = (tagname or "").lower()
    return t in {"nsfw", "18+", "lewd", "porn", "adult"}

def guess_ext_from_bytes_or_url(content_type, url):
    # prefer content-type
    if content_type:
        ext = mimetypes.guess_extension(content_type.split(";")[0].strip().lower()) or ""
        if ext.lower() in SAFE_EXTS:
            return ext.lower()
    # fallback to URL path
    path = urlparse(url).path
    ext2 = os.path.splitext(path)[1].lower()
    if ext2 in SAFE_EXTS:
        return ext2
    return ".jpg"

# ---------- fetch from bubble servers ----------
def get_json(url, params=None):
    try:
        r = SESSION.get(url, params=params or {}, timeout=TIMEOUT)
        r.raise_for_status()
        return r.json()
    except (requests.RequestException, json.JSONDecodeError):
        return None

def fetch_masto_tag_timeline(domain, tag, limit=40):
    safe_tag = quote(tag.lstrip("#"), safe="")
    return get_json(f"https://{domain}/api/v1/timelines/tag/{safe_tag}", params={"limit": limit}) or []

def fetch_misskey_tag_timeline(domain, tag, limit=40):
    base = f"https://{domain}/api"
    try:
        r = SESSION.post(f"{base}/notes/search-by-tag",
                         json={"tag": tag, "limit": limit}, timeout=TIMEOUT)
        if r.status_code == 200:
            return r.json() or []
    except Exception:
        pass
    try:
        r = SESSION.post(f"{base}/notes/search",
                         json={"query": f"#{tag}", "limit": limit}, timeout=TIMEOUT)
        if r.status_code == 200:
            return r.json() or []
    except Exception:
        pass
    return []

def detect_stack(domain):
    if isinstance(get_json(f"https://{domain}/api/v1/trends/tags", params={"limit": 1}), list):
        return "mastodon"
    if isinstance(get_json(f"https://{domain}/api/hashtags/trend"), list):
        return "misskey"
    return "unknown"

# ---------- consensus + popularity aggregation ----------
def masto_status_key(s, domain):
    return s.get("uri") or s.get("url") or f"{domain}#masto#{s.get('id')}"

def misskey_note_key(n, domain):
    return n.get("uri") or n.get("url") or f"{domain}#misskey#{n.get('id')}"

def pick_image_from_masto_status(s):
    for a in (s.get("media_attachments") or []):
        if (a.get("type") or "").lower() == "image":
            return a.get("remote_url") or a.get("url") or a.get("preview_url")
    return None

def pick_image_from_misskey_note(n):
    for f in (n.get("files") or []):
        if f.get("isSensitive") is True: 
            continue
        ctype = (f.get("type") or f.get("contentType") or "").lower()
        if ctype.startswith("image/"):
            return f.get("url") or f.get("thumbnailUrl")
    return None

def masto_score(s):
    fav = int(s.get("favourites_count", 0))
    rebs = int(s.get("reblogs_count", 0))
    reps = int(s.get("replies_count", 0))
    return fav + rebs*2 + reps

def misskey_score(n):
    rn = int(n.get("renoteCount", 0))
    rp = int(n.get("repliesCount", 0))
    reacts = n.get("reactions") or {}
    rsum = 0
    for v in reacts.values():
        try: rsum += int(v)
        except: pass
    return rsum + rn*2 + rp

def is_safe_masto(s):
    if s.get("sensitive") is True: return False
    if text_has_nsfw(s.get("spoiler_text")): return False
    if any(is_nsfw_tag(t.get("name")) for t in (s.get("tags") or [])): return False
    return True

def is_safe_misskey(n):
    if n.get("cw") and text_has_nsfw(n.get("cw")): return False
    if text_has_nsfw(n.get("text")): return False
    return True

# ---------- download, hash, upload ----------
def download_image(url):
    r = SESSION.get(url, timeout=TIMEOUT, stream=True, allow_redirects=True)
    r.raise_for_status()
    content = r.content  # small enough for this use-case
    ctype = (r.headers.get("Content-Type") or "").split(";")[0].strip().lower()
    sha = hashlib.sha256(content).hexdigest()
    return content, ctype, sha

def upload_bytes_to_drive(content_bytes, filename, folder_id, content_type):
    # /api/drive/files/create (multipart)
    data = {"i": SHARKEY_TOKEN, "folderId": folder_id, "name": filename}
    if not content_type:
        content_type = "application/octet-stream"
    files = {"file": (filename, BytesIO(content_bytes), content_type)}
    up = SESSION.post(f"{SHARKEY_BASE}/api/drive/files/create", data=data, files=files, timeout=TIMEOUT)
    try:
        up.raise_for_status()
    except requests.HTTPError as e:
        snippet = (up.text or "")[:300].replace("\n", " ")
        raise RuntimeError(f"drive/files/create HTTP {up.status_code}: {snippet}") from e
    try:
        return up.json()
    except json.JSONDecodeError:
        raise RuntimeError("drive/files/create returned non-JSON")

def update_file(file_id, name=None, folder_id=None):
    payload = {"fileId": file_id}
    if name: payload["name"] = name
    if folder_id: payload["folderId"] = folder_id
    return mk_api("drive/files/update", payload)

# ---------- main ----------
def main():
    if not SHARKEY_BASE or not SHARKEY_TOKEN:
        die("Set SHARKEY_BASE and SHARKEY_TOKEN in .env")

    tags = [t.lstrip("#").lower() for t in read_lines("selected_tags.txt")]
    domains = [d.lower() for d in read_lines("bubble_domains.txt")]
    if not tags: die("selected_tags.txt is empty")
    if not domains: die("bubble_domains.txt is empty")

    # Prove Drive works
    _ = mk_api("drive/folders", {})

    folder_id = ensure_folder(AD_FOLDER)
    today = date.today().isoformat()
    idx = load_index()
    results = []

    for tag in tags:
        print(f"\n[tag] #{tag}")
        safe_tag = sanitize_tag_for_filename(tag)

        # collect candidates across servers
        posts = {}  # key -> {appearances, best_score, image_url, origin_domain}
        for domain in domains:
            stack = detect_stack(domain)
            print(f"  - probing {domain} ({stack}) …")
            if stack == "mastodon":
                for s in fetch_masto_tag_timeline(domain, tag, limit=STATUS_SCAN_LIMIT):
                    if not s or not is_safe_masto(s): continue
                    img = pick_image_from_masto_status(s)
                    if not img: continue
                    key = masto_status_key(s, domain)
                    score = masto_score(s)
                    origin = urlparse(s.get("url") or "").netloc or domain
                    e = posts.get(key, {"appearances":0, "best_score":-1, "image_url":img, "origin_domain":origin})
                    e["appearances"] += 1
                    if score > e["best_score"]:
                        e["best_score"] = score
                        e["image_url"] = img
                        e["origin_domain"] = origin
                    posts[key] = e
            elif stack == "misskey":
                for n in fetch_misskey_tag_timeline(domain, tag, limit=STATUS_SCAN_LIMIT):
                    if not n or not is_safe_misskey(n): continue
                    img = pick_image_from_misskey_note(n)
                    if not img: continue
                    key = misskey_note_key(n, domain)
                    score = misskey_score(n)
                    origin = urlparse(n.get("url") or "").netloc or domain
                    e = posts.get(key, {"appearances":0, "best_score":-1, "image_url":img, "origin_domain":origin})
                    e["appearances"] += 1
                    if score > e["best_score"]:
                        e["best_score"] = score
                        e["image_url"] = img
                        e["origin_domain"] = origin
                    posts[key] = e
            else:
                print(f"    [skip] unknown stack")

        if not posts:
            print(f"  [warn] no candidates found for #{tag}")
            continue

        # consensus first, then popularity
        chosen = sorted(posts.values(), key=lambda e: (e["appearances"], e["best_score"]), reverse=True)[0]
        if chosen["appearances"] < 2:
            chosen = max(posts.values(), key=lambda e: e["best_score"])

        img_url = chosen["image_url"]
        origin = chosen["origin_domain"].replace("/", "")

        # download → hash → dedupe
        try:
            content, ctype, sha = download_image(img_url)
        except requests.RequestException as e:
            print(f"    [warn] download failed: {e}")
            continue

        ext = guess_ext_from_bytes_or_url(ctype, img_url)
        filename = f"{today}_{safe_tag}_{origin}{ext}"

        # dedupe by hash
        existing = idx["by_hash"].get(sha)
        if existing:
            file_id = existing["fileId"]
            # Ensure it sits in our folder, and optionally rename
            try:
                if DEDUP_MODE == "rename":
                    update_file(file_id, name=filename, folder_id=folder_id)
                    current_name = filename
                else:
                    # reuse: ensure folder, keep original name
                    update_file(file_id, folder_id=folder_id)
                    current_name = existing.get("filename") or filename
                print(f"    [reuse] matched existing file (sha={sha[:10]}…). Using {current_name}")
                results.append({
                    "tag": tag,
                    "origin": origin,
                    "image_source": img_url,
                    "drive_file_id": file_id,
                    "drive_url": existing.get("url"),
                    "filename": current_name,
                    "appearances": chosen["appearances"],
                    "score": chosen["best_score"],
                    "dedup": True
                })
                continue
            except Exception as e:
                print(f"    [warn] reuse/update failed, will re-upload: {e}")

        # new upload
        try:
            up = upload_bytes_to_drive(content, filename, folder_id, ctype)
            file_id = up.get("id")
            final_url = up.get("url") or f"{SHARKEY_BASE}/files/{file_id}"
            print(f"    [ok] uploaded -> {filename}")
            # index it
            idx["by_hash"][sha] = {"fileId": file_id, "filename": filename, "url": final_url}
            results.append({
                "tag": tag,
                "origin": origin,
                "image_source": img_url,
                "drive_file_id": file_id,
                "drive_url": final_url,
                "filename": filename,
                "appearances": chosen["appearances"],
                "score": chosen["best_score"],
                "dedup": False
            })
            save_index(idx)
        except Exception as e:
            print(f"    [warn] upload failed: {e}")
            continue

    MANIFEST_PATH.write_text(
        json.dumps({"generated_at": int(__import__('time').time()), "results": results}, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    print("\n[done] wrote ads_uploads_manifest.json and updated ads_dedupe_index.json")

if __name__ == "__main__":
    main()

