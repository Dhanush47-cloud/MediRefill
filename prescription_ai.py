"""Conservative prescription OCR draft extraction. Never authorises dispensing."""
from __future__ import annotations
import io, re
from dataclasses import dataclass, asdict
from typing import Any

@dataclass
class PrescriptionDraft:
    raw_text: str
    medicines: list[dict[str, Any]]
    confidence: float
    review_required: bool = True
    warning: str = "OCR output is an unverified draft. A registered pharmacist must review every field."

def extract_prescription(file_bytes: bytes, filename: str) -> PrescriptionDraft:
    """OCR an image or PDF. PDF uses first page only. Returns conservative text candidates."""
    if not file_bytes:
        raise ValueError("The uploaded prescription is empty.")
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    if ext not in {"png", "jpg", "jpeg", "pdf"}:
        raise ValueError("Only PDF, JPG and PNG files are accepted.")
    try:
        import pytesseract
        from PIL import Image, ImageOps, ImageEnhance
        if ext == "pdf":
            from pdf2image import convert_from_bytes
            pages = convert_from_bytes(file_bytes, first_page=1, last_page=1, dpi=220)
            if not pages:
                raise ValueError("No readable page was found in the PDF.")
            image = pages[0]
        else:
            image = Image.open(io.BytesIO(file_bytes))
        image = ImageOps.grayscale(image)
        image = ImageEnhance.Contrast(image).enhance(1.6)
        text = pytesseract.image_to_string(image, config="--psm 6")
    except ValueError:
        raise
    except Exception as exc:
        raise RuntimeError("OCR could not read this file. Request a clearer upload or manual pharmacist review.") from exc
    cleaned = "\n".join(line.strip() for line in text.splitlines() if line.strip())
    candidates=[]
    for line in cleaned.splitlines():
        if re.search(r"\b(mg|mcg|ml|tablet|tab|capsule|cap|syrup)\b", line, re.I):
            candidates.append({"text": line[:240], "match_status": "unmatched_draft", "confidence": None})
    confidence = 0.65 if len(cleaned) >= 30 else 0.2
    if not cleaned:
        confidence = 0.0
    return PrescriptionDraft(cleaned, candidates[:20], confidence)

def draft_to_dict(draft: PrescriptionDraft) -> dict:
    return asdict(draft)
