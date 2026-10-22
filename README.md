# Biểu đồ phụ tải HTĐ quốc gia

Trang web tĩnh hiển thị biểu đồ phụ tải hệ thống điện quốc gia (chu kỳ 30 phút; toàn quốc và theo miền). Số liệu lấy từ [NSMO](https://www.nsmo.vn/dashboard/tonghop) và tự cập nhật hằng ngày bằng GitHub Actions, trang được đăng lên GitHub Pages.

## Cấu trúc

```
.github/workflows/update.yml   Lịch chạy 09:17 và 12:47 (giờ VN): lấy số liệu → commit → đăng trang
scripts/fetch_nsmo.py          Lấy số liệu NSMO, bù mọi ngày còn thiếu từ 01/01/2026, chỉ dùng thư viện chuẩn của Python
docs/index.html                Trang dashboard (d3 v7)
docs/data/phu_tai.csv          Số liệu: ngay, gio, quoc_gia_MW, bac_MW, trung_MW, nam_MW
docs/data/meta.json            Thời điểm cập nhật, khoảng ngày có số liệu
```

## Đưa lên web (làm một lần, khoảng 10 phút)

1. Đăng nhập GitHub, bấm **New repository**, đặt tên (ví dụ `phu-tai-htd`), chọn **Public**, bấm **Create repository**.
2. Trong repo vừa tạo, bấm **uploading an existing file**, rồi kéo thả **toàn bộ nội dung** thư mục này (gồm cả thư mục `.github`) và bấm **Commit changes**.
   - Kiểm tra trong repo có file `.github/workflows/update.yml`. Nếu không có (Windows đôi khi bỏ qua thư mục bắt đầu bằng dấu chấm), bấm **Add file → Create new file**, gõ tên `.github/workflows/update.yml` rồi dán nội dung file vào.
3. **Settings → Pages → Build and deployment → Source**: chọn **GitHub Actions**.
4. **Settings → Actions → General → Workflow permissions**: chọn **Read and write permissions**, bấm **Save**.
5. Vào tab **Actions**, chọn **Cap nhat phu tai NSMO**, bấm **Run workflow**. Lần đầu script bù số liệu từ 01/01/2026, mất khoảng 5–10 phút.
6. Chạy xong, link trang là `https://<tên-tài-khoản>.github.io/<tên-repo>/`. Link cũng hiện ở bước **deploy** trong lần chạy.

Từ đó trở đi, workflow tự chạy mỗi ngày. Lần 12:47 dùng để chạy bù khi buổi sáng NSMO chưa công bố đủ số liệu ngày hôm trước.

## Sử dụng

- Chọn ngày: dùng ô ngày, nút ‹ ›, bấm vào biểu đồ Pmax–Pmin hoặc vào một dòng trong bảng ngày.
- Mở thẳng một ngày: `.../?ngay=2026-10-21`.
- Tải số liệu gốc: `.../data/phu_tai.csv`.

## Khi workflow báo lỗi

GitHub gửi email khi một lần chạy thất bại. Nguyên nhân thường gặp:

- **NSMO chặn truy cập từ máy chủ nước ngoài** (máy chạy GitHub Actions đặt ở Mỹ/châu Âu). Cách xử lý: chạy script trên máy ở Việt Nam rồi đẩy số liệu lên.
  ```
  python scripts/fetch_nsmo.py
  ```
  Sau đó upload file `docs/data/phu_tai.csv` lên repo (hoặc dùng `git push`). Nếu tình trạng này kéo dài, nên cài **self-hosted runner** trên một máy tại VN (Settings → Actions → Runners) và đổi `runs-on: ubuntu-latest` thành `runs-on: self-hosted`.
- **NSMO đổi cấu trúc trang.** Script đang dùng hai endpoint nội bộ của trang tổng hợp (không phải API công khai):
  - `/api/services/app/HomePage/GetBieuDoTuongQuanPT?day=dd/mm/yyyy`: toàn quốc
  - `/Dashboard/GetBcsxChartDataPhuTai?ngay=dd/mm/yyyy`: theo miền

  Nếu endpoint đổi thì cần sửa `fetch_nsmo.py`.

## Ghi chú số liệu

- Giờ là thời điểm cuối chu kỳ 30 phút; `24:00` là chu kỳ cuối ngày.
- Ptb là trung bình 48 chu kỳ. Điện năng ngày A = ΣP × 0,5 h. Đây là số tính lại từ biểu đồ, không phải số NSMO công bố chính thức.
- Số liệu miền lấy từ endpoint khác với số toàn quốc, nên tổng 3 miền có thể lệch nhỏ so với số toàn quốc.
- Muốn lấy lịch sử xa hơn (API có số liệu ít nhất từ 2025): `python scripts/fetch_nsmo.py --from 2025-01-01`, hoặc sửa `NSMO_START` trong script.
- Khi công bố trang ra ngoài cần ghi rõ nguồn NSMO; trang đã có dòng ghi nguồn ở cuối.
