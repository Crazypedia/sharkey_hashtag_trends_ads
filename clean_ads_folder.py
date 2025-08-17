# replace this block in ads_stage_create_ads.py
#   (search for: payload = { "title": title, "memo": memo, ... })
payload = {
    "title": title,
    "memo": memo,
    "imageUrl": image_url,
    "url": target_url,           # <-- was "targetUrl"; use "url"
    "priority": priority
}
if schema["ratio"] and ratio is not None:
    payload["ratio"] = ratio

# dates if supported (we only set them if your instance surfaced keys via list)
if schema["start_key"]:
    payload[schema["start_key"]] = to_iso8601(now)
if schema["end_key"]:
    payload[schema["end_key"]] = to_iso8601(new_end)

