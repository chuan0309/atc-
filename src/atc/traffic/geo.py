from __future__ import annotations

import math

R_NM = 3440.065  # 地球半徑（海里）


def distance_nm(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R_NM * math.asin(math.sqrt(a))


def bearing_deg(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def destination(lat, lon, brg_deg, dist_nm) -> tuple[float, float]:
    d = dist_nm / R_NM
    b = math.radians(brg_deg)
    p1, l1 = math.radians(lat), math.radians(lon)
    p2 = math.asin(math.sin(p1) * math.cos(d) + math.cos(p1) * math.sin(d) * math.cos(b))
    l2 = l1 + math.atan2(math.sin(b) * math.sin(d) * math.cos(p1), math.cos(d) - math.sin(p1) * math.sin(p2))
    return math.degrees(p2), (math.degrees(l2) + 540) % 360 - 180


def along_cross_nm(lat, lon, ref_lat, ref_lon, course_deg) -> tuple[float, float]:
    """點相對於一條線（從 ref 往 course 方向）的 沿線距離 / 偏離距離（海里）。"""
    d = distance_nm(ref_lat, ref_lon, lat, lon)
    if d < 1e-9:
        return 0.0, 0.0
    ang = math.radians(bearing_deg(ref_lat, ref_lon, lat, lon) - course_deg)
    return d * math.cos(ang), d * math.sin(ang)
