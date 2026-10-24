# Tự động hoá hồ sơ thương vụ trên Google Drive

Các script Python dùng [Google Workspace CLI (`gws`)](https://github.com/googleworkspace/cli):

| Script | Làm gì |
|---|---|
| `scripts/tao_ho_so.py` | Tạo bộ thư mục hồ sơ chuẩn cho một thương vụ (Quyển 1/3, 2/3, 3/3…), tải file từ máy lên đúng thư mục, chia sẻ cho đồng nghiệp |
| `scripts/tao_tai_lieu_tu_mau.py` | Sinh Google Docs (vd. *Tổng quan doanh nghiệp*) từ file mẫu có chỗ trống `{{TEN_TRUONG}}`, dữ liệu lấy từ file JSON hoặc Google Sheet |
| `scripts/kiem_tra_chia_se.py` | Liệt kê các file đang để "Bất kỳ ai có đường liên kết" và tắt chế độ đó |

Hai script đầu **chạy lại được nhiều lần mà không tạo bản trùng**, và có chế độ `--chay-thu` để xem trước mà không thay đổi gì trên Drive.

---

## 1. Cài đặt (một lần)

**a. Python 3.9+** — kiểm tra bằng `python3 --version` (Windows: `py --version`). Script chỉ dùng thư viện có sẵn.

**b. Cài `gws`:**

```bash
npm install -g @googleworkspace/cli      # hoặc: brew install googleworkspace-cli
gws --version
```

Windows: nên tải `gws.exe` từ [trang Releases](https://github.com/googleworkspace/cli/releases) rồi đặt biến môi trường `GWS_BIN` trỏ tới file đó.

**c. Kết nối tài khoản Google:**

- Nếu máy có `gcloud`: chạy `gws auth setup` và làm theo hướng dẫn.
- Nếu không có `gcloud`:
  1. Vào [Google Cloud Console](https://console.cloud.google.com/), tạo một project.
  2. Bật **Google Drive API**, **Google Docs API**, **Google Sheets API**.
  3. Mở *OAuth consent screen*: chọn **External**, rồi ở mục **Test users** thêm chính email của bạn (thiếu bước này sẽ bị lỗi "Access blocked").
  4. Mở *Credentials* → *Create credentials* → *OAuth client ID* → loại **Desktop app**. Tải file JSON về, lưu thành `~/.config/gws/client_secret.json`.

Sau đó đăng nhập, **chỉ xin quyền cần thiết**. Tài khoản @gmail.com bị giới hạn khoảng 25 quyền, nên đừng chọn bộ `recommended`.

```bash
gws auth login -s drive,docs,sheets
```

Nếu màn hình hiện "Google hasn't verified this app", bấm **Advanced → Go to … (unsafe)**. Cảnh báo này là bình thường với ứng dụng của chính bạn.

---

## 2. Tạo bộ thư mục hồ sơ — `tao_ho_so.py`

```bash
# Bước 1: xem trước cây thư mục
python3 scripts/tao_ho_so.py cau_hinh/ho_so_chao_ban_cdhh.json --bien MA_CK=PDR --chay-thu

# Bước 2 (tuỳ chọn): tạo sẵn cây thư mục trên máy, rồi bỏ file PDF/DOCX vào đúng chỗ
python3 scripts/tao_ho_so.py cau_hinh/ho_so_chao_ban_cdhh.json --bien MA_CK=PDR --tao-local ho_so_local/PDR

# Bước 3: tạo trên Drive + tải file lên + chia sẻ
python3 scripts/tao_ho_so.py cau_hinh/ho_so_chao_ban_cdhh.json --bien MA_CK=PDR \
    --tai-len ho_so_local/PDR \
    --chia-se dongnghiep@gmail.com:writer \
    --luu-id ho_so_local/PDR.ids.json
```

Kết quả mẫu:

```
Sẽ tạo trong My Drive / 01. Công việc / 1. Đang làm / PDR - Chào bán cho CĐHH 2026:

📁 Tài liệu PDR - Phát hành thêm cổ phiếu cho cổ đông hiện hữu _14102026
├── 00. Mới nhận   ← file khách gửi, chờ xếp vào quyển
├── Quyển 1/3   ← 10 file
│   └── 10.PDR- Điều lệ công ty   ← 2 file
├── Quyển 2/3   ← 8 file
└── Quyển 3/3   ← 5 file
```

File trên máy nên đặt tên bắt đầu bằng STT trong Danh mục (vd. `01. Giay dang ky chao ban.pdf`, `08. Ban cao bach.pdf`) để trên Drive tự xếp đúng thứ tự.

**Các tuỳ chọn:**

| Tuỳ chọn | Ý nghĩa |
|---|---|
| `--bien TEN=GIATRI` | Điền biến trong tên thư mục, vd. `{MA_CK}`. `NGAY` (ddmmyyyy) và `NAM` có sẵn, có thể ghi đè: `--bien NGAY=19052026` |
| `--thu-muc-cha ID` | Đặt bộ hồ sơ vào đúng thư mục Drive có ID này, bỏ qua `duong_dan_cha` của file cấu hình. ID là đoạn cuối của link `drive.google.com/drive/folders/<ID>` |
| `--tai-len DIR` | Thư mục trên máy có cùng cấu trúc. Trên máy, dấu `/` trong tên thư mục được đổi thành `-` (vd. `Quyển 1/3` → `Quyển 1-3`). Thư mục nào không khớp cấu hình sẽ bị cảnh báo |
| `--chia-se EMAIL:QUYEN` | Chia sẻ thư mục gốc với quyền `writer`/`sua`, `commenter`/`binh_luan` hoặc `reader`/`xem`. Mặc định không gửi email thông báo |
| `--luu-id FILE.json` | Lưu ID các thư mục, để dùng cho `--thu-muc` của script thứ hai |
| `--dong-y` | Không hỏi xác nhận |

**Chạy lại an toàn:** thư mục đã có thì dùng lại, file trùng tên trong thư mục đích thì bỏ qua, người đã được chia sẻ thì giữ nguyên quyền.

**Tự tạo cấu trúc riêng:** sao chép một file trong `cau_hinh/` rồi sửa. Mỗi thư mục là `{"ten": "...", "thu_muc_con": [...]}`. Có thể khai báo sẵn vị trí đặt bộ hồ sơ và danh sách chia sẻ:

```json
"duong_dan_cha": "01. Công việc/1. Đang làm/{MA_CK} - Chào bán cho CĐHH {NAM}",
"chia_se": [ { "email": "dongnghiep@gmail.com", "quyen": "writer" } ],
"gui_email_thong_bao": false
```

`duong_dan_cha` là đường dẫn tính từ My Drive, các cấp cách nhau bằng `/`, dùng được biến như tên thư mục. Cấp nào chưa có thì script tự tạo. Bỏ khoá này đi thì bộ hồ sơ nằm ngay ở My Drive.

Có sẵn 2 cấu hình:

- `cau_hinh/ho_so_chao_ban_cdhh.json` — hồ sơ chào bán thêm cổ phiếu cho cổ đông hiện hữu, theo cách đã làm ở đợt PDR 05/2026: Quyển 1/3, 2/3, 3/3, file đặt thẳng trong quyển, riêng mục 10 Điều lệ có thư mục con (`--bien MA_CK=...`)
- `cau_hinh/tham_dinh_doanh_nghiep.json` — **ví dụ** hồ sơ tìm hiểu/thẩm định doanh nghiệp (`--bien TEN_KH=...`)

⚠ Nếu truyền `--bien NGAY=...` trùng ngày của một bộ hồ sơ đã có trên Drive, script sẽ dùng lại bộ đó và chỉ thêm phần còn thiếu. Bỏ trống `NGAY` (mặc định là hôm nay) để tạo bộ mới. Sang năm sau, muốn bổ sung vào bộ hồ sơ của năm trước thì truyền thêm `--bien NAM=...` để `duong_dan_cha` trỏ đúng thư mục cũ.

---

## 3. Sinh tài liệu từ mẫu — `tao_tai_lieu_tu_mau.py`

### Bước 1 — Tạo file mẫu trên Drive (một lần)

```bash
python3 scripts/tao_tai_lieu_tu_mau.py tao-mau mau/tong_quan_doanh_nghiep.html --ten "MẪU - Tổng quan doanh nghiệp"
```

Lệnh trả về **ID** của Google Docs mẫu. Mở file đó để chỉnh định dạng nếu muốn, chỉ cần giữ nguyên các chỗ trống `{{...}}`.

Bạn cũng có thể dùng bất kỳ Google Docs nào làm mẫu: gõ `{{TEN_TRUONG}}` vào chỗ cần điền. Tên trường chỉ gồm chữ không dấu, số và `_`.

### Bước 2 — Chuẩn bị dữ liệu

**Cách A: file JSON.** Xem ví dụ `du_lieu/vi_du_tong_quan.json` (dữ liệu giả).

```json
{
  "TEN_CONG_TY": "Công ty Cổ phần ...",
  "TOM_TAT": ["Đoạn 1", "Đoạn 2"],
  "BANG_TAI_CHINH": {
    "NAM":       ["2021", "2022", "2023", "2024", "2025"],
    "DOANH_THU": [905, 1120, 1260, 1385, 1340.5]
  }
}
```

- Chuỗi hoặc số điền vào `{{TEN_CONG_TY}}`.
- Danh sách `[...]` thành nhiều đoạn. Nếu chỗ trống nằm trong dòng gạch đầu dòng, mỗi phần tử thành một gạch đầu dòng.
- Object `{...}` là bảng số liệu: `DOANH_THU` có 5 giá trị sẽ điền vào `{{DOANH_THU_1}}` … `{{DOANH_THU_5}}`.
- **Số** (viết không có ngoặc kép) được tự định dạng kiểu Việt Nam: `1340.5` thành `1.340,5`. Vì vậy **năm và tỷ lệ nên để trong ngoặc kép** (`"2025"`, `"69%"`).
- Khoá bắt đầu bằng `_` là ghi chú, script bỏ qua.

**Cách B: Google Sheet.** Cột A là tên trường, các cột sau là giá trị, dòng 1 là tiêu đề (bị bỏ qua):

| Trường | Giá trị | | | | |
|---|---|---|---|---|---|
| TEN_CONG_TY | Công ty Cổ phần … | | | | |
| NAM | 2021 | 2022 | 2023 | 2024 | 2025 |
| DOANH_THU | 905 | 1.120 | 1.260 | 1.385 | 1.340,5 |

Dòng có 1 giá trị điền vào `{{TEN_CONG_TY}}`. Dòng có từ 2 giá trị trở lên tạo ra `{{NAM_1}}` … `{{NAM_5}}`. Giá trị được lấy đúng như hiển thị trong Sheet.

**Trường có sẵn:** `{{HOM_NAY}}` (dd/mm/yyyy), `{{THANG}}` (yyyy-mm), `{{NAM}}` (yyyy).

> 💡 **Nhờ Claude điền dữ liệu:** *"Dựa vào `du_lieu/vi_du_tong_quan.json`, tạo `du_lieu/xyz.json` cho công ty XYZ, lấy số liệu tài chính từ SSI/TCBS."* Rồi chạy bước 3.

### Bước 3 — Kiểm tra rồi tạo

```bash
# Kiểm tra: mẫu cần trường nào, dữ liệu thiếu gì (không tạo file)
python3 scripts/tao_tai_lieu_tu_mau.py tao --mau TEMPLATE_ID --du-lieu du_lieu/xyz.json \
    --ten "{TEN_VIET_TAT}_Tong_quan_doanh_nghiep_{THANG}" --chay-thu

# Tạo thật, đặt vào thư mục "05. Sản phẩm" của bộ hồ sơ (ID lấy từ file --luu-id)
python3 scripts/tao_tai_lieu_tu_mau.py tao --mau TEMPLATE_ID --du-lieu du_lieu/xyz.json \
    --ten "{TEN_VIET_TAT}_Tong_quan_doanh_nghiep_{THANG}" --thu-muc FOLDER_ID

# Hoặc lấy dữ liệu từ Google Sheet
python3 scripts/tao_tai_lieu_tu_mau.py tao --mau TEMPLATE_ID --sheet SHEET_ID --vung "DuLieu!A:G" \
    --ten "{TEN_VIET_TAT}_Tong_quan_doanh_nghiep_{THANG}"
```

- Nếu trong thư mục đích **đã có file trùng tên**, script dừng lại thay vì tạo bản thứ hai. Muốn tạo vẫn tạo thì thêm `--cho-phep-trung`.
- Chỗ trống thiếu dữ liệu được giữ nguyên `{{...}}`. Script liệt kê những chỗ này ở cuối để bạn điền tay.

---

## 4. Kiểm tra link công khai — `kiem_tra_chia_se.py`

```bash
# Liệt kê mọi file bạn sở hữu đang để "Bất kỳ ai có đường liên kết" (chỉ xem, không đổi gì)
python3 scripts/kiem_tra_chia_se.py

# Tắt link công khai của một thư mục và mọi thứ bên trong
python3 scripts/kiem_tra_chia_se.py --thu-muc <FOLDER_ID> --de-quy --tat

# Tắt cho đúng vài file/thư mục
python3 scripts/kiem_tra_chia_se.py --id <ID_1> --id <ID_2> --tat
```

- Tắt link công khai không ảnh hưởng tới người được chia sẻ đích danh qua email: họ vẫn mở được như cũ.
- File chỉ công khai vì nằm trong thư mục đang công khai được ghi `[theo thư mục cha]`. Tắt ở thư mục cha thì các file đó hết công khai theo.

---

## 5. Lưu ý bảo mật

- `.gitignore` đã chặn `du_lieu/*` (trừ file ví dụ), `ho_so_local/` và file ID. **Đừng commit dữ liệu khách hàng** lên GitHub.
- Script chỉ gọi Google API từ máy bạn, bằng tài khoản bạn đăng nhập qua `gws`. Trước khi đưa tài liệu thương vụ chưa công bố vào công cụ tự động hoặc AI, hãy kiểm tra quy định bảo mật của công ty.
- `gws` chưa có bản 1.0, có thể thay đổi giữa các phiên bản, và không phải sản phẩm được Google hỗ trợ chính thức. Script đã được kiểm tra với `gws` 0.22.5.

## 6. Dành cho người sửa script

```bash
python3 -m unittest discover -s tests -v
# Thêm kiểm tra cú pháp lệnh bằng gws thật (chạy --dry-run, không cần đăng nhập):
REAL_GWS=$(which gws) python3 -m unittest discover -s tests -v
```

Test dùng `tests/fake_gws.py`, một bản `gws` giả lập Drive/Docs/Sheets, nên không cần tài khoản Google.
