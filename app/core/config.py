import os
import tomllib
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()  # Loads from .env file

# Load project metadata from pyproject.toml if present
_pyproject_path = Path(__file__).resolve().parents[2] / "pyproject.toml"
_pyproject_data = {}
if _pyproject_path.exists():
    try:
        with open(_pyproject_path, "rb") as _f:
            _pyproject_data = tomllib.load(_f).get("project", {})
    except Exception:
        pass


class Settings:
    PROJECT_NAME: str = _pyproject_data.get("name")
    VERSION: str = _pyproject_data.get("version")
    DESCRIPTION: str = _pyproject_data.get("description")

    # JWT
    SECRET_KEY = os.getenv("SECRET_KEY")
    if not SECRET_KEY:
        raise RuntimeError("SECRET_KEY environment variable is required for token signing")

    ALGORITHM = os.getenv("ALGORITHM", "HS256")
    ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", 15))

    REFRESH_TOKEN_HASH_KEY = os.getenv("REFRESH_TOKEN_HASH_KEY")
    if not REFRESH_TOKEN_HASH_KEY:
        raise RuntimeError("REFRESH_TOKEN_HASH_KEY environment variable is required for refresh token HMAC")
    # Enforce minimum length to avoid weak HMAC keys
    if len(REFRESH_TOKEN_HASH_KEY) < 16:
        raise RuntimeError("REFRESH_TOKEN_HASH_KEY must be at least 16 characters long")
    REFRESH_TOKEN_HASH_KEY = REFRESH_TOKEN_HASH_KEY.encode("utf-8")

    REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", 30))
    TOMBSTONE_RETENTION_DAYS = int(os.getenv("TOMBSTONE_RETENTION_DAYS", "30"))
    # DB
    DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./data/clipboard.db")
    REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379") # Default to docker service name; override for local
