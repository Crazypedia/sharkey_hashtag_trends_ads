from mastodon import Mastodon
from urllib.parse import quote

TIMEOUT = 15
USER_AGENT = "BubbleTrends/1.1 (+https://mypocketpals.online)"

def _client(domain):
    """Return a Mastodon API client for the given domain."""
    return Mastodon(api_base_url=f"https://{domain}",
                    request_timeout=TIMEOUT,
                    user_agent=USER_AGENT)

def get_trends(domain, limit=20):
    """Return [(tag, score), ...] for Mastodon instance."""
    masto = _client(domain)
    try:
        data = masto.trending_tags(limit=limit)
    except Exception:
        data = []
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
    masto = _client(domain)
    try:
        return masto.timeline_hashtag(safe, limit=limit) or []
    except Exception:
        return []

def pick_image(post):
    """Return (url, alt_text) for first image attachment in status."""
    for a in (post.get("media_attachments") or []):
        if (a.get("type") or "").lower() == "image":
            url = a.get("remote_url") or a.get("url") or a.get("preview_url")
            alt = a.get("description") or ""
            if url:
                return url, alt
    return None, None
