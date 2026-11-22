"""Zero-dependency configuration loader for the video downloader backend."""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass, field
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

DEFAULT_ALLOWED_ORIGINS = (
    "https://mesutpeker.com,"
    "https://indir.mesutpeker.com,"
    "https://mesutpeker.github.io,"
    "http://localhost:5500,"
    "http://127.0.0.1:5500,"
    "http://localhost:8080,"
    "http://127.0.0.1:8080,"
    "http://localhost:3000,"
    "http://127.0.0.1:3000"
)


def load_dotenv_file(env_path: Path) -> None:
    """Load key=value pairs from a .env file without overriding existing env vars."""
    if not env_path.is_file():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if key:
            os.environ.setdefault(key, value)


def _parse_bool(raw: str | None, default: bool = False) -> bool:
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on", "evet"}


def _parse_int(raw: str | None, default: int, minimum: int = 0) -> int:
    if raw is None or not raw.strip():
        return default
    try:
        parsed = int(raw.strip())
    except ValueError:
        return default
    return max(minimum, parsed)


def _parse_origins(raw: str | None) -> list[str]:
    source = raw if raw is not None and raw.strip() else DEFAULT_ALLOWED_ORIGINS
    origins: list[str] = []
    for item in source.split(","):
        cleaned = item.strip().rstrip("/")
        if cleaned and cleaned not in origins:
            origins.append(cleaned)
    return origins


@dataclass(frozen=True)
class Settings:
    """Application runtime configuration."""

    api_key: str
    allowed_origins: list[str] = field(default_factory=lambda: _parse_origins(None))
    download_dir: Path = field(default_factory=lambda: BASE_DIR / "downloads")
    file_ttl_seconds: int = 900
    max_concurrent_jobs: int = 2
    max_filesize_mb: int = 1024
    cookies_file: str | None = None
    cookies_from_browser: str | None = None
    po_token_base_url: str | None = None
    require_api_key: bool = False
    allow_all_domains: bool = False
    host: str = "127.0.0.1"
    port: int = 8000

    @classmethod
    def from_env(
        cls,
        env_path: Path | None = None,
        *,
        require_api_key: bool | None = None,
    ) -> "Settings":
        """Build Settings from environment variables and an optional .env file."""
        target_env = env_path if env_path is not None else BASE_DIR / ".env"
        load_dotenv_file(target_env)

        enforce_key = (
            _parse_bool(os.environ.get("REQUIRE_API_KEY"), False)
            if require_api_key is None
            else bool(require_api_key)
        )
        api_key = os.environ.get("API_KEY", "").strip()
        if enforce_key and not api_key:
            raise RuntimeError(
                "API_KEY ortam degiskeni tanimli degil. "
                "Lutfen backend/.env dosyasini olusturun veya API_KEY degerini ayarlayin."
            )

        raw_dir = os.environ.get("DOWNLOAD_DIR", "").strip()
        download_dir = Path(raw_dir).expanduser() if raw_dir else (BASE_DIR / "downloads")
        if not download_dir.is_absolute():
            download_dir = (BASE_DIR / download_dir).resolve()

        cookies_file = os.environ.get("COOKIES_FILE", "").strip() or None
        if cookies_file:
            cookies_path = Path(cookies_file).expanduser()
            if not cookies_path.is_absolute():
                cookies_path = (BASE_DIR / cookies_path).resolve()
            cookies_file = str(cookies_path)

        if cookies_file is None:
            cookies_b64 = os.environ.get("COOKIES_B64", "").strip()
            if cookies_b64:
                try:
                    decoded_bytes = base64.b64decode(cookies_b64, validate=True)
                    download_dir.mkdir(parents=True, exist_ok=True)
                    decoded_path = download_dir / ".cookies.txt"
                    decoded_path.write_bytes(decoded_bytes)
                    decoded_path.chmod(0o600)
                    cookies_file = str(decoded_path)
                except Exception:
                    pass

        cookies_from_browser = os.environ.get("COOKIES_FROM_BROWSER", "").strip() or None
        po_token_base_url = os.environ.get("PO_TOKEN_BASE_URL", "").strip() or None

        return cls(
            api_key=api_key,
            allowed_origins=_parse_origins(os.environ.get("ALLOWED_ORIGINS")),
            download_dir=download_dir,
            file_ttl_seconds=_parse_int(os.environ.get("FILE_TTL_SECONDS"), 900, minimum=60),
            max_concurrent_jobs=_parse_int(os.environ.get("MAX_CONCURRENT_JOBS"), 2, minimum=1),
            max_filesize_mb=_parse_int(os.environ.get("MAX_FILESIZE_MB"), 1024, minimum=0),
            cookies_file=cookies_file,
            cookies_from_browser=cookies_from_browser,
            po_token_base_url=po_token_base_url,
            require_api_key=enforce_key,
            allow_all_domains=_parse_bool(os.environ.get("ALLOW_ALL_DOMAINS"), False),
            host=os.environ.get("HOST", "127.0.0.1").strip() or "127.0.0.1",
            port=_parse_int(os.environ.get("PORT"), 8000, minimum=1),
        )
