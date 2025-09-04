from sharkey_ads.apis import mastodon, misskey

def test_mastodon_pick_image():
    post = {
        "media_attachments": [
            {"type": "image", "url": "https://example/image.png", "description": "alt"},
            {"type": "video"},
        ]
    }
    assert mastodon.pick_image(post) == ("https://example/image.png", "alt")

def test_misskey_pick_image_skips_sensitive():
    post = {
        "files": [
            {"isSensitive": True, "type": "image/png", "url": "https://example/skip.png"},
            {
                "isSensitive": False,
                "type": "image/jpeg",
                "url": "https://example/use.jpg",
                "comment": "alt-text",
            },
        ]
    }
    assert misskey.pick_image(post) == ("https://example/use.jpg", "alt-text")
