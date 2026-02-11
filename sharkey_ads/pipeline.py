import os
import json
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .bubble_trends import load_domains, fetch_domain_tags
from .ads_stage_uploads import main as upload_main, is_nsfw_tag
from .ad_stage_create_ad import main as create_ad_main


def prompt_domains(path: str) -> list:
    domains = load_domains(path)
    print("Current domains:")
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
    print("\nUsing domains:")
    for d in domains:
        print(f" - {d}")
    if input("Proceed? [y/N]: ").strip().lower() != "y":
        print("Aborted.")
        raise SystemExit(1)
    with open(path, "w", encoding="utf-8") as f:
        for d in domains:
            f.write(d + "\n")
    return domains


def fetch_and_merge(domains, limit=40):
    # Deduplicate domains
    domains = list(dict.fromkeys(domains))
    aggregate = defaultdict(int)
    per_domain = {}
    failed = []
    with ThreadPoolExecutor(max_workers=min(8, len(domains) or 1)) as exe:
        futs = {exe.submit(fetch_domain_tags, d, limit): d for d in domains}
        for fut in as_completed(futs):
            domain_name = futs[fut]
            try:
                d, tags = fut.result()
            except Exception as e:
                print(f"[error] {domain_name}: {e}")
                failed.append(domain_name)
                per_domain[domain_name] = []
                continue
            per_domain[d] = tags
            for name, score in tags:
                norm = name.lstrip("#").lower()
                if not norm or is_nsfw_tag(norm):
                    continue
                aggregate[norm] += int(score)
    if failed:
        print(f"[warn] {len(failed)} domain(s) failed: {', '.join(failed)}")
    merged = sorted(aggregate.items(), key=lambda kv: kv[1], reverse=True)
    return merged, per_domain


def main():
    base = Path(__file__).resolve().parents[1]
    domains_path = base / "trendy_domains.txt"
    domains = prompt_domains(str(domains_path))

    merged, per_domain = fetch_and_merge(domains)
    print("\n=== Bubble-wide trending (merged) ===")
    for i, (tag, score) in enumerate(merged[:100], 1):
        print(f"{i:2}. #{tag}  — score {score}")

    try:
        n = int(input("How many hashtags to select? ").strip() or "10")
    except ValueError:
        n = 10
    selected = [t for t, _ in merged[:n]]

    # Save outputs for downstream stages
    (base / "selected_tags.txt").write_text("\n".join(selected) + "\n", encoding="utf-8")
    bubble = {
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
        json.dump(bubble, f, ensure_ascii=False, indent=2)

    duration_in = input("Ad duration in days (default 3): ").strip()
    try:
        duration = int(duration_in) if duration_in else 3
    except ValueError:
        duration = 3
    os.environ["AD_DURATION_DAYS"] = str(duration)

    stage_errors = []

    print("\n[stage] Uploading images…")
    try:
        upload_main()
    except SystemExit:
        print("[error] upload stage exited early — check logs above")
        stage_errors.append("uploads")
    except Exception as e:
        print(f"[error] upload stage failed: {e}")
        stage_errors.append("uploads")

    print("\n[stage] Creating ads…")
    try:
        create_ad_main()
    except SystemExit:
        print("[error] ad creation stage exited early — check logs above")
        stage_errors.append("ad_create")
    except Exception as e:
        print(f"[error] ad creation stage failed: {e}")
        stage_errors.append("ad_create")

    if stage_errors:
        print(f"\n[warn] pipeline completed with errors in: {', '.join(stage_errors)}")
    else:
        print("\n[done] pipeline completed successfully")


if __name__ == "__main__":
    main()
