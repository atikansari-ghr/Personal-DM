"""Deterministic local field extraction from OCR/native text.

Produces *proposed* values only. Users confirm before values affect naming or reminders.
Includes an ICAO 9303 TD3 (passport) MRZ parser with check-digit validation and labelled-field
heuristics for common document templates. Not every discrepancy can be detected.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def parse_date(text: str) -> date | None:
    text = (text or "").strip()
    m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", text)
    try:
        if m:
            return date(int(m[1]), int(m[2]), int(m[3]))
        m = re.fullmatch(r"(\d{1,2})[/.\- ](\d{1,2})[/.\- ](\d{4})", text)
        if m:  # day-first (common on Indian/Saudi documents)
            return date(int(m[3]), int(m[2]), int(m[1]))
        m = re.fullmatch(r"(\d{1,2})[\s\-/]*([A-Za-z]{3})[A-Za-z]*[\s\-/,]*(\d{4})", text)
        if m and m[2].lower() in MONTHS:
            return date(int(m[3]), MONTHS[m[2].lower()], int(m[1]))
    except ValueError:
        return None
    return None


@dataclass
class Proposal:
    key: str
    value: str
    source: str
    confidence: float
    flags: list[str] = field(default_factory=list)
    excerpt: str = ""


def _check_digit(data: str) -> int:
    weights = (7, 3, 1)
    total = 0
    for i, ch in enumerate(data):
        if ch.isdigit():
            v = int(ch)
        elif ch.isalpha():
            v = ord(ch.upper()) - 55
        else:
            v = 0
        total += v * weights[i % 3]
    return total % 10


def _mrz_date(yymmdd: str, future: bool) -> date | None:
    if not re.fullmatch(r"\d{6}", yymmdd):
        return None
    yy, mm, dd = int(yymmdd[:2]), int(yymmdd[2:4]), int(yymmdd[4:])
    today = date.today()
    century = 2000 if (yy + 2000) <= today.year + (20 if future else 0) else 1900
    try:
        return date(century + yy, mm, dd)
    except ValueError:
        return None


def parse_mrz(text: str) -> list[Proposal]:
    lines = [re.sub(r"\s", "", ln).upper() for ln in text.splitlines()]
    lines = [ln.replace("«", "<") for ln in lines if len(ln) >= 40 and ln.count("<") >= 3]
    for i in range(len(lines) - 1):
        l1, l2 = lines[i], lines[i + 1]
        if not l1.startswith("P") or len(l2) < 44:
            continue
        l1, l2 = l1[:44].ljust(44, "<"), l2[:44]
        out: list[Proposal] = []
        excerpt = "MRZ"
        country = l1[2:5].replace("<", "")
        names = l1[5:].split("<<", 1)
        surname = names[0].replace("<", " ").strip()
        given = names[1].replace("<", " ").strip() if len(names) > 1 else ""
        number, num_cd = l2[0:9], l2[9]
        nationality = l2[10:13].replace("<", "")
        dob, dob_cd = l2[13:19], l2[19]
        sex = l2[20]
        exp, exp_cd = l2[21:27], l2[27]

        def flag_if(ok, msg):
            return [] if ok else [msg]

        num_ok = num_cd.isdigit() and _check_digit(number) == int(num_cd)
        dob_ok = dob_cd.isdigit() and _check_digit(dob) == int(dob_cd)
        exp_ok = exp_cd.isdigit() and _check_digit(exp) == int(exp_cd)
        full = " ".join(p for p in (given, surname) if p)
        if full:
            out.append(Proposal("full_name", full.title(), "mrz", 0.85, [], excerpt))
        out.append(Proposal("document_number", number.replace("<", ""), "mrz", 0.95 if num_ok else 0.4,
                            flag_if(num_ok, "MRZ check digit mismatch for document number — check for misread characters."), excerpt))
        if country:
            out.append(Proposal("country_code", country, "mrz", 0.9, [], excerpt))
        if nationality:
            out.append(Proposal("nationality", nationality, "mrz", 0.9, [], excerpt))
        d = _mrz_date(dob, future=False)
        if d:
            out.append(Proposal("date_of_birth", d.isoformat(), "mrz", 0.95 if dob_ok else 0.4,
                                flag_if(dob_ok, "MRZ check digit mismatch for date of birth."), excerpt))
        e = _mrz_date(exp, future=True)
        if e:
            out.append(Proposal("expiry_date", e.isoformat(), "mrz", 0.95 if exp_ok else 0.4,
                                flag_if(exp_ok, "MRZ check digit mismatch for expiry date."), excerpt))
        if sex in "MFX":
            out.append(Proposal("sex", sex, "mrz", 0.9, [], excerpt))
        return out
    return []


LABELS = {
    "issue_date": [r"date\s*of\s*issue", r"issue\s*date", r"issued\s*on", r"date\s*issued"],
    "expiry_date": [r"date\s*of\s*expiry", r"expiry\s*date", r"expiration\s*date", r"valid\s*(?:until|till|thru|through)", r"expires?\s*(?:on)?"],
    "date_of_birth": [r"date\s*of\s*birth", r"\bdob\b", r"birth\s*date"],
    "document_number": [r"passport\s*no\.?", r"document\s*(?:no\.?|number)", r"licen[cs]e\s*(?:no\.?|number)", r"id\s*(?:no\.?|number)", r"policy\s*(?:no\.?|number)"],
    "issuer": [r"issuing\s*authority", r"authority", r"issued\s*by"],
    "place_of_issue": [r"place\s*of\s*issue"],
    "nationality": [r"nationality"],
}
DATE_RX = r"(\d{4}-\d{1,2}-\d{1,2}|\d{1,2}[/.\- ]\d{1,2}[/.\- ]\d{4}|\d{1,2}[\s\-/]*[A-Za-z]{3,9}[\s\-/,]*\d{4})"


def parse_labels(text: str) -> list[Proposal]:
    out = []
    flat = text.replace("\r", "")
    for key, patterns in LABELS.items():
        for pat in patterns:
            if key.endswith("_date") or key == "date_of_birth":
                m = re.search(pat + r"[\s:./-]*\n?\s*" + DATE_RX, flat, re.I)
                if m:
                    d = parse_date(m.group(1))
                    if d:
                        out.append(Proposal(key, d.isoformat(), "ocr", 0.6, [], m.group(0)[:200]))
                        break
            else:
                m = re.search(pat + r"[\s:./-]*\n?\s*([A-Z0-9][A-Z0-9 \-/]{2,40})", flat, re.I)
                if m:
                    val = m.group(1).strip().split("\n")[0].strip()
                    flags = []
                    if key == "document_number" and re.search(r"(?<=\d)[OIlSB]|[OIlSB](?=\d)", val[1:]):
                        flags.append("Possibly ambiguous characters (O/0, I/1, S/5) — please verify.")
                    out.append(Proposal(key, val, "ocr", 0.5, flags, m.group(0)[:200]))
                    break
    return out


def extract(text: str, *, owner_names: list[str] | None = None, template: str = "generic") -> list[Proposal]:
    proposals: dict[str, Proposal] = {}
    for p in parse_labels(text or ""):
        proposals[p.key] = p
    for p in parse_mrz(text or ""):  # MRZ wins over labels when both exist, but conflicts are flagged
        prev = proposals.get(p.key)
        if prev and prev.value != p.value:
            p.flags.append(f"Conflicts with printed value '{prev.value}'.")
            p.confidence = min(p.confidence, 0.5)
        proposals[p.key] = p
    issue = parse_date(proposals["issue_date"].value) if "issue_date" in proposals else None
    expiry = parse_date(proposals["expiry_date"].value) if "expiry_date" in proposals else None
    dob = parse_date(proposals["date_of_birth"].value) if "date_of_birth" in proposals else None
    if issue and expiry and issue >= expiry:
        proposals["expiry_date"].flags.append("Expiry date is not after issue date.")
    if dob and issue and dob >= issue:
        proposals["issue_date"].flags.append("Issue date is before the date of birth.")
    if owner_names and "full_name" in proposals:
        name = proposals["full_name"].value.lower()
        if not any(tok and tok.lower() in name for n in owner_names for tok in n.split()):
            proposals["full_name"].flags.append("Name does not match the document owner's account name.")
    return list(proposals.values())
