"""Market-implied Fed odds from 30-day Fed funds futures (ZQ), via Stooq CSV.

FedWatch-style arithmetic on the contract covering the month AFTER the next
FOMC meeting: implied rate = 100 - price; probability of a 25bp move =
(implied - current_effective) / 0.25, clamped.

Everything degrades gracefully: on any failure we return None and the
builder ships scenarios.json with pricing marked stale/absent.
"""
import io, json, time
from pathlib import Path

import pandas as pd
import requests

from . import config

CACHE = Path(__file__).parent / ".cache"
CACHE.mkdir(exist_ok=True)

STOOQ = "https://stooq.com/q/d/l/?s={sym}&i=d"
_UA = {"User-Agent": "Mozilla/5.0 (compatible; money-flow/1.0)"}


def _yahoo_series(sym: str, rng: str = "5y",
                  max_age_hours: float = 0.4) -> pd.Series | None:
    """Daily closes from Yahoo's public chart endpoint -> Series, or None.

    Same degrade-never-die contract as the rest of the fetchers: network
    failure falls back to the cached copy, and a total miss returns None.
    """
    p = CACHE / f"yahoo_{sym.replace('=', '_').replace('.', '_')}.json"
    raw = None
    if p.exists() and (time.time() - p.stat().st_mtime) < max_age_hours * 3600:
        try:
            raw = json.loads(p.read_text())
        except Exception:
            raw = None
    if raw is None:
        try:
            r = requests.get(config.YAHOO_CHART.format(sym=sym),
                             params={"range": rng, "interval": "1d"},
                             headers=_UA, timeout=25)
            r.raise_for_status()
            raw = r.json()
            p.write_text(json.dumps(raw))
        except Exception as e:
            print(f"[prices] yahoo {sym} fetch failed: {e}")
            if not p.exists():
                return None
            try:
                raw = json.loads(p.read_text())
            except Exception:
                return None
    try:
        res = raw["chart"]["result"][0]
        pairs = [(t, c) for t, c in zip(res["timestamp"],
                                        res["indicators"]["quote"][0]["close"])
                 if c is not None]
        if not pairs:
            return None
        s = pd.Series([float(c) for _, c in pairs],
                      index=pd.to_datetime([t for t, _ in pairs], unit="s").normalize(),
                      name=sym)
        return s[~s.index.duplicated(keep="last")].sort_index()
    except Exception:
        return None


def gold_series() -> pd.Series | None:
    """Gold daily closes. FRED retired its LBMA series over licensing, so this
    is the fallback config.FRED_SERIES always pointed at."""
    return _yahoo_series(config.GOLD_SYMBOL, rng=config.GOLD_HISTORY)


def _stooq_last(sym: str) -> float | None:
    p = CACHE / f"stooq_{sym.replace('.', '_')}.json"
    try:
        r = requests.get(STOOQ.format(sym=sym), timeout=20)
        r.raise_for_status()
        df = pd.read_csv(io.StringIO(r.text))
        if df.empty or "Close" not in df:
            raise ValueError("empty")
        val = float(df["Close"].dropna().iloc[-1])
        p.write_text(json.dumps({"v": val}))
        return val
    except Exception:
        if p.exists():
            return json.loads(p.read_text())["v"]
        return None


def zq_symbol(year: int, month: int) -> str:
    codes = "FGHJKMNQUVXZ"
    return f"zq{codes[month - 1]}{str(year)[-2:]}.f"


def zq_yahoo_symbol(year: int, month: int) -> str:
    codes = "FGHJKMNQUVXZ"
    return f"ZQ{codes[month - 1]}{str(year)[-2:]}.CBT"


def implied_fed_odds(next_fomc: str, current_effective: float) -> dict | None:
    """Return {'hike': p, 'hold': p, 'cut': p, 'stale': bool} or None."""
    try:
        d = pd.Timestamp(next_fomc)
        after = d + pd.DateOffset(months=1)
        px = _stooq_last(zq_symbol(after.year, after.month))
        if px is None:  # Stooq now serves a JS bot-challenge, not CSV
            ys = _yahoo_series(zq_yahoo_symbol(after.year, after.month), rng="1mo")
            px = float(ys.iloc[-1]) if ys is not None and len(ys) else None
        if px is None:
            return None
        implied = 100.0 - px
        move = implied - current_effective          # + = hikes priced
        p25 = max(-1.0, min(1.0, move / 0.25))
        if p25 >= 0:
            hike, cut = round(p25, 2), 0.0
        else:
            hike, cut = 0.0, round(-p25, 2)
        hold = round(max(0.0, 1.0 - hike - cut), 2)
        return {"hike": hike, "hold": hold, "cut": cut, "stale": False}
    except Exception:
        return None
