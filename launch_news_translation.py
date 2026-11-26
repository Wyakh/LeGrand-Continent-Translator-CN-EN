"""Windows launcher support: isolated dependency setup and a simple PDF prompt.

--check installs/checks dependencies only; it never reads .env or contacts the AI API.
"""
from __future__ import annotations

from pathlib import Path
import os
import re
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


def dropped_paths(value: str) -> list[str]:
    """Split Explorer's space-separated, double-quoted paths; keep backslashes."""
    value = value.strip()
    if not value:
        raise ValueError("No PDFs selected.")
    if '"' not in value and Path(value).expanduser().is_file():
        return [value]  # Also accept one pasted, unquoted path containing spaces.
    if value.count('"') % 2:
        raise ValueError("Unmatched quotation mark in PDF paths.")
    return [part.strip('"') for part in re.findall(r'"[^"]*"|[^\s"]+', value)]


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if sys.version_info < (3, 10):
        print("Python 3.10 or newer is required. Install a current 64-bit Python.", file=sys.stderr)
        return 2
    if args in (["--help"], ["-h"]):
        print("Usage: launch_news_translation.py [ARTICLE.pdf ... | --check]\n"
              "Drop PDFs onto the batch launcher, or into its path prompt, then press Enter.\n"
              "--check prepares dependencies without reading private configuration or calling the AI API.")
        return 0
    try:
        if args == ["--check"]:
            python = prepare_runtime(ROOT)
            print(f"Ready: {python}\nPyMuPDF 1.26.7 loaded. No private configuration or AI API was used.")
            return 0
        values = args or dropped_paths(input("Drag French PDFs here, then press Enter: "))
        pdfs = []
        for value in values:
            pdf = Path(value.strip().strip('"')).expanduser().resolve()
            if not value.strip() or not pdf.is_file() or pdf.suffix.lower() != ".pdf":
                raise ValueError(f"PDF not found or not a PDF: {value}")
            if pdf not in pdfs:
                pdfs.append(pdf)
        print(f"Selected {len(pdfs)} PDF(s); translations will run one by one.\n"
              "Enter K to KEEP each original and cache.\n"
              "Press Enter to DELETE each original/cache only after its two new PDFs validate.")
        choice = input("Keep source and cache for all selected PDFs? [K/Enter]: ").strip().lower()
        if choice not in ("", "k"):
            raise ValueError("Invalid choice; use K to keep or Enter to delete. Nothing was translated or deleted.")
        python = prepare_runtime(ROOT)
        failed = []
        for index, pdf in enumerate(pdfs, 1):
            print(f"\n[{index}/{len(pdfs)}] Translating: {pdf.name}", flush=True)
            command = [str(python), str(ROOT / "news_translate.py"), str(pdf)]
            if choice == "k":
                command.append("--keep")
            if subprocess.run(command).returncode:
                failed.append(pdf)
                print(f"Translation failed: {pdf.name}. Continuing with remaining PDFs.", flush=True)
        print(f"\nFinished: {len(pdfs) - len(failed)} succeeded, {len(failed)} failed.", flush=True)
        for pdf in failed:
            print(f"  Failed: {pdf}")
        return 1 if failed else 0
    except (EOFError, KeyboardInterrupt):
        print("\nCancelled. Earlier completed files may already have been cleaned up if deletion was selected.", file=sys.stderr)
        return 1
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"Setup/launch failed: {exc}\nNo source was deliberately deleted by the launcher.", file=sys.stderr)
        print("If this folder was copied from another PC, recreate .venv on this PC; do not transfer .venv.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
