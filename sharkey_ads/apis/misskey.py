import requests

TIMEOUT = 15
HEADERS = {"User-Agent": "BubbleTrends/1.1 (+https://mypocketpals.online)"}

def _get_json(url, method="GET", json_body=None):
    try:
        if method == "GET":
            r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        else:
            r = requests.post(url, headers={"Content-Type":"application/json", **HEADERS},
                              json=json_body or {}, timeout=TIMEOUT)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None

def get_trends(domain, limit=20):
    """Return [(tag, score), ...] for Misskey/Sharkey instance."""
    base = f"https://{domain}/api/hashtags/trend"
    data = _get_json(base, "GET") or _get_json(base, "POST", {"limit": limit})
    tags = []
    if isinstance(data, list):
        for item in data:
            if isinstance(item, str):
                tags.append((item, 1))
            elif isinstance(item, dict):
                name = item.get("tag") or item.get("name") or item.get("hashtag")
                score = 0
                if isinstance(item.get("count"), int):
                    score = item["count"]
                elif isinstance(item.get("chart"), list):
                    for v in item["chart"]:
                        try:
                            score += int(v)
                        except Exception:
                            pass
                if not score:
                    score = 1
                if name:
                    tags.append((name, score))
    return tags

def tag_timeline(domain, tag, limit=40):
    """Return list of notes for a hashtag."""
    base = f"https://{domain}/api"
    try:
        r = requests.post(f"{base}/notes/search-by-tag",
                         json={"tag": tag, "limit": limit},
                         headers=HEADERS, timeout=TIMEOUT)
        if r.status_code == 200:
            return r.json() or []
    except Exception:
        pass
    try:
        r = requests.post(f"{base}/notes/search",
                         json={"query": f"#{tag}", "limit": limit},
                         headers=HEADERS, timeout=TIMEOUT)
        if r.status_code == 200:
            return r.json() or []
    except Exception:
        pass
    return []

def pick_image(post):
    """Return (url, alt_text) for first safe image file in note."""
    for f in (post.get("files") or []):
        if f.get("isSensitive") is True:
            continue
        ctype = (f.get("type") or f.get("contentType") or "").lower()
        if ctype.startswith("image/"):
            url = f.get("url") or f.get("thumbnailUrl")
            alt = f.get("comment") or f.get("name") or ""
            if url:
                return url, alt
    return None, None
