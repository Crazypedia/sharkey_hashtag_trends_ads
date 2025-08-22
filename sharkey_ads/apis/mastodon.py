import requests
from urllib.parse import quote

TIMEOUT = 15
HEADERS = {"User-Agent": "BubbleTrends/1.1 (+https://mypocketpals.online)"}

def _get_json(url, params=None):
    try:
        r = requests.get(url, headers=HEADERS, params=params or {}, timeout=TIMEOUT)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None

def get_trends(domain, limit=20):
    """Return [(tag, score), ...] for Mastodon instance."""
    url = f"https://{domain}/api/v1/trends/tags"
    data = _get_json(url, params={"limit": limit})
    tags = []
    if isinstance(data, list):
        for item in data:
            name = (item.get("name") or "").strip()
            score = 0
            for h in (item.get("history") or []):
                try:
                    score += int(h.get("uses", 0))
                except Exception:
                    pass
            if not score:
                score = 1
            if name:
                tags.append((name, score))
    return tags

def tag_timeline(domain, tag, limit=40):
    """Return list of statuses for a hashtag."""
    safe = quote(tag.lstrip("#"), safe="")
    url = f"https://{domain}/api/v1/timelines/tag/{safe}"
    return _get_json(url, params={"limit": limit}) or []

def pick_image(post):
    """Return (url, alt_text) for first image attachment in status."""
    for a in (post.get("media_attachments") or []):
        if (a.get("type") or "").lower() == "image":
            url = a.get("remote_url") or a.get("url") or a.get("preview_url")
            alt = a.get("description") or ""
            if url:
                return url, alt
    return None, None
