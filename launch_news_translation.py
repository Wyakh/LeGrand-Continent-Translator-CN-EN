"""Windows launcher support: isolated dependency setup and a simple PDF prompt.

--check installs/checks dependencies only; it never reads .env or contacts the AI API.
"""
from __future__ import annotations

from pathlib import Path
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parent


def prepare_runtime(root: Path) -> Path:
    """Use this copy's virtual environment, never a copied vendor binary."""
    environment = root / ".venv"
    python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not python.is_file():
        print("Creating this project's Python environment...", flush=True)
        subprocess.run([sys.executable, "-m", "venv", str(environment)], check=True)
    check = subprocess.run(
        [str(python), "-c", "import pymupdf; assert pymupdf.VersionBind == '1.26.7'"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    if check.returncode:
        print("Installing the pinned PDF dependency from PyPI...", flush=True)
        subprocess.run([str(python), "-m", "pip", "install", "-r", str(root / "requirements.txt")], check=True)
        subprocess.run([str(python), "-c", "import pymupdf; assert pymupdf.VersionBind == '1.26.7'"], check=True)
    return python


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if sys.version_info < (3, 10):
        print("Python 3.10 or newer is required. Install a current 64-bit Python.", file=sys.stderr)
        return 2
    if args in (["--help"], ["-h"]):
        print("Usage: launch_news_translation.py [ARTICLE.pdf | --check]\n"
              "Drop one PDF onto the batch launcher, or start it and paste a full PDF path.\n"
              "--check prepares dependencies without reading private configuration or calling the AI API.")
        return 0
    try:
        if args == ["--check"]:
            python = prepare_runtime(ROOT)
            print(f"Ready: {python}\nPyMuPDF 1.26.7 loaded. No private configuration or AI API was used.")
            return 0
        if len(args) > 1:
            raise ValueError("Select one PDF at a time.")
        value = args[0] if args else input("Full path to French PDF: ")
        pdf = Path(value.strip().strip('"')).expanduser().resolve()
        if not value.strip() or not pdf.is_file() or pdf.suffix.lower() != ".pdf":
            raise ValueError(f"PDF not found or not a PDF: {value}")
        print("Enter K to KEEP the original and cache.\n"
              "Press Enter to DELETE them only after both new PDFs validate.")
        choice = input("Keep source and cache? [K/Enter]: ").strip().lower()
        if choice not in ("", "k"):
            raise ValueError("Invalid choice; use K to keep or Enter to delete. Nothing was translated or deleted.")
        python = prepare_runtime(ROOT)
        command = [str(python), str(ROOT / "news_translate.py"), str(pdf)]
        if choice == "k":
            command.append("--keep")
        return subprocess.run(command).returncode
    except (EOFError, KeyboardInterrupt):
        print("\nCancelled. Nothing was deliberately deleted.", file=sys.stderr)
        return 1
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"Setup/launch failed: {exc}\nNo source was deliberately deleted by the launcher.", file=sys.stderr)
        print("If this folder was copied from another PC, recreate .venv on this PC; do not transfer .venv.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
