"""
ad_stage_create_ad.py
Version: 0.2.0-beta.2
"""

import json

def create_ads_from_manifest(manifest_path, output_path):
    """
    Reads the uploads manifest and constructs ad payloads including image alt text.
    """
    with open(manifest_path, 'r') as f:
        manifest = json.load(f)
    uploads = manifest.get("results", [])

    ads = []
    for r in uploads:
        title = r.get("tag", "Untitled")
        memo = r.get("origin", "")
        url = r.get("drive_url", "")
        priority_val = r.get("priority", 0)
        base = {
            "title": title,
            "memo": memo,
            "imageUrl": r.get("drive_url"),
            "alt": r.get("image_alt", ""),  # pass through alt text
            "url": url,
            "priority": str(priority_val),
            "place": r.get("default_place", ""),
        }
        ads.append(base)

    with open(output_path, 'w') as f:
        json.dump({"ads": ads}, f, indent=2)

if __name__ == "__main__":
    import sys
    if len(sys.argv) != 3:
        print("Usage: python ad_stage_create_ad.py <manifest.json> <output_ads.json>")
    else:
        create_ads_from_manifest(sys.argv[1], sys.argv[2])
