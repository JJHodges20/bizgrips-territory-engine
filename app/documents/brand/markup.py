"""Parser for BizGrips document markdown.

Turns a plain-text/markdown source into a list of blocks that the PDF and
DOCX builders both consume.

Supported syntax
----------------
    ---                       YAML-ish frontmatter (title, subtitle, header,
    title: Bath Charter       footer, intro)
    ---

    ^ THE GROWTH ENGINE       eyebrow label (blue, uppercase) - attaches to
    # What's Included         the heading on the next line

    ## 01 Lead Acquisition    numbered sub-heading (the "01" is auto-detected)
    ### Smaller heading

    Body paragraph with **bold** and *italic*.

    - bullet item

    ::: columns               two-column bullet list
    - item
    :::

    ::: green | PERFORMANCE GUARANTEE     callout box
    Body of the callout, bullets allowed.
    :::

    Label :: Value            definition row (label column + value column)

    ===                       page break

Everything that is not one of the above is treated as a paragraph, so pasting
ordinary prose in still produces a correctly branded document.
"""

import re

CALLOUT_COLOURS = ("blue", "green", "orange", "grey")


def _strip_bom(text):
    return text.lstrip("\ufeff")


def parse_frontmatter(text):
    """Return (meta_dict, remaining_text)."""
    meta = {}
    text = _strip_bom(text)
    if not text.startswith("---"):
        return meta, text
    lines = text.split("\n")
    if lines[0].strip() != "---":
        return meta, text
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return meta, text

    key = None
    buf = []
    for raw in lines[1:end]:
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*):\s*(.*)$", raw)
        if m:
            if key:
                meta[key] = "\n".join(buf).strip()
            key = m.group(1).strip().lower()
            val = m.group(2).strip()
            buf = [] if val in ("|", ">") else [val]
        elif key:
            buf.append(raw.strip())
    if key:
        meta[key] = "\n".join(buf).strip()

    return meta, "\n".join(lines[end + 1:])


def parse_blocks(text):
    """Parse body text into a flat list of block dicts."""
    lines = text.split("\n")
    blocks = []
    i = 0
    pending_eyebrow = None
    para = []

    def flush_para():
        nonlocal para
        if para:
            blocks.append({"type": "para", "text": " ".join(para).strip()})
            para = []

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # ---- blank line ends a paragraph
        if not stripped:
            flush_para()
            i += 1
            continue

        # ---- page break
        if re.fullmatch(r"={3,}", stripped):
            flush_para()
            blocks.append({"type": "pagebreak"})
            i += 1
            continue

        # ---- horizontal rule
        if re.fullmatch(r"(-{3,}|_{3,}|\*{3,})", stripped):
            flush_para()
            blocks.append({"type": "rule"})
            i += 1
            continue

        # ---- eyebrow
        if stripped.startswith("^ ") or stripped.startswith("^^"):
            flush_para()
            pending_eyebrow = stripped.lstrip("^").strip()
            i += 1
            continue

        # ---- fenced block  ::: ...
        if stripped.startswith(":::"):
            flush_para()
            spec = stripped[3:].strip()
            body = []
            i += 1
            while i < len(lines) and lines[i].strip() != ":::":
                body.append(lines[i])
                i += 1
            i += 1  # consume closing :::

            if spec.lower().startswith("columns"):
                items = [
                    re.sub(r"^[-*+]\s+", "", b.strip())
                    for b in body
                    if b.strip().startswith(("-", "*", "+"))
                ]
                blocks.append({"type": "columns", "items": items})
            else:
                parts = [p.strip() for p in spec.split("|", 1)]
                colour = parts[0].lower() if parts[0].lower() in CALLOUT_COLOURS else "blue"
                title = parts[1] if len(parts) > 1 else ""
                if parts[0].lower() not in CALLOUT_COLOURS and parts[0]:
                    title = spec.strip()
                blocks.append({
                    "type": "callout",
                    "colour": colour,
                    "title": title,
                    "children": parse_blocks("\n".join(body)),
                })
            continue

        # ---- headings
        m = re.match(r"^(#{1,4})\s+(.*)$", stripped)
        if m:
            flush_para()
            level = len(m.group(1))
            title = m.group(2).strip()
            number = None
            nm = re.match(r"^(\d{1,2})[.)]?\s+(.+)$", title)
            if nm and level >= 2:
                number, title = nm.group(1), nm.group(2)
            blocks.append({
                "type": "heading",
                "level": level,
                "text": title,
                "number": number,
                "eyebrow": pending_eyebrow,
            })
            pending_eyebrow = None
            i += 1
            continue

        # ---- definition row:  Label :: Value
        if "::" in stripped and not stripped.startswith(("-", "*", "+")):
            label, _, value = stripped.partition("::")
            if label.strip() and value.strip():
                flush_para()
                rows = [(label.strip(), value.strip())]
                i += 1
                while i < len(lines):
                    nxt = lines[i].strip()
                    if "::" in nxt and not nxt.startswith(("-", "*", "+", "#", ":::")):
                        l2, _, v2 = nxt.partition("::")
                        if l2.strip() and v2.strip():
                            rows.append((l2.strip(), v2.strip()))
                            i += 1
                            continue
                    break
                blocks.append({"type": "deflist", "rows": rows})
                continue

        # ---- pipe table row:  | Label | Value |
        if stripped.startswith("|") and stripped.count("|") >= 3:
            flush_para()
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-{2,}:?", c or "-") for c in cells):
                    if len(cells) >= 2:
                        rows.append((cells[0], " ".join(cells[1:])))
                i += 1
            if rows:
                blocks.append({"type": "deflist", "rows": rows})
            continue

        # ---- bullets
        if re.match(r"^[-*+]\s+", stripped):
            flush_para()
            items = []
            while i < len(lines) and re.match(r"^\s*[-*+]\s+", lines[i]):
                items.append(re.sub(r"^\s*[-*+]\s+", "", lines[i]).strip())
                i += 1
            blocks.append({"type": "bullets", "items": items})
            continue

        # ---- numbered list -> treated as bullets with their own markers
        if re.match(r"^\d+[.)]\s+", stripped):
            flush_para()
            items = []
            while i < len(lines) and re.match(r"^\s*\d+[.)]\s+", lines[i]):
                items.append(re.sub(r"^\s*\d+[.)]\s+", "", lines[i]).strip())
                i += 1
            blocks.append({"type": "bullets", "items": items, "ordered": True})
            continue

        # ---- plain paragraph text
        para.append(stripped)
        i += 1

    flush_para()
    return blocks


def parse(text):
    meta, body = parse_frontmatter(text)
    return meta, parse_blocks(body)


# --------------------------------------------------------------- inline
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_ITAL = re.compile(r"(?<!\*)\*([^*]+?)\*(?!\*)")
_CODE = re.compile(r"`([^`]+?)`")


def inline_to_rl(text):
    """Convert inline markdown to ReportLab mini-HTML, escaping XML first."""
    out = (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
    out = _BOLD.sub(r"<b>\1</b>", out)
    out = _ITAL.sub(r"<i>\1</i>", out)
    out = _CODE.sub(r"<font face='Courier'>\1</font>", out)
    return out


def inline_runs(text):
    """Split inline markdown into (text, bold, italic) runs for python-docx."""
    runs = []
    pos = 0
    pattern = re.compile(r"\*\*(.+?)\*\*|(?<!\*)\*([^*]+?)\*(?!\*)")
    for m in pattern.finditer(text):
        if m.start() > pos:
            runs.append((text[pos:m.start()], False, False))
        if m.group(1) is not None:
            runs.append((m.group(1), True, False))
        else:
            runs.append((m.group(2), False, True))
        pos = m.end()
    if pos < len(text):
        runs.append((text[pos:], False, False))
    return runs or [(text, False, False)]
