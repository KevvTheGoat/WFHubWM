#!/usr/bin/env python3
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

RELIC_REWARDS_URL = "https://drops.warframestat.us/data/relics.json"
ITEMS_URL = "https://api.warframe.market/v2/items"
STATS_URL_TEMPLATE = "https://api.warframe.market/v1/items/{slug}/statistics"
OUTPUT_PATH = "warframe_market_wa_prices.json"

REQUESTS_PER_SECOND = 3
MAX_WORKERS = 3
REQUEST_TIMEOUT = 20
MAX_RETRIES = 4

# Set TEST_LIMIT=10 to only fetch the first 10 matched relic parts.
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
        "User-Agent": "wfhub-relic-part-prices/1.0",
        "Accept": "application/json",
    }
    if "warframe.market" in url:
        headers["Platform"] = "pc"
        headers["Language"] = "en"

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


def normalize_name(value: str) -> str:
    return " ".join(str(value or "").split()).strip().lower()


def fetch_relic_part_names():
    payload = fetch_with_retries(RELIC_REWARDS_URL)
    relics = payload.get("relics") or []

    part_names = set()
    for relic in relics:
        for reward in relic.get("rewards") or []:
            item_name = reward.get("itemName")
            if item_name:
                part_names.add(normalize_name(item_name))

    return part_names


def fetch_items():
    payload = fetch_with_retries(ITEMS_URL)
    return payload.get("data") or payload.get("payload", {}).get("items") or []


def fetch_target_items():
    relic_part_names = fetch_relic_part_names()
    items = fetch_items()

    matched = []
    for item in items:
        en_name = ((item.get("i18n") or {}).get("en") or {}).get("name")
        if normalize_name(en_name) in relic_part_names:
            matched.append(item)

    matched.sort(key=lambda x: (((x.get("i18n") or {}).get("en") or {}).get("name") or "").lower())

    if TEST_LIMIT > 0:
        matched = matched[:TEST_LIMIT]

    return matched


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
            "relic_parts": RELIC_REWARDS_URL,
            "market_items": ITEMS_URL,
            "market_stats": "v1/items/{slug}/statistics",
        },
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

            result["items"][slug] = {
                "en_name": ((item.get("i18n") or {}).get("en") or {}).get("name"),
                "zh_name": ((item.get("i18n") or {}).get("zh-hans") or {}).get("name"),
                "wa_price": wa_price,
            }

    result["count"] = len(result["items"])

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, separators=(",", ":"))

    print(f"Wrote {result['count']} relic parts to {OUTPUT_PATH} (TEST_LIMIT={TEST_LIMIT})")


if __name__ == "__main__":
    main()
