"""Probe: capture API auth + sample responses from the EarlyON SPA."""
from __future__ import annotations

import json
import re
from pathlib import Path

from playwright.sync_api import sync_playwright

URL = "https://www.missioninc.com/cso/york/en-ca/earlyon/calendar?ho_id_num=163"
API_HOST = "www.missioninc.com/OccmsApi/York"

OUT = Path("tmp_probe")
OUT.mkdir(exist_ok=True)


def safe_name(url: str) -> str:
    path = url.split("?", 1)[0].split("/OccmsApi/York/", 1)[-1]
    qs = url.split("?", 1)[1] if "?" in url else ""
    name = re.sub(r"[^a-zA-Z0-9._-]+", "_", path)[:120]
    if qs:
        name += "__" + re.sub(r"[^a-zA-Z0-9._-]+", "_", qs)[:80]
    return name + ".json"


def main() -> None:
    captured: dict[str, str] = {"token": ""}
    requests_log: list[dict] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context()
        page = ctx.new_page()

        def on_request(req):
            if API_HOST in req.url:
                auth = req.headers.get("authorization", "")
                if auth and not captured["token"]:
                    captured["token"] = auth
                requests_log.append({"method": req.method, "url": req.url, "auth": bool(auth)})

        def on_response(resp):
            if API_HOST not in resp.url:
                return
            try:
                ctype = resp.headers.get("content-type", "")
                if "json" not in ctype:
                    return
                body = resp.json()
            except Exception as e:  # noqa: BLE001
                print(f"  ! could not read body for {resp.url}: {e}")
                return
            fname = OUT / safe_name(resp.url)
            fname.write_text(json.dumps(body, indent=2, default=str))
            sz = len(json.dumps(body))
            print(f"  saved {fname.name} ({sz} bytes)")

        page.on("request", on_request)
        page.on("response", on_response)

        print(f"navigating to {URL}")
        page.goto(URL, wait_until="networkidle", timeout=60_000)
        # Give the SPA time to fire all initial calendar requests
        page.wait_for_timeout(5000)

        # Try interacting with the calendar to trigger more event fetches.
        # The SPA likely loads "today" by default. Trigger more by clicking
        # next-month a couple times.
        try:
            for _ in range(2):
                # Common Material/Kendo next-button selectors
                btn = page.locator("button[aria-label*='Next' i], button.k-nav-next").first
                if btn and btn.count():
                    btn.click(timeout=3000)
                    page.wait_for_timeout(2500)
        except Exception as e:  # noqa: BLE001
            print(f"  (next-month click skipped: {e})")

        browser.close()

    print(f"\ncaptured token: {captured['token'][:40]}...")
    print(f"total api requests seen: {len(requests_log)}")
    (OUT / "_requests.json").write_text(json.dumps(requests_log, indent=2))
    (OUT / "_token.txt").write_text(captured["token"])
    print("\nfiles in tmp_probe/:")
    for f in sorted(OUT.iterdir()):
        print(f"  {f.name}  ({f.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
