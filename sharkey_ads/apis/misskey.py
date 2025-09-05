from mastodon import Mastodon

TIMEOUT = 15
USER_AGENT = "SeedTrends/1.1 (+https://mypocketpals.online)"

def _client(domain):
    """Return a Mastodon API client for the given Misskey/Sharkey domain."""
    return Mastodon(api_base_url=f"https://{domain}",
                    request_timeout=TIMEOUT,
                    user_agent=USER_AGENT)

def _api(client, method, endpoint, params=None, json=False):
    """Helper to perform API requests via Mastodon.py."""
    try:
        return client._Mastodon__api_request(method, endpoint,
                                             params=params or {},
                                             use_json=json)
    except Exception:
        return None

def get_trends(domain, limit=20):
    """Return [(tag, score), ...] for Misskey/Sharkey instance."""
    client = _client(domain)
    data = _api(client, "GET", "/api/hashtags/trend") or \
           _api(client, "POST", "/api/hashtags/trend",
                params={"limit": limit}, json=True)
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
    client = _client(domain)
    base = "/api"
    data = _api(client, "POST", f"{base}/notes/search-by-tag",
                params={"tag": tag, "limit": limit}, json=True)
    if data is None:
        data = _api(client, "POST", f"{base}/notes/search",
                    params={"query": f"#{tag}", "limit": limit}, json=True)
    return data or []

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
