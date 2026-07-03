from __future__ import annotations

"""PDF bill/receipt extraction helpers.

This is intentionally heuristic and local-only: it extracts selectable text from
PDF files and converts it into editable expense candidates. It does not post any
money movement by itself; routes still save through the existing transaction and
receipt services.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from io import BytesIO
import re
from typing import Any, Iterable


TOTAL_KEYWORDS = (
    "totale",
    "total",
    "total",
    "importo",
    "amount due",
    "amount paid",
    "pagato",
    "paid",
    "grand total",
    "saldo",
)
SUBTOTAL_KEYWORDS = ("subtotale", "subtotal", "imponibile", "netto")
DISCOUNT_KEYWORDS = ("sconto", "discount", "coupon", "voucher", "buono", "promo", "rebate")
IGNORE_ITEM_KEYWORDS = (
    "iva",
    "vat",
    "tax",
    "totale",
    "total",
    "subtotal",
    "subtotale",
    "pagato",
    "payment",
    "carta",
    "card",
    "bancomat",
    "contanti",
    "cash",
    "resto",
    "change",
    "sconto",
    "discount",
    "invoice",
    "fattura",
    "receipt",
    "ricevuta",
)
DATE_PATTERNS = (
    re.compile(r"\b(?P<day>\d{1,2})[\-/\.](?P<month>\d{1,2})[\-/\.](?P<year>\d{2,4})\b"),
    re.compile(r"\b(?P<year>20\d{2}|19\d{2})[\-/\.](?P<month>\d{1,2})[\-/\.](?P<day>\d{1,2})\b"),
)
AMOUNT_RE = re.compile(
    r"(?<!\d)(?:€|EUR)?\s*(?P<amount>-?\d{1,3}(?:[.\s]\d{3})*(?:[,.]\d{2})|-?\d+[,.]\d{2}|-?\d+)\s*(?:€|EUR)?(?!\d)",
    re.IGNORECASE,
)
TRAILING_AMOUNT_RE = re.compile(
    r"^(?P<label>.*?)(?:\s+|\t)(?:€|EUR)?\s*(?P<amount>-?\d{1,3}(?:[.\s]\d{3})*(?:[,.]\d{2})|-?\d+[,.]\d{2})\s*(?:€|EUR)?\s*$",
    re.IGNORECASE,
)
PERCENT_RE = re.compile(r"(?P<value>\d{1,3}(?:[,.]\d+)?)\s*%")


@dataclass(slots=True)
class BillCandidate:
    source_filename: str
    merchant: str
    date: str
    description: str
    amount: float
    subtotal: float
    discount_type: str = "none"
    discount_value: float = 0.0
    items: list[dict[str, Any]] = field(default_factory=list)
    notes: str = ""
    confidence: str = "medium"
    warning: str = ""
    extracted_text_preview: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "source_filename": self.source_filename,
            "merchant": self.merchant,
            "date": self.date,
            "description": self.description,
            "amount": round(float(self.amount or 0), 2),
            "subtotal": round(float(self.subtotal or 0), 2),
            "discount_type": self.discount_type,
            "discount_value": round(float(self.discount_value or 0), 2),
            "items": self.items,
            "notes": self.notes,
            "confidence": self.confidence,
            "warning": self.warning,
            "extracted_text_preview": self.extracted_text_preview,
        }


def scan_bill_files(files: Iterable[Any], *, default_date: str | None = None) -> dict[str, Any]:
    """Return editable expense candidates from uploaded PDF/text files."""
    candidates: list[dict[str, Any]] = []
    errors: list[str] = []
    today = default_date or date.today().isoformat()

    for uploaded in files or []:
        filename = _safe_filename(getattr(uploaded, "filename", "") or "uploaded-file")
        if not filename:
            continue
        try:
            payload = uploaded.read()
        except Exception as exc:  # pragma: no cover - defensive for FileStorage variants
            errors.append(f"{filename}: could not read upload ({exc}).")
            continue
        if not payload:
            errors.append(f"{filename}: empty file.")
            continue

        try:
            text = extract_text_from_upload(filename, payload)
        except Exception as exc:
            errors.append(f"{filename}: {exc}")
            continue
        if not text.strip():
            errors.append(f"{filename}: no selectable text found. Scanned-image PDFs need OCR before importing.")
            continue

        candidate = parse_bill_text(text, source_filename=filename, default_date=today)
        candidates.append(candidate.as_dict())

    return {"candidates": candidates, "errors": errors, "ok": bool(candidates)}


def extract_text_from_upload(filename: str, payload: bytes) -> str:
    suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if suffix == "pdf":
        return extract_pdf_text(payload)
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError:
        return payload.decode("latin-1", errors="ignore")


def extract_pdf_text(payload: bytes) -> str:
    try:
        from pypdf import PdfReader
    except Exception as exc:  # pragma: no cover - depends on optional install
        raise RuntimeError("PDF text extraction requires the pypdf package. Run: pip install pypdf") from exc

    reader = PdfReader(BytesIO(payload))
    chunks: list[str] = []
    for page in reader.pages:
        try:
            chunks.append(page.extract_text() or "")
        except Exception:
            chunks.append("")
    return "\n".join(chunks)


def parse_bill_text(text: str, *, source_filename: str = "", default_date: str | None = None) -> BillCandidate:
    lines = _normalised_lines(text)
    merchant = _detect_merchant(lines, source_filename)
    purchased_at = _detect_date(lines) or default_date or date.today().isoformat()
    discount_type, discount_value = _detect_discount(lines)
    total = _detect_total(lines)
    subtotal = _detect_subtotal(lines)
    items = _detect_items(lines)

    if subtotal <= 0 and items:
        subtotal = round(sum(float(item.get("line_total") or 0) for item in items), 2)
    if total <= 0 and subtotal > 0:
        total = round(max(0.0, subtotal - (discount_value if discount_type == "voucher" else 0.0)), 2)
    if total <= 0:
        amounts = [_parse_amount(match.group("amount")) for line in lines for match in AMOUNT_RE.finditer(line)]
        amounts = [value for value in amounts if value > 0]
        total = max(amounts) if amounts else 0.0
    if subtotal <= 0:
        subtotal = round(total + (discount_value if discount_type == "voucher" else 0.0), 2)
    if not items and total > 0:
        items = [{
            "name": merchant or "PDF bill",
            "qty": 1,
            "unit_price": round(total, 2),
            "line_total": round(total, 2),
            "note": "Fallback row from detected total.",
        }]

    warning = ""
    confidence = "high" if total > 0 and purchased_at and merchant and len(items) > 1 else "medium"
    if total <= 0:
        warning = "No reliable total was detected; review the amount before saving."
        confidence = "low"
    elif len(items) <= 1:
        warning = "Only one receipt row was detected; review items if the PDF contains a detailed receipt."
        confidence = "medium"

    description = merchant or _safe_filename(source_filename) or "PDF bill"
    preview = "\n".join(lines[:24])
    return BillCandidate(
        source_filename=source_filename,
        merchant=merchant,
        date=purchased_at,
        description=description,
        amount=round(total, 2),
        subtotal=round(subtotal, 2),
        discount_type=discount_type,
        discount_value=round(discount_value, 2),
        items=items[:80],
        notes=f"Imported from {source_filename}" if source_filename else "Imported from PDF bill scanner",
        confidence=confidence,
        warning=warning,
        extracted_text_preview=preview,
    )


def _normalised_lines(text: str) -> list[str]:
    result: list[str] = []
    for raw in str(text or "").replace("\r", "\n").split("\n"):
        line = " ".join(raw.strip().split())
        if line:
            result.append(line)
    return result


def _detect_merchant(lines: list[str], filename: str) -> str:
    for line in lines[:20]:
        clean = line.strip(" -_·•")
        lowered = clean.casefold()
        if len(clean) < 3:
            continue
        if any(token in lowered for token in ("receipt", "ricevuta", "fattura", "invoice", "documento", "totale", "total", "p.iva", "vat")):
            continue
        if _line_amounts(clean):
            continue
        return clean[:80]
    base = _safe_filename(filename).rsplit(".", 1)[0]
    return base[:80] if base else "PDF bill"


def _detect_date(lines: list[str]) -> str:
    for line in lines[:80]:
        for pattern in DATE_PATTERNS:
            match = pattern.search(line)
            if not match:
                continue
            try:
                year = int(match.group("year"))
                if year < 100:
                    year += 2000 if year < 70 else 1900
                month = int(match.group("month"))
                day = int(match.group("day"))
                return datetime(year, month, day).date().isoformat()
            except ValueError:
                continue
    return ""


def _detect_total(lines: list[str]) -> float:
    candidates: list[tuple[int, float]] = []
    for line in lines:
        lowered = line.casefold()
        if any(word in lowered for word in SUBTOTAL_KEYWORDS):
            continue
        if not any(word in lowered for word in TOTAL_KEYWORDS):
            continue
        amounts = _line_amounts(line)
        if amounts:
            # Prefer the rightmost amount on total lines.
            candidates.append((len(line), amounts[-1]))
    if candidates:
        return round(candidates[-1][1], 2)
    return 0.0


def _detect_subtotal(lines: list[str]) -> float:
    for line in lines:
        lowered = line.casefold()
        if not any(word in lowered for word in SUBTOTAL_KEYWORDS):
            continue
        amounts = _line_amounts(line)
        if amounts:
            return round(amounts[-1], 2)
    return 0.0


def _detect_discount(lines: list[str]) -> tuple[str, float]:
    for line in lines:
        lowered = line.casefold()
        if not any(word in lowered for word in DISCOUNT_KEYWORDS):
            continue
        percent = PERCENT_RE.search(line)
        if percent:
            return "percent", min(100.0, max(0.0, _parse_amount(percent.group("value"))))
        amounts = _line_amounts(line)
        if amounts:
            return "voucher", round(abs(amounts[-1]), 2)
    return "none", 0.0


def _detect_items(lines: list[str]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for line in lines:
        lowered = line.casefold()
        if any(word in lowered for word in IGNORE_ITEM_KEYWORDS):
            continue
        match = TRAILING_AMOUNT_RE.match(line)
        if not match:
            continue
        label = re.sub(r"\s{2,}", " ", match.group("label") or "").strip(" -–—·•")
        if len(label) < 2 or label.isdigit():
            continue
        amount = _parse_amount(match.group("amount"))
        if amount <= 0:
            continue
        qty = 1.0
        unit_price = amount
        # Common receipt pattern: "2 x Milk 1,20 2,40" or "2 Milk 2,40".
        qty_match = re.match(r"^(?P<qty>\d+(?:[,.]\d+)?)\s*(?:x|×)?\s+(?P<name>.+)$", label, flags=re.IGNORECASE)
        if qty_match:
            parsed_qty = _parse_amount(qty_match.group("qty"))
            if 0 < parsed_qty <= 999:
                qty = parsed_qty
                label = qty_match.group("name").strip()
                unit_price = round(amount / qty, 2) if qty else amount
        items.append({
            "name": label[:120],
            "qty": qty,
            "unit_price": round(unit_price, 2),
            "line_total": round(amount, 2),
            "note": "",
        })
    return _dedupe_items(items)


def _dedupe_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, float]] = set()
    result: list[dict[str, Any]] = []
    for item in items:
        key = (str(item.get("name") or "").casefold(), round(float(item.get("line_total") or 0), 2))
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _line_amounts(line: str) -> list[float]:
    values: list[float] = []
    for match in AMOUNT_RE.finditer(line or ""):
        value = _parse_amount(match.group("amount"))
        # Avoid treating years as money when the line is mainly a date.
        if 1900 <= value <= 2099 and re.search(r"\d{1,2}[\-/\.]\d{1,2}[\-/\.]\d{2,4}", line):
            continue
        values.append(value)
    return values


def _parse_amount(value: Any) -> float:
    text = str(value or "").strip().replace("€", "").replace("EUR", "").replace(" ", "")
    if not text:
        return 0.0
    # Italian/euro format: 1.234,56. English: 1,234.56.
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        text = text.replace(",", ".")
    try:
        return round(float(text), 2)
    except ValueError:
        return 0.0


def _safe_filename(value: str) -> str:
    text = str(value or "").strip().replace("\\", "/").rsplit("/", 1)[-1]
    text = re.sub(r"[^A-Za-z0-9À-ÿ._()\-\s]+", "_", text)
    return text[:120].strip(" ._")
