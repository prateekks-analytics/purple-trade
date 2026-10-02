"""The single upload path: bots, code, notes, spreadsheets and documents are read and converted into rules.

Nothing uploaded is ever executed. Files are only read as text: a Purple strategy .json imports exactly,
everything else is handed to the AI as data to translate. Office files and PDFs are read with the
standard library only (zip + XML, best-effort PDF text), so no extra packages are needed.
"""
from __future__ import annotations

import io
import json
import re
import zipfile
import zlib
from pathlib import PurePath
from xml.etree import ElementTree as ET

from pydantic import ValidationError

from .schema import Strategy

MAX_BYTES = 5 * 1024 * 1024
MAX_TEXT_BYTES = 200 * 1024
MAX_AI_CHARS = 16_000  # keeps prompt + file inside the local model's context window
CODE_EXTENSIONS = {".py", ".pine", ".js", ".ts", ".mq4", ".mq5", ".mql", ".cs", ".java", ".r", ".ipynb"}
TEXT_EXTENSIONS = {".txt", ".md", ".csv", ".tsv", ".json"}
OFFICE_EXTENSIONS = {".xlsx", ".xlsm", ".docx"}
ACCEPTED = sorted(CODE_EXTENSIONS | TEXT_EXTENSIONS | OFFICE_EXTENSIONS | {".pdf"})
EXPORT_FORMAT = "purple-strategy"


class AgentError(ValueError):
    pass


def decode_upload(filename: str, data: bytes) -> tuple[str, str]:
    """Return (kind, text). kind: 'purple-json' (exact import), 'code' (bot source) or 'document'."""
    if not data:
        raise AgentError("The file is empty.")
    if len(data) > MAX_BYTES:
        raise AgentError("The file is larger than 5 MB.")
    ext = PurePath(filename or "").suffix.lower()
    if ext in (".xls", ".doc"):
        raise AgentError(f"Old {ext} files can't be read. Save it as {ext}x (or .csv / .pdf) and upload again.")
    if ext in (".xlsx", ".xlsm"):
        return "document", _xlsx_text(data)
    if ext == ".docx":
        return "document", _docx_text(data)
    if ext == ".pdf":
        return "document", _pdf_text(data)
    if ext and ext not in CODE_EXTENSIONS | TEXT_EXTENSIONS:
        raise AgentError(f"Unsupported file type '{ext}'. Upload bot code (.py, .pine, .js, .mq5…), text (.txt, .md), "
                         "a spreadsheet (.xlsx, .csv), a document (.docx, .pdf) or a Purple .json.")
    if len(data) > MAX_TEXT_BYTES:
        raise AgentError("Text files can be at most 200 KB.")
    if b"\x00" in data[:4096]:
        raise AgentError("This looks like a binary file, not text.")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("cp1252", errors="replace")
    if ext == ".json":
        return "purple-json", text
    if ext == ".ipynb":
        return "code", _notebook_code(text)
    if ext in (".csv", ".tsv") and _looks_like_prices(text):
        raise AgentError("This looks like price data, not a strategy. Import it under 'Test on → Import NSE CSV…' "
                         "in a strategy instead.")
    return ("code" if ext in CODE_EXTENSIONS else "document"), text


def parse_purple_json(text: str) -> Strategy:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise AgentError(f"Not valid JSON (line {e.lineno}).") from None
    if isinstance(data, dict) and isinstance(data.get("strategy"), dict):
        data = data["strategy"]
    try:
        return Strategy.model_validate(data)
    except ValidationError as e:
        first = e.errors()[0]
        loc = ".".join(str(p) for p in first["loc"])
        raise AgentError(f"JSON is not a Purple strategy ({loc}: {first['msg']}).") from None


def is_purple_json(text: str) -> bool:
    try:
        parse_purple_json(text)
        return True
    except AgentError:
        return False


def export_payload(strategy: dict) -> dict:
    return {"format": EXPORT_FORMAT, "version": 1, "strategy": strategy}


def check_code_size(text: str) -> None:
    if not text.strip():
        raise AgentError("The file has no readable text.")
    if len(text) > MAX_AI_CHARS:
        raise AgentError(f"The file has {len(text):,} characters of text; the local AI can read about {MAX_AI_CHARS:,}. "
                         "Upload just the part that contains the buy/sell logic.")


# ---------- readers (no execution, standard library only) ----------

def _looks_like_prices(text: str) -> bool:
    head = text.splitlines()[0].lower() if text.strip() else ""
    cols = {c.strip().strip('"') for c in re.split(r"[,\t;]", head)}
    return "date" in cols and ("close" in cols or "close price" in cols) and ("open" in cols or "open price" in cols)


def _zip(data: bytes) -> zipfile.ZipFile:
    try:
        return zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise AgentError("The file is damaged or not a real Office file.") from None


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _xlsx_text(data: bytes) -> str:
    z = _zip(data)
    names = z.namelist()
    shared: list[str] = []
    if "xl/sharedStrings.xml" in names:
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")):
            shared.append("".join(t.text or "" for t in si.iter() if _local(t.tag) == "t"))
    sheets = sorted(n for n in names if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n))
    out: list[str] = []
    for n in sheets:
        out.append(f"# {PurePath(n).stem}")
        for row in ET.fromstring(z.read(n)).iter():
            if _local(row.tag) != "row":
                continue
            cells = []
            for c in row:
                if _local(c.tag) != "c":
                    continue
                v = next((x.text for x in c.iter() if _local(x.tag) in ("v", "t") and x.text), "")
                if c.get("t") == "s" and v.isdigit() and int(v) < len(shared):
                    v = shared[int(v)]
                cells.append(v)
            if any(cells):
                out.append("\t".join(cells))
    text = "\n".join(out)
    if not text.strip():
        raise AgentError("The spreadsheet has no readable cells.")
    return text


def _docx_text(data: bytes) -> str:
    z = _zip(data)
    if "word/document.xml" not in z.namelist():
        raise AgentError("Not a Word .docx file.")
    paras = []
    for p in ET.fromstring(z.read("word/document.xml")).iter():
        if _local(p.tag) == "p":
            line = "".join(t.text or "" for t in p.iter() if _local(t.tag) == "t")
            if line.strip():
                paras.append(line)
    if not paras:
        raise AgentError("The document has no readable text.")
    return "\n".join(paras)


_PDF_ESC = {"n": "\n", "r": "\r", "t": "\t", "b": "\b", "f": "\f", "(": "(", ")": ")", "\\": "\\"}


def _pdf_literal(s: str) -> str:
    out, i = [], 0
    while i < len(s):
        ch = s[i]
        if ch == "\\" and i + 1 < len(s):
            nxt = s[i + 1]
            if nxt in _PDF_ESC:
                out.append(_PDF_ESC[nxt]); i += 2; continue
            m = re.match(r"[0-7]{1,3}", s[i + 1:])
            if m:
                out.append(chr(int(m.group(0), 8))); i += 1 + len(m.group(0)); continue
            i += 1; continue
        out.append(ch); i += 1
    return "".join(out)


def _pdf_text(data: bytes) -> str:
    """Best effort: text drawn with simple fonts. Scanned PDFs and some embedded fonts are not readable."""
    if not data.startswith(b"%PDF"):
        raise AgentError("Not a PDF file.")
    chunks: list[str] = []
    for m in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", data, re.S):
        raw = m.group(1)
        try:
            raw = zlib.decompress(raw)
        except zlib.error:
            pass
        content = raw.decode("latin-1")
        if "BT" not in content:
            continue
        for block in re.findall(r"BT(.*?)ET", content, re.S):
            line = []
            for op in re.finditer(r"\((?:\\.|[^\\)])*\)\s*(?:Tj|'|\")|\[(.*?)\]\s*TJ|(T\*|Td|TD)", block, re.S):
                tok = op.group(0)
                if op.group(2):
                    line.append("\n")
                elif tok.startswith("("):
                    line.append(_pdf_literal(tok[1:tok.rindex(")")]))
                else:  # TJ array: strings plus kerning numbers; a big negative gap is a space
                    for s, num in re.findall(r"(\((?:\\.|[^\\)])*\))|(-?\d+(?:\.\d+)?)", op.group(1)):
                        if s:
                            line.append(_pdf_literal(s[1:-1]))
                        elif num and float(num) < -200:
                            line.append(" ")
            chunks.append("".join(line))
    text = re.sub(r"[ \t]+", " ", "\n".join(chunks))
    text = "\n".join(l.strip() for l in text.splitlines() if l.strip())
    letters = sum(c.isalpha() for c in text)
    if letters < 20:
        raise AgentError("Couldn't read text from this PDF (it may be scanned or use special fonts). "
                         "Copy the strategy text into the idea box, or upload it as .docx or .txt.")
    return text


def _notebook_code(text: str) -> str:
    try:
        nb = json.loads(text)
        cells = [c for c in nb.get("cells", []) if c.get("cell_type") == "code"]
        return "\n\n".join("".join(c.get("source", [])) for c in cells)
    except (json.JSONDecodeError, AttributeError):
        raise AgentError("Could not read the notebook.") from None
