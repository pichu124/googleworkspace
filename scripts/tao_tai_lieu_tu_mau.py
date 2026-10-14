#!/usr/bin/env python3
"""Sinh Google Docs từ file mẫu có chỗ trống dạng {{TEN_TRUONG}}.

Ví dụ:
  # 1. (Một lần) Đưa file mẫu HTML lên Drive thành Google Docs mẫu
  python scripts/tao_tai_lieu_tu_mau.py tao-mau mau/tong_quan_doanh_nghiep.html \
      --ten "MẪU - Tổng quan doanh nghiệp"

  # 2. Kiểm tra trước: file mẫu cần những trường nào, dữ liệu còn thiếu gì
  python scripts/tao_tai_lieu_tu_mau.py tao --mau TEMPLATE_ID \
      --du-lieu du_lieu/vi_du_tong_quan.json --ten "{TEN_VIET_TAT}_Tong_quan_doanh_nghiep_{THANG}" --chay-thu

  # 3. Tạo tài liệu (dữ liệu từ file JSON hoặc từ Google Sheet)
  python scripts/tao_tai_lieu_tu_mau.py tao --mau TEMPLATE_ID --du-lieu du_lieu/abc.json \
      --ten "{TEN_VIET_TAT}_Tong_quan_doanh_nghiep_{THANG}" --thu-muc FOLDER_ID
  python scripts/tao_tai_lieu_tu_mau.py tao --mau TEMPLATE_ID --sheet SHEET_ID --vung "DuLieu!A:G" \
      --ten "{TEN_VIET_TAT}_Tong_quan_doanh_nghiep_{THANG}"

Trường có sẵn (không cần khai báo): HOM_NAY (dd/mm/yyyy), THANG (yyyy-mm), NAM (yyyy).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import string
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gws_client import (  # noqa: E402
    DOC_MIME,
    GwsError,
    doc_link,
    get_file,
    gws,
    list_children,
    setup_console,
)

PLACEHOLDER = re.compile(r"\{\{([A-Za-z0-9_]+)\}\}")
ANY_BRACES = re.compile(r"\{\{[^{}]*\}\}")
VALID_KEY = re.compile(r"^[A-Za-z0-9_]+$")


# ---------------------------------------------------------------------------
# Dữ liệu
# ---------------------------------------------------------------------------


def format_number_vn(x: int | float) -> str:
    """1160 → "1.160"; 732.7 → "732,7" (kiểu Việt Nam)."""
    s = format(x, ",")
    return s.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def format_value(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Có" if value else "Không"
    if isinstance(value, (int, float)):
        return format_number_vn(value)
    if isinstance(value, list):
        return "\n".join(format_value(v) for v in value)
    return str(value)


def builtins_today(today: dt.date | None = None) -> dict[str, str]:
    today = today or dt.date.today()
    return {"HOM_NAY": today.strftime("%d/%m/%Y"), "THANG": today.strftime("%Y-%m"), "NAM": str(today.year)}


def flatten_json(data: dict) -> dict[str, str]:
    """Chuyển dữ liệu JSON thành {TRUONG: chuỗi}.

    - "KEY": "chuỗi" hoặc số            → {{KEY}}
    - "KEY": ["đoạn 1", "đoạn 2"]        → {{KEY}} gồm nhiều đoạn (xuống dòng)
    - "BANG": {"DOANH_THU": [1, 2, 3]}   → {{DOANH_THU_1}}, {{DOANH_THU_2}}, {{DOANH_THU_3}}
    - Khoá bắt đầu bằng "_" là ghi chú, bị bỏ qua.
    """
    out: dict[str, str] = {}
    for key, value in data.items():
        if key.startswith("_"):
            continue
        if isinstance(value, dict):
            for row_key, row in value.items():
                if row_key.startswith("_"):
                    continue
                cells = row if isinstance(row, list) else [row]
                for i, cell in enumerate(cells, start=1):
                    out[f"{row_key}_{i}"] = format_value(cell)
        else:
            out[key] = format_value(value)
    return out


def rows_to_data(rows: list[list[str]]) -> dict[str, str]:
    """Đọc bảng từ Google Sheet: cột A là tên trường, các cột sau là giá trị. Dòng đầu là tiêu đề.

    - 1 giá trị  (A=KEY, B=...)             → {{KEY}}
    - ≥2 giá trị (A=DOANH_THU, B, C, D...)  → {{DOANH_THU_1}}, {{DOANH_THU_2}}, ...
    """
    out: dict[str, str] = {}
    for row in rows[1:]:
        if not row or not str(row[0]).strip():
            continue
        key = str(row[0]).strip()
        values = [str(v) for v in row[1:]]
        while values and values[-1] == "":
            values.pop()
        if len(values) <= 1:
            out[key] = values[0] if values else ""
        else:
            for i, v in enumerate(values, start=1):
                out[f"{key}_{i}"] = v
    return out


def load_data(args) -> dict[str, str]:
    if args.du_lieu:
        raw = json.loads(Path(args.du_lieu).read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise SystemExit("File dữ liệu JSON phải là một object {...}.")
        return flatten_json(raw)
    resp = gws(
        "sheets", "spreadsheets", "values", "get",
        params={"spreadsheetId": args.sheet, "range": args.vung},
    )
    return rows_to_data(resp.get("values", []))


# ---------------------------------------------------------------------------
# Google Docs
# ---------------------------------------------------------------------------


def collect_text(node, out: list[str]) -> None:
    """Gom toàn bộ chữ trong JSON của Google Docs (mọi tab, bảng, header, footer)."""
    if isinstance(node, dict):
        run = node.get("textRun")
        if isinstance(run, dict):
            out.append(run.get("content", ""))
        for key, value in node.items():
            if key != "textRun":
                collect_text(value, out)
    elif isinstance(node, list):
        for value in node:
            collect_text(value, out)


def document_text(doc_id: str) -> str:
    doc = gws("docs", "documents", "get", params={"documentId": doc_id, "includeTabsContent": True})
    parts: list[str] = []
    collect_text(doc, parts)
    return "".join(parts)


def unique(items) -> list[str]:
    return list(dict.fromkeys(items))


def render_name(template: str, values: dict[str, str]) -> str:
    names = [f for _, f, _, _ in string.Formatter().parse(template) if f]
    missing = sorted({n for n in names if n not in values})
    if missing:
        raise SystemExit(f"Tên file \"{template}\" dùng trường chưa có dữ liệu: {', '.join(missing)}")
    return template.format_map(values).strip()


# ---------------------------------------------------------------------------
# Lệnh tao-mau
# ---------------------------------------------------------------------------


def cmd_tao_mau(args) -> int:
    path = Path(args.file)
    if not path.is_file():
        raise SystemExit(f"Không thấy file {path}")
    name = args.ten or f"MẪU - {path.stem}"
    folder = args.thu_muc or "root"
    if list_children(folder, name=name) and not args.cho_phep_trung:
        raise SystemExit(f"Đã có file \"{name}\" trong thư mục đích. Đổi --ten hoặc thêm --cho-phep-trung.")
    created = gws(
        "drive", "files", "create",
        params={"fields": "id,name", "supportsAllDrives": True},
        body={"name": name, "mimeType": DOC_MIME, "parents": [folder]},
        upload=path,
    )
    print(f"Đã tạo file mẫu \"{created['name']}\"")
    print(f"  ID:   {created['id']}")
    print(f"  Link: {doc_link(created['id'])}")
    print("Mở file để chỉnh định dạng nếu cần. Dùng ID này cho --mau khi chạy lệnh `tao`.")
    return 0


# ---------------------------------------------------------------------------
# Lệnh tao
# ---------------------------------------------------------------------------


def cmd_tao(args) -> int:
    data = load_data(args)
    bad_keys = [k for k in data if not VALID_KEY.match(k)]
    for k in bad_keys:
        print(f"⚠ Tên trường \"{k}\" chỉ nên gồm chữ không dấu, số và dấu _ — sẽ không khớp chỗ trống nào.")
    values = {**builtins_today(), **data}

    meta = get_file(args.mau)
    if meta.get("mimeType") != DOC_MIME:
        raise SystemExit(
            f"\"{meta.get('name')}\" không phải Google Docs. Nếu là .docx, mở bằng Google Docs và "
            "chọn Tệp → Lưu dưới dạng Google Tài liệu, hoặc dùng lệnh `tao-mau`."
        )

    template_text = document_text(args.mau)
    fields = unique(PLACEHOLDER.findall(template_text))
    malformed = unique(m for m in ANY_BRACES.findall(template_text) if not PLACEHOLDER.fullmatch(m))
    missing = [f for f in fields if f not in values]
    unused = [k for k in data if k not in fields]

    name = render_name(args.ten, values)
    dest = args.thu_muc or (meta.get("parents") or ["root"])[0]

    print(f"File mẫu: {meta['name']}")
    print(f"  Có {len(fields)} chỗ trống; dữ liệu điền được {len(fields) - len(missing)}.")
    if missing:
        print(f"  ⚠ Thiếu dữ liệu cho {len(missing)} chỗ (sẽ giữ nguyên {{{{...}}}} để điền tay):")
        for f in missing:
            print(f"     - {f}")
    if malformed:
        print(f"  ⚠ Chỗ trống sai định dạng (chỉ dùng chữ không dấu, số, _): {', '.join(malformed)}")
    if unused:
        print(f"  ℹ Dữ liệu không dùng tới ({len(unused)}): {', '.join(unused)}")
    print(f"Tài liệu mới: \"{name}\"")
    print(f"  Đặt trong thư mục: {'cùng thư mục với file mẫu' if not args.thu_muc else dest}")

    if args.chay_thu:
        print("\n(Chạy thử — chưa tạo gì trên Drive.)")
        return 0

    if list_children(dest, name=name) and not args.cho_phep_trung:
        raise SystemExit(
            f"\n✗ Đã có file \"{name}\" trong thư mục đích. Đổi --ten, xoá bản cũ, hoặc thêm --cho-phep-trung."
        )

    copy_body = {"name": name}
    if args.thu_muc:
        copy_body["parents"] = [args.thu_muc]
    new_doc = gws(
        "drive", "files", "copy",
        params={"fileId": args.mau, "fields": "id,name", "supportsAllDrives": True},
        body=copy_body,
    )
    doc_id = new_doc["id"]

    targets = [f for f in fields if f in values]
    if targets:
        requests = [
            {
                "replaceAllText": {
                    "containsText": {"text": "{{" + f + "}}", "matchCase": True},
                    "replaceText": values[f],
                }
            }
            for f in targets
        ]
        try:
            resp = gws("docs", "documents", "batchUpdate", params={"documentId": doc_id}, body={"requests": requests})
        except GwsError:
            print(f"\n✗ Đã tạo bản sao nhưng điền dữ liệu bị lỗi. Xoá file dở dang rồi chạy lại: {doc_link(doc_id)}")
            raise
        replies = resp.get("replies", [])
        changed = sum(r.get("replaceAllText", {}).get("occurrencesChanged", 0) for r in replies)
        print(f"\nĐã điền {changed} chỗ ({len(targets)} trường).")

    leftover = unique(ANY_BRACES.findall(document_text(doc_id)))
    if leftover:
        print(f"⚠ Còn {len(leftover)} chỗ trống chưa điền: {', '.join(leftover)}")
    print(f"\nXong: {doc_link(doc_id)}")
    return 0


# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    setup_console()
    ap = argparse.ArgumentParser(
        description="Sinh Google Docs từ file mẫu có chỗ trống {{TEN_TRUONG}} (dùng gws).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("Ví dụ:", 1)[1],
    )
    sub = ap.add_subparsers(dest="lenh", required=True)

    p_mau = sub.add_parser("tao-mau", help="Đưa file .html/.docx lên Drive thành Google Docs mẫu")
    p_mau.add_argument("file", help="File mẫu trên máy (.html hoặc .docx)")
    p_mau.add_argument("--ten", help="Tên file mẫu trên Drive")
    p_mau.add_argument("--thu-muc", metavar="FOLDER_ID", help="Thư mục Drive chứa file mẫu (mặc định: My Drive)")
    p_mau.add_argument("--cho-phep-trung", action="store_true", help="Vẫn tạo nếu đã có file trùng tên")
    p_mau.set_defaults(func=cmd_tao_mau)

    p_tao = sub.add_parser("tao", help="Tạo tài liệu mới từ file mẫu và dữ liệu")
    p_tao.add_argument("--mau", required=True, metavar="DOC_ID", help="ID Google Docs mẫu")
    src = p_tao.add_mutually_exclusive_group(required=True)
    src.add_argument("--du-lieu", metavar="FILE.json", help="Dữ liệu dạng JSON")
    src.add_argument("--sheet", metavar="SHEET_ID", help="Dữ liệu từ Google Sheet (cột A = tên trường)")
    p_tao.add_argument("--vung", default="A:Z", help="Vùng đọc trong Sheet, vd. \"DuLieu!A:G\" (mặc định: A:Z của trang đầu)")
    p_tao.add_argument("--ten", required=True,
                       help="Tên tài liệu mới, dùng được {TRUONG}, vd. \"{TEN_VIET_TAT}_Tong_quan_doanh_nghiep_{THANG}\"")
    p_tao.add_argument("--thu-muc", metavar="FOLDER_ID", help="Thư mục Drive đặt tài liệu (mặc định: cùng chỗ file mẫu)")
    p_tao.add_argument("--cho-phep-trung", action="store_true", help="Vẫn tạo nếu đã có file trùng tên")
    p_tao.add_argument("--chay-thu", "--dry-run", action="store_true", help="Chỉ kiểm tra, không tạo file")
    p_tao.set_defaults(func=cmd_tao)

    args = ap.parse_args(argv)
    try:
        return args.func(args)
    except GwsError as e:
        print(f"\n✗ Lỗi từ gws: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
