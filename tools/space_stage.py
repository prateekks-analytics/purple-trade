"""Copy exactly what the Hugging Face Space needs into a folder (no data, keys, node_modules or build output).

    python tools/space_stage.py <out-folder>

Then upload that folder to the Space, e.g. `hf upload <user>/purple-desk <out-folder> . --repo-type space`.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONT = ["index.html", "package.json", "package-lock.json", "tsconfig.json", "tsconfig.app.json",
         "tsconfig.node.json", "vite.config.ts", "public", "src"]
SKIP = shutil.ignore_patterns("__pycache__", "*.pyc", ".env", "*.sqlite3")


def stage(out: Path) -> list[str]:
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    shutil.copy(ROOT / "space" / "Dockerfile", out / "Dockerfile")
    shutil.copy(ROOT / "space" / "README.md", out / "README.md")
    (out / "backend").mkdir()
    shutil.copy(ROOT / "backend" / "pyproject.toml", out / "backend" / "pyproject.toml")
    shutil.copytree(ROOT / "backend" / "purple_api", out / "backend" / "purple_api", ignore=SKIP)
    (out / "frontend").mkdir()
    for name in FRONT:
        src = ROOT / "frontend" / name
        if src.is_dir():
            shutil.copytree(src, out / "frontend" / name, ignore=SKIP)
        elif src.exists():
            shutil.copy(src, out / "frontend" / name)
    (out / "coach").mkdir()
    shutil.copy(ROOT / "coach" / "playbook.md", out / "coach" / "playbook.md")
    files = sorted(str(p.relative_to(out)).replace("\\", "/") for p in out.rglob("*") if p.is_file())
    bad = [f for f in files if f.endswith((".env", ".sqlite3")) or "node_modules" in f]
    if bad:
        raise SystemExit(f"refusing to stage private files: {bad}")
    return files


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    fs = stage(Path(sys.argv[1]))
    print(f"{len(fs)} files staged in {sys.argv[1]}")
