"""Reference resolver for lesson `{slot}` templates.

Lessons are static text with slots; the slots are filled from today's shipped
JSON so the example is always live while the lesson stays evergreen. The
frontend ships its own resolver — this one is the specification it must match,
and it is what the test suite uses to prove every slot in every lesson
resolves against both mock states.

Grammar (documented for humans in content/README.md):

    a.b.c              walk objects by key
    arr[0]             index
    arr[-1]            last element
    arr[key=value]     first element whose `key` equals `value`
    arr.length         number of elements
    a.$b               resolve `b` from the same file's root, use it as the key

Modifiers:
    "round": n         round to n decimals (0 gives an int)
    "map": name        one of the MAPS below, applied before rounding

Anything unresolvable yields None, and render() leaves a visible placeholder
rather than raising — a lesson must never take the page down.
"""
from __future__ import annotations

import re


def _updown_word(v):
    if v is None:
        return None
    return "up" if v > 0 else "down" if v < 0 else "sideways"


def _percent(v):
    return None if v is None else v * 100.0


def _long_short(v):
    if v is None:
        return None
    return "betting on higher prices" if v > 0 else "betting on lower prices"


MAPS = {
    "updown_word": _updown_word,
    "percent": _percent,
    "longshort_word": _long_short,
}

_STEP = re.compile(r"^([^\[]+)?(?:\[(.+)\])?$")


def _walk(node, step: str, root):
    """One path step against `node`; `root` backs `$name` lookups."""
    m = _STEP.match(step)
    if not m:
        return None
    name, sel = m.group(1), m.group(2)

    if name:
        if name == "length":
            return len(node) if hasattr(node, "__len__") else None
        if name.startswith("$"):
            key = resolve_path(root, name[1:])
            if key is None or not isinstance(node, dict):
                return None
            node = node.get(key)
        elif isinstance(node, dict):
            node = node.get(name)
        else:
            return None

    if sel is None or node is None:
        return node

    if not isinstance(node, list):
        return None
    if re.fullmatch(r"-?\d+", sel):
        i = int(sel)
        return node[i] if -len(node) <= i < len(node) else None
    if "=" in sel:
        key, want = sel.split("=", 1)
        for item in node:
            if isinstance(item, dict) and str(item.get(key)) == want:
                return item
    return None


def resolve_path(root, path: str):
    node = root
    for step in path.split("."):
        node = _walk(node, step, root)
        if node is None:
            return None
    return node


def resolve_slot(spec: dict, files: dict):
    """One slot spec -> a display-ready value, or None."""
    root = files.get(spec.get("file"))
    if root is None:
        return None
    value = resolve_path(root, spec.get("path", ""))
    fn = MAPS.get(spec.get("map"))
    if fn is not None:
        value = fn(value)
    if value is None:
        return None
    if "round" in spec and isinstance(value, (int, float)):
        n = spec["round"]
        value = int(round(value)) if n == 0 else round(float(value), n)
    return value


def resolve_lesson(lesson: dict, files: dict) -> dict:
    """{'text': rendered, 'missing': [slot names that did not resolve]}"""
    live = lesson.get("live") or {}
    template = live.get("template", "")
    values, missing = {}, []
    for name, spec in (live.get("slots") or {}).items():
        v = resolve_slot(spec, files)
        if v is None:
            missing.append(name)
            values[name] = "—"
        else:
            values[name] = v
    try:
        text = template.format(**values)
    except Exception:
        text = template
    return {"text": text, "missing": missing, "values": values}
