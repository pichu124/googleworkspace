"""Test hai script với `gws` giả lập (tests/fake_gws.py).

Chạy:  python -m unittest discover -s tests -v
Thêm REAL_GWS=$(which gws) để mỗi lệnh còn được gws thật kiểm tra cú pháp bằng --dry-run.
"""

import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
FAKE = Path(__file__).resolve().parent / "fake_gws.py"
sys.path.insert(0, str(SCRIPTS))

import tao_tai_lieu_tu_mau as tl  # noqa: E402


class FakeDriveTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.state = self.tmp / "state.json"
        self.log = self.tmp / "log.jsonl"
        FAKE.chmod(FAKE.stat().st_mode | stat.S_IXUSR)
        self.env = {
            **os.environ,
            "GWS_BIN": str(FAKE),
            "FAKE_GWS_STATE": str(self.state),
            "FAKE_GWS_LOG": str(self.log),
            "PYTHONIOENCODING": "utf-8",
        }

    def run_script(self, script, *args, expect=0):
        proc = subprocess.run(
            [sys.executable, str(SCRIPTS / script), *args],
            capture_output=True, text=True, encoding="utf-8", env=self.env, stdin=subprocess.DEVNULL,
        )
        self.assertEqual(proc.returncode, expect, proc.stdout + proc.stderr)
        return proc.stdout + proc.stderr

    def drive(self):
        return json.loads(self.state.read_text(encoding="utf-8")) if self.state.exists() else {"files": {}, "perms": {}}

    def calls(self):
        if not self.log.exists():
            return []
        return [json.loads(line) for line in self.log.read_text(encoding="utf-8").splitlines()]

    def children(self, parent, files=None):
        files = files or self.drive()["files"]
        return {f["name"]: f for f in files.values() if parent in f["parents"]}

    def find_path(self, *names, files=None):
        """Đi từ My Drive theo từng tên thư mục, trả về file/thư mục cuối."""
        node = {"id": "root"}
        for name in names:
            node = self.children(node["id"], files)[name]
        return node


class TaoHoSoTest(FakeDriveTest):
    CFG = str(ROOT / "cau_hinh" / "ho_so_chao_ban_cdhh.json")
    DOSSIER = "Tài liệu PDR - Phát hành thêm cổ phiếu cho cổ đông hiện hữu _19052026"
    PARENT = ("01. Công việc", "1. Đang làm", "PDR - Chào bán cho CĐHH 2026")

    def test_chay_thu_khong_goi_drive(self):
        out = self.run_script("tao_ho_so.py", self.CFG, "--bien", "MA_CK=PDR", "--bien", "NGAY=19052026",
                              "--bien", "NAM=2026", "--chay-thu")
        self.assertIn("Sẽ tạo trong My Drive / 01. Công việc / 1. Đang làm / PDR - Chào bán cho CĐHH 2026", out)
        self.assertIn(self.DOSSIER, out)
        self.assertIn("10.PDR- Điều lệ công ty", out)
        self.assertEqual(self.calls(), [])

    def test_duong_dan_cha_dung_lai_thu_muc_co_san(self):
        # Thư mục "01. Công việc" đã có sẵn (do người dùng tạo) → dùng lại, chỉ tạo các cấp còn thiếu.
        self.run_script("tao_ho_so.py", str(self.write_cfg({"ten_thu_muc_goc": "01. Công việc"})), "--dong-y")
        out = self.run_script("tao_ho_so.py", self.CFG, "--bien", "MA_CK=PDR", "--bien", "NGAY=19052026",
                              "--bien", "NAM=2026", "--dong-y")
        self.assertIn("= Đã có: 01. Công việc", out)
        self.assertIn("+ Tạo mới: 01. Công việc / 1. Đang làm", out)
        self.assertEqual(set(self.children("root")), {"01. Công việc"})
        self.find_path(*self.PARENT, self.DOSSIER, "Quyển 1/3", "10.PDR- Điều lệ công ty")

    def test_thu_muc_cha_ghi_de_duong_dan_cha(self):
        self.run_script("tao_ho_so.py", str(self.write_cfg({"ten_thu_muc_goc": "Đích"})), "--dong-y")
        target = self.find_path("Đích")["id"]
        self.run_script("tao_ho_so.py", self.CFG, "--bien", "MA_CK=PDR", "--bien", "NGAY=19052026",
                        "--thu-muc-cha", target, "--dong-y")
        self.find_path("Đích", self.DOSSIER)
        self.assertNotIn("01. Công việc", self.children("root"))

    def write_cfg(self, cfg):
        path = self.tmp / f"cfg{len(list(self.tmp.glob('cfg*')))}.json"
        path.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
        return path

    def test_thieu_bien(self):
        out = self.run_script("tao_ho_so.py", self.CFG, "--chay-thu", expect=1)
        self.assertIn("Thiếu biến MA_CK", out)

    def test_khong_co_ban_phim_thi_khong_chay(self):
        out = self.run_script("tao_ho_so.py", self.CFG, "--bien", "MA_CK=PDR", expect=1)
        self.assertIn("--dong-y", out)
        self.assertEqual(self.calls(), [])

    def test_tao_local_doi_dau_gach_cheo(self):
        base = self.tmp / "local"
        self.run_script("tao_ho_so.py", self.CFG, "--bien", "MA_CK=PDR", "--tao-local", str(base))
        self.assertTrue((base / "Quyển 1-3" / "10.PDR- Điều lệ công ty").is_dir())
        self.assertTrue((base / "Quyển 3-3").is_dir())
        self.assertEqual(self.calls(), [])

    def test_tao_tai_len_chia_se_va_chay_lai(self):
        base = self.tmp / "local"
        self.run_script("tao_ho_so.py", self.CFG, "--bien", "MA_CK=PDR", "--tao-local", str(base))
        (base / "Quyển 3-3" / "3. BCTC rieng kiem toan 2025.pdf").write_bytes(b"%PDF")
        (base / "Quyển 3-3" / ".DS_Store").write_bytes(b"x")
        (base / "ghi-chu.txt").write_text("x", encoding="utf-8")
        (base / "Thu muc la").mkdir()
        (base / "Thu muc la" / "a.pdf").write_bytes(b"x")
        ids = self.tmp / "ids.json"

        out = self.run_script(
            "tao_ho_so.py", self.CFG, "--bien", "MA_CK=PDR", "--bien", "NGAY=19052026", "--bien", "NAM=2026",
            "--tai-len", str(base), "--chia-se", "dongnghiep@gmail.com:sua",
            "--chia-se", "ai.do@khong-ton-tai.invalid", "--luu-id", str(ids), "--dong-y", expect=1,
        )
        self.assertIn("Thu muc la", out)  # cảnh báo thư mục lệch cấu hình
        self.assertIn("Không chia sẻ được cho ai.do@khong-ton-tai.invalid", out)

        files = self.drive()["files"]
        root = self.find_path(*self.PARENT, self.DOSSIER, files=files)
        top = self.children(root["id"], files)
        self.assertEqual(
            set(top),
            {"00. Mới nhận", "Quyển 1/3", "Quyển 2/3", "Quyển 3/3", "ghi-chu.txt"},
        )
        bctc = self.children(top["Quyển 3/3"]["id"], files)
        self.assertEqual(set(bctc), {"3. BCTC rieng kiem toan 2025.pdf"})
        perms = self.drive()["perms"][root["id"]]
        self.assertEqual([(p["emailAddress"], p["role"], p["notify"]) for p in perms],
                         [("dongnghiep@gmail.com", "writer", False)])
        saved = json.loads(ids.read_text(encoding="utf-8"))
        self.assertEqual(saved["thu_muc_goc"]["id"], root["id"])
        self.assertEqual(saved["thu_muc"]["Quyển 1/3 / 10.PDR- Điều lệ công ty"],
                         self.children(top["Quyển 1/3"]["id"], files)["10.PDR- Điều lệ công ty"]["id"])

        # Chạy lại: không tạo trùng thư mục, không tải lại file, không chia sẻ lại.
        before = len(files)
        out = self.run_script(
            "tao_ho_so.py", self.CFG, "--bien", "MA_CK=PDR", "--bien", "NGAY=19052026", "--bien", "NAM=2026",
            "--tai-len", str(base), "--chia-se", "dongnghiep@gmail.com:writer", "--dong-y",
        )
        self.assertEqual(len(self.drive()["files"]), before)
        self.assertIn("Bỏ qua (đã có)", out)
        self.assertIn("đã có quyền writer", out)
        self.assertNotIn("Tạo mới", out)

    def test_ten_co_dau_nhay_don(self):
        cfg = self.tmp / "cfg.json"
        cfg.write_text(json.dumps({"ten_thu_muc_goc": "{TEN_KH}", "thu_muc_con": [{"ten": "A\\B"}]}), encoding="utf-8")
        for _ in range(2):
            self.run_script("tao_ho_so.py", str(cfg), "--bien", "TEN_KH=Nhà O'Neil", "--dong-y")
        roots = [f for f in self.drive()["files"].values() if f["name"] == "Nhà O'Neil"]
        self.assertEqual(len(roots), 1)
        self.assertEqual(list(self.children(roots[0]["id"])), ["A\\B"])


class KiemTraChiaSeTest(FakeDriveTest):
    def seed(self):
        """Thư mục H có 2 file mở link công khai và 1 file riêng tư; ngoài H có thêm 1 file công khai."""
        state = {
            "files": {
                "root": {"id": "root", "name": "My Drive", "mimeType": "application/vnd.google-apps.folder", "parents": []},
                "H": {"id": "H", "name": "Hộ chiếu", "mimeType": "application/vnd.google-apps.folder", "parents": ["root"]},
                "a": {"id": "a", "name": "Hochieu_A.pdf", "mimeType": "application/pdf", "parents": ["H"]},
                "b": {"id": "b", "name": "Hochieu_B.pdf", "mimeType": "application/pdf", "parents": ["H"]},
                "c": {"id": "c", "name": "Riêng tư.pdf", "mimeType": "application/pdf", "parents": ["H"]},
                "d": {"id": "d", "name": "Bài thuyết trình.pdf", "mimeType": "application/pdf", "parents": ["root"]},
            },
            "perms": {
                "a": [{"id": "anyoneWithLink", "type": "anyone", "role": "reader"},
                      {"id": "p1", "type": "user", "role": "writer", "emailAddress": "dongnghiep@gmail.com"}],
                "b": [{"id": "anyoneWithLink", "type": "anyone", "role": "reader"}],
                "c": [{"id": "p2", "type": "user", "role": "reader", "emailAddress": "x@gmail.com"}],
                "d": [{"id": "anyoneWithLink", "type": "anyone", "role": "reader"}],
            },
        }
        self.state.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")

    def test_liet_ke_khong_doi_gi(self):
        self.seed()
        out = self.run_script("kiem_tra_chia_se.py")
        self.assertIn("3 file đang mở link công khai", out)
        self.assertIn("Bài thuyết trình.pdf", out)
        self.assertNotIn("Riêng tư.pdf", out)
        self.assertFalse(any(c[:3] == ["drive", "permissions", "delete"] for c in self.calls()))

    def test_tat_trong_mot_thu_muc(self):
        self.seed()
        self.run_script("kiem_tra_chia_se.py", "--thu-muc", "H", "--tat", expect=1)  # không có bàn phím → huỷ
        self.assertEqual(len(self.drive()["perms"]["a"]), 2)

        out = self.run_script("kiem_tra_chia_se.py", "--thu-muc", "H", "--tat", "--dong-y")
        self.assertIn("tắt 2/2 file", out)
        perms = self.drive()["perms"]
        self.assertEqual([p["id"] for p in perms["a"]], ["p1"])  # quyền đích danh vẫn giữ
        self.assertEqual(perms["b"], [])
        self.assertEqual(len(perms["d"]), 1)  # file ngoài thư mục không bị đụng tới

        out = self.run_script("kiem_tra_chia_se.py", "--thu-muc", "H")
        self.assertIn("Không có file nào", out)


class TaoTaiLieuTest(FakeDriveTest):
    HTML = str(ROOT / "mau" / "tong_quan_doanh_nghiep.html")
    DATA = str(ROOT / "du_lieu" / "vi_du_tong_quan.json")
    NAME = "{TEN_VIET_TAT}_Tong_quan_doanh_nghiep_{THANG}"

    def make_template(self):
        self.run_script("tao_tai_lieu_tu_mau.py", "tao-mau", self.HTML, "--ten", "MẪU - Tổng quan")
        return next(f["id"] for f in self.drive()["files"].values() if f["name"] == "MẪU - Tổng quan")

    def test_mau_va_du_lieu_vi_du_khop_nhau(self):
        tid = self.make_template()
        out = self.run_script("tao_tai_lieu_tu_mau.py", "tao", "--mau", tid, "--du-lieu", self.DATA,
                              "--ten", self.NAME, "--chay-thu")
        self.assertNotIn("Thiếu dữ liệu", out)
        self.assertNotIn("Dữ liệu không dùng tới", out)  # TEN_VIET_TAT chỉ dùng trong tên file
        self.assertFalse(any(c[:3] == ["drive", "files", "copy"] for c in self.calls()))

    def test_tao_tai_lieu_tu_json(self):
        tid = self.make_template()
        out = self.run_script("tao_tai_lieu_tu_mau.py", "tao", "--mau", tid, "--du-lieu", self.DATA, "--ten", self.NAME)
        self.assertNotIn("Còn", out)
        doc = next(f for f in self.drive()["files"].values() if f["name"].startswith("ABCGroup_Tong_quan_doanh_nghiep_"))
        self.assertEqual(doc["parents"], ["root"])
        text = doc["text"]
        self.assertNotIn("{{", text)
        self.assertIn("Công ty Cổ phần Tập đoàn ABC (ví dụ)", text)
        self.assertIn("1.340,5", text)  # 1340.5 → kiểu Việt Nam
        self.assertIn("2025", text)
        self.assertIn("Chủ tịch HĐQT: Ông Nguyễn Văn A\nTổng Giám đốc: Bà Trần Thị B", text)

        # Chạy lại cùng tên → dừng, không tạo bản trùng.
        out = self.run_script("tao_tai_lieu_tu_mau.py", "tao", "--mau", tid, "--du-lieu", self.DATA,
                              "--ten", self.NAME, expect=1)
        self.assertIn("Đã có file", out)

    def test_tao_tai_lieu_tu_sheet_thieu_du_lieu(self):
        tid = self.make_template()
        state = self.drive()
        state["sheets"]["S1"] = [
            ["Trường", "Giá trị"],
            ["TEN_CONG_TY", "Công ty X"],
            ["NAM", "2021", "2022", "2023", "2024", "2025"],
            ["DOANH_THU", "1.000", "1.100", "", "1.300", "1.400"],
            [],
            ["Tên có dấu", "x"],
        ]
        self.state.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        folder = self.tmp.name  # thư mục đích không tồn tại → lỗi rõ ràng
        out = self.run_script("tao_tai_lieu_tu_mau.py", "tao", "--mau", tid, "--sheet", "S1",
                              "--ten", "X_{NAM_5}", "--thu-muc", folder, expect=1)
        self.assertIn("Lỗi từ gws", out)

        out = self.run_script("tao_tai_lieu_tu_mau.py", "tao", "--mau", tid, "--sheet", "S1", "--ten", "X_{NAM_5}")
        self.assertIn("Tên có dấu", out)
        self.assertIn("Thiếu dữ liệu", out)
        self.assertIn("Còn", out)
        doc = next(f for f in self.drive()["files"].values() if f["name"] == "X_2025")
        self.assertIn("Công ty X", doc["text"])
        self.assertIn("1.300", doc["text"])
        self.assertIn("{{LNST_1}}", doc["text"])

    def test_mau_khong_phai_google_docs(self):
        self.run_script("tao_ho_so.py", str(ROOT / "cau_hinh" / "tham_dinh_doanh_nghiep.json"),
                        "--bien", "TEN_KH=X", "--dong-y")
        folder_id = next(f["id"] for f in self.drive()["files"].values() if f["name"].startswith("X - "))
        out = self.run_script("tao_tai_lieu_tu_mau.py", "tao", "--mau", folder_id, "--du-lieu", self.DATA,
                              "--ten", "x", expect=1)
        self.assertIn("không phải Google Docs", out)


class DuLieuTest(unittest.TestCase):
    def test_dinh_dang_so(self):
        self.assertEqual(tl.format_number_vn(1160), "1.160")
        self.assertEqual(tl.format_number_vn(732.7), "732,7")
        self.assertEqual(tl.format_number_vn(-1234567.25), "-1.234.567,25")
        self.assertEqual(tl.format_value(["a", 1000, None]), "a\n1.000\n")

    def test_flatten_json(self):
        data = tl.flatten_json({"_ghi_chu": "x", "A": "1", "B": ["x", "y"],
                                "BANG": {"_c": "z", "DT": [1, 2000], "NAM": "2025"}})
        self.assertEqual(data, {"A": "1", "B": "x\ny", "DT_1": "1", "DT_2": "2.000", "NAM_1": "2025"})

    def test_rows_to_data(self):
        rows = [["key", "value"], ["A", "1"], ["B"], ["C", "1", "2", "", ""], ["", "bỏ"]]
        self.assertEqual(tl.rows_to_data(rows), {"A": "1", "B": "", "C_1": "1", "C_2": "2"})

    def test_collect_text(self):
        doc = {"tabs": [{"documentTab": {"body": {"content": [
            {"paragraph": {"elements": [{"textRun": {"content": "{{A"}}, {"textRun": {"content": "B}}"}}]}},
            {"table": {"tableRows": [{"tableCells": [{"content": [
                {"paragraph": {"elements": [{"textRun": {"content": "{{C}}"}}]}}]}]}]}},
        ]}}}]}
        parts = []
        tl.collect_text(doc, parts)
        self.assertEqual(tl.PLACEHOLDER.findall("".join(parts)), ["AB", "C"])


if __name__ == "__main__":
    unittest.main()
