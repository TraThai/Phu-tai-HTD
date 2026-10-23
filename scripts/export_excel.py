#!/usr/bin/env python3
"""
Xuất số liệu NSMO (docs/data/*.csv) ra một file Excel và chép kèm 2 file CSV vào thư mục EXCEL_DIR
(ví dụ thư mục OneDrive của phòng đã đồng bộ về máy). Chỉ dùng thư viện chuẩn Python (>= 3.8),
không cần openpyxl.

    set EXCEL_DIR=D:\\OneDrive\\...\\So lieu Web NSMO
    python scripts/export_excel.py

Các sheet: HuongDan, TongHop_Ngay, TongHop_Thang, PhuTai_30p, CoCauNguon_30p.
"""
import csv
import json
import os
import shutil
import sys
import tempfile
import time
import zipfile
from collections import OrderedDict, defaultdict
from datetime import date, datetime, timedelta, timezone
from xml.sax.saxutils import escape

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "docs", "data")
OUT_DIR = os.environ.get("EXCEL_DIR", "").strip().strip('"')
OUT_NAME = os.environ.get("EXCEL_NAME", "So_lieu_NSMO_HTD.xlsx")
VN_TZ = timezone(timedelta(hours=7))

NGUON = OrderedDict([
    ("nd_than", "NĐ than"), ("tbk_khi", "TBK khí"), ("tbk_dau", "TBK dầu"),
    ("nd_dau_fo", "NĐ dầu FO"), ("nd_dau_do", "NĐ dầu DO"), ("nd_khac", "NĐ khác"),
    ("thuy_dien", "Thủy điện"), ("nhap_khau_tq", "Nhập khẩu TQ"), ("sinh_khoi", "Sinh khối"),
    ("dien_gio", "Điện gió"), ("mt_farm", "ĐMT trang trại"), ("mt_mai_nha", "ĐMT mái nhà"),
    ("khac_chua_phan_loai", "Khác (chưa phân loại)"),
])
NLTT = ["sinh_khoi", "dien_gio", "mt_farm", "mt_mai_nha"]
THU = ["T2", "T3", "T4", "T5", "T6", "T7", "CN"]

# Kiểu ô (chỉ số trong styles.xml)
S_HDR, S_DATE, S_INT, S_DEC, S_PCT, S_TXT, S_TITLE = 1, 2, 3, 4, 5, 6, 7


# ---------------------------------------------------------------- xlsx tối giản
def col_name(i):
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def excel_date(s):
    return (date.fromisoformat(s) - date(1899, 12, 30)).days


def sheet_xml(rows, widths, freeze=True, autofilter=True):
    """rows: list các list (value, style). value None = ô trống."""
    out = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">']
    if freeze:
        out.append('<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" '
                   'activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>')
    out.append("<cols>" + "".join(
        f'<col min="{i+1}" max="{i+1}" width="{w}" customWidth="1"/>' for i, w in enumerate(widths)) + "</cols>")
    out.append("<sheetData>")
    for r, row in enumerate(rows, 1):
        cells = []
        for c, cell in enumerate(row):
            v, st = cell if isinstance(cell, tuple) else (cell, 0)
            if v is None or v == "":
                continue
            ref = f"{col_name(c)}{r}"
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                cells.append(f'<c r="{ref}" s="{st}"><v>{v}</v></c>')
            else:
                cells.append(f'<c r="{ref}" s="{st}" t="inlineStr"><is><t xml:space="preserve">{escape(str(v))}</t></is></c>')
        out.append(f'<row r="{r}">' + "".join(cells) + "</row>")
    out.append("</sheetData>")
    if autofilter and rows:
        out.append(f'<autoFilter ref="A1:{col_name(len(rows[0]) - 1)}{len(rows)}"/>')
    out.append("</worksheet>")
    return "".join(out)


STYLES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<numFmts count="4">
<numFmt numFmtId="164" formatCode="dd/mm/yyyy"/>
<numFmt numFmtId="165" formatCode="#,##0"/>
<numFmt numFmtId="166" formatCode="#,##0.0"/>
<numFmt numFmtId="167" formatCode="0.0%"/>
</numFmts>
<fonts count="3">
<font><sz val="11"/><name val="Calibri"/><family val="2"/></font>
<font><b/><sz val="11"/><color rgb="FFFFFFFF"/><name val="Calibri"/><family val="2"/></font>
<font><b/><sz val="14"/><name val="Calibri"/><family val="2"/></font>
</fonts>
<fills count="3">
<fill><patternFill patternType="none"/></fill>
<fill><patternFill patternType="gray125"/></fill>
<fill><patternFill patternType="solid"><fgColor rgb="FF1F4E79"/><bgColor indexed="64"/></patternFill></fill>
</fills>
<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>
<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
<cellXfs count="8">
<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1" applyAlignment="1"><alignment wrapText="1" vertical="center" horizontal="center"/></xf>
<xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>
<xf numFmtId="165" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>
<xf numFmtId="166" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>
<xf numFmtId="167" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>
<xf numFmtId="49" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>
<xf numFmtId="0" fontId="2" fillId="0" borderId="0" xfId="0" applyFont="1"/>
</cellXfs>
<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
</styleSheet>"""


def write_xlsx(path, sheets):
    """sheets: list (tên, xml)."""
    n = len(sheets)
    ct = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
          '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
          '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
          '<Default Extension="xml" ContentType="application/xml"/>'
          '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
          '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
          + "".join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" '
                    'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                    for i in range(1, n + 1)) + "</Types>")
    rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            '</Relationships>')
    wb = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
          '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
          'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
          + "".join(f'<sheet name="{escape(nm)}" sheetId="{i}" r:id="rId{i}"/>' for i, (nm, _) in enumerate(sheets, 1))
          + "</sheets>"
          + "".join(f'<definedNames><definedName name="_xlnm._FilterDatabase" localSheetId="{i}" hidden="1"/></definedNames>'
                    for i in [])
          + "</workbook>")
    wbrels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
              '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
              + "".join(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>'
                        for i in range(1, n + 1))
              + f'<Relationship Id="rId{n+1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
              '</Relationships>')
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", ct)
        z.writestr("_rels/.rels", rels)
        z.writestr("xl/workbook.xml", wb)
        z.writestr("xl/_rels/workbook.xml.rels", wbrels)
        z.writestr("xl/styles.xml", STYLES)
        for i, (_, xml) in enumerate(sheets, 1):
            z.writestr(f"xl/worksheets/sheet{i}.xml", xml)


# ---------------------------------------------------------------- số liệu
def read_csv(name):
    p = os.path.join(DATA, name)
    if not os.path.exists(p):
        return []
    with open(p, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def build():
    pt = read_csv("phu_tai.csv")
    cc = read_csv("co_cau_nguon.csv")
    try:
        with open(os.path.join(DATA, "meta.json"), encoding="utf-8") as f:
            meta = json.load(f)
    except Exception:
        meta = {}

    pt_day = defaultdict(list)
    for r in pt:
        pt_day[r["ngay"]].append(r)
    cc_day = defaultdict(list)
    for r in cc:
        cc_day[r["ngay"]].append(r)

    # ---- Tổng hợp ngày
    daily = []
    for d in sorted(set(pt_day) | set(cc_day)):
        o = {"ngay": d}
        rs = pt_day.get(d, [])
        ps = [(num(r["quoc_gia_MW"]), r["gio"]) for r in rs if num(r["quoc_gia_MW"])]
        if ps:
            mx, mn = max(ps), min(ps)
            s = sum(p for p, _ in ps)
            o.update(pmax=mx[0], gmax=mx[1], pmin=mn[0], gmin=mn[1], ptb=s / len(ps), a=s * 0.5 / 1000)
            for k in ("bac_MW", "trung_MW", "nam_MW"):
                vs = [num(r[k]) for r in rs if num(r[k]) is not None]
                o[k] = max(vs) if vs else None
        rs = cc_day.get(d, [])
        if rs:
            tot = 0.0
            for k in NGUON:
                g = sum(max(0.0, num(r.get(k)) or 0.0) for r in rs) * 0.5 / 1000
                o["g_" + k] = g
                tot += g
            o["g_tot"] = tot
            o["nltt"] = sum(o["g_" + k] for k in NLTT) / tot if tot else None
        daily.append(o)

    hdr = ["Ngày", "Thứ", "Pmax (MW)", "Giờ Pmax", "Pmin (MW)", "Giờ Pmin", "Ptb (MW)", "A phụ tải (GWh)",
           "Ptb/Pmax", "Pmin/Pmax", "Pmax Bắc (MW)", "Pmax Trung (MW)", "Pmax Nam (MW)"] + \
          [f"{v} (GWh)" for v in NGUON.values()] + ["Tổng phát (GWh)", "Tỷ trọng NLTT"]
    rows = [[(h, S_HDR) for h in hdr]]
    for o in daily:
        dd = date.fromisoformat(o["ngay"])
        has = "pmax" in o
        row = [(excel_date(o["ngay"]), S_DATE), (THU[dd.weekday()], S_TXT),
               (o.get("pmax"), S_INT), (o.get("gmax"), S_TXT), (o.get("pmin"), S_INT), (o.get("gmin"), S_TXT),
               (o.get("ptb"), S_INT), (o.get("a"), S_DEC),
               (o["ptb"] / o["pmax"] if has else None, S_PCT), (o["pmin"] / o["pmax"] if has else None, S_PCT),
               (o.get("bac_MW"), S_INT), (o.get("trung_MW"), S_INT), (o.get("nam_MW"), S_INT)]
        row += [(o.get("g_" + k), S_DEC) for k in NGUON]
        row += [(o.get("g_tot"), S_DEC), (o.get("nltt"), S_PCT)]
        rows.append(row)
    sh_day = sheet_xml(rows, [12, 6, 11, 9, 11, 9, 11, 12, 10, 10, 12, 12, 12] + [11] * len(NGUON) + [12, 11])

    # ---- Tổng hợp tháng
    months = OrderedDict()
    for o in daily:
        months.setdefault(o["ngay"][:7], []).append(o)
    hdr = ["Tháng", "Số ngày", "Pmax (MW)", "Ngày Pmax", "Giờ Pmax", "Pmin (MW)", "Ngày Pmin", "Ptb (MW)",
           "A phụ tải (GWh)"] + [f"{v} (GWh)" for v in NGUON.values()] + ["Tổng phát (GWh)", "Tỷ trọng NLTT"]
    rows = [[(h, S_HDR) for h in hdr]]
    for m, os_ in months.items():
        p = [o for o in os_ if "pmax" in o]
        c = [o for o in os_ if "g_tot" in o]
        mx = max(p, key=lambda o: o["pmax"]) if p else None
        mn = min(p, key=lambda o: o["pmin"]) if p else None
        row = [(f"{m[5:]}/{m[:4]}", S_TXT), (len(os_), S_INT),
               (mx["pmax"] if mx else None, S_INT), (excel_date(mx["ngay"]) if mx else None, S_DATE),
               (mx["gmax"] if mx else None, S_TXT),
               (mn["pmin"] if mn else None, S_INT), (excel_date(mn["ngay"]) if mn else None, S_DATE),
               (sum(o["ptb"] for o in p) / len(p) if p else None, S_INT),
               (sum(o["a"] for o in p) if p else None, S_DEC)]
        tot = sum(o["g_tot"] for o in c) if c else None
        row += [(sum(o["g_" + k] for o in c) if c else None, S_DEC) for k in NGUON]
        row += [(tot, S_DEC),
                ((sum(o["g_" + k] for o in c for k in NLTT) / tot) if tot else None, S_PCT)]
        rows.append(row)
    sh_month = sheet_xml(rows, [10, 8, 11, 12, 9, 11, 12, 11, 12] + [11] * len(NGUON) + [12, 11])

    # ---- Số liệu 30 phút
    hdr = ["Ngày", "Giờ", "Toàn quốc (MW)", "Bắc (MW)", "Trung (MW)", "Nam (MW)"]
    rows = [[(h, S_HDR) for h in hdr]]
    for r in pt:
        rows.append([(excel_date(r["ngay"]), S_DATE), (r["gio"], S_TXT)] +
                    [(num(r[k]), S_DEC) for k in ("quoc_gia_MW", "bac_MW", "trung_MW", "nam_MW")])
    sh_pt = sheet_xml(rows, [12, 7, 14, 11, 11, 11])

    hdr = ["Ngày", "Giờ"] + [f"{v} (MW)" for v in NGUON.values()]
    rows = [[(h, S_HDR) for h in hdr]]
    for r in cc:
        rows.append([(excel_date(r["ngay"]), S_DATE), (r["gio"], S_TXT)] + [(num(r.get(k)), S_DEC) for k in NGUON])
    sh_cc = sheet_xml(rows, [12, 7] + [12] * len(NGUON))

    # ---- Hướng dẫn
    now = datetime.now(VN_TZ).strftime("%H:%M %d/%m/%Y")
    def rng(rs):
        ds = sorted({r["ngay"] for r in rs})
        return f"{date.fromisoformat(ds[0]):%d/%m/%Y} – {date.fromisoformat(ds[-1]):%d/%m/%Y} ({len(ds)} ngày)" if ds else "chưa có"
    info = [
        [("Số liệu vận hành HTĐ quốc gia – NSMO", S_TITLE)],
        [],
        [("Nguồn", S_TXT), ("https://www.nsmo.vn/dashboard/tonghop", S_TXT)],
        [("Cập nhật lúc", S_TXT), (now, S_TXT)],
        [("Phụ tải 30 phút", S_TXT), (rng(pt), S_TXT)],
        [("Cơ cấu nguồn 30 phút", S_TXT), (rng(cc), S_TXT)],
        [("Dashboard", S_TXT), ("https://trathai.github.io/Phu-tai-HTD/", S_TXT)],
        [],
        [("Ghi chú", S_TXT)],
        [("", 0), ("File được ghi đè tự động mỗi ngày (khoảng 09:20). Không sửa hay thêm sheet trong file này; "
                   "muốn làm báo cáo thì tạo file khác và liên kết/Power Query tới file này.", S_TXT)],
        [("", 0), ("Giờ là thời điểm cuối chu kỳ 30 phút; 24:00 là chu kỳ cuối ngày.", S_TXT)],
        [("", 0), ("Ptb là trung bình 48 chu kỳ; A = ΣP × 0,5 h; sản lượng nguồn tính từ công suất 30 phút "
                   "(giá trị âm của ĐMT trang trại ban đêm tính bằng 0).", S_TXT)],
        [("", 0), ("NLTT = sinh khối + điện gió + ĐMT trang trại + ĐMT mái nhà.", S_TXT)],
        [("", 0), ("Số liệu miền và số toàn quốc lấy từ hai bảng khác nhau của NSMO nên tổng 3 miền có thể lệch nhỏ.", S_TXT)],
    ]
    sh_info = sheet_xml(info, [22, 110], freeze=False, autofilter=False)

    return [("HuongDan", sh_info), ("TongHop_Ngay", sh_day), ("TongHop_Thang", sh_month),
            ("PhuTai_30p", sh_pt), ("CoCauNguon_30p", sh_cc)]


def place(src, dst, tries=6, wait=20):
    """Chép src -> dst; nếu dst đang bị khóa (có người mở) thì thử lại."""
    for i in range(tries):
        try:
            shutil.copyfile(src, dst + ".tmp")
            os.replace(dst + ".tmp", dst)
            return True
        except PermissionError:
            print(f"  {os.path.basename(dst)} đang bị khóa (có người mở?), thử lại sau {wait} s…", flush=True)
            try:
                os.remove(dst + ".tmp")
            except OSError:
                pass
            time.sleep(wait)
    return False


def main():
    if not OUT_DIR:
        print("Chưa đặt EXCEL_DIR, bỏ qua xuất Excel.")
        return
    if not os.path.isdir(OUT_DIR):
        print(f"Không thấy thư mục: {OUT_DIR}")
        sys.exit(1)
    sheets = build()
    tmp = os.path.join(tempfile.gettempdir(), OUT_NAME)
    write_xlsx(tmp, sheets)
    ok = place(tmp, os.path.join(OUT_DIR, OUT_NAME))
    for n in ("phu_tai.csv", "co_cau_nguon.csv"):
        p = os.path.join(DATA, n)
        if os.path.exists(p):
            ok = place(p, os.path.join(OUT_DIR, n)) and ok
    print(("Đã ghi" if ok else "CHƯA ghi được (file đang mở)") + f" vào {OUT_DIR}")
    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
