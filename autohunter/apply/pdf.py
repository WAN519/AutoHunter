"""Export the tailored .docx to PDF for upload, using Microsoft Word on macOS (exact layout).

Word only exports reliably when `saveAs` is called on the *document* (JXA), and the file must sit
inside Word's own sandbox container, or Word asks "Grant File Access" and blocks until clicked.
A same-named PDF that's newer than the .docx (e.g. one the user exported) is reused.
If Word isn't available, return the .docx: every ATS here accepts it.
"""
from __future__ import annotations

import platform
import shutil
import subprocess
import tempfile
from pathlib import Path

WORD = Path("/Applications/Microsoft Word.app")
# Word is sandboxed: opening a file anywhere else pops "Grant File Access". Its own container is
# always readable / writable for it, so round-trip through there and no dialog ever appears.
WORD_SANDBOX = Path.home() / "Library" / "Containers" / "com.microsoft.Word" / "Data" / "tmp"

JXA = r"""
function run(argv) {
  const [src, dst, quit] = argv;
  const w = Application("Microsoft Word");
  w.open(Path(src));
  let d = null;
  for (let i = 0; i < 40 && !d; i++) { delay(0.25); try { d = w.activeDocument; d.name(); } catch (e) { d = null; } }
  d.saveAs({fileName: dst, fileFormat: "format PDF"});
  d.close({saving: "no"});
  if (quit === "1") w.quit({saving: "no"});
  return "ok";
}
"""


def word_responsive(timeout: int = 6) -> bool:
    """False if Word is stuck behind a dialog: then every Apple Event to it would hang forever."""
    if not _word_running():
        return True
    try:
        r = subprocess.run(["osascript", "-e", 'tell application "Microsoft Word" to get name'],
                           capture_output=True, text=True, timeout=timeout)
        return r.returncode == 0
    except subprocess.TimeoutExpired:
        return False


def _word_running() -> bool:
    return subprocess.run(["pgrep", "-x", "Microsoft Word"], capture_output=True).returncode == 0


def to_pdf(docx: Path, timeout: int = 45) -> Path:
    pdf = docx.with_suffix(".pdf")
    if pdf.exists() and pdf.stat().st_mtime >= docx.stat().st_mtime:
        return pdf
    if platform.system() != "Darwin" or not WORD.exists():
        return docx
    if not word_responsive():
        return docx  # caller notes it; never wait on a Word dialog
    quit_after = "0" if _word_running() else "1"
    base = WORD_SANDBOX if WORD_SANDBOX.parent.exists() else Path("/tmp")
    base.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="autohunter-pdf-", dir=base) as tmp:
        src, dst = Path(tmp) / "resume.docx", Path(tmp) / "resume.pdf"
        shutil.copy2(docx, src)
        try:
            subprocess.run(["osascript", "-l", "JavaScript", "-e", JXA, str(src), str(dst), quit_after],
                           capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return docx
        if not dst.exists() or dst.stat().st_size < 1000:
            return docx
        shutil.move(str(dst), str(pdf))
    return pdf
