#!/usr/bin/env python3
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

ITEMS_URL = "https://api.warframe.market/v2/items"
STATS_URL_TEMPLATE = "https://api.warframe.market/v1/items/{slug}/statistics"
OUTPUT_PATH = "warframe_market_set_wa_prices.json"

REQUESTS_PER_SECOND = 3
MAX_WORKERS = 3
REQUEST_TIMEOUT = 20
MAX_RETRIES = 4

# Set TEST_LIMIT=10 to fetch only the first 10 sets.
TEST_LIMIT = int(os.getenv("TEST_LIMIT", "0") or "0")

_last_request_at = 0.0


def rate_limited_get_json(url: str):
    global _last_request_at
    now = time.monotonic()
    min_interval = 1.0 / REQUESTS_PER_SECOND
    wait_for = (_last_request_at + min_interval) - now
    if wait_for > 0:
        time.sleep(wait_for)

    headers = {
        "User-Agent": "wfhub-set-price-fetcher/1.0",
        "Accept": "application/json",
        "Platform": "pc",
        "Language": "en",
    }
    req = Request(url, headers=headers)

    _last_request_at = time.monotonic()
    with urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
        return json.load(resp)


def fetch_with_retries(url: str):
    last_error = None
    for attempt in range(MAX_RETRIES):
        try:
            return rate_limited_get_json(url)
        except (HTTPError, URLError, TimeoutError, ConnectionError) as exc:
            last_error = str(exc)
            time.sleep(min(2 ** attempt, 10))
    raise RuntimeError(f"Failed after retries: {url} :: {last_error}")


def fetch_items():
    payload = fetch_with_retries(ITEMS_URL)
    return payload.get("data") or payload.get("payload", {}).get("items") or []


def fetch_target_items():
    items = fetch_items()

    set_items = [
        item for item in items
        if "set" in (item.get("tags") or []) and item.get("slug")
    ]

    set_items.sort(key=lambda x: (((x.get("i18n") or {}).get("en") or {}).get("name") or "").lower())

    if TEST_LIMIT > 0:
        set_items = set_items[:TEST_LIMIT]

    return set_items


def fetch_item_wa_price(slug: str):
    url = STATS_URL_TEMPLATE.format(slug=quote(slug, safe=""))
    payload = fetch_with_retries(url)
    root = payload.get("payload") or payload.get("data") or payload
    stats = (root.get("statistics_closed") or {}).get("90days") or []
    latest = stats[-1] if stats else None
    return latest.get("wa_price") if latest else None


def main():
    items = fetch_target_items()

    result = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source": {
            "market_items": ITEMS_URL,
            "market_stats": "v1/items/{slug}/statistics",
        },
        "kind": "set_prices_only",
        "test_limit": TEST_LIMIT,
        "count": 0,
        "items": {},
    }

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_map = {}
        for item in items:
            slug = item.get("slug")
            if not slug:
                continue
            future_map[executor.submit(fetch_item_wa_price, slug)] = item

        for future in as_completed(future_map):
            item = future_map[future]
            slug = item.get("slug")

            try:
                wa_price = future.result()
            except Exception:
                wa_price = None

            i18n = item.get("i18n") or {}
            en = i18n.get("en") or {}
            zh = i18n.get("zh-hans") or {}

            result["items"][slug] = {
                "en_name": en.get("name"),
                "zh_name": zh.get("name"),
                "wa_price": wa_price,
                "vaulted": item.get("vaulted"),
                "tags": item.get("tags"),
            }

    result["count"] = len(result["items"])

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, separators=(",", ":"))

    print(f"Wrote {result['count']} set items to {OUTPUT_PATH} (TEST_LIMIT={TEST_LIMIT})")


if __name__ == "__main__":
    main()
