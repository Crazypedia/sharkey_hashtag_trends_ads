import argparse
from .apis import mastodon as mastodon_api, misskey as misskey_api

def main():
    ap = argparse.ArgumentParser(description="Fetch trending tags from a domain")
    sub = ap.add_subparsers(dest="stack", required=True)

    p_masto = sub.add_parser("mastodon", help="Fetch Mastodon trends")
    p_masto.add_argument("domain")
    p_masto.add_argument("--limit", type=int, default=20)

    p_miss = sub.add_parser("misskey", help="Fetch Misskey/Sharkey trends")
    p_miss.add_argument("domain")
    p_miss.add_argument("--limit", type=int, default=20)

    args = ap.parse_args()
    if args.stack == "mastodon":
        tags = mastodon_api.get_trends(args.domain, args.limit)
    else:
        tags = misskey_api.get_trends(args.domain, args.limit)

    for name, score in tags:
        print(f"{name}\t{score}")

if __name__ == "__main__":
    main()
