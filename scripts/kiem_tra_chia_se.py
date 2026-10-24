#!/usr/bin/env python3
"""Tìm file của bạn đang để "Bất kỳ ai có đường liên kết" và tắt chế độ đó nếu muốn.

Ví dụ:
  # 1. Liệt kê mọi file bạn sở hữu đang mở link công khai (chỉ xem, không đổi gì)
  python scripts/kiem_tra_chia_se.py

  # 2. Chỉ xem các file nằm ngay trong một thư mục (thêm --de-quy để xét cả thư mục con)
  python scripts/kiem_tra_chia_se.py --thu-muc FOLDER_ID --de-quy

  # 3. Tắt link công khai của các file đó (người được chia sẻ đích danh vẫn giữ quyền)
  python scripts/kiem_tra_chia_se.py --thu-muc FOLDER_ID --de-quy --tat

  # 4. Tắt cho đúng vài file/thư mục
  python scripts/kiem_tra_chia_se.py --id FILE_ID --id FOLDER_ID --tat

File chỉ công khai vì nằm trong thư mục đang công khai thì được ghi "theo thư mục cha": muốn tắt,
hãy tắt ở thư mục cha đó (mọi file bên trong sẽ hết công khai theo).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gws_client import FOLDER_MIME, GwsError, get_file, gws, list_children, setup_console  # noqa: E402

YES = {"c", "co", "có", "y", "yes"}
PUBLIC_QUERY = (
    "'me' in owners and trashed = false"
    " and (visibility = 'anyoneWithLink' or visibility = 'anyoneCanFind')"
)


def walk(folder_id: str, recursive: bool) -> list[dict]:
    items = []
    for child in list_children(folder_id):
        items.append(child)
        if recursive and child["mimeType"] == FOLDER_MIME:
            items += walk(child["id"], recursive)
    return items


def candidates(folder_id: str | None, recursive: bool, ids: list[str]) -> list[dict]:
    if ids:
        return [get_file(i, fields="id,name,mimeType") for i in ids]
    if folder_id:
        items = walk(folder_id, recursive)
        if recursive:
            items.insert(0, get_file(folder_id, fields="id,name,mimeType"))
        return items
    pages = gws(
        "drive", "files", "list",
        params={"q": PUBLIC_QUERY, "pageSize": 1000, "fields": "nextPageToken,files(id,name,mimeType)"},
        page_all=True,
    )
    return [f for page in pages for f in page.get("files", [])]


def public_permissions(file_id: str) -> list[dict]:
    perms = gws(
        "drive", "permissions", "list",
        params={
            "fileId": file_id,
            "fields": "permissions(id,type,role,permissionDetails(inherited))",
            "supportsAllDrives": True,
        },
    ).get("permissions", [])
    return [p for p in perms if p.get("type") == "anyone"]


def is_inherited(perm: dict) -> bool:
    """Quyền chỉ đến từ thư mục cha (không đặt trực tiếp trên file) thì không xoá được ở file."""
    details = perm.get("permissionDetails") or []
    return bool(details) and all(d.get("inherited") for d in details)


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
                    help="Chỉ xét các file nằm ngay trong thư mục này")
    ap.add_argument("--de-quy", action="store_true",
                    help="Cùng --thu-muc: xét cả chính thư mục đó và mọi thư mục con")
    ap.add_argument("--id", action="append", default=[], metavar="FILE_ID",
                    help="Chỉ xét đúng file/thư mục này (dùng nhiều lần được)")
    ap.add_argument("--tat", action="store_true", help="Tắt link công khai của các file tìm được")
    ap.add_argument("--dong-y", "-y", action="store_true", help="Không hỏi xác nhận")
    args = ap.parse_args(argv)

    try:
        found = []
        for f in candidates(args.thu_muc, args.de_quy, args.id):
            perms = public_permissions(f["id"])
            if perms:
                found.append((f, perms))
    except GwsError as e:
        print(f"✗ Lỗi từ gws: {e}", file=sys.stderr)
        return 1

    if not found:
        print("Không có file nào đang mở link công khai.")
        return 0
    direct = [(f, [p for p in perms if not is_inherited(p)]) for f, perms in found]
    direct = [(f, perms) for f, perms in direct if perms]
    print(f"{len(found)} file đang mở link công khai:\n")
    for f, perms in found:
        roles = ", ".join(sorted({p.get("role", "?") for p in perms}))
        note = "" if any(not is_inherited(p) for p in perms) else "  [theo thư mục cha]"
        print(f"  - {f['name']}  ({roles}){note}  https://drive.google.com/file/d/{f['id']}/view")
    print()

    if not args.tat:
        print("(Chỉ liệt kê. Thêm --tat để tắt link công khai.)")
        return 0
    if not direct:
        print("Các file trên chỉ công khai theo thư mục cha. Hãy tắt ở thư mục cha.")
        return 0
    if not args.dong_y and not confirm(f"Tắt link công khai đặt trực tiếp trên {len(direct)} file/thư mục?"):
        print("Đã huỷ.")
        return 1

    errors = 0
    for f, perms in direct:
        try:
            for p in perms:
                gws(
                    "drive", "permissions", "delete",
                    params={"fileId": f["id"], "permissionId": p["id"], "supportsAllDrives": True},
                )
            print(f"  ✓ Đã tắt: {f['name']}")
        except GwsError as e:
            # Quyền kế thừa có thể đã mất theo thư mục cha vừa tắt ở bước trước.
            try:
                still_public = public_permissions(f["id"])
            except GwsError:
                still_public = perms
            if not still_public:
                print(f"  ✓ Đã hết công khai theo thư mục cha: {f['name']}")
                continue
            errors += 1
            print(f"  ✗ Không tắt được {f['name']}: {e}")
    print(f"\nXong: tắt {len(direct) - errors}/{len(direct)} file/thư mục.")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
