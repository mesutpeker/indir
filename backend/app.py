"""FastAPI backend for the personal YouTube / X / Instagram / Facebook downloader."""

from __future__ import annotations

import asyncio
import hmac
import re
import secrets
import shutil
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote

import yt_dlp
from fastapi import Depends, FastAPI, Header, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

from config import Settings
from downloader import (
    PLATFORM_LABELS,
    PRESETS,
    detect_js_runtimes,
    download_video,
    fetch_video_info,
    find_ffmpeg,
    format_ytdlp_error,
    validate_and_detect_platform,
)

PUBLIC_PRESETS = [
    {
        "id": key,
        "label": cfg["label"],
        "description": cfg["description"],
        "kind": cfg["kind"],
    }
    for key, cfg in PRESETS.items()
]


class InfoRequest(BaseModel):
    url: str = Field(..., min_length=1, max_length=2048)


class CreateJobRequest(BaseModel):
    url: str = Field(..., min_length=1, max_length=2048)
    preset: str = Field(default="best_mp4", min_length=1, max_length=64)


@dataclass
class JobRecord:
    id: str
    url: str
    platform: str
    preset: str
    job_dir: Path
    status: str = "queued"
    progress: float = 0.0
    speed: str | None = None
    eta: int | None = None
    title: str | None = None
    filename: str | None = None
    filepath: Path | None = None
    filesize: int | None = None
    error: str | None = None
    download_token: str | None = None
    created_at: float = field(default_factory=time.time)
    expires_at: float | None = None
    cancel_event: threading.Event = field(default_factory=threading.Event)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.id,
            "status": self.status,
            "progress": self.progress,
            "speed": self.speed,
            "eta": self.eta,
            "platform": self.platform,
            "platform_label": PLATFORM_LABELS.get(self.platform, "Diğer"),
            "preset": self.preset,
            "title": self.title,
            "filename": self.filename,
            "filesize": self.filesize,
            "error": self.error,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
        }
        if self.status == "ready" and self.download_token:
            payload["download_token"] = self.download_token
        return payload


class JobStore:
    """Thread-safe in-memory job registry paired with on-disk temp folders."""

    def __init__(self, download_dir: Path, ttl_seconds: int) -> None:
        self.download_dir = download_dir
        self.ttl_seconds = ttl_seconds
        self._jobs: dict[str, JobRecord] = {}
        self._lock = threading.Lock()

    def create(self, url: str, platform: str, preset: str) -> JobRecord:
        job_id = secrets.token_urlsafe(12).replace("-", "").replace("_", "")[:16]
        job_dir = self.download_dir / job_id
        record = JobRecord(
            id=job_id,
            url=url,
            platform=platform,
            preset=preset,
            job_dir=job_dir,
        )
        with self._lock:
            self._jobs[job_id] = record
        return record

    def get(self, job_id: str) -> JobRecord | None:
        with self._lock:
            return self._jobs.get(job_id)

    def update(self, job_id: str, **changes: Any) -> JobRecord | None:
        with self._lock:
            record = self._jobs.get(job_id)
            if record is None:
                return None
            for key, value in changes.items():
                setattr(record, key, value)
            return record

    def snapshot(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            record = self._jobs.get(job_id)
            if record is None:
                return None
            if (
                record.status == "ready"
                and record.expires_at is not None
                and time.time() > record.expires_at
            ):
                record.status = "expired"
                record.download_token = None
                record.filepath = None
                shutil.rmtree(record.job_dir, ignore_errors=True)
            return record.to_dict()

    def delete(self, job_id: str) -> bool:
        with self._lock:
            record = self._jobs.pop(job_id, None)
        if record is None:
            return False
        record.cancel_event.set()
        shutil.rmtree(record.job_dir, ignore_errors=True)
        return True

    def cleanup_expired(self) -> int:
        now = time.time()
        to_remove: list[JobRecord] = []
        max_stale = max(3600, self.ttl_seconds * 2)

        with self._lock:
            for job_id, record in list(self._jobs.items()):
                expired_ready = record.expires_at is not None and now > record.expires_at
                abandoned = (now - record.created_at) > max_stale
                if expired_ready or abandoned:
                    to_remove.append(self._jobs.pop(job_id))

        for record in to_remove:
            record.cancel_event.set()
            shutil.rmtree(record.job_dir, ignore_errors=True)
        return len(to_remove)

    def cleanup_all_files(self) -> None:
        with self._lock:
            records = list(self._jobs.values())
            self._jobs.clear()
        for record in records:
            record.cancel_event.set()
        if self.download_dir.exists():
            for child in self.download_dir.iterdir():
                if child.is_dir():
                    shutil.rmtree(child, ignore_errors=True)
                elif child.is_file():
                    child.unlink(missing_ok=True)


def _ascii_filename_fallback(filename: str) -> str:
    normalized = unicodedata.normalize("NFKD", filename).encode("ascii", "ignore").decode("ascii")
    cleaned = re.sub(r"[^A-Za-z0-9._ -]+", "_", normalized).strip(" .")
    return cleaned or "video.mp4"


def _build_content_disposition(filename: str) -> str:
    ascii_name = _ascii_filename_fallback(filename).replace('"', "")
    utf8_name = quote(filename, safe="")
    return f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'{utf8_name}'


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create and configure a FastAPI application instance."""
    active_settings = settings if settings is not None else Settings.from_env()
    store = JobStore(active_settings.download_dir, active_settings.file_ttl_seconds)
    executor = ThreadPoolExecutor(max_workers=active_settings.max_concurrent_jobs)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if active_settings.require_api_key and not active_settings.api_key:
            raise RuntimeError(
                "API_KEY ortam değişkeni tanımlı değil. "
                "Lütfen backend/.env dosyasını oluşturun veya API_KEY değerini ayarlayın."
            )
        active_settings.download_dir.mkdir(parents=True, exist_ok=True)
        store.cleanup_all_files()

        stop_event = asyncio.Event()

        async def cleanup_loop() -> None:
            while not stop_event.is_set():
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=30.0)
                except asyncio.TimeoutError:
                    store.cleanup_expired()

        cleanup_task = asyncio.create_task(cleanup_loop())
        try:
            yield
        finally:
            stop_event.set()
            cleanup_task.cancel()
            try:
                await cleanup_task
            except asyncio.CancelledError:
                pass
            executor.shutdown(wait=False, cancel_futures=True)
            store.cleanup_all_files()

    app = FastAPI(
        title="Mesut Video İndirici API",
        version="1.0.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=active_settings.allowed_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "X-API-Key"],
        expose_headers=["Content-Disposition", "Content-Length"],
        max_age=3600,
    )

    def verify_api_key(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> None:
        if not active_settings.require_api_key:
            return
        if not active_settings.api_key:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Sunucuda API_KEY yapılandırılmamış.",
            )
        if not x_api_key or not hmac.compare_digest(x_api_key.strip(), active_settings.api_key):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Geçersiz veya eksik API anahtarı.",
            )

    def _run_download_job(job_id: str) -> None:
        record = store.get(job_id)
        if record is None or record.cancel_event.is_set():
            return

        store.update(job_id, status="downloading", progress=1.0)

        def on_progress(update: dict[str, Any]) -> None:
            if record.cancel_event.is_set():
                return
            store.update(
                job_id,
                status=update.get("status", "downloading"),
                progress=update.get("progress", record.progress),
                speed=update.get("speed"),
                eta=update.get("eta"),
            )

        try:
            result = download_video(
                url=record.url,
                preset=record.preset,
                job_dir=record.job_dir,
                settings=active_settings,
                progress_cb=on_progress,
                cancel_event=record.cancel_event,
            )
        except yt_dlp.utils.DownloadCancelled:
            shutil.rmtree(record.job_dir, ignore_errors=True)
            store.update(
                job_id,
                status="cancelled",
                speed=None,
                eta=None,
                error="İndirme iptal edildi.",
                expires_at=time.time() + 60,
            )
            return
        except Exception as exc:
            shutil.rmtree(record.job_dir, ignore_errors=True)
            store.update(
                job_id,
                status="error",
                speed=None,
                eta=None,
                error=format_ytdlp_error(exc),
                expires_at=time.time() + 180,
            )
            return

        if record.cancel_event.is_set():
            shutil.rmtree(record.job_dir, ignore_errors=True)
            return

        token = secrets.token_urlsafe(24)
        store.update(
            job_id,
            status="ready",
            progress=100.0,
            speed=None,
            eta=None,
            title=result["title"],
            filename=result["filename"],
            filepath=result["filepath"],
            filesize=result["filesize"],
            download_token=token,
            expires_at=time.time() + active_settings.file_ttl_seconds,
        )

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "auth_required": active_settings.require_api_key,
            "yt_dlp_version": yt_dlp.version.__version__,
            "ffmpeg": bool(find_ffmpeg()),
            "js_runtimes": list(detect_js_runtimes().keys()),
        }

    @app.get("/api/auth/verify", dependencies=[Depends(verify_api_key)])
    async def auth_verify() -> dict[str, Any]:
        return {
            "ok": True,
            "auth_required": active_settings.require_api_key,
            "yt_dlp_version": yt_dlp.version.__version__,
            "ffmpeg": bool(find_ffmpeg()),
            "js_runtimes": list(detect_js_runtimes().keys()),
            "max_filesize_mb": active_settings.max_filesize_mb,
            "file_ttl_seconds": active_settings.file_ttl_seconds,
            "presets": PUBLIC_PRESETS,
        }

    @app.post("/api/info", dependencies=[Depends(verify_api_key)])
    async def video_info(body: InfoRequest) -> dict[str, Any]:
        try:
            validate_and_detect_platform(body.url, allow_all_domains=active_settings.allow_all_domains)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

        try:
            info = await asyncio.to_thread(fetch_video_info, body.url, active_settings)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=format_ytdlp_error(exc),
            ) from exc

        return {
            "info": info,
            "presets": PUBLIC_PRESETS,
        }

    @app.post(
        "/api/jobs",
        status_code=status.HTTP_202_ACCEPTED,
        dependencies=[Depends(verify_api_key)],
    )
    async def create_job(body: CreateJobRequest) -> dict[str, Any]:
        if body.preset not in PRESETS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Geçersiz format seçimi: {body.preset}",
            )

        try:
            normalized_url, platform = validate_and_detect_platform(
                body.url, allow_all_domains=active_settings.allow_all_domains
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

        record = store.create(normalized_url, platform, body.preset)
        loop = asyncio.get_running_loop()
        loop.run_in_executor(executor, _run_download_job, record.id)
        return record.to_dict()

    @app.get("/api/jobs/{job_id}", dependencies=[Depends(verify_api_key)])
    async def get_job(job_id: str) -> dict[str, Any]:
        snap = store.snapshot(job_id)
        if snap is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="İndirme işi bulunamadı.")
        return snap

    @app.get("/api/jobs/{job_id}/file")
    async def download_job_file(
        job_id: str,
        token: str = Query(..., min_length=8),
    ) -> FileResponse:
        record = store.get(job_id)
        if record is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="İndirme işi bulunamadı.")

        if record.status == "expired" or (
            record.expires_at is not None and time.time() > record.expires_at
        ):
            store.update(job_id, status="expired", download_token=None, filepath=None)
            shutil.rmtree(record.job_dir, ignore_errors=True)
            raise HTTPException(
                status_code=status.HTTP_410_GONE,
                detail="Dosyanın geçerlilik süresi doldu. Lütfen tekrar indirin.",
            )

        if record.status != "ready":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Dosya henüz indirilmeye hazır değil.",
            )

        if not record.download_token or not hmac.compare_digest(token, record.download_token):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Geçersiz veya süresi dolmuş indirme anahtarı.",
            )

        if not record.filepath or not record.filepath.is_file():
            raise HTTPException(
                status_code=status.HTTP_410_GONE,
                detail="Dosya sunucudan temizlenmiş. Lütfen tekrar indirin.",
            )

        filename = record.filename or record.filepath.name
        headers = {
            "Content-Disposition": _build_content_disposition(filename),
            "Cache-Control": "no-store",
        }
        return FileResponse(
            path=record.filepath,
            media_type="application/octet-stream",
            headers=headers,
            background=BackgroundTask(store.delete, job_id),
        )

    @app.delete("/api/jobs/{job_id}", dependencies=[Depends(verify_api_key)])
    async def delete_job(job_id: str) -> dict[str, Any]:
        deleted = store.delete(job_id)
        if not deleted:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="İndirme işi bulunamadı.")
        return {"deleted": True, "id": job_id}

    return app


app = create_app(Settings.from_env())
