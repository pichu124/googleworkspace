"""Gọi lệnh `gws` (Google Workspace CLI) từ Python và đọc kết quả JSON.

Dùng chung cho tao_ho_so.py và tao_tai_lieu_tu_mau.py.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

FOLDER_MIME = "application/vnd.google-apps.folder"
DOC_MIME = "application/vnd.google-apps.document"

_GWS_BIN: str | None = None


class GwsError(RuntimeError):
    def __init__(self, message: str, exit_code: int | None = None):
        super().__init__(message)
        self.exit_code = exit_code


def setup_console() -> None:
    """Tránh lỗi khi in tiếng Việt ra console/file không dùng UTF-8 (thường gặp trên Windows)."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")


def find_gws() -> str:
    """Tìm file chạy `gws`. Có thể ghi đè bằng biến môi trường GWS_BIN."""
    override = os.environ.get("GWS_BIN")
    if override:
        return override
    path = shutil.which("gws")
    if not path:
        raise GwsError(
            "Không tìm thấy lệnh `gws`. Cài bằng `npm install -g @googleworkspace/cli`, "
            "hoặc tải bản build sẵn tại https://github.com/googleworkspace/cli/releases, "
            "hoặc đặt biến môi trường GWS_BIN trỏ tới file gws."
        )
    if path.lower().endswith((".cmd", ".bat", ".ps1")):
        # Trên Windows, npm tạo file .cmd. Truyền JSON qua cmd.exe dễ hỏng dấu ngoặc kép,
        # nên gọi thẳng file gws.exe nằm trong gói npm.
        exe = Path(path).parent / "node_modules" / "@googleworkspace" / "cli" / "bin" / "gws.exe"
        if exe.exists():
            return str(exe)
        raise GwsError(
            f"`gws` đang trỏ tới {path} (file .cmd của npm). Hãy đặt biến GWS_BIN trỏ tới gws.exe "
            "(tải tại https://github.com/googleworkspace/cli/releases)."
        )
    return path


def _bin() -> str:
    global _GWS_BIN
    if _GWS_BIN is None:
        _GWS_BIN = find_gws()
    return _GWS_BIN


def _error_message(stdout: str, stderr: str, code: int) -> str:
    message = ""
    try:
        err = json.loads(stdout).get("error", {})
        message = err.get("message", "")
        if err.get("reason"):
            message += f" ({err['reason']})"
    except (ValueError, AttributeError):
        pass
    if not message:
        message = (stderr or stdout).strip() or f"gws thoát với mã {code}"
    if code == 2:
        message += "\n→ Chạy `gws auth login -s drive,docs,sheets` rồi thử lại."
    return message


def gws(
    *args: str,
    params: dict | None = None,
    body: dict | None = None,
    upload: str | Path | None = None,
    page_all: bool = False,
):
    """Chạy `gws <args>` và trả về JSON đã parse.

    Với page_all=True, gws tự lật trang và in mỗi trang một dòng JSON; hàm trả về list các trang.
    """
    cmd = [_bin(), *args]
    if params is not None:
        cmd += ["--params", json.dumps(params, ensure_ascii=False)]
    if body is not None:
        cmd += ["--json", json.dumps(body, ensure_ascii=False)]
    if upload is not None:
        cmd += ["--upload", str(upload)]
    if page_all:
        cmd += ["--page-all", "--page-limit", "100"]

    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    out = proc.stdout.strip()
    if proc.returncode != 0:
        raise GwsError(_error_message(out, proc.stderr, proc.returncode), proc.returncode)
    if page_all:
        return [json.loads(line) for line in out.splitlines() if line.strip()]
    return json.loads(out) if out else {}


# ---------------------------------------------------------------------------
# Drive
# ---------------------------------------------------------------------------


def q_quote(value: str) -> str:
    """Đặt chuỗi vào dấu nháy đơn cho câu truy vấn Drive (thoát \\ và ')."""
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def list_children(parent_id: str, name: str | None = None, mime_type: str | None = None) -> list[dict]:
    """Liệt kê file/thư mục (chưa xoá) nằm trực tiếp trong parent_id."""
    clauses = [f"{q_quote(parent_id)} in parents", "trashed = false"]
    if name is not None:
        clauses.append(f"name = {q_quote(name)}")
    if mime_type is not None:
        clauses.append(f"mimeType = {q_quote(mime_type)}")
    pages = gws(
        "drive", "files", "list",
        params={
            "q": " and ".join(clauses),
            "pageSize": 1000,
            "fields": "nextPageToken,files(id,name,mimeType)",
            "supportsAllDrives": True,
            "includeItemsFromAllDrives": True,
        },
        page_all=True,
    )
    return [f for page in pages for f in page.get("files", [])]


def create_folder(name: str, parent_id: str) -> dict:
    return gws(
        "drive", "files", "create",
        params={"fields": "id,name", "supportsAllDrives": True},
        body={"name": name, "mimeType": FOLDER_MIME, "parents": [parent_id]},
    )


def upload_file(path: str | Path, parent_id: str, name: str | None = None) -> dict:
    args = ["drive", "+upload", str(path), "--parent", parent_id]
    if name:
        args += ["--name", name]
    return gws(*args)


def get_file(file_id: str, fields: str = "id,name,mimeType,parents") -> dict:
    return gws(
        "drive", "files", "get",
        params={"fileId": file_id, "fields": fields, "supportsAllDrives": True},
    )


def folder_link(folder_id: str) -> str:
    return f"https://drive.google.com/drive/folders/{folder_id}"


def doc_link(doc_id: str) -> str:
    return f"https://docs.google.com/document/d/{doc_id}/edit"
