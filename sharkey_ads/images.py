import argparse
from .apis import mastodon as mastodon_api, misskey as misskey_api

def main():
    ap = argparse.ArgumentParser(description="Fetch images from tag timelines")
    sub = ap.add_subparsers(dest="stack", required=True)

    p_masto = sub.add_parser("mastodon", help="Scan Mastodon hashtag timeline")
    p_masto.add_argument("domain")
    p_masto.add_argument("tag")
    p_masto.add_argument("--limit", type=int, default=40)

    p_miss = sub.add_parser("misskey", help="Scan Misskey/Sharkey hashtag timeline")
    p_miss.add_argument("domain")
    p_miss.add_argument("tag")
    p_miss.add_argument("--limit", type=int, default=40)

    args = ap.parse_args()
    if args.stack == "mastodon":
        posts = mastodon_api.tag_timeline(args.domain, args.tag, args.limit)
        for p in posts:
            url, alt = mastodon_api.pick_image(p)
            if url:
                print(f"{url}\t{alt or ''}")
    else:
        posts = misskey_api.tag_timeline(args.domain, args.tag, args.limit)
        for n in posts:
            url, alt = misskey_api.pick_image(n)
            if url:
                print(f"{url}\t{alt or ''}")

if __name__ == "__main__":
    main()
