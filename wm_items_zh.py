#!/usr/bin/env python3
import json
import os
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ITEMS_URL = "https://api.warframe.market/v2/items"
OUTPUT_PATH = "items_zh.json"

REQUEST_TIMEOUT = 30
MAX_RETRIES = 4


def fetch_with_retries(url: str):
    last_error = None
    for attempt in range(MAX_RETRIES):
        try:
            req = Request(
                url,
                headers={
                    "User-Agent": "wfhub-items-sync/1.0",
                    "Accept": "application/json",
                    "Platform": "pc",
                    "Language": "zh-hans",
                },
            )
            with urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
                return json.load(resp)
        except (HTTPError, URLError, TimeoutError, ConnectionError) as exc:
            last_error = str(exc)
            time.sleep(min(2 ** attempt, 10))
    raise RuntimeError(f"Failed after retries: {url} :: {last_error}")


def main():
    payload = fetch_with_retries(ITEMS_URL)

    result = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source": ITEMS_URL,
        "data": payload.get("data", []),
    }

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, separators=(",", ":"))

    print(f"Wrote {len(result['data'])} items to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
