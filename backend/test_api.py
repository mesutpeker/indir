"""Unit and integration tests for the video downloader backend."""

from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import app as app_module
from config import Settings
from downloader import validate_and_detect_platform

TEST_API_KEY = "super-secret-test-key-12345"


class PlatformValidationTests(unittest.TestCase):
    def test_accepts_supported_platforms(self) -> None:
        cases = [
            ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "youtube"),
            ("https://youtu.be/dQw4w9WgXcQ", "youtube"),
            ("https://x.com/user/status/1234567890", "twitter"),
            ("https://twitter.com/user/status/1234567890", "twitter"),
            ("https://www.instagram.com/reel/ABC123/", "instagram"),
            ("https://www.facebook.com/watch/?v=123456", "facebook"),
            ("https://fb.watch/abc123/", "facebook"),
        ]
        for url, expected_platform in cases:
            normalized, platform = validate_and_detect_platform(url)
            self.assertEqual(normalized, url)
            self.assertEqual(platform, expected_platform)

    def test_rejects_unsafe_and_unsupported_urls(self) -> None:
        bad_urls = [
            "file:///etc/passwd",
            "http://127.0.0.1:8000/secret",
            "http://localhost:8000",
            "http://169.254.169.254/latest/meta-data/",
            "http://192.168.1.10/video.mp4",
            "https://example.com/video.mp4",
            "not-a-url",
        ]
        for url in bad_urls:
            with self.assertRaises(ValueError, msg=f"Expected ValueError for {url}"):
                validate_and_detect_platform(url)


class ApiLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.download_dir = Path(self.tmp_dir.name) / "downloads"
        self.settings = Settings(
            api_key=TEST_API_KEY,
            require_api_key=True,
            allowed_origins=["https://indir.mesutpeker.com"],
            download_dir=self.download_dir,
            file_ttl_seconds=300,
            max_concurrent_jobs=2,
            max_filesize_mb=500,
        )
        self.client_cm = TestClient(app_module.create_app(self.settings))
        self.client = self.client_cm.__enter__()

    def tearDown(self) -> None:
        self.client_cm.__exit__(None, None, None)
        self.tmp_dir.cleanup()

    def test_health_is_public(self) -> None:
        resp = self.client.get("/api/health")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "ok")
        self.assertIn("yt_dlp_version", data)
        self.assertIsInstance(data["ffmpeg"], bool)
        self.assertIsInstance(data["js_runtimes"], list)

    def test_auth_protection(self) -> None:
        for method, path, body in [
            ("GET", "/api/auth/verify", None),
            ("POST", "/api/info", {"url": "https://youtu.be/abc"}),
            ("POST", "/api/jobs", {"url": "https://youtu.be/abc", "preset": "best_mp4"}),
        ]:
            no_key = self.client.request(method, path, json=body)
            self.assertEqual(no_key.status_code, 401)
            wrong_key = self.client.request(
                method, path, json=body, headers={"X-API-Key": "wrong-key"}
            )
            self.assertEqual(wrong_key.status_code, 401)

        ok = self.client.get("/api/auth/verify", headers={"X-API-Key": TEST_API_KEY})
        self.assertEqual(ok.status_code, 200)
        self.assertTrue(ok.json()["ok"])

    def test_cors_preflight_allows_only_configured_origin(self) -> None:
        allowed = self.client.options(
            "/api/info",
            headers={
                "Origin": "https://indir.mesutpeker.com",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Content-Type, X-API-Key",
            },
        )
        self.assertEqual(
            allowed.headers.get("access-control-allow-origin"),
            "https://indir.mesutpeker.com",
        )

        disallowed = self.client.options(
            "/api/info",
            headers={
                "Origin": "https://evil.example",
                "Access-Control-Request-Method": "POST",
            },
        )
        self.assertIsNone(disallowed.headers.get("access-control-allow-origin"))

    def test_mocked_video_info(self) -> None:
        mock_meta = {
            "platform": "youtube",
            "platform_label": "YouTube",
            "id": "abc123",
            "title": "Örnek Video Başlığı",
            "uploader": "Mesut Kanalı",
            "duration": 125,
            "thumbnail": "https://i.ytimg.com/vi/abc123/hqdefault.jpg",
            "webpage_url": "https://www.youtube.com/watch?v=abc123",
            "extractor": "Youtube",
        }
        with patch("app.fetch_video_info", return_value=mock_meta):
            resp = self.client.post(
                "/api/info",
                headers={"X-API-Key": TEST_API_KEY},
                json={"url": "https://www.youtube.com/watch?v=abc123"},
            )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["info"]["title"], "Örnek Video Başlığı")
        self.assertEqual(data["info"]["platform"], "youtube")
        self.assertTrue(len(data["presets"]) >= 5)

    def test_full_async_download_lifecycle(self) -> None:
        sample_bytes = b"FAKE-MP4-BINARY-CONTENT-1234567890"
        turkish_filename = "Örnek Video Çağrı [abc123].mp4"

        def fake_download(url, preset, job_dir, settings, progress_cb, cancel_event=None):
            job_dir.mkdir(parents=True, exist_ok=True)
            progress_cb({"status": "downloading", "progress": 50.0, "speed": "2.4 MB/s", "eta": 2})
            out_file = job_dir / turkish_filename
            out_file.write_bytes(sample_bytes)
            return {
                "filepath": out_file,
                "filename": turkish_filename,
                "filesize": len(sample_bytes),
                "title": "Örnek Video Çağrı",
            }

        with patch("app.download_video", side_effect=fake_download):
            create_resp = self.client.post(
                "/api/jobs",
                headers={"X-API-Key": TEST_API_KEY},
                json={"url": "https://x.com/user/status/12345", "preset": "best_mp4"},
            )
            self.assertEqual(create_resp.status_code, 202)
            job_id = create_resp.json()["id"]

            snapshot = None
            for _ in range(30):
                poll_resp = self.client.get(
                    f"/api/jobs/{job_id}",
                    headers={"X-API-Key": TEST_API_KEY},
                )
                self.assertEqual(poll_resp.status_code, 200)
                snapshot = poll_resp.json()
                if snapshot["status"] == "ready":
                    break
                time.sleep(0.05)

            self.assertIsNotNone(snapshot)
            self.assertEqual(snapshot["status"], "ready")
            token = snapshot.get("download_token")
            self.assertTrue(token)

            bad_file = self.client.get(f"/api/jobs/{job_id}/file?token=wrong-token-value")
            self.assertEqual(bad_file.status_code, 403)

            good_file = self.client.get(f"/api/jobs/{job_id}/file?token={token}")
            self.assertEqual(good_file.status_code, 200)
            self.assertEqual(good_file.content, sample_bytes)
            cd = good_file.headers.get("content-disposition", "")
            self.assertIn("filename*=UTF-8''", cd)
            self.assertIn("%C3%96rnek", cd)

            job_dir = self.download_dir / job_id
            self.assertTrue(job_dir.is_dir())

            del_resp = self.client.delete(
                f"/api/jobs/{job_id}",
                headers={"X-API-Key": TEST_API_KEY},
            )
            self.assertEqual(del_resp.status_code, 200)
            self.assertFalse(job_dir.exists())


class PasswordlessModeTests(unittest.TestCase):
    def test_passwordless_mode_allows_requests_without_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_name:
            settings = Settings(
                api_key="unused",
                require_api_key=False,
                allowed_origins=["https://mesutpeker.com"],
                download_dir=Path(tmp_name) / "downloads",
            )
            with TestClient(app_module.create_app(settings)) as client:
                health = client.get("/api/health")
                self.assertEqual(health.status_code, 200)
                self.assertFalse(health.json()["auth_required"])

                verify = client.get("/api/auth/verify")
                self.assertEqual(verify.status_code, 200)
                self.assertTrue(verify.json()["ok"])
                self.assertFalse(verify.json()["auth_required"])


if __name__ == "__main__":
    unittest.main()
