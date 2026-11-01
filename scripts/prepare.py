"""Get a checkout ready for `docker compose up`.

1. Builds the library wheel from the sibling library checkout and puts it where the images expect
   it: ./wheels (Materials) and <REPOS_DIR>/lightsmith-cloud/wheels (Cloud).
2. Creates .env from .env.example on first run, filling every secret with a fresh random value.
   An existing .env is kept; only LIBRARY_WHEEL is updated.

    uv run --no-project python scripts/prepare.py [--library PATH]

The library is found at --library, $LIBRARY_DIR or <REPOS_DIR>/lightsmith.
"""

from __future__ import annotations

import argparse
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SECRETS = (
    "POSTGRES_PASSWORD", "COMMUNITY_DB_PASSWORD", "CLOUD_DB_PASSWORD", "MATERIALS_DB_PASSWORD",
    "PLATFORM_JWT_SECRET", "COMMUNITY_AUTH_SECRET", "CLOUD_API_KEY_PEPPER", "CLOUD_ADMIN_TOKEN",
    "COMMUNITY_S3_SECRET", "CLOUD_S3_SECRET",
)


def read_env(path: Path) -> dict[str, str]:
    out = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line and not line.lstrip().startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip()
    return out


def find_library(repos: Path, explicit: str | None) -> Path:
    candidates = [Path(p) for p in (explicit, os.environ.get("LIBRARY_DIR")) if p]
    candidates += [repos / "lightsmith"]
    for c in candidates:
        if (c / "pyproject.toml").is_file() and (c / "src" / "lightsmith").is_dir():
            return c.resolve()
    sys.exit(f"library checkout not found (tried {', '.join(map(str, candidates))}); pass --library")


def build_wheel(library: Path, repos: Path) -> str:
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(["uv", "build", "--wheel", "--out-dir", tmp, str(library)], check=True)
        (wheel,) = Path(tmp).glob("lightsmith-*.whl")
        targets = [ROOT / "wheels", repos / "lightsmith-cloud" / "wheels"]
        for t in targets:
            if not t.parent.is_dir():
                sys.exit(f"{t.parent} not found; check REPOS_DIR")
            t.mkdir(exist_ok=True)
            shutil.copy2(wheel, t / wheel.name)
        print(f"wheel {wheel.name} -> " + ", ".join(str(t) for t in targets))
        return wheel.name


def write_env(wheel: str) -> None:
    env_path, example = ROOT / ".env", ROOT / ".env.example"
    first_run = not env_path.exists()
    lines = (example if first_run else env_path).read_text(encoding="utf-8").splitlines()
    seen, out = set(), []
    for line in lines:
        key = line.split("=", 1)[0].strip() if "=" in line and not line.lstrip().startswith("#") else None
        if key == "LIBRARY_WHEEL":
            line = f"LIBRARY_WHEEL={wheel}"
        elif first_run and key in SECRETS and not line.split("=", 1)[1].strip():
            line = f"{key}={secrets.token_urlsafe(32)}"
        seen.add(key)
        out.append(line)
    if "LIBRARY_WHEEL" not in seen:
        out.append(f"LIBRARY_WHEEL={wheel}")
    env_path.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(("created" if first_run else "updated") + f" {env_path}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--library", help="path of the library checkout")
    args = ap.parse_args()
    repos = Path(read_env(ROOT / ".env").get("REPOS_DIR") or os.environ.get("REPOS_DIR") or ROOT.parent)
    if not repos.is_absolute():
        repos = (ROOT / repos).resolve()
    write_env(build_wheel(find_library(repos, args.library), repos))


if __name__ == "__main__":
    main()
