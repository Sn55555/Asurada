from __future__ import annotations

import re
from pathlib import Path

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Mm, Pt, RGBColor


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "doc" / "ASURADA_AGENT_RESEARCH_AND_ARCHITECTURE_CN.md"
OUT = ROOT / "doc" / "ASURADA_AGENT_RESEARCH_AND_ARCHITECTURE_CN.docx"

FONT_CN = "SimSun"
FONT_HEADING = "SimHei"
FONT_LATIN = "Times New Roman"
BLUE = RGBColor(31, 77, 120)
MUTED = RGBColor(90, 90, 90)
TABLE_HEADER_FILL = "E8EEF5"
CODE_FILL = "F2F4F7"


def set_run_font(run, cn=FONT_CN, latin=FONT_LATIN, size=None, bold=None, italic=None, color=None):
    run.font.name = latin
    run._element.rPr.rFonts.set(qn("w:ascii"), latin)
    run._element.rPr.rFonts.set(qn("w:hAnsi"), latin)
    run._element.rPr.rFonts.set(qn("w:eastAsia"), cn)
    if size is not None:
        run.font.size = Pt(size)
    if bold is not None:
        run.bold = bold
    if italic is not None:
        run.italic = italic
    if color is not None:
        run.font.color.rgb = color


def set_para_font(paragraph, cn=FONT_CN, latin=FONT_LATIN, size=10.5):
    for run in paragraph.runs:
        set_run_font(run, cn=cn, latin=latin, size=size)


def set_paragraph_shading(paragraph, fill):
    p_pr = paragraph._p.get_or_add_pPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:fill"), fill)
    p_pr.append(shd)


def set_cell_shading(cell, fill):
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:fill"), fill)
    tc_pr.append(shd)


def set_cell_margins(cell, top=100, start=120, bottom=100, end=120):
    tc = cell._tc
    tc_pr = tc.get_or_add_tcPr()
    tc_mar = tc_pr.first_child_found_in("w:tcMar")
    if tc_mar is None:
        tc_mar = OxmlElement("w:tcMar")
        tc_pr.append(tc_mar)
    for m, v in (("top", top), ("start", start), ("bottom", bottom), ("end", end)):
        node = tc_mar.find(qn(f"w:{m}"))
        if node is None:
            node = OxmlElement(f"w:{m}")
            tc_mar.append(node)
        node.set(qn("w:w"), str(v))
        node.set(qn("w:type"), "dxa")


def set_cell_width(cell, width_dxa):
    tc_pr = cell._tc.get_or_add_tcPr()
    tc_w = tc_pr.first_child_found_in("w:tcW")
    if tc_w is None:
        tc_w = OxmlElement("w:tcW")
        tc_pr.append(tc_w)
    tc_w.set(qn("w:w"), str(width_dxa))
    tc_w.set(qn("w:type"), "dxa")


def set_table_geometry(table, widths):
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    tbl_pr = table._tbl.tblPr
    tbl_w = tbl_pr.first_child_found_in("w:tblW")
    if tbl_w is None:
        tbl_w = OxmlElement("w:tblW")
        tbl_pr.append(tbl_w)
    tbl_w.set(qn("w:w"), str(sum(widths)))
    tbl_w.set(qn("w:type"), "dxa")
    for row in table.rows:
        for idx, cell in enumerate(row.cells):
            set_cell_width(cell, widths[idx])
            set_cell_margins(cell)
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER


def configure_styles(doc):
    section = doc.sections[0]
    section.page_width = Mm(210)
    section.page_height = Mm(297)
    section.top_margin = Cm(2.54)
    section.bottom_margin = Cm(2.54)
    section.left_margin = Cm(2.8)
    section.right_margin = Cm(2.6)
    section.header_distance = Cm(1.5)
    section.footer_distance = Cm(1.5)

    styles = doc.styles
    normal = styles["Normal"]
    normal.font.name = FONT_LATIN
    normal._element.rPr.rFonts.set(qn("w:eastAsia"), FONT_CN)
    normal.font.size = Pt(10.5)
    normal.paragraph_format.first_line_indent = Cm(0.74)
    normal.paragraph_format.line_spacing = 1.5
    normal.paragraph_format.space_after = Pt(0)

    for name, size, before, after in (
        ("Heading 1", 14, 14, 8),
        ("Heading 2", 12, 10, 6),
        ("Heading 3", 11, 8, 4),
    ):
        style = styles[name]
        style.font.name = FONT_LATIN
        style._element.rPr.rFonts.set(qn("w:eastAsia"), FONT_HEADING)
        style.font.size = Pt(size)
        style.font.bold = True
        style.font.color.rgb = BLUE
        style.paragraph_format.first_line_indent = None
        style.paragraph_format.line_spacing = 1.25
        style.paragraph_format.space_before = Pt(before)
        style.paragraph_format.space_after = Pt(after)
        style.paragraph_format.keep_with_next = True

    if "论文代码块" not in styles:
        code_style = styles.add_style("论文代码块", 1)
    else:
        code_style = styles["论文代码块"]
    code_style.font.name = "Courier New"
    code_style._element.rPr.rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")
    code_style.font.size = Pt(9)
    code_style.paragraph_format.first_line_indent = None
    code_style.paragraph_format.left_indent = Cm(0.2)
    code_style.paragraph_format.right_indent = Cm(0.2)
    code_style.paragraph_format.line_spacing = 1.05
    code_style.paragraph_format.space_before = Pt(3)
    code_style.paragraph_format.space_after = Pt(6)

    if "参考文献" not in styles:
        ref_style = styles.add_style("参考文献", 1)
    else:
        ref_style = styles["参考文献"]
    ref_style.font.name = FONT_LATIN
    ref_style._element.rPr.rFonts.set(qn("w:eastAsia"), FONT_CN)
    ref_style.font.size = Pt(9.5)
    ref_style.paragraph_format.first_line_indent = Cm(-0.45)
    ref_style.paragraph_format.left_indent = Cm(0.45)
    ref_style.paragraph_format.line_spacing = 1.15
    ref_style.paragraph_format.space_after = Pt(4)


def add_page_number(paragraph):
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = paragraph.add_run()
    fld_begin = OxmlElement("w:fldChar")
    fld_begin.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = " PAGE "
    fld_end = OxmlElement("w:fldChar")
    fld_end.set(qn("w:fldCharType"), "end")
    run._r.append(fld_begin)
    run._r.append(instr)
    run._r.append(fld_end)


def add_header_footer(doc):
    section = doc.sections[0]
    hp = section.header.paragraphs[0]
    hp.text = "Asurada Cyber System 研究"
    hp.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    set_para_font(hp, size=9)
    hp.runs[0].font.color.rgb = MUTED

    fp = section.footer.paragraphs[0]
    add_page_number(fp)
    set_para_font(fp, size=9)


def add_title_block(doc, title):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.first_line_indent = None
    p.paragraph_format.space_after = Pt(16)
    run = p.add_run(title)
    set_run_font(run, cn=FONT_HEADING, size=18, bold=True, color=RGBColor(0, 0, 0))


def add_keyword_line(doc, line):
    p = doc.add_paragraph()
    p.paragraph_format.first_line_indent = None
    p.paragraph_format.space_before = Pt(6)
    p.paragraph_format.space_after = Pt(8)
    label, rest = line.split("：", 1)
    r1 = p.add_run(label + "：")
    set_run_font(r1, cn=FONT_HEADING, size=10.5, bold=True)
    r2 = p.add_run(rest)
    set_run_font(r2, size=10.5)


def md_plain(text):
    return text.replace("*", "").replace("`", "")


def add_body_paragraph(doc, text):
    p = doc.add_paragraph()
    p.paragraph_format.first_line_indent = Cm(0.74)
    p.paragraph_format.line_spacing = 1.5
    p.paragraph_format.space_after = Pt(0)
    run = p.add_run(md_plain(text))
    set_run_font(run, size=10.5)
    return p


def add_caption(doc, text):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.first_line_indent = None
    p.paragraph_format.space_before = Pt(6)
    p.paragraph_format.space_after = Pt(4)
    run = p.add_run(text)
    set_run_font(run, cn=FONT_HEADING, size=10, bold=True, color=BLUE)
    return p


def add_code_block(doc, code):
    for line in code.splitlines():
        p = doc.add_paragraph(style="论文代码块")
        set_paragraph_shading(p, CODE_FILL)
        p.add_run(line if line else " ")


def add_architecture_figure(doc, figure_no):
    doc.add_page_break()
    add_caption(doc, f"图 {figure_no} Asurada Cyber System 实时主链架构")
    lines = [
        "F1 25 Official UDP Telemetry -> UDP Receiver -> Packet Decoder -> Frame Assembler",
        "Frame Assembler -> Session State -> Feature Layer -> Rules and Small Models -> Strategy Arbiter",
        "Strategy Arbiter -> Output Coordinator -> Voice / HUD / LED / Haptics / Replay Log",
        "Replay Log -> Post-session Analysis -> Driver Profile -> Feature Layer",
    ]
    for line in lines:
        p = doc.add_paragraph(style="论文代码块")
        set_paragraph_shading(p, CODE_FILL)
        p.add_run(line)


def parse_table(lines, start):
    rows = []
    i = start
    while i < len(lines) and lines[i].strip().startswith("|"):
        raw = lines[i].strip()
        cells = [c.strip() for c in raw.strip("|").split("|")]
        if not all(re.fullmatch(r":?-{3,}:?", c) for c in cells):
            rows.append(cells)
        i += 1
    return rows, i


def add_markdown_table(doc, rows, caption, table_no):
    if not rows:
        return
    add_caption(doc, f"表 {table_no} {caption}")
    cols = len(rows[0])
    table = doc.add_table(rows=len(rows), cols=cols)
    table.style = "Table Grid"
    widths = [int(9360 / cols)] * cols
    if cols == 2:
        widths = [2500, 6860]
    elif cols == 3:
        widths = [1700, 3100, 4560]
    elif cols >= 4:
        widths = [1300] + [int((9360 - 1300) / (cols - 1))] * (cols - 1)
    set_table_geometry(table, widths[:cols])
    for r_idx, row in enumerate(rows):
        for c_idx, text in enumerate(row):
            cell = table.cell(r_idx, c_idx)
            cell.text = ""
            p = cell.paragraphs[0]
            p.paragraph_format.first_line_indent = None
            p.paragraph_format.line_spacing = 1.15
            p.paragraph_format.space_after = Pt(0)
            if c_idx == 0:
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            run = p.add_run(md_plain(text))
            set_run_font(run, size=9.5, bold=(r_idx == 0))
            if r_idx == 0:
                set_cell_shading(cell, TABLE_HEADER_FILL)
    doc.add_paragraph().paragraph_format.space_after = Pt(2)


def heading_caption(current_heading):
    text = current_heading.replace("### ", "").replace("## ", "").strip()
    return re.sub(r"^\d+(?:\.\d+)*\s*", "", text)


def build_docx():
    lines = SRC.read_text(encoding="utf-8").splitlines()
    title = lines[0].lstrip("# ").strip()

    doc = Document()
    configure_styles(doc)
    add_header_footer(doc)
    add_title_block(doc, title)

    i = 1
    current_heading = ""
    table_no = 1
    figure_no = 1
    in_references = False

    while i < len(lines):
        line = lines[i].rstrip()
        stripped = line.strip()
        if not stripped:
            i += 1
            continue

        if stripped.startswith("## "):
            text = stripped[3:].strip()
            p = doc.add_heading(text, level=1)
            set_para_font(p, cn=FONT_HEADING, size=14)
            current_heading = text
            in_references = text == "参考文献"
            i += 1
            continue

        if stripped.startswith("### "):
            text = stripped[4:].strip()
            p = doc.add_heading(text, level=2)
            set_para_font(p, cn=FONT_HEADING, size=12)
            current_heading = text
            i += 1
            continue

        if stripped.startswith("关键词："):
            add_keyword_line(doc, stripped)
            i += 1
            continue

        if stripped.startswith("```"):
            lang = stripped.strip("`").strip()
            block = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                block.append(lines[i])
                i += 1
            i += 1
            if lang == "mermaid":
                add_architecture_figure(doc, figure_no)
                figure_no += 1
            else:
                add_code_block(doc, "\n".join(block))
            continue

        if stripped.startswith("|"):
            rows, next_i = parse_table(lines, i)
            add_markdown_table(doc, rows, heading_caption(current_heading), table_no)
            table_no += 1
            i = next_i
            continue

        if stripped.startswith("- "):
            p = doc.add_paragraph(style="List Bullet")
            p.paragraph_format.first_line_indent = None
            p.paragraph_format.line_spacing = 1.25
            p.paragraph_format.space_after = Pt(2)
            run = p.add_run(md_plain(stripped[2:].strip()))
            set_run_font(run, size=10.5)
            i += 1
            continue

        numbered = re.match(r"^(\d+)\.\s+(.*)", stripped)
        if numbered and not in_references:
            p = doc.add_paragraph(style="List Number")
            p.paragraph_format.first_line_indent = None
            p.paragraph_format.line_spacing = 1.25
            p.paragraph_format.space_after = Pt(2)
            run = p.add_run(md_plain(numbered.group(2)))
            set_run_font(run, size=10.5)
            i += 1
            continue

        if in_references:
            p = doc.add_paragraph(style="参考文献")
            run = p.add_run(md_plain(stripped))
            set_run_font(run, size=9.5)
            i += 1
            continue

        add_body_paragraph(doc, stripped)
        i += 1

    doc.save(OUT)
    print(OUT)


if __name__ == "__main__":
    build_docx()
