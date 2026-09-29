"""BizGrips brand constants and font registration.

Single source of truth for colours, type scale and asset paths.
Both build_pdf.py and build_docx.py import from here.
"""

import os

ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")  # vendored layout
FONT_DIR = os.path.join(ASSETS, "fonts")
LOGO_DARK = os.path.join(ASSETS, "bizgrips-logo.png")
LOGO_WHITE = os.path.join(ASSETS, "bizgrips-logo-white.png")

# Native pixel dimensions of the logo (used to preserve aspect ratio)
LOGO_W, LOGO_H = 1908, 976
LOGO_RATIO = LOGO_H / LOGO_W  # 0.5115

# ---------------------------------------------------------------- colours
BLUE = "#1A8BF6"        # primary brand blue - eyebrows, accents, numbers
NAVY = "#0F172A"        # headings
BODY = "#475569"        # body copy
MUTED = "#64748B"        # footers, captions
RULE = "#E2E8F0"        # hairlines and borders
WHITE = "#FFFFFF"

# Callout palettes: (border, background, title colour)
CALLOUTS = {
    "blue":   ("#BFDBFE", "#F0F7FF", BLUE),
    "green":  ("#22C55E", "#F0FDF4", "#15803D"),
    "orange": ("#FDBA74", "#FFF7ED", "#C2410C"),
    "grey":   (RULE, "#F8FAFC", MUTED),
}

# ---------------------------------------------------------------- type
# Headline family: Montserrat.  Body family: Poppins.
FONTS = {
    "Montserrat":            "Montserrat-Regular.ttf",
    "Montserrat-SemiBold":   "Montserrat-SemiBold.ttf",
    "Montserrat-Bold":       "Montserrat-Bold.ttf",
    "Montserrat-ExtraBold":  "Montserrat-ExtraBold.ttf",
    "Poppins":               "Poppins-Regular.ttf",
    "Poppins-Medium":        "Poppins-Medium.ttf",
    "Poppins-SemiBold":      "Poppins-SemiBold.ttf",
    "Poppins-Bold":          "Poppins-Bold.ttf",
    "Poppins-Italic":        "Poppins-Italic.ttf",
}

HEAD = "Montserrat-Bold"
HEAD_XB = "Montserrat-ExtraBold"
TEXT = "Poppins"
TEXT_BOLD = "Poppins-SemiBold"
TEXT_ITALIC = "Poppins-Italic"

# Page geometry (points)
PAGE_MARGIN = 72
HEADER_TOP = 36
FOOTER_BOTTOM = 40


def register_fonts():
    """Register the embedded TTFs with ReportLab. Falls back to Helvetica."""
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.lib.fonts import addMapping

    registered = []
    for name, filename in FONTS.items():
        path = os.path.join(FONT_DIR, filename)
        if os.path.exists(path):
            try:
                pdfmetrics.registerFont(TTFont(name, path))
                registered.append(name)
            except Exception:
                pass

    if "Poppins" in registered:
        addMapping("Poppins", 0, 0, "Poppins")
        addMapping("Poppins", 1, 0, "Poppins-SemiBold" if "Poppins-SemiBold" in registered else "Poppins")
        addMapping("Poppins", 0, 1, "Poppins-Italic" if "Poppins-Italic" in registered else "Poppins")
        addMapping("Poppins", 1, 1, "Poppins-SemiBold" if "Poppins-SemiBold" in registered else "Poppins")
    if "Montserrat" in registered:
        addMapping("Montserrat", 0, 0, "Montserrat")
        addMapping("Montserrat", 1, 0, "Montserrat-Bold")

    missing = [n for n in FONTS if n not in registered]
    if missing:
        # Graceful degradation rather than a hard crash.
        globals()["HEAD"] = "Helvetica-Bold" if "Montserrat-Bold" in missing else HEAD
        globals()["TEXT"] = "Helvetica" if "Poppins" in missing else TEXT
    return registered, missing
