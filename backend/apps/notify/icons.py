"""Central semantic icon and severity mapping for every notification channel.

Each key has an emoji (Telegram, plain text, email headings), the name of the app's SVG icon (in-app cards) and a
text label (screen readers; meaning is never carried by colour or icon alone).
"""
from __future__ import annotations

# key: (emoji, svg icon name in the web app, accessible label)
ICONS: dict[str, tuple[str, str, str]] = {
    "alarm": ("🚨", "alert", "Critical alert"),
    "shield": ("🛡️", "shield", "Security"),
    "user": ("👤", "users", "Account"),
    "globe_location": ("🌍", "globe", "Location / network"),
    "key": ("🔑", "key", "Sign-in"),
    "device": ("💻", "monitor", "Device"),
    "time": ("⏱️", "clock", "Time"),
    "calendar": ("📅", "calendar", "Date"),
    "document": ("📄", "file", "Document"),
    "folder": ("📁", "folder", "Folder"),
    "upload": ("⬆️", "upload", "Upload"),
    "scan": ("🔍", "search", "Text recognition"),
    "ai": ("🧠", "sparkle", "Local AI"),
    "backup": ("💿", "db", "Backup"),
    "internet": ("🌐", "globe", "Internet / HTTPS"),
    "warning": ("🔶", "alert", "Warning"),
    "health": ("🚦", "shield", "Security Health"),
    "info": ("ℹ️", "info", "Information"),
    "system": ("⚙️", "settings", "System"),
    "storage": ("🗄️", "db", "Storage"),
    "reminder": ("🔔", "bell", "Reminder"),
    "success": ("✅", "check", "Success"),
    "failure": ("❌", "x", "Failure"),
}

# severity: (emoji, label, text colour, background, border) — colours meet WCAG AA on their background
SEVERITY: dict[str, tuple[str, str, str, str, str]] = {
    "critical": ("🚨", "Critical", "#9b1c1c", "#fdecea", "#f3b4ae"),
    "warning": ("🔶", "Warning", "#8a4500", "#fef3e2", "#f6cf98"),
    "success": ("✅", "Success", "#17642f", "#e7f5ec", "#a8d9b8"),
    "info": ("ℹ️", "Information", "#174d93", "#e8f1fc", "#b2cdef"),
}

CATEGORY_LABELS = {"documents": "Documents", "expiry": "Expiry & renewal", "ocr": "OCR & Local AI", "security": "Security",
                   "system": "System", "sharing": "Sharing & access"}

# a detail label from older call sites -> icon
FACT_ICONS = {
    "Folder": "folder", "Location": "folder", "Date/time": "time", "Time": "time", "Device": "device",
    "IP address": "globe_location", "Country": "globe_location", "Sign-in method": "key", "Expiry date": "calendar",
    "Days left": "time", "Access": "user", "OCR": "scan", "Pages": "document", "Document type": "document",
    "Type": "document", "Full name": "user", "Name": "user", "Owner": "user", "Document number": "key",
    "Issue date": "calendar", "Status": "health", "Signatures": "shield", "Detection": "alarm", "File": "document",
}


def emoji(key: str) -> str:
    return ICONS.get(key, ICONS["info"])[0]


def svg(key: str) -> str:
    return ICONS.get(key, ICONS["info"])[1]


def label(key: str) -> str:
    return ICONS.get(key, ICONS["info"])[2]
