# sharkey_hashtag_trends_ads

Pull trending hashtags from a FediBuzz (Mastodon-compatible) API, pick a safe image for each,
upload to a Sharkey/Misskey Drive folder, and create/update an advertisement linking to the local tag page.

## Setup
1) `python -m venv .venv && source .venv/bin/activate`
2) `pip install -r requirements.txt`
3) Copy `.env.example` to `.env` and set values.

## Run
# one-off (all three buckets: now, daily, weekly)
python app.py

# just one bucket
python app.py --freq now
python app.py --freq daily
python app.py --freq weekly
