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


class TaoHoSoTest(FakeDriveTest):
    CFG = str(ROOT / "cau_hinh" / "ho_so_chao_ban_cdhh.json")

    def test_chay_thu_khong_goi_drive(self):
        out = self.run_script("tao_ho_so.py", self.CFG, "--bien", "MA_CK=PDR", "--bien", "NGAY=19052026", "--chay-thu")
        self.assertIn("Tài liệu PDR - Phát hành thêm cổ phiếu cho cổ đông hiện hữu _19052026", out)
        self.assertIn("05. PDR - Điều lệ công ty", out)
        self.assertEqual(self.calls(), [])

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
        self.assertTrue((base / "Quyển 1-3" / "02. Bản cáo bạch").is_dir())
        self.assertTrue((base / "00. Danh mục hồ sơ").is_dir())
        self.assertEqual(self.calls(), [])

    def test_tao_tai_len_chia_se_va_chay_lai(self):
        base = self.tmp / "local"
        self.run_script("tao_ho_so.py", self.CFG, "--bien", "MA_CK=PDR", "--tao-local", str(base))
        (base / "Quyển 3-3" / "01. BCTC riêng đã kiểm toán" / "BCTC-Rieng-2025.pdf").write_bytes(b"%PDF")
        (base / "Quyển 3-3" / "01. BCTC riêng đã kiểm toán" / ".DS_Store").write_bytes(b"x")
        (base / "ghi-chu.txt").write_text("x", encoding="utf-8")
        (base / "Thu muc la").mkdir()
        (base / "Thu muc la" / "a.pdf").write_bytes(b"x")
        ids = self.tmp / "ids.json"

        out = self.run_script(
            "tao_ho_so.py", self.CFG, "--bien", "MA_CK=PDR", "--bien", "NGAY=19052026",
            "--tai-len", str(base), "--chia-se", "dongnghiep@gmail.com:sua",
            "--chia-se", "ai.do@khong-ton-tai.invalid", "--luu-id", str(ids), "--dong-y", expect=1,
        )
        self.assertIn("Thu muc la", out)  # cảnh báo thư mục lệch cấu hình
        self.assertIn("Không chia sẻ được cho ai.do@khong-ton-tai.invalid", out)

        files = self.drive()["files"]
        root = self.children("root", files)["Tài liệu PDR - Phát hành thêm cổ phiếu cho cổ đông hiện hữu _19052026"]
        top = self.children(root["id"], files)
        self.assertEqual(
            set(top),
            {"00. Danh mục hồ sơ", "Quyển 1/3", "Quyển 2/3", "Quyển 3/3", "99. Nháp và trao đổi nội bộ", "ghi-chu.txt"},
        )
        bctc = self.children(self.children(top["Quyển 3/3"]["id"], files)["01. BCTC riêng đã kiểm toán"]["id"], files)
        self.assertEqual(set(bctc), {"BCTC-Rieng-2025.pdf"})
        perms = self.drive()["perms"][root["id"]]
        self.assertEqual([(p["emailAddress"], p["role"], p["notify"]) for p in perms],
                         [("dongnghiep@gmail.com", "writer", False)])
        saved = json.loads(ids.read_text(encoding="utf-8"))
        self.assertEqual(saved["thu_muc_goc"]["id"], root["id"])
        self.assertEqual(saved["thu_muc"]["Quyển 2/3 / 02. Hợp đồng"],
                         self.children(top["Quyển 2/3"]["id"], files)["02. Hợp đồng"]["id"])

        # Chạy lại: không tạo trùng thư mục, không tải lại file, không chia sẻ lại.
        before = len(files)
        out = self.run_script(
            "tao_ho_so.py", self.CFG, "--bien", "MA_CK=PDR", "--bien", "NGAY=19052026",
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
        self.assertIn("ℹ Dữ liệu không dùng tới (1): TEN_VIET_TAT", out)
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
