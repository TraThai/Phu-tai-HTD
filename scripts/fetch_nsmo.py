#!/usr/bin/env python3
"""
Lấy biểu đồ phụ tải HTĐ quốc gia (chu kỳ 30 phút) từ NSMO và ghi vào docs/data/phu_tai.csv.

- Tự bù mọi ngày còn thiếu từ START đến hôm qua (giờ Việt Nam).
- Lấy lại REFRESH_DAYS ngày gần nhất để cập nhật nếu NSMO hiệu chỉnh số liệu.
- Chỉ dùng thư viện chuẩn của Python (>= 3.9).

Cách dùng:
    python scripts/fetch_nsmo.py                 # bù ngày thiếu đến hôm qua
    python scripts/fetch_nsmo.py --from 2025-01-01
    python scripts/fetch_nsmo.py --refresh 0     # không lấy lại ngày đã có

Nguồn: https://www.nsmo.vn/dashboard/tonghop (endpoint nội bộ của trang, không phải API công khai).
"""
import argparse
import csv
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV_PATH = os.path.join(ROOT, "docs", "data", "phu_tai.csv")
META_PATH = os.path.join(ROOT, "docs", "data", "meta.json")

BASE = "https://www.nsmo.vn"
URL_QG = BASE + "/api/services/app/HomePage/GetBieuDoTuongQuanPT?day={d}"
URL_MIEN = BASE + "/Dashboard/GetBcsxChartDataPhuTai?ngay={d}"

COLS = ["ngay", "gio", "quoc_gia_MW", "bac_MW", "trung_MW", "nam_MW"]
MIEN = {"Bắc": "bac_MW", "Trung": "trung_MW", "Nam": "nam_MW"}
VN_TZ = timezone(timedelta(hours=7))
HEADERS = {
    "User-Agent": "Mozilla/5.0 (phu-tai-htd dashboard; +https://github.com)",
    "Accept": "application/json, text/plain, */*",
    "Referer": BASE + "/dashboard/tonghop",
}


def get_json(url, retries=3):
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=40) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:  # mạng chập chờn, 5xx...
            last = e
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"{url}: {last}")


def fetch_day(d):
    """Trả về list 48 dòng của ngày d, hoặc None nếu NSMO chưa có đủ số liệu."""
    ds = urllib.parse.quote(d.strftime("%d/%m/%Y"), safe="")
    qg = get_json(URL_QG.format(d=ds))
    pts = (((qg or {}).get("result") or {}).get("data") or {}).get("phuTai") or []
    if len(pts) < 48:
        return None
    mien = get_json(URL_MIEN.format(d=ds)).get("result") or []
    reg = {}
    for s in mien:
        col = MIEN.get(s.get("name"))
        if not col:
            continue
        for p in s.get("data") or []:
            reg.setdefault(p.get("hour"), {})[col] = p.get("value")
    rows = []
    for p in pts:
        hh = p["thoiGian"][11:16]
        r = reg.get(hh, {})
        row = {
            "ngay": d.isoformat(),
            "gio": "24:00" if hh == "00:00" else hh,
            "quoc_gia_MW": p["congSuat"],
        }
        for col in MIEN.values():
            v = r.get(col)
            row[col] = "" if v is None else round(float(v), 1)
        rows.append(row)
    if any(float(r["quoc_gia_MW"] or 0) <= 0 for r in rows):
        return None
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="start", default=os.environ.get("NSMO_START", "2026-01-01"))
    ap.add_argument("--refresh", type=int, default=int(os.environ.get("REFRESH_DAYS", "2")))
    ap.add_argument("--max-days", type=int, default=500)
    ap.add_argument("--sleep", type=float, default=0.4)
    a = ap.parse_args()

    by_day = {}
    if os.path.exists(CSV_PATH):
        with open(CSV_PATH, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                by_day.setdefault(r["ngay"], []).append(r)

    yesterday = datetime.now(VN_TZ).date() - timedelta(days=1)
    start = date.fromisoformat(a.start)
    want, d = [], start
    while d <= yesterday:
        k = d.isoformat()
        if k not in by_day or len(by_day[k]) < 48 or (yesterday - d).days < a.refresh:
            want.append(d)
        d += timedelta(days=1)
    want = want[-a.max_days:]
    print(f"Cần lấy {len(want)} ngày (đến {yesterday.isoformat()}).")

    ok, miss, err = 0, [], []
    for d in want:
        try:
            rows = fetch_day(d)
        except Exception as e:
            err.append(f"{d}: {e}")
            print("  lỗi", d, e)
            continue
        if rows is None:
            miss.append(d.isoformat())
        else:
            by_day[d.isoformat()] = rows
            ok += 1
        time.sleep(a.sleep)

    os.makedirs(os.path.dirname(CSV_PATH), exist_ok=True)
    tmp = CSV_PATH + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLS, lineterminator="\n")
        w.writeheader()
        for k in sorted(by_day):
            for r in by_day[k]:
                w.writerow({c: r.get(c, "") for c in COLS})
    os.replace(tmp, CSV_PATH)

    days = sorted(by_day)
    meta = {
        "nguon": BASE + "/dashboard/tonghop",
        "so_ngay": len(days),
        "ngay_dau": days[0] if days else None,
        "ngay_cuoi": days[-1] if days else None,
        "cap_nhat_luc": datetime.now(VN_TZ).isoformat(timespec="minutes"),
    }
    with open(META_PATH, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)

    print(f"Đã lấy {ok} ngày; chưa có số liệu: {len(miss)}; lỗi: {len(err)}.")
    if miss:
        print("  Ngày NSMO chưa có đủ số liệu:", ", ".join(miss[:20]))
    # Báo lỗi (để GitHub gửi email) khi mọi lần gọi đều thất bại: thường là bị chặn mạng.
    if want and ok == 0 and err:
        sys.exit(1)


if __name__ == "__main__":
    main()
