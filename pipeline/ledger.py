"""Append-only record of what the site actually claimed, and when.

The point of this module is to make the engine judgeable later. It writes what
was asserted on a given day — the full claim state plus the raw input vintage
that produced it — so a future scoring pass can ask "was that right?" without
relying on memory or on re-deriving history from a changed engine.

Four streams, all JSONL, all append-only:

    snapshots.jsonl    one line per market day, the complete claim state
    events.jsonl       a watch object appearing, and later resolving
    divergences.jsonl  a scorecard row or overview card turning disagreeing
    health.jsonl       stale flags and fetch failures

Every line carries `prev_hash`, the hash of the line before it. Editing any
historical line breaks the chain from that point on and fails CI. This is not
security — anyone can rewrite the whole file — it is a tripwire against
quietly improving your own track record.

HARD RULE: a ledger failure must never block the data build. Every public
entry point swallows its exception, tries to record it to health.jsonl, and
returns. The six data files ship regardless.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from . import config

ROOT = Path(__file__).parent.parent
GENESIS = "0" * 64


# ---- primitives ----------------------------------------------------------
def ledger_dir(root: Path | None = None) -> Path:
    return (root or ROOT) / config.LEDGER_DIR


def _path(stream: str, root: Path | None = None) -> Path:
    return ledger_dir(root) / config.LEDGER_FILES[stream]


def canonical(obj: dict) -> str:
    """The exact bytes a line hashes to. Stable ordering, no whitespace drift."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)


def line_hash(obj: dict) -> str:
    return hashlib.sha256(canonical(obj).encode()).hexdigest()


def config_hash() -> str:
    """Fingerprint of the tunables that change what a claim means.

    Two snapshots with different config hashes are not directly comparable —
    the scoring pass records it so a later reader can tell whether an accuracy
    shift came from the world or from a config edit.
    """
    payload = {}
    for key in config.CONFIG_HASH_KEYS:
        value = getattr(config, key, None)
        # EVENT_BRANCH_MAPS etc. are plain JSON; tuple-keyed tables are excluded
        payload[key] = json.loads(json.dumps(value, sort_keys=True, default=str))
    return hashlib.sha256(canonical(payload).encode()).hexdigest()


def read_lines(stream: str, root: Path | None = None) -> list[dict]:
    p = _path(stream, root)
    if not p.exists():
        return []
    out = []
    for raw in p.read_text().splitlines():
        raw = raw.strip()
        if raw:
            out.append(json.loads(raw))
    return out


def last_line(stream: str, root: Path | None = None) -> dict | None:
    lines = read_lines(stream, root)
    return lines[-1] if lines else None


def append(stream: str, record: dict, root: Path | None = None) -> dict:
    """Append one record, chaining it to whatever came before."""
    prev = last_line(stream, root)
    record = dict(record)
    record["prev_hash"] = line_hash(prev) if prev is not None else GENESIS
    p = _path(stream, root)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        fh.write(canonical(record) + "\n")
    return record


def verify_chain(stream: str, root: Path | None = None) -> tuple[bool, str]:
    """(ok, message). Walks the whole file and re-derives every link."""
    lines = read_lines(stream, root)
    expected = GENESIS
    for i, rec in enumerate(lines):
        got = rec.get("prev_hash")
        if got != expected:
            return False, (f"{stream}.jsonl line {i + 1}: prev_hash {got!r} "
                           f"but the previous line hashes to {expected!r} — "
                           f"a historical line was edited")
        expected = line_hash(rec)
    return True, f"{stream}.jsonl: {len(lines)} lines, chain intact"


# ---- health --------------------------------------------------------------
def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def record_health(kind: str, source: str, detail: str = "",
                  root: Path | None = None) -> None:
    """Never raises. If even this fails, the build still ships."""
    try:
        append("health", {"ts": _now(), "kind": kind, "source": source,
                          "detail": str(detail)[:400]}, root)
    except Exception:
        pass


def _guard(fn, *a, **kw):
    """Run a ledger write; on failure log to health and carry on."""
    try:
        return fn(*a, **kw)
    except Exception as exc:
        record_health("ledger_error", fn.__name__, repr(exc),
                      kw.get("root") or (a[-1] if a and isinstance(a[-1], Path) else None))
        return None


# ---- snapshots -----------------------------------------------------------
def is_final_slot(now: datetime | None = None) -> bool:
    """True on the last scheduled weekday run.

    LEDGER_FORCE_SNAPSHOT=1 overrides, which is what backfill and the tests use.
    """
    if os.environ.get("LEDGER_FORCE_SNAPSHOT") == "1":
        return True
    now = now or datetime.now(timezone.utc)
    return now.weekday() < 5 and now.hour == config.LEDGER_FINAL_SLOT_UTC_HOUR


def _input_vintage(inputs: dict) -> dict:
    """The raw readings behind the claim, so a later pass can see what moved."""
    keys = ("pce_yoy", "pce_mom3", "unrate", "sahm_gap", "payems_3mo",
            "spread_10y3m", "spread_slope_3mo", "walcl_6mo", "real_5y")
    return {k: inputs.get(k) for k in keys}


def build_snapshot(day: str, regime: dict, overview: dict, dials: dict,
                   scenarios: dict, evidence: dict, inputs: dict,
                   source: str = "live") -> dict:
    """The full claim state for one market day."""
    return {
        "day": day,
        "source": source,
        "engine_version": config.ENGINE_VERSION,
        "config_hash": config_hash(),
        "schema_version": config.SCHEMA_VERSION,
        "claim": {
            "needle": regime.get("needle"),
            "probabilities": regime.get("probabilities"),
            "projection": regime.get("projection"),
            "in_regime_since": regime.get("in_regime_since"),
            "mood": (overview.get("mood") or {}).get("label"),
            "assets": [
                {"asset": a.get("asset"), "expected": a.get("expected"),
                 "actual": a.get("actual"), "agree": a.get("agree")}
                for a in (overview.get("assets") or [])
            ],
            "verdict_bias": ((dials.get("verdict") or {}).get("bias")),
            "market_pricing": scenarios.get("market_pricing"),
            "pricing_stale": scenarios.get("pricing_stale"),
            "scorecard": {
                "confirmed": ((evidence.get("scorecard") or {}).get("confirmed")),
                "total": ((evidence.get("scorecard") or {}).get("total")),
                "rows": ((evidence.get("scorecard") or {}).get("rows") or []),
            },
        },
        "inputs": _input_vintage(inputs),
    }


def write_snapshot(snapshot: dict, root: Path | None = None) -> dict | None:
    """Append unless this day is already recorded (two builds, one line)."""
    existing = {rec.get("day") for rec in read_lines("snapshots", root)}
    if snapshot["day"] in existing:
        return None
    return append("snapshots", snapshot, root)


# ---- events --------------------------------------------------------------
def _event_key(rec: dict) -> tuple:
    return (rec.get("date"), rec.get("event"), rec.get("phase"))


def record_events(calendar: dict, day: str, root: Path | None = None) -> int:
    """A watch object first appearing, and a resolution first appearing."""
    seen = {_event_key(r) for r in read_lines("events", root)}
    written = 0
    for entry in (calendar.get("upcoming") or []):
        watch = entry.get("watch")
        if not watch:
            continue
        key = (entry.get("date"), entry.get("event"), "watch")
        if key in seen:
            continue
        append("events", {
            "ts": _now(), "day": day, "phase": "watch",
            "date": entry.get("date"), "event": entry.get("event"),
            "stakes": watch.get("stakes"),
            "branches": {k: {"label": b.get("label"),
                             "pricing_effect": b.get("pricing_effect"),
                             "assets": b.get("assets")}
                         for k, b in (watch.get("branches") or {}).items()},
        }, root)
        seen.add(key)
        written += 1
    for entry in (calendar.get("recent") or []):
        res = entry.get("resolution")
        if not res:
            continue
        key = (entry.get("reference_month"), entry.get("event"), "resolution")
        if key in seen:
            continue
        append("events", {
            "ts": _now(), "day": day, "phase": "resolution",
            "date": entry.get("reference_month"), "event": entry.get("event"),
            "branch": res.get("branch"), "as_mapped": res.get("as_mapped"),
            "reactions": entry.get("reactions"),
        }, root)
        seen.add(key)
        written += 1
    return written


# ---- divergences ---------------------------------------------------------
def _scorecard_status(snapshot: dict) -> dict:
    rows = ((snapshot.get("claim") or {}).get("scorecard") or {}).get("rows") or []
    return {r.get("says"): r.get("status") for r in rows}


def _agreement(snapshot: dict) -> dict:
    return {a.get("asset"): a.get("agree")
            for a in ((snapshot.get("claim") or {}).get("assets") or [])}


def record_divergences(snapshot: dict, root: Path | None = None) -> int:
    """Transitions only, measured against the PREVIOUS snapshot line.

    A row that was already diverging yesterday is not news. Comparing against
    the previous snapshot rather than against earlier state in the same run is
    what makes this a transition log instead of a status dump.
    """
    lines = read_lines("snapshots", root)
    prev = None
    for rec in reversed(lines):
        if rec.get("day") != snapshot.get("day"):
            prev = rec
            break
    if prev is None:
        return 0

    written = 0
    was, now = _scorecard_status(prev), _scorecard_status(snapshot)
    for says, status in now.items():
        if status == "diverging" and was.get(says) not in ("diverging", None):
            append("divergences", {
                "ts": _now(), "day": snapshot["day"], "kind": "scorecard",
                "subject": says, "from": was.get(says), "to": status,
            }, root)
            written += 1

    was_a, now_a = _agreement(prev), _agreement(snapshot)
    for asset, agree in now_a.items():
        if agree is False and was_a.get(asset) is True:
            append("divergences", {
                "ts": _now(), "day": snapshot["day"], "kind": "overview_asset",
                "subject": asset, "from": True, "to": False,
            }, root)
            written += 1
    return written


# ---- the one call the builder makes --------------------------------------
def record_build(day: str, regime: dict, overview: dict, dials: dict,
                 scenarios: dict, evidence: dict, calendar: dict, inputs: dict,
                 now: datetime | None = None, root: Path | None = None,
                 source: str = "live") -> dict:
    """Best-effort. Returns a summary; never raises into the build."""
    out = {"snapshot": False, "events": 0, "divergences": 0, "errors": []}
    try:
        if not is_final_slot(now):
            return out
        snap = build_snapshot(day, regime, overview, dials, scenarios,
                              evidence, inputs, source=source)
        written = write_snapshot(snap, root)
        out["snapshot"] = written is not None
        if written is not None:
            out["divergences"] = record_divergences(snap, root) or 0
        out["events"] = record_events(calendar, day, root) or 0
        for name, obj in (("scenarios", scenarios), ("regime", regime)):
            if obj.get("pricing_stale") or obj.get("stale"):
                record_health("stale", name, f"{name} reported stale", root)
    except Exception as exc:                    # never block the data build
        out["errors"].append(repr(exc))
        record_health("ledger_error", "record_build", repr(exc), root)
    return out
