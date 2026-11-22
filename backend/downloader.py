"""URL validation, platform detection, and yt-dlp download orchestration."""

from __future__ import annotations

import ipaddress
import re
import shutil
import threading
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

import yt_dlp

from config import Settings

PLATFORM_DOMAINS: dict[str, tuple[str, ...]] = {
    "youtube": ("youtube.com", "youtu.be", "youtube-nocookie.com"),
    "twitter": ("twitter.com", "x.com", "fxtwitter.com", "vxtwitter.com", "fixupx.com"),
    "instagram": ("instagram.com", "instagr.am"),
    "facebook": ("facebook.com", "fb.watch", "fb.com"),
}

PLATFORM_LABELS: dict[str, str] = {
    "youtube": "YouTube",
    "twitter": "X (Twitter)",
    "instagram": "Instagram",
    "facebook": "Facebook",
    "other": "Diğer",
}

PRESETS: dict[str, dict[str, Any]] = {
    "best_mp4": {
        "label": "En İyi MP4 (Uyumlu)",
        "description": "H.264 + AAC öncelikli en yüksek kalite MP4",
        "kind": "video",
        "format": "bv*+ba/b",
        "format_sort": ["vcodec:h264", "acodec:aac", "ext:mp4:m4a"],
        "merge_output_format": "mp4",
    },
    "1080p": {
        "label": "1080p Full HD",
        "description": "Maksimum 1080p MP4",
        "kind": "video",
        "format": "bv*[height<=1080]+ba/b[height<=1080]/bv*+ba/b",
        "format_sort": ["res:1080", "vcodec:h264", "acodec:aac", "ext:mp4:m4a"],
        "merge_output_format": "mp4",
    },
    "720p": {
        "label": "720p HD",
        "description": "Daha küçük boyutlu 720p MP4",
        "kind": "video",
        "format": "bv*[height<=720]+ba/b[height<=720]/bv*+ba/b",
        "format_sort": ["res:720", "vcodec:h264", "acodec:aac", "ext:mp4:m4a"],
        "merge_output_format": "mp4",
    },
    "audio_mp3": {
        "label": "Sadece Ses (MP3)",
        "description": "192 kbps MP3 ses dosyası",
        "kind": "audio",
        "format": "ba/b",
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }
        ],
    },
    "audio_m4a": {
        "label": "Sadece Ses (M4A)",
        "description": "Apple/Mobil uyumlu M4A ses dosyası",
        "kind": "audio",
        "format": "ba[ext=m4a]/ba/b",
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "m4a",
                "preferredquality": "192",
            }
        ],
    },
}

_TEMP_SUFFIXES = (".part", ".ytdl", ".temp")
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _is_forbidden_host(hostname: str) -> bool:
    host = hostname.rstrip(".").lower()
    if not host:
        return True
    if host in {"localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback"}:
        return True
    if host.endswith(".local") or host.endswith(".internal") or host.endswith(".localhost"):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def _matches_domain(hostname: str, domain: str) -> bool:
    return hostname == domain or hostname.endswith(f".{domain}")


def validate_and_detect_platform(url: str, allow_all_domains: bool = False) -> tuple[str, str]:
    """Validate an external media URL and identify its platform.

    Returns (normalized_url, platform_key). Raises ValueError for invalid or disallowed URLs.
    """
    cleaned = (url or "").strip()
    if not cleaned:
        raise ValueError("Lütfen geçerli bir video bağlantısı girin.")

    parsed = urlparse(cleaned)
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"}:
        raise ValueError("Yalnızca http:// veya https:// bağlantıları desteklenir.")

    hostname = (parsed.hostname or "").rstrip(".").lower()
    if not hostname or _is_forbidden_host(hostname):
        raise ValueError("Yerel veya özel ağ adreslerine izin verilmiyor.")

    for platform, domains in PLATFORM_DOMAINS.items():
        if any(_matches_domain(hostname, domain) for domain in domains):
            return cleaned, platform

    if allow_all_domains:
        return cleaned, "other"

    raise ValueError(
        "Desteklenmeyen alan adı. Şu an yalnızca YouTube, X (Twitter), Instagram ve Facebook bağlantıları kabul ediliyor."
    )


def _find_binary(name: str, extra_paths: tuple[str, ...]) -> str | None:
    found = shutil.which(name)
    if found:
        return found
    for candidate in extra_paths:
        path = Path(candidate)
        if path.is_file():
            return str(path)
    return None


def find_ffmpeg() -> str | None:
    """Locate ffmpeg executable on PATH or standard macOS/Linux prefixes."""
    return _find_binary("ffmpeg", ("/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg", "/usr/bin/ffmpeg"))


def detect_js_runtimes() -> dict[str, dict[str, str | None]]:
    """Detect available JS runtimes (deno / node) for yt-dlp signature extraction."""
    runtimes: dict[str, dict[str, str | None]] = {}
    deno_path = _find_binary("deno", ("/opt/homebrew/bin/deno", "/usr/local/bin/deno", "/root/.deno/bin/deno"))
    if deno_path:
        runtimes["deno"] = {"path": deno_path}
    node_path = _find_binary("node", ("/opt/homebrew/bin/node", "/usr/local/bin/node", "/usr/bin/node"))
    if node_path:
        runtimes["node"] = {"path": node_path}
    return runtimes


def _sanitize_http_url(raw_url: Any) -> str | None:
    if not isinstance(raw_url, str):
        return None
    candidate = raw_url.strip()
    if not candidate:
        return None
    parsed = urlparse(candidate)
    if parsed.scheme.lower() in {"http", "https"} and parsed.hostname:
        return candidate
    return None


def _format_speed(speed_bytes: Any) -> str | None:
    if not isinstance(speed_bytes, (int, float)) or speed_bytes <= 0:
        return None
    if speed_bytes >= 1024 * 1024:
        return f"{speed_bytes / (1024 * 1024):.1f} MB/s"
    if speed_bytes >= 1024:
        return f"{speed_bytes / 1024:.0f} KB/s"
    return f"{speed_bytes:.0f} B/s"


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text).strip()


def format_ytdlp_error(exc: Exception) -> str:
    """Translate raw yt-dlp/network exceptions into clear Turkish error messages."""
    raw = _strip_ansi(str(exc))
    lower = raw.lower()

    if "sign in to confirm" in lower or "not a bot" in lower:
        return (
            "YouTube bot doğrulaması istedi. Ev IP'siyle tekrar deneyin veya backend/.env içinde "
            "COOKIES_FROM_BROWSER / COOKIES_FILE (ya da PO Token sunucusu) tanımlayın."
        )
    if "login required" in lower or "cookies" in lower and ("instagram" in lower or "facebook" in lower):
        return (
            "Bu içerik giriş gerektiriyor. backend/.env dosyasında COOKIES_FROM_BROWSER=chrome "
            "(veya cookies.txt) ayarlayarak indirebilirsiniz."
        )
    if "private video" in lower or "this video is private" in lower:
        return "Bu video gizli (private) olduğu için indirilemiyor."
    if "video unavailable" in lower or "has been removed" in lower or "does not exist" in lower:
        return "Video bulunamadı, silinmiş veya bölgenizde erişime kapalı."
    if "file is larger than max-filesize" in lower or "max_filesize" in lower:
        return "Dosya boyutu yapılandırılan maksimum sınırı (MAX_FILESIZE_MB) aşıyor."
    if "ffmpeg" in lower and ("not found" in lower or "installed" in lower):
        return "Video/ses birleştirme için ffmpeg bulunamadı. Lütfen ffmpeg kurun."
    if "unsupported url" in lower:
        return "Bu bağlantıdan video çıkarılamadı (desteklenmeyen veya medya içermeyen sayfa)."
    if "http error 429" in lower or "too many requests" in lower:
        return "Platform çok fazla istek nedeniyle geçici hız sınırı uyguladı. Bir süre sonra tekrar deneyin."
    if "http error 403" in lower:
        return "Platform erişimi reddetti (403). yt-dlp güncellemesi veya çerez gerekebilir."

    if raw.startswith("ERROR:"):
        raw = raw[len("ERROR:") :].strip()
    return raw or "İndirme sırasında beklenmeyen bir hata oluştu."


def build_ydl_opts(settings: Settings, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """Construct common yt-dlp options from runtime settings."""
    opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "windowsfilenames": True,
        "restrictfilenames": False,
        "socket_timeout": 30,
        "retries": 3,
        "fragment_retries": 3,
    }

    ffmpeg_path = find_ffmpeg()
    if ffmpeg_path:
        opts["ffmpeg_location"] = ffmpeg_path

    js_runtimes = detect_js_runtimes()
    if js_runtimes:
        opts["js_runtimes"] = js_runtimes

    if settings.cookies_file and Path(settings.cookies_file).is_file():
        opts["cookiefile"] = settings.cookies_file
    elif settings.cookies_from_browser:
        opts["cookiesfrombrowser"] = (settings.cookies_from_browser, None, None, None)

    if settings.max_filesize_mb > 0:
        opts["max_filesize"] = settings.max_filesize_mb * 1024 * 1024

    if settings.po_token_base_url:
        opts["extractor_args"] = {
            "youtubepot-bgutilhttp": {
                "base_url": [settings.po_token_base_url],
            }
        }

    if extra:
        opts.update(extra)
    return opts


def fetch_video_info(url: str, settings: Settings) -> dict[str, Any]:
    """Extract metadata for a supported video URL without downloading media."""
    normalized_url, platform = validate_and_detect_platform(url, allow_all_domains=settings.allow_all_domains)
    opts = build_ydl_opts(settings, {"skip_download": True})

    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(normalized_url, download=False)

    if not isinstance(info, dict):
        raise ValueError("Video bilgileri alınamadı.")

    # Handle playlist/carousel wrappers by inspecting the first entry when top-level metadata is minimal
    if "entries" in info and isinstance(info["entries"], list) and info["entries"]:
        first = next((entry for entry in info["entries"] if isinstance(entry, dict)), None)
        if first and not info.get("duration") and first.get("title"):
            info = first

    duration_raw = info.get("duration")
    duration = int(duration_raw) if isinstance(duration_raw, (int, float)) and duration_raw >= 0 else None

    thumbnail = _sanitize_http_url(info.get("thumbnail"))
    if not thumbnail and isinstance(info.get("thumbnails"), list):
        for thumb in reversed(info["thumbnails"]):
            if isinstance(thumb, dict):
                candidate = _sanitize_http_url(thumb.get("url"))
                if candidate:
                    thumbnail = candidate
                    break

    return {
        "platform": platform,
        "platform_label": PLATFORM_LABELS.get(platform, "Diğer"),
        "id": str(info.get("id") or ""),
        "title": str(info.get("title") or "Video"),
        "uploader": str(info.get("uploader") or info.get("channel") or info.get("uploader_id") or ""),
        "duration": duration,
        "thumbnail": thumbnail,
        "webpage_url": _sanitize_http_url(info.get("webpage_url")) or normalized_url,
        "extractor": str(info.get("extractor_key") or info.get("extractor") or ""),
    }


def _find_output_file(job_dir: Path) -> Path | None:
    if not job_dir.is_dir():
        return None
    candidates = [
        p
        for p in job_dir.iterdir()
        if p.is_file() and not p.name.startswith(".") and not p.name.endswith(_TEMP_SUFFIXES)
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda p: (p.stat().st_size, p.stat().st_mtime), reverse=True)
    return candidates[0]


def download_video(
    url: str,
    preset: str,
    job_dir: Path,
    settings: Settings,
    progress_cb: Callable[[dict[str, Any]], None],
    cancel_event: threading.Event | None = None,
) -> dict[str, Any]:
    """Download and optionally postprocess a video into job_dir."""
    if preset not in PRESETS:
        raise ValueError(f"Geçersiz format seçimi: {preset}")

    normalized_url, _ = validate_and_detect_platform(url, allow_all_domains=settings.allow_all_domains)
    preset_cfg = PRESETS[preset]

    job_dir.mkdir(parents=True, exist_ok=True)
    captured_paths: list[Path] = []
    outtmpl = str(job_dir / "%(title).120B [%(id)s].%(ext)s")

    def on_progress(data: dict[str, Any]) -> None:
        if cancel_event and cancel_event.is_set():
            raise yt_dlp.utils.DownloadCancelled("İndirme kullanıcı tarafından iptal edildi.")

        status = data.get("status")
        if status == "downloading":
            total = data.get("total_bytes") or data.get("total_bytes_estimate") or 0
            downloaded = data.get("downloaded_bytes") or 0
            pct = 0.0
            if isinstance(total, (int, float)) and total > 0:
                pct = min(99.0, max(0.0, (float(downloaded) / float(total)) * 100.0))
            eta_raw = data.get("eta")
            eta = int(eta_raw) if isinstance(eta_raw, (int, float)) and eta_raw >= 0 else None
            progress_cb(
                {
                    "status": "downloading",
                    "progress": round(pct, 1),
                    "speed": _format_speed(data.get("speed")),
                    "eta": eta,
                }
            )
        elif status == "finished":
            filename = data.get("filename")
            if isinstance(filename, str) and filename:
                captured_paths.append(Path(filename))
            progress_cb(
                {
                    "status": "processing",
                    "progress": 96.0,
                    "speed": None,
                    "eta": None,
                }
            )

    def on_postprocessor(data: dict[str, Any]) -> None:
        if cancel_event and cancel_event.is_set():
            raise yt_dlp.utils.DownloadCancelled("İndirme kullanıcı tarafından iptal edildi.")
        if data.get("status") == "finished":
            info_dict = data.get("info_dict")
            if isinstance(info_dict, dict):
                filepath = info_dict.get("filepath")
                if isinstance(filepath, str) and filepath:
                    captured_paths.append(Path(filepath))
        elif data.get("status") == "started":
            progress_cb(
                {
                    "status": "processing",
                    "progress": 98.0,
                    "speed": None,
                    "eta": None,
                }
            )

    extra_opts: dict[str, Any] = {
        "outtmpl": outtmpl,
        "format": preset_cfg["format"],
        "progress_hooks": [on_progress],
        "postprocessor_hooks": [on_postprocessor],
    }
    if "format_sort" in preset_cfg:
        extra_opts["format_sort"] = preset_cfg["format_sort"]
    if "merge_output_format" in preset_cfg:
        extra_opts["merge_output_format"] = preset_cfg["merge_output_format"]
    if "postprocessors" in preset_cfg:
        extra_opts["postprocessors"] = preset_cfg["postprocessors"]

    opts = build_ydl_opts(settings, extra_opts)
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(normalized_url, download=True)

    final_file: Path | None = None
    for candidate in reversed(captured_paths):
        if candidate.is_file() and candidate.parent.resolve() == job_dir.resolve():
            final_file = candidate
            break

    if final_file is None and isinstance(info, dict):
        requested = info.get("requested_downloads")
        if isinstance(requested, list):
            for entry in reversed(requested):
                if isinstance(entry, dict) and isinstance(entry.get("filepath"), str):
                    candidate = Path(entry["filepath"])
                    if candidate.is_file():
                        final_file = candidate
                        break

    if final_file is None:
        final_file = _find_output_file(job_dir)

    if final_file is None or not final_file.is_file():
        raise RuntimeError("İndirme tamamlandı ancak çıktı dosyası bulunamadı.")

    title = str(info.get("title") or final_file.stem) if isinstance(info, dict) else final_file.stem
    return {
        "filepath": final_file,
        "filename": final_file.name,
        "filesize": final_file.stat().st_size,
        "title": title,
    }
