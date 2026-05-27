"""Mirror of sdk/llm_sdk/pii.py — kept inside ingestion to provide
defense-in-depth (SDK may run untrusted code; ingestion enforces redaction
again before write)."""
import re

_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
_PHONE = re.compile(
    r"(?:\+?\d{1,3}[\s-])?"
    r"(?:\(\d{3}\)\s?\d{3}[\s-]?\d{4}|\b\d{3}[\s-]\d{3}[\s-]\d{4}\b)"
)
_SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_CC = re.compile(r"\b(?:\d[ -]*?){13,19}\b")


def _luhn(d: str) -> bool:
    total, alt = 0, False
    for ch in reversed(d):
        n = int(ch)
        if alt:
            n *= 2
            if n > 9:
                n -= 9
        total += n
        alt = not alt
    return total % 10 == 0


def _cc_filter(m: re.Match) -> str:
    digits = re.sub(r"\D", "", m.group(0))
    if 13 <= len(digits) <= 19 and _luhn(digits):
        return "[REDACTED-CC]"
    return m.group(0)


def redact(text: str | None) -> str | None:
    if not text:
        return text
    text = _EMAIL.sub("[REDACTED-EMAIL]", text)
    text = _CC.sub(_cc_filter, text)
    text = _SSN.sub("[REDACTED-SSN]", text)
    text = _PHONE.sub("[REDACTED-PHONE]", text)
    return text
