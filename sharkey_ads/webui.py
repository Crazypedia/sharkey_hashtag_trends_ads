from pathlib import Path
from typing import List

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .apis import mastodon as mastodon_api, misskey as misskey_api

app = FastAPI(title="Sharkey Ads Admin")

BASE_PATH = Path(__file__).parent
templates = Jinja2Templates(directory=str(BASE_PATH / "templates"))
app.mount("/static", StaticFiles(directory=str(BASE_PATH / "static")), name="static")


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse(
        "index.html", {"request": request, "images": [], "error": None}
    )


@app.post("/fetch", response_class=HTMLResponse)
async def fetch_images(
    request: Request,
    stack: str = Form(...),
    domain: str = Form(...),
    tag: str = Form(...),
    limit: int = Form(40),
):
    images: List[dict] = []
    error = None
    try:
        if stack == "mastodon":
            posts = mastodon_api.tag_timeline(domain, tag, limit)
            for p in posts:
                url, alt = mastodon_api.pick_image(p)
                if url:
                    images.append({"url": url, "alt": alt})
        else:
            posts = misskey_api.tag_timeline(domain, tag, limit)
            for n in posts:
                url, alt = misskey_api.pick_image(n)
                if url:
                    images.append({"url": url, "alt": alt})
    except Exception as exc:  # pragma: no cover - network errors
        error = str(exc)

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "images": images,
            "error": error,
            "stack": stack,
            "domain": domain,
            "tag": tag,
            "limit": limit,
        },
    )


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    uvicorn.run("sharkey_ads.webui:app", host="0.0.0.0", port=8000, reload=False)
