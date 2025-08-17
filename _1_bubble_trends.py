# bubble_trends.py
# Aggregate trending hashtags across your bubble servers and pick a subset for the next step.
# Usage:
#   1) Create bubble_domains.txt with one domain per line (e.g. mastodon.social, misskey.io)
#   2) python3 bubble_trends.py --select 12
#      or: python3 bubble_trends.py --interactive

import argparse
import json, os, sys, time
from collections import defaultdict

import requests

TIMEOUT = 15
HEADERS = {"User-Agent": "BubbleTrends/1.1 (+https://mypocketpals.online)"}

def load_domains(path="bubble_domains.txt"):
    if not os.path.exists(path):
        print(f"[error] {path} not found. Create it with one domain per line.", file=sys.stderr)
        sys.exit(1)
    out = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            d = line.strip().lower()
            if d and not d.startswith("#"):
                out.append(d)
    return out

def get_json(url, method="GET", json_body=None):
    try:
        if method == "GET":
            r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        else:
            r = requests.post(url, headers={"Content-Type":"application/json", **HEADERS},
                              json=json_body or {}, timeout=TIMEOUT)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"[warn] {method} {url} failed: {e}")
        return None

def fetch_mastodon_trends(domain, limit=20):
    # https://docs.joinmastodon.org/methods/trends/
    url = f"https://{domain}/api/v1/trends/tags?limit={limit}"
    data = get_json(url, "GET")
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

def fetch_misskey_trends(domain, limit=20):
    # Misskey/Sharkey: /api/hashtags/trend (GET or POST JSON)
    base = f"https://{domain}/api/hashtags/trend"
    data = get_json(base, "GET") or get_json(base, "POST", {"limit": limit})
    tags = []
    if isinstance(data, list):
        for item in data:
            if isinstance(item, str):
                tags.append((item, 1))
            elif isinstance(item, dict):
                name = item.get("tag") or item.get("name") or item.get("hashtag")
                score = 0
                if "count" in item and isinstance(item["count"], int):
                    score = item["count"]
                elif "chart" in item and isinstance(item["chart"], list):
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

def guess_stack(domain):
    # Probe Mastodon first (public), then Misskey.
    m = fetch_mastodon_trends(domain, limit=1)
    if m:
        return "mastodon"
    ms = fetch_misskey_trends(domain, limit=1)
    if ms:
        return "misskey"
    return "unknown"

def parse_selection_ranges(spec: str, max_index: int):
    # spec like "1-3,7,10"
    chosen = set()
    parts = [p.strip() for p in spec.split(",") if p.strip()]
    for p in parts:
        if "-" in p:
            a, b = p.split("-", 1)
            try:
                start = int(a)
                end = int(b)
            except ValueError:
                continue
            if start > end:
                start, end = end, start
            for idx in range(start, end + 1):
                if 1 <= idx <= max_index:
                    chosen.add(idx)
        else:
            try:
                idx = int(p)
                if 1 <= idx <= max_index:
                    chosen.add(idx)
            except ValueError:
                continue
    return sorted(chosen)

def main():
    ap = argparse.ArgumentParser(description="Merge trending tags across bubble servers and select a subset.")
    ap.add_argument("--domains-file", default="bubble_domains.txt", help="Path to bubble domains list")
    ap.add_argument("--limit-per-domain", type=int, default=40, help="Fetch up to this many tags per domain")
    ap.add_argument("--select", type=int, default=10, help="Automatically pick top N merged tags")
    ap.add_argument("--interactive", action="store_true", help="Interactively choose tags by index ranges")
    args = ap.parse_args()

    domains = load_domains(args.domains_file)
    aggregate = defaultdict(int)
    per_domain = {}

    for d in domains:
        print(f"[info] {d}")
        stack = guess_stack(d)
        if stack == "mastodon":
            tags = fetch_mastodon_trends(d, limit=args.limit_per_domain)
        elif stack == "misskey":
            tags = fetch_misskey_trends(d, limit=args.limit_per_domain)
        else:
            print(f"[warn] {d}: could not detect a supported API; skipping.")
            tags = []
        per_domain[d] = tags
        for name, score in tags:
            norm = name.lstrip("#").lower()
            aggregate[norm] += int(score)

    merged = sorted(aggregate.items(), key=lambda kv: kv[1], reverse=True)

    # Print a preview
    print("\n=== Bubble-wide trending (merged) ===")
    for i, (tag, score) in enumerate(merged[:100], 1):
        print(f"{i:2}. #{tag}  — score {score}")

    # Selection step
    selected = []
    if args.interactive and merged:
        max_index = len(merged)
        print("\nSelect tags by index ranges (e.g., 1-5,8,12). Press Enter to accept top N.")
        user = input(f"Your selection (N={args.select} by default): ").strip()
        if user:
            idxs = parse_selection_ranges(user, max_index)
            for idx in idxs:
                selected.append(merged[idx-1][0])
        else:
            selected = [t for t, _ in merged[:args.select]]
    else:
        selected = [t for t, _ in merged[:args.select]]

    print("\n=== Selected tags ===")
    for i, tag in enumerate(selected, 1):
        print(f"{i:2}. #{tag}")

    # Save outputs
    out = {
        "generated_at": int(time.time()),
        "domains": domains,
        "per_domain": {d: [{"tag": t, "score": s} for t, s in per_domain.get(d, [])] for d in domains},
        "merged": [{"tag": t, "score": s} for t, s in merged],
        "selected": [{"tag": t} for t in selected]
    }
    with open("bubble_trends.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    with open("selected_tags.txt", "w", encoding="utf-8") as f:
        for t in selected:
            f.write(f"{t}\n")

    print("\n[done] wrote bubble_trends.json and selected_tags.txt")

if __name__ == "__main__":
    main()

