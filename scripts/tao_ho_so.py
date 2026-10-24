#!/usr/bin/env python3
"""Tạo bộ thư mục hồ sơ cho một thương vụ trên Google Drive, tải file lên và chia sẻ.

Ví dụ:
  # 1. Xem trước cây thư mục sẽ tạo
  python scripts/tao_ho_so.py cau_hinh/ho_so_chao_ban_cdhh.json --bien MA_CK=PDR --chay-thu

  # 2. Tạo sẵn cây thư mục trên máy để bỏ file vào cho đúng chỗ
  python scripts/tao_ho_so.py cau_hinh/ho_so_chao_ban_cdhh.json --bien MA_CK=PDR --tao-local ./ho_so_local/PDR

  # 3. Tạo trên Drive, tải file lên, chia sẻ cho đồng nghiệp
  python scripts/tao_ho_so.py cau_hinh/ho_so_chao_ban_cdhh.json --bien MA_CK=PDR \
      --tai-len ./ho_so_local/PDR --chia-se dongnghiep@gmail.com:writer

Chạy lại nhiều lần vẫn an toàn: thư mục đã có thì dùng lại, file trùng tên thì bỏ qua.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import string
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gws_client import (  # noqa: E402
    FOLDER_MIME,
    GwsError,
    create_folder,
    folder_link,
    gws,
    list_children,
    setup_console,
    upload_file,
)

ROLE_ALIASES = {
    "writer": "writer", "sua": "writer", "chinh_sua": "writer",
    "commenter": "commenter", "binh_luan": "commenter",
    "reader": "reader", "xem": "reader",
}
YES = {"c", "co", "có", "y", "yes"}


@dataclass
class Node:
    name: str
    path: tuple[str, ...]  # đường dẫn tính từ thư mục gốc (gốc = ())
    children: list[Node] = field(default_factory=list)
    folder_id: str | None = None

    def walk(self):
        yield self
        for child in self.children:
            yield from child.walk()

    @property
    def label(self) -> str:
        return " / ".join(self.path) if self.path else self.name


# ---------------------------------------------------------------------------
# Đọc cấu hình
# ---------------------------------------------------------------------------


def render(template: str, variables: dict[str, str]) -> str:
    names = [f for _, f, _, _ in string.Formatter().parse(template) if f]
    missing = sorted({n for n in names if n not in variables})
    if missing:
        raise SystemExit(
            f"Thiếu biến {', '.join(missing)} cho tên \"{template}\". "
            f"Thêm bằng --bien {missing[0]}=..."
        )
    return template.format_map(variables)


def build_tree(config: dict, variables: dict[str, str]) -> Node:
    def build(spec: dict, parent_path: tuple[str, ...], is_root: bool) -> Node:
        name = render(spec["ten"], variables).strip()
        if not name:
            raise SystemExit("Có thư mục bị trống tên trong file cấu hình.")
        path = () if is_root else parent_path + (name,)
        node = Node(name=name, path=path)
        seen = set()
        for child_spec in spec.get("thu_muc_con", []):
            child = build(child_spec, path, False)
            if child.name in seen:
                raise SystemExit(f"Trùng tên thư mục \"{child.name}\" trong {node.label}.")
            seen.add(child.name)
            node.children.append(child)
        return node

    return build({"ten": config["ten_thu_muc_goc"], "thu_muc_con": config.get("thu_muc_con", [])}, (), True)


def parent_segments(config: dict, variables: dict[str, str]) -> list[str]:
    """Các cấp thư mục (tính từ My Drive) sẽ chứa bộ hồ sơ, lấy từ khoá "duong_dan_cha"."""
    raw = config.get("duong_dan_cha", "")
    return [render(part, variables).strip() for part in raw.split("/") if part.strip()]


def parse_vars(pairs: list[str]) -> dict[str, str]:
    today = dt.date.today()
    variables = {"NGAY": today.strftime("%d%m%Y"), "NAM": str(today.year)}
    for pair in pairs:
        key, sep, value = pair.partition("=")
        if not sep or not key.strip():
            raise SystemExit(f"--bien phải có dạng TEN=giatri (nhận được: {pair!r})")
        variables[key.strip()] = value.strip()
    return variables


def parse_shares(config: dict, extra: list[str]) -> list[tuple[str, str]]:
    raw = [(s["email"], s.get("quyen", "writer")) for s in config.get("chia_se", [])]
    for item in extra:
        email, _, role = item.partition(":")
        raw.append((email, role or "writer"))
    shares = []
    for email, role in raw:
        role_key = role.strip().lower()
        if role_key not in ROLE_ALIASES:
            raise SystemExit(f"Quyền \"{role}\" không hợp lệ cho {email}. Dùng: writer/sua, commenter/binh_luan, reader/xem.")
        if "@" not in email:
            raise SystemExit(f"Email không hợp lệ: {email!r}")
        shares.append((email.strip(), ROLE_ALIASES[role_key]))
    return shares


# ---------------------------------------------------------------------------
# Ánh xạ thư mục trên máy
# ---------------------------------------------------------------------------


def safe_local_name(name: str) -> str:
    """Tên thư mục hợp lệ trên Windows/macOS/Linux (vd. "Quyển 1/3" → "Quyển 1-3")."""
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "-", name).rstrip(". ")
    return cleaned or "_"


def local_dir(base: Path, node: Node) -> Path:
    return base.joinpath(*(safe_local_name(p) for p in node.path))


def plan_uploads(root: Node, base: Path) -> tuple[dict[tuple[str, ...], list[Path]], list[Path]]:
    """Trả về (file cần tải lên theo từng thư mục, các thư mục trên máy không khớp cấu hình)."""
    uploads: dict[tuple[str, ...], list[Path]] = {}
    known_dirs = set()
    for node in root.walk():
        d = local_dir(base, node)
        known_dirs.add(d.resolve())
        if d.is_dir():
            files = sorted(p for p in d.iterdir() if p.is_file() and not p.name.startswith("."))
            if files:
                uploads[node.path] = files
    unmatched = sorted(
        p for p in base.rglob("*")
        if p.is_dir() and not p.name.startswith(".") and p.resolve() not in known_dirs
    )
    # Chỉ báo thư mục lệch ở cấp cao nhất, bỏ các thư mục con của nó.
    unmatched = [p for p in unmatched if not any(q in p.parents for q in unmatched)]
    return uploads, unmatched


# ---------------------------------------------------------------------------
# In kế hoạch
# ---------------------------------------------------------------------------


def print_tree(root: Node, uploads: dict[tuple[str, ...], list[Path]]) -> None:
    def line(node: Node, prefix: str, is_last: bool, is_root: bool) -> None:
        count = len(uploads.get(node.path, []))
        suffix = f"   ← {count} file" if count else ""
        if is_root:
            print(f"📁 {node.name}{suffix}")
            child_prefix = ""
        else:
            print(f"{prefix}{'└── ' if is_last else '├── '}{node.name}{suffix}")
            child_prefix = prefix + ("    " if is_last else "│   ")
        for i, child in enumerate(node.children):
            line(child, child_prefix, i == len(node.children) - 1, False)

    line(root, "", True, True)


# ---------------------------------------------------------------------------
# Thực thi trên Drive
# ---------------------------------------------------------------------------


def ensure_path(parent_id: str, segments: list[str]) -> str:
    """Tìm hoặc tạo lần lượt từng cấp thư mục, trả về ID của cấp cuối."""
    for depth, name in enumerate(segments, 1):
        label = " / ".join(segments[:depth])
        found = list_children(parent_id, name=name, mime_type=FOLDER_MIME)
        if found:
            parent_id = found[0]["id"]
            print(f"  = Đã có: {label}")
        else:
            parent_id = create_folder(name, parent_id)["id"]
            print(f"  + Tạo mới: {label}")
    return parent_id


def ensure_folders(root: Node, parent_id: str) -> None:
    def ensure(node: Node, parent: str) -> None:
        found = list_children(parent, name=node.name, mime_type=FOLDER_MIME)
        if found:
            node.folder_id = found[0]["id"]
            note = f" (có {len(found)} thư mục trùng tên, dùng thư mục đầu tiên)" if len(found) > 1 else ""
            print(f"  = Đã có: {node.label}{note}")
        else:
            node.folder_id = create_folder(node.name, parent)["id"]
            print(f"  + Tạo mới: {node.label}")
        for child in node.children:
            ensure(child, node.folder_id)

    ensure(root, parent_id)


def do_uploads(root: Node, uploads: dict[tuple[str, ...], list[Path]]) -> list[str]:
    errors = []
    for node in root.walk():
        files = uploads.get(node.path)
        if not files:
            continue
        existing = {f["name"] for f in list_children(node.folder_id)}
        for path in files:
            if path.name in existing:
                print(f"  = Bỏ qua (đã có): {node.label} / {path.name}")
                continue
            try:
                upload_file(path, node.folder_id, path.name)
                print(f"  ↑ Đã tải lên: {node.label} / {path.name}")
            except GwsError as e:
                errors.append(f"Tải lên {path}: {e}")
                print(f"  ✗ Lỗi khi tải {path.name}: {e}")
    return errors


def do_shares(folder_id: str, shares: list[tuple[str, str]], notify: bool) -> list[str]:
    errors = []
    current = gws(
        "drive", "permissions", "list",
        params={"fileId": folder_id, "fields": "permissions(id,emailAddress,role)", "supportsAllDrives": True},
    ).get("permissions", [])
    by_email = {p.get("emailAddress", "").lower(): p for p in current}
    for email, role in shares:
        existing = by_email.get(email.lower())
        if existing:
            print(f"  = {email} đã có quyền {existing['role']} (giữ nguyên)")
            continue
        try:
            gws(
                "drive", "permissions", "create",
                params={
                    "fileId": folder_id,
                    "sendNotificationEmail": notify,
                    "supportsAllDrives": True,
                    "fields": "id",
                },
                body={"type": "user", "role": role, "emailAddress": email},
            )
            print(f"  ✓ Đã chia sẻ cho {email} ({role})")
        except GwsError as e:
            errors.append(f"Chia sẻ cho {email}: {e}")
            print(f"  ✗ Không chia sẻ được cho {email}: {e}")
    return errors


def confirm(question: str) -> bool:
    if not sys.stdin.isatty():
        print("Không có bàn phím để xác nhận. Thêm --dong-y để chạy không cần hỏi.")
        return False
    return input(f"{question} [c/K]: ").strip().lower() in YES


# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    setup_console()
    ap = argparse.ArgumentParser(
        description="Tạo bộ thư mục hồ sơ thương vụ trên Google Drive (dùng gws).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("Ví dụ:", 1)[1],
    )
    ap.add_argument("cau_hinh", help="File cấu hình JSON mô tả cây thư mục (xem thư mục cau_hinh/)")
    ap.add_argument("--bien", action="append", default=[], metavar="TEN=GIATRI",
                    help="Biến dùng trong tên thư mục, vd. --bien MA_CK=PDR. NGAY (ddmmyyyy) và NAM có sẵn.")
    ap.add_argument("--thu-muc-cha", metavar="FOLDER_ID",
                    help="ID thư mục Drive chứa bộ hồ sơ. Mặc định: theo \"duong_dan_cha\" trong file cấu hình, "
                         "không có thì để ở My Drive")
    ap.add_argument("--tai-len", type=Path, metavar="THU_MUC_MAY",
                    help="Thư mục trên máy có cùng cấu trúc; file trong đó được tải lên đúng thư mục Drive")
    ap.add_argument("--tao-local", type=Path, metavar="THU_MUC_MAY",
                    help="Chỉ tạo cây thư mục trống trên máy (không đụng tới Drive) rồi thoát")
    ap.add_argument("--chia-se", action="append", default=[], metavar="EMAIL[:QUYEN]",
                    help="Chia sẻ thư mục gốc, vd. ban@gmail.com:writer (writer/commenter/reader)")
    ap.add_argument("--luu-id", type=Path, metavar="FILE.json",
                    help="Lưu ID các thư mục vừa tạo ra file JSON")
    ap.add_argument("--chay-thu", "--dry-run", action="store_true",
                    help="Chỉ in kế hoạch, không thay đổi gì trên Drive")
    ap.add_argument("--dong-y", "-y", action="store_true", help="Không hỏi xác nhận")
    args = ap.parse_args(argv)

    config = json.loads(Path(args.cau_hinh).read_text(encoding="utf-8-sig"))
    variables = parse_vars(args.bien)
    root = build_tree(config, variables)
    segments = [] if args.thu_muc_cha else parent_segments(config, variables)
    shares = parse_shares(config, args.chia_se)
    notify = bool(config.get("gui_email_thong_bao", False))

    if args.tao_local:
        for node in root.walk():
            local_dir(args.tao_local, node).mkdir(parents=True, exist_ok=True)
        print(f"Đã tạo cây thư mục trên máy tại: {args.tao_local}")
        print("Bỏ file vào đúng thư mục con, rồi chạy lại với --tai-len", args.tao_local)
        return 0

    uploads: dict[tuple[str, ...], list[Path]] = {}
    if args.tai_len:
        if not args.tai_len.is_dir():
            raise SystemExit(f"Không thấy thư mục {args.tai_len}")
        uploads, unmatched = plan_uploads(root, args.tai_len)
        for d in unmatched:
            print(f"⚠ Thư mục trên máy không khớp cấu hình, file trong đó sẽ KHÔNG được tải: {d}")

    if args.thu_muc_cha:
        parent_label = f"thư mục {args.thu_muc_cha}"
    else:
        parent_label = " / ".join(["My Drive", *segments])
    print(f"\nSẽ tạo trong {parent_label}:\n")
    print_tree(root, uploads)
    total = sum(len(v) for v in uploads.values())
    if args.tai_len:
        print(f"\nTải lên: {total} file từ {args.tai_len}")
    if shares:
        mode = "có gửi email thông báo" if notify else "không gửi email thông báo"
        print(f"Chia sẻ thư mục gốc ({mode}):")
        for email, role in shares:
            print(f"  - {email}: {role}")
    print()

    if args.chay_thu:
        print("(Chạy thử — chưa thay đổi gì trên Drive.)")
        return 0
    if not args.dong_y and not confirm("Tiếp tục?"):
        print("Đã huỷ.")
        return 1

    errors: list[str] = []
    try:
        parent_id = args.thu_muc_cha or "root"
        if segments:
            print("Vị trí:")
            parent_id = ensure_path(parent_id, segments)
        print("Thư mục:")
        ensure_folders(root, parent_id)
        if uploads:
            print("File:")
            errors += do_uploads(root, uploads)
        if shares:
            print("Chia sẻ:")
            errors += do_shares(root.folder_id, shares, notify)
    except GwsError as e:
        print(f"\n✗ Lỗi từ gws: {e}", file=sys.stderr)
        return 1

    if args.luu_id:
        data = {
            "thu_muc_goc": {"ten": root.name, "id": root.folder_id, "link": folder_link(root.folder_id)},
            "thu_muc": {node.label: node.folder_id for node in root.walk() if node.path},
        }
        args.luu_id.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nĐã lưu ID thư mục vào {args.luu_id}")

    print(f"\nXong. Mở bộ hồ sơ: {folder_link(root.folder_id)}")
    if errors:
        print(f"\n⚠ Có {len(errors)} lỗi:")
        for e in errors:
            print(f"  - {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
