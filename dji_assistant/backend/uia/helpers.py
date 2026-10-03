from __future__ import annotations

from collections.abc import Iterable


def info_of(ctrl) -> dict:
    info = ctrl.element_info
    return {
        "type": getattr(info, "control_type", "") or "",
        "name": getattr(info, "name", "") or "",
        "automation_id": getattr(info, "automation_id", "") or "",
        "class_name": getattr(info, "class_name", "") or "",
    }


def safe_children(ctrl):
    try:
        return ctrl.children()
    except Exception:
        return []


def safe_descendants(ctrl):
    try:
        return ctrl.descendants()
    except Exception:
        return []


def safe_parent(ctrl):
    try:
        return ctrl.parent()
    except Exception:
        return None


def compact_control(ctrl) -> str:
    i = info_of(ctrl)
    bits = [i["type"] or "?"]

    if i["name"]:
        bits.append(f"name={i['name']!r}")
    if i["automation_id"]:
        bits.append(f"id={i['automation_id']!r}")
    if i["class_name"]:
        bits.append(f"class={i['class_name']!r}")

    return " ".join(bits)
