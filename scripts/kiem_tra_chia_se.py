#!/usr/bin/env python3
"""Tìm file của bạn đang để "Bất kỳ ai có đường liên kết" và tắt chế độ đó nếu muốn.

Ví dụ:
  # 1. Liệt kê mọi file bạn sở hữu đang mở link công khai (chỉ xem, không đổi gì)
  python scripts/kiem_tra_chia_se.py

  # 2. Chỉ xem các file nằm ngay trong một thư mục
  python scripts/kiem_tra_chia_se.py --thu-muc FOLDER_ID

  # 3. Tắt link công khai của các file trong thư mục đó (người được chia sẻ đích danh vẫn giữ quyền)
  python scripts/kiem_tra_chia_se.py --thu-muc FOLDER_ID --tat
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gws_client import GwsError, gws, list_children, setup_console  # noqa: E402

YES = {"c", "co", "có", "y", "yes"}
PUBLIC_QUERY = (
    "'me' in owners and trashed = false"
    " and (visibility = 'anyoneWithLink' or visibility = 'anyoneCanFind')"
)


def candidates(folder_id: str | None) -> list[dict]:
    if folder_id:
        return list_children(folder_id)
    pages = gws(
        "drive", "files", "list",
        params={"q": PUBLIC_QUERY, "pageSize": 1000, "fields": "nextPageToken,files(id,name,mimeType)"},
        page_all=True,
    )
    return [f for page in pages for f in page.get("files", [])]


def public_permissions(file_id: str) -> list[dict]:
    perms = gws(
        "drive", "permissions", "list",
        params={"fileId": file_id, "fields": "permissions(id,type,role)", "supportsAllDrives": True},
    ).get("permissions", [])
    return [p for p in perms if p.get("type") == "anyone"]


def confirm(question: str) -> bool:
    if not sys.stdin.isatty():
        print("Không có bàn phím để xác nhận. Thêm --dong-y để chạy không cần hỏi.")
        return False
    return input(f"{question} [c/K]: ").strip().lower() in YES


def main(argv: list[str] | None = None) -> int:
    setup_console()
    ap = argparse.ArgumentParser(
        description="Liệt kê và tắt link công khai trên Google Drive (dùng gws).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("Ví dụ:", 1)[1],
    )
    ap.add_argument("--thu-muc", metavar="FOLDER_ID",
                    help="Chỉ xét các file nằm ngay trong thư mục này (không xét thư mục con)")
    ap.add_argument("--tat", action="store_true", help="Tắt link công khai của các file tìm được")
    ap.add_argument("--dong-y", "-y", action="store_true", help="Không hỏi xác nhận")
    args = ap.parse_args(argv)

    try:
        found = []
        for f in candidates(args.thu_muc):
            perms = public_permissions(f["id"])
            if perms:
                found.append((f, perms))
    except GwsError as e:
        print(f"✗ Lỗi từ gws: {e}", file=sys.stderr)
        return 1

    if not found:
        print("Không có file nào đang mở link công khai.")
        return 0
    print(f"{len(found)} file đang mở link công khai:\n")
    for f, perms in found:
        roles = ", ".join(sorted({p.get("role", "?") for p in perms}))
        print(f"  - {f['name']}  ({roles})  https://drive.google.com/file/d/{f['id']}/view")
    print()

    if not args.tat:
        print("(Chỉ liệt kê. Thêm --tat để tắt link công khai.)")
        return 0
    if not args.dong_y and not confirm(f"Tắt link công khai của {len(found)} file trên?"):
        print("Đã huỷ.")
        return 1

    errors = 0
    for f, perms in found:
        try:
            for p in perms:
                gws(
                    "drive", "permissions", "delete",
                    params={"fileId": f["id"], "permissionId": p["id"], "supportsAllDrives": True},
                )
            print(f"  ✓ Đã tắt: {f['name']}")
        except GwsError as e:
            errors += 1
            print(f"  ✗ Không tắt được {f['name']}: {e}")
    print(f"\nXong: tắt {len(found) - errors}/{len(found)} file.")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
