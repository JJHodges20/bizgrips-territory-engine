# Vendored brand renderer

Source: the "BizGrips client document formatting" skill (v1), scripts `brand.py`, `parser.py`
(here `markup.py`) and `build_pdf.py` (here `pdf.py`, exposed as `render_pdf`). Changes are
limited to package-relative imports and the in-memory `render_pdf` entry point; colours, type
scale and page geometry are unchanged so documents match the skill's output.

Fonts: Montserrat and Poppins, SIL Open Font License 1.1. Logo files are BizGrips brand assets.
The DOCX builder is not vendored (PDF only).
