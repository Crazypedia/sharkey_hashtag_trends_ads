# bubble_trends.py
# Aggregate trending hashtags across your seed list servers and pick a subset for the next step.
# Usage:
#   1) Create trendy_domains.txt with one domain per line (e.g. mastodon.social, misskey.io)
#   2) python -m sharkey_ads.bubble_trends --select 12
#      or: python -m sharkey_ads.bubble_trends --interactive

import argparse
import json, os, sys, time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

from .apis import mastodon as mastodon_api, misskey as misskey_api

def load_domains(path="trendy_domains.txt"):
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

def guess_stack(domain):
    # Probe Mastodon first (public), then Misskey.
    m = mastodon_api.get_trends(domain, limit=1)
    if m:
        return "mastodon"
    ms = misskey_api.get_trends(domain, limit=1)
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

def fetch_domain_tags(domain, limit):
    """Detect server type and fetch trending tags for a single domain."""
    try:
        print(f"[info] {domain}")
        stack = guess_stack(domain)
        if stack == "mastodon":
            tags = mastodon_api.get_trends(domain, limit=limit)
        elif stack == "misskey":
            tags = misskey_api.get_trends(domain, limit=limit)
        else:
            print(f"[warn] {domain}: could not detect a supported API; skipping.")
            tags = []
    except Exception as e:
        print(f"[error] {domain}: {e}")
        tags = []
    return domain, tags

def main():
    ap = argparse.ArgumentParser(description="Merge trending tags across seed list servers and select a subset.")
    ap.add_argument("--domains-file", default="trendy_domains.txt", help="Path to trendy domains list")
    ap.add_argument("--limit-per-domain", type=int, default=40, help="Fetch up to this many tags per domain")
    ap.add_argument("--select", type=int, default=10, help="Automatically pick top N merged tags")
    ap.add_argument("--interactive", action="store_true", help="Interactively choose tags by index ranges")
    args = ap.parse_args()

    domains = load_domains(args.domains_file)
    aggregate = defaultdict(int)
    per_domain = {}

    with ThreadPoolExecutor(max_workers=min(8, len(domains) or 1)) as exe:
        futures = [exe.submit(fetch_domain_tags, d, args.limit_per_domain) for d in domains]
        for fut in as_completed(futures):
            d, tags = fut.result()
            per_domain[d] = tags
            for name, score in tags:
                norm = name.lstrip("#").lower()
                aggregate[norm] += int(score)

    merged = sorted(aggregate.items(), key=lambda kv: kv[1], reverse=True)

    # Print a preview
    print("\n=== Seed list trending (merged) ===")
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

