"""FRED fetcher with disk cache. All series -> pandas Series (DatetimeIndex)."""
import json, os, time
from pathlib import Path

import pandas as pd
import requests

from . import config

CACHE = Path(__file__).parent / ".cache"
CACHE.mkdir(exist_ok=True)


def _api_key() -> str:
    key = os.environ.get("FRED_API_KEY", "")
    if not key:
        raise RuntimeError("FRED_API_KEY not set")
    return key


def _cached(name: str, max_age_hours: float):
    p = CACHE / f"{name}.json"
    if p.exists() and (time.time() - p.stat().st_mtime) < max_age_hours * 3600:
        return json.loads(p.read_text())
    return None


def _save(name: str, obj) -> None:
    (CACHE / f"{name}.json").write_text(json.dumps(obj))


def fetch_series(series_id: str, start: str = "1990-01-01",
                 max_age_hours: float = 0.4) -> pd.Series:
    """One FRED series as a float Series. Cache TTL default ~25 min so the
    30-min cron always refetches, but local re-runs are free."""
    cached = _cached(f"fred_{series_id}", max_age_hours)
    if cached is None:
        r = requests.get(
            f"{config.FRED_BASE}/series/observations",
            params={"series_id": series_id, "api_key": _api_key(),
                    "file_type": "json", "observation_start": start},
            timeout=30,
        )
        r.raise_for_status()
        cached = r.json()["observations"]
        _save(f"fred_{series_id}", cached)
    idx, vals = [], []
    for o in cached:
        if o["value"] in (".", ""):
            continue
        idx.append(o["date"]); vals.append(float(o["value"]))
    s = pd.Series(vals, index=pd.to_datetime(idx), name=series_id)
    return s.sort_index()


def fetch_all(start: str = "1990-01-01") -> dict[str, pd.Series]:
    out = {}
    for name, sid in config.FRED_SERIES.items():
        try:
            out[name] = fetch_series(sid, start=start)
        except Exception as e:  # per-series failure -> stale, not fatal
            stale = _cached(f"fred_{sid}", max_age_hours=24 * 14)
            if stale is not None:
                idx = [o["date"] for o in stale if o["value"] not in (".", "")]
                vals = [float(o["value"]) for o in stale if o["value"] not in (".", "")]
                out[name] = pd.Series(vals, index=pd.to_datetime(idx), name=sid).sort_index()
                out[name].attrs["stale"] = True
            else:
                print(f"[fetch_fred] MISSING {name} ({sid}): {e}")
    return out


def fetch_release_dates(release_id: int, lookahead_days: int) -> list[str]:
    """Upcoming scheduled release dates from FRED's release calendar."""
    today = pd.Timestamp.utcnow().date()
    r = requests.get(
        f"{config.FRED_BASE}/release/dates",
        params={"release_id": release_id, "api_key": _api_key(),
                "file_type": "json", "include_release_dates_with_no_data": "true",
                "realtime_start": str(today),
                "realtime_end": str(today + pd.Timedelta(days=lookahead_days))},
        timeout=30,
    )
    r.raise_for_status()
    ds = [d["date"] for d in r.json().get("release_dates", [])]
    return [d for d in ds if str(today) <= d <= str(today + pd.Timedelta(days=lookahead_days))]


# ---- transforms ----------------------------------------------------------
def yoy(s: pd.Series) -> pd.Series:
    return (s / s.shift(12) - 1.0) * 100.0


def mom_delta(s: pd.Series) -> pd.Series:
    return s - s.shift(1)


def pct_change_days(s: pd.Series, days: int) -> float | None:
    s = s.dropna()
    if len(s) < 2:
        return None
    end = s.index[-1]
    ref = s[s.index <= end - pd.Timedelta(days=days)]
    if ref.empty:
        return None
    return float((s.iloc[-1] / ref.iloc[-1] - 1.0) * 100.0)


def diff_days(s: pd.Series, days: int) -> float | None:
    s = s.dropna()
    if len(s) < 2:
        return None
    end = s.index[-1]
    ref = s[s.index <= end - pd.Timedelta(days=days)]
    if ref.empty:
        return None
    return float(s.iloc[-1] - ref.iloc[-1])


def last(s: pd.Series | None):
    if s is None:
        return None
    s = s.dropna()
    return float(s.iloc[-1]) if len(s) else None


def spark(s: pd.Series, points: int = 30, days: int | None = None) -> list[float]:
    s = s.dropna()
    if days:
        s = s[s.index >= s.index[-1] - pd.Timedelta(days=days)]
    if len(s) <= points:
        return [round(float(v), 4) for v in s.values]
    step = max(1, len(s) // points)
    vals = list(s.values[::step])[-points:]
    return [round(float(v), 4) for v in vals]
