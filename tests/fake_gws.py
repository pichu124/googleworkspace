#!/usr/bin/env python3
"""`gws` giả lập để test script mà không cần tài khoản Google.

Trạng thái Drive/Docs/Sheets lưu trong file JSON (biến FAKE_GWS_STATE); mọi lệnh được ghi vào
FAKE_GWS_LOG. Nếu đặt REAL_GWS=<đường dẫn gws thật>, mỗi lệnh còn được chạy thử bằng gws thật
với --dry-run để chắc cú pháp lệnh hợp lệ.
"""

import json
import os
import re
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path

FOLDER = "application/vnd.google-apps.folder"
DOC = "application/vnd.google-apps.document"


class _Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self._skip = False

    def handle_starttag(self, tag, attrs):
        self._skip = tag in ("style", "title")

    def handle_endtag(self, tag):
        self._skip = False
        if tag in ("p", "li", "td", "th", "h1", "h2", "tr"):
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    p = _Text()
    p.feed(html)
    return "".join(p.parts)


def unq(s):
    return s.replace("\\'", "'").replace("\\\\", "\\")


QUOTED = r"'((?:[^'\\]|\\.)*)'"


def main(argv):
    state_path = Path(os.environ["FAKE_GWS_STATE"])
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    state.setdefault("files", {"root": {"id": "root", "name": "My Drive", "mimeType": FOLDER, "parents": []}})
    state.setdefault("perms", {})
    state.setdefault("sheets", {})
    state.setdefault("next", 1)

    with open(os.environ["FAKE_GWS_LOG"], "a", encoding="utf-8") as log:
        log.write(json.dumps(argv, ensure_ascii=False) + "\n")

    real = os.environ.get("REAL_GWS")
    if real:
        proc = subprocess.run([real, *argv, "--dry-run"], capture_output=True, text=True)
        if proc.returncode != 0:
            print(json.dumps({"error": {"code": 400, "message": f"real gws dry-run rejected: {proc.stdout} {proc.stderr}"}}))
            return 3

    opts, pos, i = {}, [], 0
    while i < len(argv):
        a = argv[i]
        if a in ("--params", "--json", "--upload", "--parent", "--name", "--page-limit"):
            opts[a] = argv[i + 1]
            i += 2
        elif a.startswith("--"):
            opts[a] = True
            i += 1
        else:
            pos.append(a)
            i += 1
    params = json.loads(opts.get("--params", "{}"))
    body = json.loads(opts.get("--json", "{}"))
    files = state["files"]

    def new_id(prefix):
        state["next"] += 1
        return f"{prefix}{state['next']}"

    def out(obj):
        print(json.dumps(obj, ensure_ascii=False))

    def fail(code, msg, exit_code=1):
        out({"error": {"code": code, "message": msg}})
        return exit_code

    cmd = tuple(pos)
    rc = 0
    if cmd == ("drive", "files", "list"):
        q = params["q"]
        parent = re.search(QUOTED + r" in parents", q)
        name = re.search(r"name = " + QUOTED, q)
        mime = re.search(r"mimeType = " + QUOTED, q)
        hits = [
            {"id": f["id"], "name": f["name"], "mimeType": f["mimeType"]}
            for f in files.values()
            if f["id"] != "root"
            and (not parent or unq(parent.group(1)) in f["parents"])
            and (not name or f["name"] == unq(name.group(1)))
            and (not mime or f["mimeType"] == unq(mime.group(1)))
        ]
        out({"files": hits})
    elif cmd == ("drive", "files", "create"):
        parents = body.get("parents", ["root"])
        if parents[0] not in files:
            rc = fail(404, f"File not found: {parents[0]}")
        else:
            fid = new_id("doc" if body.get("mimeType") == DOC else "f")
            f = {"id": fid, "name": body["name"], "mimeType": body.get("mimeType", "application/octet-stream"), "parents": parents}
            if "--upload" in opts and f["mimeType"] == DOC:
                f["text"] = html_to_text(Path(opts["--upload"]).read_text(encoding="utf-8"))
            files[fid] = f
            out({"id": fid, "name": f["name"]})
    elif cmd[:2] == ("drive", "+upload"):
        parent = opts.get("--parent", "root")
        fid = new_id("u")
        files[fid] = {"id": fid, "name": opts.get("--name") or Path(pos[2]).name, "mimeType": "application/pdf", "parents": [parent]}
        out({"kind": "drive#file", "id": fid, "name": files[fid]["name"]})
    elif cmd == ("drive", "files", "get"):
        f = files.get(params["fileId"])
        if not f:
            rc = fail(404, "File not found")
        else:
            out({k: f[k] for k in ("id", "name", "mimeType", "parents")})
    elif cmd == ("drive", "files", "copy"):
        src = files.get(params["fileId"])
        if not src or any(p not in files for p in body.get("parents", [])):
            rc = fail(404, "File not found")
        else:
            fid = new_id("doc")
            files[fid] = {**src, "id": fid, "name": body.get("name", "Copy of " + src["name"]),
                          "parents": body.get("parents", src["parents"])}
            out({"id": fid, "name": files[fid]["name"]})
    elif cmd == ("drive", "permissions", "list"):
        out({"permissions": state["perms"].get(params["fileId"], [])})
    elif cmd == ("drive", "permissions", "create"):
        if body["emailAddress"].endswith("@khong-ton-tai.invalid"):
            rc = fail(400, "No Google account for this email")
        else:
            perm = {"id": new_id("p"), "emailAddress": body["emailAddress"], "role": body["role"],
                    "notify": params.get("sendNotificationEmail")}
            state["perms"].setdefault(params["fileId"], []).append(perm)
            out({"id": perm["id"]})
    elif cmd == ("docs", "documents", "get"):
        text = files[params["documentId"]]["text"]
        # Cắt chữ thành nhiều textRun, cố ý cắt ngang chỗ trống để thử việc ghép chữ.
        runs = [{"textRun": {"content": text[i:i + 7]}} for i in range(0, len(text), 7)]
        out({"documentId": params["documentId"],
             "tabs": [{"documentTab": {"body": {"content": [{"paragraph": {"elements": runs}}]}}}]})
    elif cmd == ("docs", "documents", "batchUpdate"):
        f = files[params["documentId"]]
        replies = []
        for req in body["requests"]:
            r = req["replaceAllText"]
            needle = r["containsText"]["text"]
            n = f["text"].count(needle)
            f["text"] = f["text"].replace(needle, r["replaceText"])
            replies.append({"replaceAllText": {"occurrencesChanged": n}} if n else {"replaceAllText": {}})
        out({"documentId": f["id"], "replies": replies})
    elif cmd == ("sheets", "spreadsheets", "values", "get"):
        out({"range": params["range"], "values": state["sheets"][params["spreadsheetId"]]})
    else:
        rc = fail(400, f"fake gws: unsupported command {cmd}", 3)

    state_path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
