import io
import os
import uuid
from pathlib import Path

from docx import Document
from fastapi import HTTPException, UploadFile
from pypdf import PdfReader


UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "uploads")).resolve()
MAX_BYTES = 5 * 1024 * 1024


async def save_and_extract(file: UploadFile) -> tuple[str, str]:
    ext = Path(file.filename or "").suffix.lower()
    if ext not in {".pdf", ".docx"}:
        raise HTTPException(422, "只支持 PDF / DOCX 简历")
    data = await file.read(MAX_BYTES + 1)
    if not data or len(data) > MAX_BYTES:
        raise HTTPException(422, "简历必须是非空且不超过 5 MB")
    if ext == ".pdf" and not data.startswith(b"%PDF"):
        raise HTTPException(422, "PDF 文件格式无效")
    if ext == ".docx" and not data.startswith(b"PK"):
        raise HTTPException(422, "DOCX 文件格式无效")
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    path = UPLOAD_DIR / (uuid.uuid4().hex + ext)
    path.write_bytes(data)
    try:
        if ext == ".pdf":
            reader = PdfReader(io.BytesIO(data))
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
        else:
            doc = Document(io.BytesIO(data))
            text = "\n".join(p.text for p in doc.paragraphs)
    except Exception:
        text = ""
    return str(path), text.strip()[:50000]
