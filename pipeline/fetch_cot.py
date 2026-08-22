"""CFTC Commitment of Traders — legacy futures-only, via Socrata open API."""
import json, time
from pathlib import Path

import requests

from . import config

CACHE = Path(__file__).parent / ".cache"
CACHE.mkdir(exist_ok=True)


def fetch_market(market_name: str, weeks: int) -> list[dict]:
    params = {
        "$where": f"market_and_exchange_names='{market_name}'",
        "$order": "report_date_as_yyyy_mm_dd DESC",
        "$limit": weeks,
        "$select": ("report_date_as_yyyy_mm_dd,"
                    "noncomm_positions_long_all,noncomm_positions_short_all"),
    }
    r = requests.get(config.COT_SOCRATA, params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def build_cot() -> list[dict]:
    out = []
    for key, market in config.COT_MARKETS.items():
        cache_p = CACHE / f"cot_{key}.json"
        try:
            rows = fetch_market(market, config.COT_PCTILE_WEEKS)
            cache_p.write_text(json.dumps(rows))
            stale = False
        except Exception as e:
            print(f"[cot] {key} fetch failed: {e}")
            if not cache_p.exists():
                continue
            rows = json.loads(cache_p.read_text())
            stale = True
        rows = sorted(rows, key=lambda x: x["report_date_as_yyyy_mm_dd"])
        net = [int(float(r["noncomm_positions_long_all"])) -
               int(float(r["noncomm_positions_short_all"])) for r in rows]
        dates = [r["report_date_as_yyyy_mm_dd"][:10] for r in rows]
        if not net:
            continue
        cur = net[-1]
        window = net[-config.COT_PCTILE_WEEKS:]
        pctile = round(100 * sum(1 for v in window if v <= cur) / len(window))
        wow = cur - net[-2] if len(net) >= 2 else 0
        out.append({
            "market": key,
            "net": net[-config.COT_WEEKS:],
            "dates": dates[-config.COT_WEEKS:],
            "current": cur,
            "pctile_3yr": pctile,
            "wow_delta": wow,
            "tuesday": dates[-1],
            "stale": stale,
        })
        time.sleep(0.3)  # be polite to Socrata
    return out
