import os
import json
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from typing import Dict, Iterable, List, Tuple

from .bubble_trends import load_domains, fetch_domain_tags
from .ads_stage_uploads import main as upload_main, is_nsfw_tag
from .ad_stage_create_ad import main as create_ad_main


def prompt_domains(path: Path) -> List[str]:
    """Load the seed list from *path* and let the user add/remove domains."""

    domains = load_domains(str(path))
    print("Current seed list:")
    for d in domains:
        print(f" - {d}")
    add = input("Add domains (comma separated, blank to skip): ").strip()
    if add:
        for d in add.split(","):
            d = d.strip().lower()
            if d and d not in domains:
                domains.append(d)
    remove = input("Remove domains (comma separated, blank to skip): ").strip()
    if remove:
        for d in remove.split(","):
            d = d.strip().lower()
            if d in domains:
                domains.remove(d)
    print("\nUsing seed list:")
    for d in domains:
        print(f" - {d}")
    if input("Proceed? [y/N]: ").strip().lower() != "y":
        print("Aborted.")
        raise SystemExit(1)
    path.write_text("\n".join(domains) + "\n", encoding="utf-8")
    return domains


def fetch_and_merge(domains: Iterable[str], limit: int = 40) -> Tuple[List[Tuple[str, int]], Dict[str, List[Tuple[str, int]]]]:
    """Fetch trending tags for each domain and merge them, filtering NSFW tags."""

    domain_list = list(domains)
    totals: Dict[str, int] = defaultdict(int)
    per_domain: Dict[str, List[Tuple[str, int]]] = {}
    max_workers = min(8, max(1, len(domain_list)))
    with ThreadPoolExecutor(max_workers=max_workers) as exe:
        futs = [exe.submit(fetch_domain_tags, d, limit) for d in domain_list]
        for fut in as_completed(futs):
            d, tags = fut.result()
            per_domain[d] = tags
            for name, score in tags:
                norm = name.lstrip("#").lower()
                if not norm or is_nsfw_tag(norm):
                    continue
                totals[norm] += int(score)
    merged = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)
    return merged, per_domain


def main() -> None:
    """Run the interactive pipeline from seed list to ad creation."""

    base = Path(__file__).resolve().parents[1]
    domains_path = base / "trendy_domains.txt"
    domains = prompt_domains(domains_path)

    merged, per_domain = fetch_and_merge(domains)
    print("\n=== Seed list trending (merged) ===")
    for i, (tag, score) in enumerate(merged[:100], 1):
        print(f"{i:2}. #{tag}  — score {score}")

    try:
        n = int(input("How many hashtags to select? ").strip() or "10")
    except ValueError:
        n = 10
    selected = [t for t, _ in merged[:n]]

    # Save results for downstream stages
    (base / "selected_tags.txt").write_text("\n".join(selected) + "\n", encoding="utf-8")
    trends_data = {
        "generated_at": int(time.time()),
        "domains": domains,
        "per_domain": {
            d: [{"tag": t, "score": s} for t, s in per_domain.get(d, [])]
            for d in domains
        },
        "merged": [{"tag": t, "score": s} for t, s in merged],
        "selected": [{"tag": t} for t in selected],
    }
    with open(base / "bubble_trends.json", "w", encoding="utf-8") as f:
        json.dump(trends_data, f, ensure_ascii=False, indent=2)

    duration_in = input("Ad duration in days (default 3): ").strip()
    try:
        duration = int(duration_in) if duration_in else 3
    except ValueError:
        duration = 3
    os.environ["AD_DURATION_DAYS"] = str(duration)

    print("\n[stage] Uploading images…")
    upload_main()
    print("\n[stage] Creating ads…")
    create_ad_main()


if __name__ == "__main__":
    main()
