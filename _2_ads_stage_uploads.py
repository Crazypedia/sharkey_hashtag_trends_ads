"""
ads_stage_uploads.py
Version: 0.2.0-beta.2
"""

def pick_image_from_masto_status(s):
    """
    Select image URL and alt text from a Mastodon status object.
    """
    for a in (s.get("media_attachments") or []):
        if (a.get("type") or "").lower() == "image":
            url = a.get("remote_url") or a.get("url") or a.get("preview_url")
            alt = a.get("description") or ""  # Mastodon alt text
            return url, alt
    return None, ""

def pick_image_from_misskey_note(n):
    """
    Select image URL and alt text from a Misskey note object.
    """
    for f in (n.get("files") or []):
        if f.get("isSensitive") is True:
            continue
        ctype = (f.get("type") or f.get("contentType") or "").lower()
        if ctype.startswith("image/"):
            url = f.get("url") or f.get("thumbnailUrl")
            alt = f.get("metadata", {}).get("description") or ""
            return url, alt
    return None, ""

def build_manifest_results(candidates):
    """
    Build manifest entries including alt text field.
    """
    results = []
    for chosen in candidates:
        tag = chosen.get("tag")
        origin = chosen.get("origin")
        img_url = chosen.get("image_url")
        alt_text = chosen.get("alt_text", "")
        results.append({
            "tag": tag,
            "origin": origin,
            "image_source": img_url,
            "image_alt": alt_text,
        })
    return results
