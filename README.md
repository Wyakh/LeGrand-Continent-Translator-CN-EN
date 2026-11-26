# Le Grand Continent — French PDF to Chinese & English

Turn a text-based French article PDF into reflowed Chinese and English PDFs using an OpenAI-compatible translation API. Images are restored and detected editorial commentary is styled separately. This is an independent tool, not an official Le Grand Continent product.

## Windows setup

1. Download this repository as a ZIP and **extract it**, or clone it. Keep the project files together; the folder may have any name. Use a writable folder, not a protected system directory.
2. Install **Python 3.10+** if needed ([python.org](https://www.python.org/downloads/)); 64-bit Python 3.13 is recommended. Enable the Python launcher or add Python to PATH.
3. Create a plain UTF-8 file named `.env` (not `.env.txt`) beside `news_translate.py`, containing:

   ```dotenv
   NEWS_API_KEY=YOUR_API_KEY_HERE
   NEWS_API_MODEL=YOUR_MODEL_NAME_HERE
   NEWS_API_BASE_URL=https://example.invalid/v1
   ```

   Replace all three example values with your provider's settings. Use its OpenAI-compatible **base URL**, not a full `/chat/completions` endpoint. The example URL is deliberately nonfunctional. **Keep an existing working `.env` unchanged.** Process environment variables with these names override the local settings.
4. Double-click `_run news translation.bat`. At the path prompt, select one or more French PDFs in Explorer, **drag them into the console, then press Enter**. You can also drop several PDFs directly onto the batch file. Quoted paths and spaces are accepted. The launcher creates `.venv` and installs **PyMuPDF 1.26.7** from `requirements.txt` automatically. Initial setup needs internet access; Python itself is not installed by the launcher.
5. Choose **K to keep the originals and intermediate files**; this choice applies to the whole batch. PDFs are translated **one by one**, in the supplied order; duplicate selections are processed only once. **Pressing Enter instead permits permanent deletion of each original PDF and its article cache after that file's two output PDFs validate.** Keep a backup; PDF validation does not establish translation accuracy. If a translation fails, the launcher continues to the next PDF and lists failures at the end. Drop files at the path prompt, not while a translation is already running.

Both output PDFs are saved **beside the input PDF**, using translated titles as filenames. Existing output names are not overwritten. An outside Windows shortcut may point to the batch launcher, but must be recreated or retargeted after moving the project.

### Check setup without translating

From this folder in PowerShell:

```powershell
py -3 launch_news_translation.py --check
```

This prepares/checks dependencies without reading `.env` or calling the translation API. The Windows batch launcher also accepts `--check`.

## Command line

Run from the project folder. After the launcher has set up `.venv`:

```powershell
# Extract only: no API call and no source deletion.
.\.venv\Scripts\python.exe news_translate.py "C:\Articles\article.pdf" --extract-only

# Translate, keeping the original and cache (recommended).
.\.venv\Scripts\python.exe news_translate.py "C:\Articles\article.pdf" --keep

# Re-render cached translations without an API call or source deletion.
.\.venv\Scripts\python.exe news_translate.py "C:\Articles\article.pdf" --render-only --keep
```

A normal translation **without `--keep` deletes the source and default cache after both outputs validate**. The default work folder is `cache/<source-stem>.work`; use distinct source stems or `--work-dir "another-folder" --keep` to avoid sharing a cache between different articles. Render-only requires the original source and its matching cache, and still refuses existing output filenames. Failed/interrupted runs may leave partial output and cache; inspect them before retrying. The program does not deliberately delete the source on a failed run.

For manual setup, use `py -3 -m venv .venv`, then `.\.venv\Scripts\python.exe -m pip install -r requirements.txt`. On macOS/Linux, use `python3 -m venv .venv`, `.venv/bin/python -m pip install -r requirements.txt`, and `.venv/bin/python news_translate.py article.pdf --keep`; these platforms are **unverified** and cannot use the Windows batch file.

## Moving, privacy, and limitations

- Git tracks source files only. `.env`, `.venv`, caches, PDFs, shortcuts, and bytecode are local-only and ignored by Git. Never upload the entire working folder or force-add private files.
- Do not copy `.venv` to another PC. After moving or downloading the project, recreate its environment locally using the launcher. The project requires a working Python installation, filesystem permissions, and network access; universal compatibility is not guaranteed.
- Translation sends **article text and the source filename** to your selected provider and may incur API charges, including retries. Review that provider's privacy/retention policies and obtain permission before submitting material. Never commit API keys or private configuration.
- Input must be a text-based French PDF; OCR, encrypted PDFs and empty documents are unsupported. Output is reflowed, not an exact reproduction of source page geometry. Complex columns, footnotes and commentary/image detection need manual review.
- Review translated facts, names, quotations, numbers, captions and commentary. The model can make mistakes; this tool does not fact-check articles or establish rights to publish articles, images or translations.
- Windows startup, dependency installation, and offline extraction/rendering were verified with Python 3.13 and PyMuPDF 1.26.7. Live API compatibility and translation quality depend on your provider and configuration.

## Licensing and third-party notices

**This repository's original code is MIT licensed**, copyright 2026 Wyakh; see [LICENSE](<LICENSE>). This grant covers the project's own code only, not third-party libraries, articles, images, trademarks or API services.

The required dependency **PyMuPDF 1.26.7**, by Artifex, and its MuPDF technology have separate **AGPL-3.0 or commercial licensing**. They are downloaded separately and are not bundled in this repository. The MIT license does **not** relicense them or remove obligations for a combined application. If using or distributing a combined work under the AGPL route, comply with its applicable source, license and notice requirements; uses that cannot comply require an appropriate commercial license. In particular, do not treat this as an MIT-only bundled product. Consult the upstream terms for your intended use and distribution:

- [PyMuPDF licensing](https://pymupdf.readthedocs.io/en/latest/about.html#license-and-copyright)
- [PyMuPDF 1.26.7 distribution](https://pypi.org/project/PyMuPDF/1.26.7/)
- [GNU AGPL-3.0 license](https://www.gnu.org/licenses/agpl-3.0.html)
- [Artifex commercial licensing](https://artifex.com/licensing/)

Dependency distributions contain their applicable full licenses and additional notices. No third-party license or endorsement is granted by this README.
