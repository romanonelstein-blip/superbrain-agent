"""Regression tests for the dependency-free credential signature audit."""
import io
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
from sys import path as sys_path

sys_path.insert(0, str(Path(__file__).resolve().parent))
from secret_audit import detect, scan_archive, scan_repo  # noqa: E402


class SecretAuditTests(unittest.TestCase):
    def test_detect_does_not_expose_credential_value(self):
        fake = b"ghp_" + b"a" * 35
        self.assertEqual(detect(fake), ["GitHub credential"])
        self.assertNotIn(fake.decode(), str(detect(fake)))

    def test_safe_text_no_detection(self):
        self.assertEqual(detect(b"# public project; no keys embedded"), [])

    def test_zip_member_scanned(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("config.txt", b"AKIA" + b"A" * 16)
        findings, errors = scan_archive(buffer.getvalue(), "build.zip")
        self.assertEqual(len(findings), 1)
        self.assertEqual(errors, [])
        self.assertNotIn("AKIA", str(findings))

    def test_unreadable_zip_fails_closed(self):
        findings, errors = scan_archive(b"not-a-zip", "broken.zip")
        self.assertEqual(findings, [])
        self.assertEqual(len(errors), 1)

    def test_untracked_not_reported(self):
        import subprocess
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            (repo / "safe.txt").write_text("ordinary documentation")
            (repo / "ignored.txt").write_text("ghp_" + "a" * 35)
            subprocess.run(["git", "add", "safe.txt"], cwd=repo, check=True)
            findings, errors = scan_repo(repo)
            self.assertEqual(findings, [])
            self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
