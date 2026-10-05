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


def parse_date_info(text: str) -> tuple[date | None, bool]:
    """(date, ambiguous). Numeric dates are read day-first (common on Saudi/Indian documents); when that is
    impossible (e.g. 12-31-2030) month-first is used. Both readings valid and different -> ambiguous."""
    text = (text or "").strip().rstrip(".,")
    try:
        m = re.fullmatch(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", text)
        if m:
            return date(int(m[1]), int(m[2]), int(m[3])), False
        m = re.fullmatch(r"(\d{1,2})[/.\- ](\d{1,2})[/.\- ](\d{4})", text)
        if m:
            a, b, y = int(m[1]), int(m[2]), int(m[3])
            dmy = mdy = None
            try:
                dmy = date(y, b, a)
            except ValueError:
                pass
            try:
                mdy = date(y, a, b)
            except ValueError:
                pass
            if dmy and mdy and dmy != mdy:
                return dmy, True
            return dmy or mdy, False
        m = re.fullmatch(r"(\d{1,2})[\s\-/]*([A-Za-z]{3})[A-Za-z]*[\s\-/,]*(\d{4})", text)
        if m and m[2].lower() in MONTHS:
            return date(int(m[3]), MONTHS[m[2].lower()], int(m[1])), False
        m = re.fullmatch(r"([A-Za-z]{3})[A-Za-z]*[\s\-/]*(\d{1,2}),?[\s\-/]*(\d{4})", text)
        if m and m[1].lower() in MONTHS:
            return date(int(m[3]), MONTHS[m[1].lower()], int(m[2])), False
    except ValueError:
        return None, False
    return None, False


def parse_date(text: str) -> date | None:
    return parse_date_info(text)[0]


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
    "issue_date": [r"date\s*of\s*issue", r"issue\s*date", r"issued\s*on", r"date\s*issued", r"\bissued\b"],
    "expiry_date": [r"date\s*of\s*expiry", r"expiry\s*date", r"expiration\s*date", r"exp(?:iry|\.)?\s*date",
                    r"valid\s*(?:until|till|thru|through|upto|up\s*to)", r"expires?\s*(?:on)?", r"\bexpiry\b"],
    "date_of_birth": [r"date\s*of\s*birth", r"\bdob\b", r"birth\s*date"],
    "document_number": [r"passport\s*no\.?", r"document\s*(?:no\.?|number)", r"licen[cs]e\s*(?:no\.?|number)",
                        r"(?:national\s*)?id\s*(?:no\.?|number|#)", r"policy\s*(?:no\.?|number)", r"badge\s*(?:no\.?|number|#)",
                        r"employee\s*(?:no\.?|number|id)", r"iqama\s*(?:no\.?|number)", r"resident\s*(?:id|no\.?|number)",
                        r"card\s*(?:no\.?|number)", r"certificate\s*(?:no\.?|number)"],
    "issuer": [r"issuing\s*authority", r"issued\s*by"],
    "place_of_issue": [r"place\s*of\s*issue"],
    "nationality": [r"nationality"],
}
DATE_RX = r"(\d{4}[-/.]\d{1,2}[-/.]\d{1,2}|\d{1,2}[/.\-]\d{1,2}[/.\-]\d{4}|\d{1,2}[\s\-/]*[A-Za-z]{3,9}[\s\-/,]*\d{4}|[A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4})"
NO_EXPIRY_RX = r"\b(?:no\s+expiry(?:\s+date)?|no\s+expiration(?:\s+date)?|does\s+not\s+expire|non[-\s]?expiring|valid\s+(?:indefinitely|for\s+life|permanently)|lifetime\s+validity|permanent)\b"
ID_RX = r"[A-Z0-9][A-Z0-9\-/]{2,30}"
DATE_KEYS = ("issue_date", "expiry_date", "date_of_birth")


def _date_proposal(key: str, raw: str, source: str, excerpt: str, confidence: float = 0.6) -> Proposal | None:
    d, ambiguous = parse_date_info(raw)
    if d is None:
        return None
    flags = ["Day and month could be read either way — please check."] if ambiguous else []
    return Proposal(key, d.isoformat(), source, confidence - (0.2 if ambiguous else 0), flags, excerpt[:200])


def _label_spans(line: str) -> list[tuple[int, int, str]]:
    """Non-overlapping (start, end, key) label matches on one line, left to right (longest match wins)."""
    found = []
    for key, patterns in LABELS.items():
        for pat in patterns:
            for m in re.finditer(pat, line, re.I):
                found.append((m.start(), m.end(), key))
    found.sort(key=lambda s: (s[0], -(s[1] - s[0])))
    out, end = [], -1
    for s in found:
        if s[0] >= end:
            out.append(s)
            end = s[1]
    return out


def parse_columns(lines: list[str]) -> list[Proposal]:
    """A header line with several labels followed by a line of values (ID-card tables such as
    'Badge No   Expiry Date' / '145070   12-31-2030'): pair values with labels left to right by type."""
    out = []
    for i in range(len(lines) - 1):
        spans = _label_spans(lines[i])
        rest = re.sub(r"[\W_]+", "", re.sub("|".join(p for ps in LABELS.values() for p in ps), "", lines[i], flags=re.I))
        if len(spans) < 2 or len(rest) > 6:  # a real header line holds (almost) only labels
            continue
        values = lines[i + 1]
        dates = [(m.start(), m.group(0)) for m in re.finditer(DATE_RX, values)]
        others = [(m.start(), m.group(0)) for m in re.finditer(ID_RX, values)
                  if not any(ds <= m.start() < ds + len(dv) for ds, dv in dates)]
        for _s, _e, key in spans:
            pool = dates if key in DATE_KEYS else others
            if not pool:
                continue
            _pos, raw = pool.pop(0)
            excerpt = f"{lines[i].strip()} / {values.strip()}"
            if key in DATE_KEYS:
                p = _date_proposal(key, raw, "ocr", excerpt, 0.65)
                if p:
                    out.append(p)
            else:
                out.append(Proposal(key, raw.strip(), "ocr", 0.55, [], excerpt[:200]))
    return out


def parse_labels(text: str) -> list[Proposal]:
    out = []
    flat = text.replace("\r", "")
    for key, patterns in LABELS.items():
        for pat in patterns:
            if key in DATE_KEYS:
                m = re.search(pat + r"[\s:./-]*\n?\s*" + DATE_RX, flat, re.I)
                if m:
                    p = _date_proposal(key, m.group(1), "ocr", m.group(0))
                    if p:
                        out.append(p)
                        break
            else:
                m = re.search(pat + r"[\s:#./-]*\n?\s*([A-Z0-9][A-Z0-9 \-/]{2,40})", flat, re.I)
                if m:
                    val = m.group(1).strip().split("\n")[0].strip()
                    if _label_spans(val) and _label_spans(val)[0][0] == 0 or re.match(r"(?i)name\b", val):
                        continue  # the next label, not a value
                    if key == "document_number":
                        val = val.split("  ")[0].split(" ")[0] if re.search(r"\d", val.split(" ")[0]) else val
                        if not re.search(r"\d", val):
                            continue  # a number field without digits is a misread label, not a value
                    flags = []
                    if key == "document_number" and re.search(r"(?<=\d)[OIlSB]|[OIlSB](?=\d)", val[1:]):
                        flags.append("Possibly ambiguous characters (O/0, I/1, S/5) — please verify.")
                    out.append(Proposal(key, val, "ocr", 0.5, flags, m.group(0)[:200]))
                    break
    return out


def find_no_expiry(lines: list[str]) -> Proposal | None:
    """An explicit 'No Expiry Date' / 'Does not expire' statement — but not the end of a 'Badge No' label
    followed by an 'Expiry Date' column header."""
    for ln in lines:
        for m in re.finditer(NO_EXPIRY_RX, ln, re.I):
            covered = any(s <= m.start() < e and key != "expiry_date" for s, e, key in _label_spans(ln))
            if not covered:
                return Proposal("no_expiry", "yes", "ocr", 0.6, ["The document says it does not expire — please confirm."], ln.strip()[:200])
    return None


def find_holder(lines: list[str], owner_names: list[str]) -> Proposal | None:
    """A line that carries the owner's name (at least two of its words) is proposed as the holder's name."""
    for n in owner_names or []:
        toks = [t.lower() for t in re.findall(r"[A-Za-z]{2,}", n)]
        if len(toks) < 2:
            continue
        for ln in lines:
            words = [w.lower() for w in re.findall(r"[A-Za-z]{2,}", ln)]
            hits = sum(1 for t in toks if t in words)
            if hits >= 2 and len(words) <= len(toks) + 3:
                value = re.sub(r"^(?:name|holder|full\s*name)\s*[:\-]?\s*", "", ln.strip(), flags=re.I)
                return Proposal("full_name", value.title(), "ocr", 0.55, [], ln.strip()[:200])
    return None


def extract(text: str, *, owner_names: list[str] | None = None, template: str = "generic") -> list[Proposal]:
    proposals: dict[str, Proposal] = {}
    lines = [ln for ln in (text or "").splitlines() if ln.strip()]
    for p in parse_labels(text or ""):
        proposals[p.key] = p
    for p in parse_columns(lines):  # header/value tables are more specific than a loose label match
        proposals[p.key] = p
    for p in parse_mrz(text or ""):  # MRZ wins over labels when both exist, but conflicts are flagged
        prev = proposals.get(p.key)
        if prev and prev.value != p.value:
            p.flags.append(f"Conflicts with printed value '{prev.value}'.")
            p.confidence = min(p.confidence, 0.5)
        proposals[p.key] = p
    if "full_name" not in proposals:
        holder = find_holder(lines, owner_names or [])
        if holder:
            proposals["full_name"] = holder
    no_exp = find_no_expiry(lines)
    if no_exp:
        if "expiry_date" in proposals:
            proposals["expiry_date"].flags.append("The document also says it does not expire — please check.")
        else:
            proposals["no_expiry"] = no_exp
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
