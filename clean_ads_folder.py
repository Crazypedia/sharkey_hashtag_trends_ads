import os
import sys
import json
from pathlib import Path
import requests
from dotenv import load_dotenv

# Load .env from this project folder
load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")

SHARKEY_BASE = (os.getenv("SHARKEY_BASE") or "").rstrip("/")
SHARKEY_TOKEN = (os.getenv("SHARKEY_TOKEN") or "").strip()
AD_FOLDER = os.getenv("AD_FOLDER", "Advertisements")
TIMEOUT = int(os.getenv("HTTP_TIMEOUT", "25"))

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "AdsFolderCleaner/1.2"})

def die(msg, code=1):
    print(f"[fatal] {msg}", file=sys.stderr); sys.exit(code)

def post_api(path: str, payload: dict, *, expect_json: bool = True):
    """POST to Misskey/Sharkey. If expect_json=False, accept empty/non-JSON 2xx bodies."""
    if not SHARKEY_BASE or not SHARKEY_TOKEN:
        die("Set SHARKEY_BASE and SHARKEY_TOKEN in .env")
    url = f"{SHARKEY_BASE}/api/{path.lstrip('/')}"
    data = dict(payload or {}); data["i"] = SHARKEY_TOKEN
    r = SESSION.post(url, json=data, timeout=TIMEOUT)
    try:
        r.raise_for_status()
    except requests.HTTPError:
        snippet = (r.text or "")[:300].replace("\n", " ")
        die(f"{path} HTTP {r.status_code}: {snippet}")
    if expect_json:
        try:
            return r.json()
        except json.JSONDecodeError:
            snippet = (r.text or "")[:300].replace("\n", " ")
            die(f"{path} returned non-JSON: {snippet}")
    else:
        # 204/no-content is fine
        try:
            return r.json()
        except Exception:
            return {}

def ensure_folder(name: str) -> str:
    """Find folder by name; create if missing; return folderId."""
    # List top-level folders
    lst = post_api("drive/folders", {}, expect_json=True) or []
    for f in lst:
        if f and f.get("name") == name:
            return f.get("id")
    # Create if not found
    created = post_api("drive/folders/create", {"name": name}, expect_json=True)
    fid = created.get("id")
    if not fid:
        die(f"Failed to create Drive folder '{name}'")
    print(f"[info] Created Drive folder '{name}' (id={fid})")
    return fid

def list_files_in_folder(folder_id: str, page_size: int = 100) -> list:
    files = []
    until_id = None
    while True:
        payload = {"folderId": folder_id, "limit": page_size}
        if until_id:
            payload["untilId"] = until_id
        batch = post_api("drive/files", payload, expect_json=True)
        if not batch:
            break
        files.extend(batch)
        if len(batch) < page_size:
            break
        until_id = batch[-1]["id"]
    return files

def delete_file(file_id: str):
    post_api("drive/files/delete", {"fileId": file_id}, expect_json=False)

def main():
    confirm = (
        "yes" if (len(sys.argv) > 1 and sys.argv[1] in {"-y", "--yes", "--force"})
        else input(f"This will DELETE all files in '{AD_FOLDER}'. Type 'yes' to continue: ").strip().lower()
    )
    if confirm != "yes":
        print("[info] Aborted."); return

    folder_id = ensure_folder(AD_FOLDER)  # create if missing

    files = list_files_in_folder(folder_id)
    if not files:
        print(f"[info] '{AD_FOLDER}' exists and is empty.")
        return

    print(f"[info] Deleting {len(files)} file(s) from '{AD_FOLDER}' …")
    deleted = 0
    for f in files:
        try:
            delete_file(f["id"])
            deleted += 1
        except Exception as e:
            print(f"[warn] failed to delete {f.get('name') or f.get('id')}: {e}")

    print(f"[done] Deleted {deleted}/{len(files)} files from '{AD_FOLDER}'.")

if __name__ == "__main__":
    main()
