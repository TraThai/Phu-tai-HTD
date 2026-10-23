#!/usr/bin/env python3
"""
Lấy số liệu vận hành HTĐ quốc gia (chu kỳ 30 phút) từ NSMO, ghi vào docs/data/:
  - phu_tai.csv      : phụ tải toàn quốc và theo miền Bắc/Trung/Nam (MW), theo Báo cáo sản xuất (BCSX)
                       quoc_gia_MW          = series "Quốc gia" của BCSX (GetBcsxChartDataPhuTai)
                       quoc_gia_trangchu_MW = biểu đồ tương quan phụ tải ở trang chủ NSMO, chỉ để tham khảo
  - co_cau_nguon.csv : công suất phát theo loại hình nguồn (MW), theo BCSX
                       khac_chua_phan_loai  = tổng các loại hình NSMO mới thêm, chưa có cột riêng

- Tự bù mọi ngày còn thiếu từ START đến hôm qua (giờ Việt Nam), riêng cho từng file.
- Lấy lại REFRESH_DAYS ngày gần nhất để cập nhật nếu NSMO hiệu chỉnh số liệu.
- Chỉ dùng thư viện chuẩn của Python (>= 3.8).

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
import socket
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "docs", "data")
PT_PATH = os.path.join(DATA, "phu_tai.csv")
CC_PATH = os.path.join(DATA, "co_cau_nguon.csv")
META_PATH = os.path.join(DATA, "meta.json")

BASE = "https://www.nsmo.vn"
URL_QG = BASE + "/api/services/app/HomePage/GetBieuDoTuongQuanPT?day={d}"
URL_MIEN = BASE + "/Dashboard/GetBcsxChartDataPhuTai?ngay={d}"
URL_NGUON = BASE + "/Dashboard/GetBcsxChartDataCongSuatTheoLoaiHinh?ngay={d}"

PT_COLS = ["ngay", "gio", "quoc_gia_MW", "bac_MW", "trung_MW", "nam_MW", "quoc_gia_trangchu_MW"]


def norm(s):
    """Chuẩn hóa tên series (NFC, chữ thường) để so khớp không phụ thuộc cách mã hóa dấu."""
    return unicodedata.normalize("NFC", str(s or "")).strip().lower()


# Tên series trên BCSX phụ tải -> tên cột (MW)
MIEN = {norm("Quốc gia"): "quoc_gia_MW", norm("Bắc"): "bac_MW",
        norm("Trung"): "trung_MW", norm("Nam"): "nam_MW"}

# Tên loại hình trên NSMO -> tên cột (MW)
NGUON = {
    "Nhiệt điện than": "nd_than",
    "Tuabin khí (GAS)": "tbk_khi",
    "Tuabin khí (DO)": "tbk_dau",
    "Nhiệt điện dầu FO": "nd_dau_fo",
    "Nhiệt điện dầu DO": "nd_dau_do",
    "Thủy điện": "thuy_dien",
    "Mua TQ": "nhap_khau_tq",
    "Sinh khối": "sinh_khoi",
    "Gió": "dien_gio",
    "Mặt trời farm": "mt_farm",
    "ĐMTMN (ĐC)": "mt_mai_nha",
    "Nhiệt điện khác": "nd_khac",
}
CC_KHAC = "khac_chua_phan_loai"
CC_COLS = ["ngay", "gio"] + list(NGUON.values()) + [CC_KHAC]

VN_TZ = timezone(timedelta(hours=7))
HEADERS = {
    "User-Agent": "Mozilla/5.0 (phu-tai-htd dashboard; +https://github.com)",
    "Accept": "application/json, text/plain, */*",
    "Referer": BASE + "/dashboard/tonghop",
}
WARNED = set()
socket.setdefaulttimeout(25)


def get_json(url, retries=2):
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:  # mạng chập chờn, 5xx...
            last = e
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"{url}: {last}")


def hlab(hh):
    return "24:00" if hh == "00:00" else hh


def hour_order(hh):
    return (hh == "00:00", hh)


def fetch_phu_tai(d, ds):
    """48 dòng phụ tải của ngày d, hoặc None nếu NSMO chưa có đủ số liệu.

    Phụ tải toàn quốc và theo miền lấy cùng một nguồn là BCSX, để khớp với số NSMO công bố
    và cân bằng được với cơ cấu nguồn. Biểu đồ trang chủ chỉ ghi thêm để tham khảo.
    """
    bcsx = get_json(URL_MIEN.format(d=ds)).get("result") or []
    reg = {}
    for s in bcsx:
        col = MIEN.get(norm(s.get("name")))
        if not col:
            continue
        for p in s.get("data") or []:
            v = p.get("value")
            if v is not None:
                reg.setdefault(p.get("hour"), {})[col] = round(float(v), 1)
    if len(reg) < 48:
        return None

    home = {}
    try:
        qg = get_json(URL_QG.format(d=ds))
        for p in (((qg or {}).get("result") or {}).get("data") or {}).get("phuTai") or []:
            home[p["thoiGian"][11:16]] = p.get("congSuat")
    except Exception as e:  # thiếu biểu đồ trang chủ không làm hỏng số liệu chính
        print(f"  {d}: không lấy được biểu đồ trang chủ ({e})", flush=True)

    rows = []
    for hh in sorted(reg, key=hour_order):
        r = reg[hh]
        if any(c not in r for c in ("bac_MW", "trung_MW", "nam_MW")):
            return None
        qg_v = r.get("quoc_gia_MW")
        if qg_v is None:  # dự phòng: NSMO không trả series Quốc gia
            qg_v = round(r["bac_MW"] + r["trung_MW"] + r["nam_MW"], 1)
            if "qg" not in WARNED:
                WARNED.add("qg")
                print("  Cảnh báo: BCSX thiếu series 'Quốc gia', tạm lấy Bắc + Trung + Nam", flush=True)
        h = home.get(hh)
        rows.append({"ngay": d.isoformat(), "gio": hlab(hh), "quoc_gia_MW": qg_v,
                     "bac_MW": r["bac_MW"], "trung_MW": r["trung_MW"], "nam_MW": r["nam_MW"],
                     "quoc_gia_trangchu_MW": "" if h is None else round(float(h), 1)})
    if any(float(r["quoc_gia_MW"] or 0) <= 0 for r in rows):
        return None
    return rows


def fetch_co_cau(d, ds):
    """48 dòng cơ cấu nguồn của ngày d, hoặc None nếu chưa có số liệu."""
    res = get_json(URL_NGUON.format(d=ds)).get("result") or []
    by_hour = {}
    for s in res:
        name = s.get("name")
        col = NGUON.get(name)
        if not col:
            # Không bỏ qua: cộng vào cột "khác" để tổng nguồn vẫn đủ.
            if name not in WARNED:
                WARNED.add(name)
                print(f"  Cảnh báo: loại hình mới chưa có cột: {name!r} (ghi vào {CC_KHAC})", flush=True)
            for p in s.get("data") or []:
                v = p.get("value")
                h = by_hour.setdefault(p.get("hour"), {})
                h[CC_KHAC] = round(float(h.get(CC_KHAC) or 0) + float(v or 0), 1)
            continue
        for p in s.get("data") or []:
            v = p.get("value")
            by_hour.setdefault(p.get("hour"), {})[col] = "" if v is None else round(float(v), 1)
    if len(by_hour) < 48:
        return None
    hours = sorted(by_hour, key=hour_order)
    rows, tot = [], 0.0
    for hh in hours:
        r = {"ngay": d.isoformat(), "gio": hlab(hh)}
        for col in CC_COLS[2:]:
            v = by_hour[hh].get(col, "" if col != CC_KHAC else 0.0)
            r[col] = v
            tot += float(v or 0)
        rows.append(r)
    return rows if tot > 0 else None


def load(path):
    out = {}
    if os.path.exists(path):
        with open(path, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                out.setdefault(r["ngay"], []).append(r)
    return out


def stale_days(data, col):
    """Ngày lấy theo cấu trúc cũ (thiếu cột col) -> cần lấy lại. Số liệu cũ vẫn giữ đến khi lấy lại xong."""
    return {k for k, rows in data.items() if any((r.get(col) or "") == "" for r in rows)}


def save(path, cols, by_day):
    tmp = path + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, lineterminator="\n")
        w.writeheader()
        for k in sorted(by_day):
            for r in by_day[k]:
                w.writerow({c: r.get(c, "") for c in cols})
    os.replace(tmp, path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="start", default=os.environ.get("NSMO_START", "2026-01-01"))
    ap.add_argument("--refresh", type=int, default=int(os.environ.get("REFRESH_DAYS", "2")))
    ap.add_argument("--max-days", type=int, default=500)
    ap.add_argument("--sleep", type=float, default=0.4)
    ap.add_argument("--budget-min", type=float, default=float(os.environ.get("BUDGET_MIN", "40")),
                    help="Hết thời gian này thì dừng, lưu phần đã lấy; lần chạy sau làm tiếp.")
    a = ap.parse_args()

    sets = {}
    for n, path, cols, fn, mark in (("pt", PT_PATH, PT_COLS, fetch_phu_tai, "quoc_gia_trangchu_MW"),
                                    ("cc", CC_PATH, CC_COLS, fetch_co_cau, CC_KHAC)):
        data = load(path)
        sets[n] = {"path": path, "cols": cols, "fn": fn, "data": data, "redo": stale_days(data, mark)}
        if sets[n]["redo"]:
            print(f"  {os.path.basename(path)}: {len(sets[n]['redo'])} ngày theo cấu trúc cũ, sẽ lấy lại.", flush=True)

    yesterday = datetime.now(VN_TZ).date() - timedelta(days=1)
    plan, d = [], date.fromisoformat(a.start)
    while d <= yesterday:
        k = d.isoformat()
        need = [n for n, s in sets.items()
                if k not in s["data"] or k in s["redo"] or len(s["data"][k]) < 48
                or (yesterday - d).days < a.refresh]
        if need:
            plan.append((d, need))
        d += timedelta(days=1)
    plan = plan[-a.max_days:]
    # Ưu tiên các ngày gần nhất (hôm qua, ngày cần làm mới) trước, rồi mới bù lịch sử.
    recent = [p for p in plan if (yesterday - p[0]).days <= max(a.refresh, 1)]
    plan = recent + [p for p in plan if p not in recent]
    print(f"Cần lấy {len(plan)} ngày (đến {yesterday.isoformat()}).", flush=True)

    def save_all():
        os.makedirs(DATA, exist_ok=True)
        meta = {"nguon": BASE + "/dashboard/tonghop",
                "cap_nhat_luc": datetime.now(VN_TZ).isoformat(timespec="minutes")}
        for n, s in sets.items():
            save(s["path"], s["cols"], s["data"])
            days = sorted(s["data"])
            meta[os.path.basename(s["path"])] = {
                "so_ngay": len(days),
                "ngay_dau": days[0] if days else None,
                "ngay_cuoi": days[-1] if days else None,
            }
        meta["ngay_cuoi"] = meta["phu_tai.csv"]["ngay_cuoi"]
        with open(META_PATH, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=1)

    t0 = time.time()
    ok = {n: 0 for n in sets}
    miss = {n: [] for n in sets}
    err, streak = [], 0
    for i, (d, need) in enumerate(plan, 1):
        if time.time() - t0 > a.budget_min * 60:
            print(f"Hết {a.budget_min:.0f} phút: dừng ở {d.isoformat()}, lưu phần đã lấy; lần chạy sau làm tiếp.", flush=True)
            break
        ds = urllib.parse.quote(d.strftime("%d/%m/%Y"), safe="")
        td = time.time()
        failed = False
        for n in need:
            try:
                rows = sets[n]["fn"](d, ds)
            except Exception as e:
                err.append(f"{d} {n}: {e}")
                print("  lỗi", d, n, e, flush=True)
                failed = True
                continue
            if rows is None:
                miss[n].append(d.isoformat())
            else:
                sets[n]["data"][d.isoformat()] = rows
                sets[n]["redo"].discard(d.isoformat())
                ok[n] += 1
        streak = streak + 1 if failed else 0
        if streak >= 3:
            print("Dừng: gọi NSMO lỗi 3 ngày liên tiếp (mất mạng hoặc bị chặn).", flush=True)
            break
        if time.time() - td > 15:
            print(f"  chậm: {d.isoformat()} mất {time.time() - td:.0f} s", flush=True)
        if i % 20 == 0 or i == len(plan):
            print(f"  {i}/{len(plan)} ngày, đến {d.isoformat()} ({(time.time() - t0) / 60:.1f} phút)", flush=True)
        if i % 10 == 0:
            save_all()
        time.sleep(a.sleep)

    save_all()

    print(f"Phụ tải: lấy {ok['pt']} ngày; Cơ cấu nguồn: lấy {ok['cc']} ngày; lỗi: {len(err)}.")
    for n, lab in (("pt", "phụ tải"), ("cc", "cơ cấu nguồn")):
        if miss[n]:
            print(f"  Ngày NSMO chưa có đủ số liệu {lab}:", ", ".join(miss[n][:20]))
    # Báo lỗi (để GitHub gửi email) khi mọi lần gọi đều thất bại: thường là mất mạng/bị chặn.
    if err and sum(ok.values()) == 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
