#!/usr/bin/env python3
"""Render BizGrips-branded PDFs.

    python3 build_pdf.py input.md -o output.pdf
    python3 build_pdf.py input.md -o output.pdf --no-cover

Reads the document markdown dialect described in parser.py and produces a
letter-size PDF with the BizGrips logo on every page, Montserrat headings and
Poppins body copy.
"""

import argparse
import io
import os
import sys

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    BaseDocTemplate, Flowable, Frame, KeepTogether, NextPageTemplate,
    PageBreak, PageTemplate, Paragraph, Spacer, Table, TableStyle,
)

from app.documents.brand import brand
from app.documents.brand.markup import inline_to_rl, parse

PAGE_W, PAGE_H = letter
MARGIN = brand.PAGE_MARGIN
CONTENT_W = PAGE_W - 2 * MARGIN


def tracked_text(canv, x, y, text, font, size, colour, tracking=0.8,
                 align="left"):
    """Draw letterspaced text. Canvas has no setCharSpace, text objects do."""
    from reportlab.pdfbase import pdfmetrics
    if not text:
        return
    width = pdfmetrics.stringWidth(text, font, size) + tracking * max(
        len(text) - 1, 0)
    if align == "right":
        x -= width
    elif align == "center":
        x -= width / 2.0
    canv.saveState()
    tobj = canv.beginText()
    tobj.setTextOrigin(x, y)
    tobj.setFont(font, size)
    tobj.setFillColor(colors.HexColor(colour))
    tobj.setCharSpace(tracking)
    tobj.textOut(text)
    # Tc is text state and persists past ET - reset it or every later line
    # in the document renders letterspaced and overflows its measured width.
    tobj.setCharSpace(0)
    canv.drawText(tobj)
    canv.restoreState()


# ----------------------------------------------------------------- styles
def build_styles():
    return {
        "cover_title": ParagraphStyle(
            "cover_title", fontName=brand.HEAD, fontSize=30, leading=36,
            textColor=colors.HexColor(brand.NAVY), alignment=TA_CENTER,
            spaceAfter=10),
        "cover_sub": ParagraphStyle(
            "cover_sub", fontName=brand.HEAD, fontSize=9.5, leading=14,
            textColor=colors.HexColor(brand.BLUE), alignment=TA_CENTER),
        "cover_body": ParagraphStyle(
            "cover_body", fontName=brand.TEXT, fontSize=9.5, leading=16,
            textColor=colors.HexColor(brand.BODY), alignment=TA_CENTER,
            spaceAfter=10),
        "h1": ParagraphStyle(
            "h1", fontName=brand.HEAD, fontSize=21, leading=26,
            textColor=colors.HexColor(brand.NAVY), spaceBefore=2, spaceAfter=12),
        "h2": ParagraphStyle(
            "h2", fontName=brand.HEAD, fontSize=12.5, leading=16,
            textColor=colors.HexColor(brand.NAVY), spaceBefore=12, spaceAfter=5),
        "h3": ParagraphStyle(
            "h3", fontName=brand.HEAD, fontSize=10.5, leading=14,
            textColor=colors.HexColor(brand.NAVY), spaceBefore=10, spaceAfter=4),
        "body": ParagraphStyle(
            "body", fontName=brand.TEXT, fontSize=9.5, leading=15.5,
            textColor=colors.HexColor(brand.BODY), alignment=TA_LEFT,
            spaceAfter=7),
        "bullet": ParagraphStyle(
            "bullet", fontName=brand.TEXT, fontSize=8.8, leading=14,
            textColor=colors.HexColor(brand.BODY), leftIndent=14,
            bulletIndent=4, spaceAfter=1.5),
        "deflabel": ParagraphStyle(
            "deflabel", fontName=brand.HEAD, fontSize=8.5, leading=13,
            textColor=colors.HexColor(brand.NAVY)),
        "defvalue": ParagraphStyle(
            "defvalue", fontName=brand.TEXT, fontSize=9.2, leading=14.5,
            textColor=colors.HexColor(brand.BODY)),
        "callout_body": ParagraphStyle(
            "callout_body", fontName=brand.TEXT, fontSize=9.2, leading=14.5,
            textColor=colors.HexColor(brand.BODY), spaceAfter=6),
        "callout_bullet": ParagraphStyle(
            "callout_bullet", fontName=brand.TEXT, fontSize=8.6, leading=13.5,
            textColor=colors.HexColor(brand.BODY), leftIndent=14,
            bulletIndent=4, spaceAfter=1.5),
    }


# -------------------------------------------------------------- flowables
class Eyebrow(Flowable):
    """Small uppercase letterspaced label above a heading."""

    def __init__(self, text, colour=None, size=8.5, space_after=5):
        Flowable.__init__(self)
        self.text = (text or "").upper()
        self.colour = colour or brand.BLUE
        self.size = size
        self.space_after = space_after

    def wrap(self, aw, ah):
        self.width = aw
        self.height = self.size + self.space_after
        return aw, self.height

    def draw(self):
        tracked_text(self.canv, 0, self.space_after, self.text, brand.HEAD,
                     self.size, self.colour, tracking=0.9)


class HRule(Flowable):
    def __init__(self, width=None, colour=None, thickness=0.6, space_before=6,
                 space_after=6):
        Flowable.__init__(self)
        self._w = width
        self.colour = colour or brand.RULE
        self.thickness = thickness
        self.sb = space_before
        self.sa = space_after

    def wrap(self, aw, ah):
        self.width = self._w or aw
        self.height = self.thickness + self.sb + self.sa
        return aw, self.height

    def draw(self):
        c = self.canv
        c.setStrokeColor(colors.HexColor(self.colour))
        c.setLineWidth(self.thickness)
        c.line(0, self.sa, self.width, self.sa)


class NumberedHeading(Flowable):
    """'01  Lead Acquisition' - blue number, navy title."""

    def __init__(self, number, text, size=12.5, space_before=13, space_after=5):
        Flowable.__init__(self)
        self.number = number
        self.text = text
        self.size = size
        self.sb = space_before
        self.sa = space_after

    def wrap(self, aw, ah):
        self.width = aw
        self.height = self.size + self.sb + self.sa
        return aw, self.height

    def draw(self):
        c = self.canv
        y = self.sa
        c.setFont(brand.HEAD, self.size)
        c.setFillColor(colors.HexColor(brand.BLUE))
        num = self.number.zfill(2)
        c.drawString(0, y, num)
        offset = c.stringWidth(num, brand.HEAD, self.size) + 10
        c.setFillColor(colors.HexColor(brand.NAVY))
        c.drawString(offset, y, self.text)


class Callout(Flowable):
    """Rounded tinted box wrapping child flowables."""

    PAD_X = 16
    PAD_Y = 14

    def __init__(self, children, colour="blue", title="", width=None):
        Flowable.__init__(self)
        self.children = children
        self.border, self.bg, self.title_colour = brand.CALLOUTS.get(
            colour, brand.CALLOUTS["blue"])
        self.title = (title or "").upper()
        self._w = width

    def wrap(self, aw, ah):
        self.width = self._w or aw
        inner = self.width - 2 * self.PAD_X
        total = 0
        self._sizes = []
        if self.title:
            total += 14
        for child in self.children:
            w, h = child.wrapOn(self.canv, inner, ah)
            self._sizes.append(h)
            total += h
        self.height = total + 2 * self.PAD_Y
        return self.width, self.height

    def draw(self):
        c = self.canv
        c.saveState()
        c.setFillColor(colors.HexColor(self.bg))
        c.setStrokeColor(colors.HexColor(self.border))
        c.setLineWidth(1)
        c.roundRect(0, 0, self.width, self.height, 8, stroke=1, fill=1)

        y = self.height - self.PAD_Y
        if self.title:
            tracked_text(c, self.PAD_X, y - 8, self.title, brand.HEAD, 8.5,
                         self.title_colour, tracking=0.8)
            y -= 14

        inner = self.width - 2 * self.PAD_X
        for child in self.children:
            _, h = child.wrapOn(c, inner, self.height)
            y -= h
            child.drawOn(c, self.PAD_X, y)
        c.restoreState()


# ------------------------------------------------------------ page canvas
class BrandedDoc(BaseDocTemplate):
    def __init__(self, filename, meta, cover=True, **kw):
        BaseDocTemplate.__init__(self, filename, pagesize=letter,
                                 leftMargin=MARGIN, rightMargin=MARGIN,
                                 topMargin=MARGIN, bottomMargin=MARGIN,
                                 title=meta.get("title", "BizGrips Document"),
                                 author="BizGrips", **kw)
        self.meta = meta
        self.page_offset = 1 if cover else 0

        pad = dict(leftPadding=0, rightPadding=0, topPadding=0,
                   bottomPadding=0, showBoundary=0)
        cover_frame = Frame(MARGIN, MARGIN, CONTENT_W, PAGE_H - 2 * MARGIN,
                            id="cover", **pad)
        body_frame = Frame(MARGIN, MARGIN + 24, CONTENT_W,
                           PAGE_H - 2 * MARGIN - 48, id="body", **pad)
        cover_tpl = PageTemplate(id="cover", frames=[cover_frame],
                                 onPage=self._draw_cover_chrome)
        body_tpl = PageTemplate(id="body", frames=[body_frame],
                                onPage=self._draw_body_chrome)
        # The first template in the list is the one page 1 uses.
        self.addPageTemplates([cover_tpl, body_tpl] if cover
                              else [body_tpl, cover_tpl])

    # -- cover: blue bars top and bottom, no header/footer
    def _draw_cover_chrome(self, canv, doc):
        canv.saveState()
        canv.setFillColor(colors.HexColor(brand.BLUE))
        canv.rect(0, PAGE_H - 14, PAGE_W, 14, stroke=0, fill=1)
        canv.rect(0, 0, PAGE_W, 14, stroke=0, fill=1)
        canv.restoreState()

    # -- body: logo top-left, doc label top-right, rules, footer
    def _draw_body_chrome(self, canv, doc):
        canv.saveState()
        label = (self.meta.get("header") or self.meta.get("title") or "").upper()
        footer = self.meta.get("footer") or "BizGrips"

        logo_w = 62
        logo_h = logo_w * brand.LOGO_RATIO
        top = PAGE_H - brand.HEADER_TOP - logo_h
        if os.path.exists(brand.LOGO_DARK):
            canv.drawImage(brand.LOGO_DARK, MARGIN, top, width=logo_w,
                           height=logo_h, mask="auto")

        if label:
            tracked_text(canv, PAGE_W - MARGIN, top + logo_h / 2 - 3, label,
                         brand.HEAD, 8, brand.NAVY, tracking=0.7,
                         align="right")

        rule_y = top - 14
        canv.setStrokeColor(colors.HexColor(brand.RULE))
        canv.setLineWidth(0.6)
        canv.line(MARGIN, rule_y, PAGE_W - MARGIN, rule_y)

        # footer
        fy = brand.FOOTER_BOTTOM
        canv.line(MARGIN, fy + 14, PAGE_W - MARGIN, fy + 14)
        canv.setFont(brand.TEXT, 7.5)
        canv.setFillColor(colors.HexColor(brand.MUTED))
        canv.drawString(MARGIN, fy, footer)
        canv.drawRightString(PAGE_W - MARGIN, fy,
                             "Page %d" % (doc.page - self.page_offset))
        canv.restoreState()


# ----------------------------------------------------------- block render
def render_blocks(blocks, styles, width=CONTENT_W):
    out = []
    for b in blocks:
        t = b["type"]

        if t == "pagebreak":
            out.append(PageBreak())

        elif t == "rule":
            out.append(HRule(width=width))

        elif t == "heading":
            group = []
            lvl = b["level"]
            if lvl == 1 and out:
                out.append(Spacer(1, 20))
            if b.get("eyebrow"):
                group.append(Eyebrow(b["eyebrow"]))
            if lvl == 1:
                group.append(Paragraph(inline_to_rl(b["text"]), styles["h1"]))
            elif b.get("number"):
                group.append(NumberedHeading(b["number"], b["text"]))
            else:
                key = "h2" if lvl == 2 else "h3"
                group.append(Paragraph(inline_to_rl(b["text"]), styles[key]))
            out.append(KeepTogether(group))

        elif t == "para":
            out.append(Paragraph(inline_to_rl(b["text"]), styles["body"]))

        elif t == "bullets":
            style = styles["bullet"]
            for idx, item in enumerate(b["items"], 1):
                if b.get("ordered"):
                    marker = "<font color='%s'><b>%d.</b></font>" % (brand.BLUE, idx)
                else:
                    marker = "<font color='%s'>&bull;</font>" % brand.BLUE
                out.append(Paragraph(
                    "%s&nbsp;&nbsp;%s" % (marker, inline_to_rl(item)), style))
            out.append(Spacer(1, 5))

        elif t == "columns":
            items = b["items"]
            half = (len(items) + 1) // 2
            left, right = items[:half], items[half:]
            right += [""] * (len(left) - len(right))
            rows = []
            for l, r in zip(left, right):
                rows.append([
                    Paragraph("<font color='%s'>&bull;</font>&nbsp;&nbsp;%s"
                              % (brand.BLUE, inline_to_rl(l)), styles["bullet"]),
                    Paragraph(("<font color='%s'>&bull;</font>&nbsp;&nbsp;%s"
                               % (brand.BLUE, inline_to_rl(r))) if r else "",
                              styles["bullet"]),
                ])
            tbl = Table(rows, colWidths=[width / 2, width / 2])
            tbl.setStyle(TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 1),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]))
            out.append(tbl)
            out.append(Spacer(1, 6))

        elif t == "deflist":
            label_w = min(150, width * 0.32)
            rows = [[Paragraph(inline_to_rl(k), styles["deflabel"]),
                     Paragraph(inline_to_rl(v), styles["defvalue"])]
                    for k, v in b["rows"]]
            tbl = Table(rows, colWidths=[label_w, width - label_w])
            tbl.setStyle(TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 9),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
                ("LINEBELOW", (0, 0), (-1, -2), 0.5,
                 colors.HexColor(brand.RULE)),
            ]))
            out.append(tbl)
            out.append(Spacer(1, 10))

        elif t == "callout":
            inner_w = width - 2 * Callout.PAD_X
            children = []
            for cb in b["children"]:
                if cb["type"] == "para":
                    children.append(Paragraph(inline_to_rl(cb["text"]),
                                              styles["callout_body"]))
                elif cb["type"] == "bullets":
                    for item in cb["items"]:
                        children.append(Paragraph(
                            "<font color='%s'>&bull;</font>&nbsp;&nbsp;%s"
                            % (brand.BLUE, inline_to_rl(item)),
                            styles["callout_bullet"]))
                    children.append(Spacer(1, 5))
                elif cb["type"] == "heading":
                    children.append(Paragraph(inline_to_rl(cb["text"]),
                                              styles["h3"]))
            out.append(Callout(children, b.get("colour", "blue"),
                               b.get("title", ""), width=width))
            out.append(Spacer(1, 12))

    return out


def build_cover(meta, styles):
    story = []
    logo_w = 175
    logo_h = logo_w * brand.LOGO_RATIO

    class CenteredLogo(Flowable):
        def wrap(self, aw, ah):
            self.width, self.height = aw, logo_h
            return aw, logo_h

        def draw(self):
            if os.path.exists(brand.LOGO_DARK):
                self.canv.drawImage(brand.LOGO_DARK,
                                    (self.width - logo_w) / 2, 0,
                                    width=logo_w, height=logo_h, mask="auto")

    class BlueBar(Flowable):
        def wrap(self, aw, ah):
            self.width, self.height = aw, 18
            return aw, 18

        def draw(self):
            self.canv.setFillColor(colors.HexColor(brand.BLUE))
            self.canv.rect((self.width - 90) / 2, 8, 90, 3.5, stroke=0, fill=1)

    story.append(Spacer(1, 2.4 * inch))
    story.append(CenteredLogo())
    story.append(Spacer(1, 26))
    story.append(Paragraph(inline_to_rl(meta.get("title", "")),
                           styles["cover_title"]))
    if meta.get("subtitle"):
        story.append(Paragraph(inline_to_rl(meta["subtitle"].upper()),
                               styles["cover_sub"]))
    story.append(BlueBar())
    story.append(Spacer(1, 14))
    for para in [p for p in meta.get("intro", "").split("\n") if p.strip()]:
        story.append(Paragraph(inline_to_rl(para), styles["cover_body"]))
    return story


_FONTS_READY = False


def ensure_fonts():
    """Register the embedded fonts once per process."""
    global _FONTS_READY
    if not _FONTS_READY:
        brand.register_fonts()
        _FONTS_READY = True


def render_pdf(text, cover=True):
    """Render markup text to PDF bytes (the API entry point; no files touched)."""
    ensure_fonts()
    meta, blocks = parse(text)
    styles = build_styles()
    use_cover = cover and bool(meta.get("title"))
    buffer = io.BytesIO()
    doc = BrandedDoc(buffer, meta, cover=use_cover)
    story = []
    if use_cover:
        story += build_cover(meta, styles)
        story.append(NextPageTemplate("body"))
        story.append(PageBreak())
    story += render_blocks(blocks, styles)
    doc.build(story)
    return buffer.getvalue()


def main():
    ap = argparse.ArgumentParser(description="Build a BizGrips-branded PDF.")
    ap.add_argument("input", help="source .md or .txt file")
    ap.add_argument("-o", "--output", required=True, help="output .pdf path")
    ap.add_argument("--no-cover", action="store_true",
                    help="skip the cover page (memos, one-pagers)")
    args = ap.parse_args()

    registered, missing = brand.register_fonts()
    if missing:
        print("WARNING: missing fonts, falling back: %s" % ", ".join(missing),
              file=sys.stderr)

    with open(args.input, encoding="utf-8") as fh:
        meta, blocks = parse(fh.read())

    styles = build_styles()
    cover = not args.no_cover and bool(meta.get("title"))

    doc = BrandedDoc(args.output, meta, cover=cover)
    story = []
    if cover:
        story += build_cover(meta, styles)
        story.append(NextPageTemplate("body"))
        story.append(PageBreak())

    story += render_blocks(blocks, styles)
    doc.build(story)
    print("Wrote %s" % args.output)


if __name__ == "__main__":
    main()
