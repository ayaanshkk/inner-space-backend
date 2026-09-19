"""
generate_cutting_list.py
Generates a cutting list Excel sheet matching the paper format in the photo.

Layout:
  Left half:  GABLE | S/H | BACKS | END PANELS & INFILLS
  Right half: T/B & FIX SHELVES | DRAWS | BRACES | DOORS & DRAW FACES
  Bottom:     S/Pegs | Hinges | Legs pack | Handles | Soft Close

Called with a dict of cutting list data matching the frontend editSections format.
"""

import openpyxl
from openpyxl.styles import (Font, Alignment, Border, Side, PatternFill)
from openpyxl.utils import get_column_letter
import io, math


# ── Style constants ──────────────────────────────────────────────────

NAVY       = "1F3864"   # dark blue header fill
WHITE      = "FFFFFF"
LIGHT_GREY = "F2F2F2"
MID_GREY   = "D9D9D9"

def font(bold=False, size=9, color="000000", name="Arial"):
    return Font(name=name, bold=bold, size=size, color=color)

def align(h="center", v="center", wrap=False, rot=0):
    return Alignment(horizontal=h, vertical=v, wrap_text=wrap,
                     text_rotation=rot)

def fill(hex_color):
    return PatternFill("solid", fgColor=hex_color)

def border(left="thin", right="thin", top="thin", bottom="thin"):
    S = Side
    sides = {k: S(style=v) if v else S(style=None)
             for k, v in dict(left=left, right=right,
                              top=top, bottom=bottom).items()}
    return Border(**sides)

THIN  = border()
THICK = border("medium","medium","medium","medium")
NO_B  = border(None,None,None,None)


# ── Main generator ───────────────────────────────────────────────────

def generate_cutting_list_xlsx(data: dict) -> bytes:
    """
    data keys:
      cabinet_type   str
      project_name   str
      customer_name  str   (optional)
      address        str   (optional)
      fitting_date   str   (optional)
      outside_wood   str   (optional)
      carcase_wood   str   (optional)
      door_wood      str   (optional)
      date           str   (optional)
      sections       list of {category, items: [{name, dimension_l, dimension_w,
                                                  quantity, notes, area_m2}]}
      accessories    list of {name, qty}   (optional)
      material_summary  dict               (optional)
    """
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Cutting List"

    # ── Column widths ────────────────────────────────────────────────
    # Left half:  A(section label) B(#) C(dims) D(sketch area)
    # Divider:    E
    # Right half: F(section label) G(#) H(dims) I(notes)
    col_widths = {
        'A': 5,    # left section label (rotated)
        'B': 4,    # line number
        'C': 22,   # left dimensions
        'D': 18,   # left sketch / notes
        'E': 1,    # centre divider
        'F': 5,    # right section label (rotated)
        'G': 4,    # right line number
        'H': 22,   # right dimensions
        'I': 18,   # right notes
    }
    for col, w in col_widths.items():
        ws.column_dimensions[col].width = w

    # ── Helper: write a cell ─────────────────────────────────────────
    def cell(row, col, value="", bold=False, size=9, color="000000",
             h="center", v="center", wrap=False, rot=0,
             bg=None, bdr=None):
        c = ws.cell(row=row, column=col, value=value)
        c.font      = font(bold=bold, size=size, color=color)
        c.alignment = align(h=h, v=v, wrap=wrap, rot=rot)
        if bg:  c.fill   = fill(bg)
        if bdr: c.border = bdr
        return c

    def merge(r1, c1, r2, c2):
        ws.merge_cells(start_row=r1, start_column=c1,
                       end_row=r2,   end_column=c2)

    # ── ROW 1: File title bar ────────────────────────────────────────
    ws.row_dimensions[1].height = 14
    merge(1,1,1,9)
    c = ws.cell(row=1, column=1,
                value=f"NAWAZ                                           CUTTING LIST / 2011")
    c.font      = font(bold=True, size=10)
    c.alignment = align(h="left", v="center")
    c.fill      = fill(LIGHT_GREY)
    c.border    = THIN

    # ── ROWS 2-5: Header info ────────────────────────────────────────
    header_rows = [
        (2, "CUSTOMER NAME", data.get("customer_name",""),
            "FITTING DATE", data.get("fitting_date","")),
        (3, "HOME ADDRESS",  data.get("address",""),
            "OUTSIDE WOOD", data.get("outside_wood","")),
        (4, "KITCHEN",       data.get("cabinet_type",""),
            "CARCASE WOOD",  data.get("carcase_wood","")),
        (5, "MODULAR",       data.get("project_name",""),
            "DOOR WOOD",     data.get("door_wood","")),
        (6, "SLIDING",       "",
            "READYMADE DOOR",""),
    ]
    for row_i, (r, lbl1, val1, lbl2, val2) in enumerate(header_rows):
        ws.row_dimensions[r].height = 13
        # Label col A-B
        merge(r,1,r,2)
        c = ws.cell(row=r, column=1, value=lbl1)
        c.font = font(bold=True, size=8); c.alignment = align(h="left",v="center")
        c.border = THIN
        # Value col C-D
        merge(r,3,r,4)
        c = ws.cell(row=r, column=3, value=val1)
        c.font = font(size=8); c.alignment = align(h="left",v="center")
        c.border = THIN
        # Label col F-G
        merge(r,6,r,7)
        c = ws.cell(row=r, column=6, value=lbl2)
        c.font = font(bold=True, size=8); c.alignment = align(h="left",v="center")
        c.border = THIN
        # Value col H only (col I reserved for DATE box)
        c = ws.cell(row=r, column=8, value=val2)
        c.font = font(size=8); c.alignment = align(h="left",v="center")
        c.border = THIN

    # DATE box top right (rows 2-6, col I) — set BEFORE header merges
    # Already merged above in header rows (col 8-9), so we use col 9 standalone
    # We merge rows 2-6 col 9 for the DATE box
    # Note: header merges go to col 8 only (changed above), col 9 is free
    merge(2,9,6,9)
    c = ws.cell(row=2, column=9, value=f"DATE\n{data.get('date','')}")
    c.font = font(bold=True, size=10)
    c.alignment = align(h="center", v="center", wrap=True)
    c.fill = fill(LIGHT_GREY)
    c.border = THICK

    # ── Organise cutting list data by section ────────────────────────
    section_map = {}
    for sec in data.get("sections", []):
        section_map[sec["category"]] = sec["items"]

    LEFT_SECTIONS  = ["GABLE", "S/H", "BACKS", "END PANELS & INFILLS"]
    RIGHT_SECTIONS = ["T/B & FIX SHELVES", "DRAWS", "BRACES", "DOORS & DRAW FACES"]

    def fmt_row(item):
        """Format a cutting list item as  L × W = qty"""
        l = item.get("dimension_l", 0)
        w = item.get("dimension_w", 0)
        q = item.get("quantity", 1)
        name = item.get("name","")
        return f"{name}  {int(l)} × {int(w)} = {q}"

    def section_lines(section_name):
        items = section_map.get(section_name, [])
        lines = []
        for i, item in enumerate(items, 1):
            lines.append((i, fmt_row(item)))
        return lines

    # ── Build left and right content blocks ──────────────────────────
    # Each block: list of (section_name, [(line_num, text), ...])
    left_blocks  = [(s, section_lines(s)) for s in LEFT_SECTIONS]
    right_blocks = [(s, section_lines(s)) for s in RIGHT_SECTIONS]

    # How many content rows does each block need? Min 4.
    def block_height(lines): return max(4, len(lines) + 1)

    left_heights  = [block_height(b[1]) for b in left_blocks]
    right_heights = [block_height(b[1]) for b in right_blocks]

    # Match up heights: each pair of left+right sections shares rows
    pair_heights = [max(l, r) for l, r in zip(left_heights, right_heights)]

    # ── Draw section grid starting at row 7 ─────────────────────────
    current_row = 7

    for pair_idx, (left_blk, right_blk, pair_h) in enumerate(
            zip(left_blocks, right_blocks, pair_heights)):

        lsec, litems = left_blk
        rsec, ritems = right_blk
        start_row = current_row
        end_row   = current_row + pair_h - 1

        for r in range(start_row, end_row + 1):
            ws.row_dimensions[r].height = 14

        # ── Left section label (col A, rotated 90°) ──────────────────
        merge(start_row, 1, end_row, 1)
        c = ws.cell(row=start_row, column=1, value=lsec)
        c.font      = font(bold=True, size=9, color=WHITE)
        c.alignment = align(h="center", v="center", rot=90)
        c.fill      = fill(NAVY)
        c.border    = THIN

        # ── Left content (cols B-D) ───────────────────────────────────
        for li, (lnum, ltxt) in enumerate(litems):
            r = start_row + li
            if r > end_row: break
            ws.row_dimensions[r].height = 14
            # Line number
            c = ws.cell(row=r, column=2, value=lnum)
            c.font = font(size=8); c.alignment = align(); c.border = THIN
            # Dimension text
            merge(r, 3, r, 4)
            c = ws.cell(row=r, column=3, value=ltxt)
            c.font = font(size=8); c.alignment = align(h="left",v="center",wrap=True)
            c.border = THIN

        # Fill empty left rows
        for r in range(start_row + len(litems), end_row + 1):
            ws.cell(row=r, column=2).border = THIN
            merge(r, 3, r, 4)
            ws.cell(row=r, column=3).border = THIN

        # ── Centre divider (col E) ─────────────────────────────────
        merge(start_row, 5, end_row, 5)
        ws.cell(row=start_row, column=5).border = border("medium","medium","thin","thin")

        # ── Right section label (col F, rotated 90°) ──────────────
        merge(start_row, 6, end_row, 6)
        c = ws.cell(row=start_row, column=6, value=rsec)
        c.font      = font(bold=True, size=9, color=WHITE)
        c.alignment = align(h="center", v="center", rot=90)
        c.fill      = fill(NAVY)
        c.border    = THIN

        # ── Right content (cols G-I) ──────────────────────────────
        for ri, (rnum, rtxt) in enumerate(ritems):
            r = start_row + ri
            if r > end_row: break
            ws.row_dimensions[r].height = 14
            c = ws.cell(row=r, column=7, value=rnum)
            c.font = font(size=8); c.alignment = align(); c.border = THIN
            merge(r, 8, r, 9)
            c = ws.cell(row=r, column=8, value=rtxt)
            c.font = font(size=8); c.alignment = align(h="left",v="center",wrap=True)
            c.border = THIN

        # Fill empty right rows
        for r in range(start_row + len(ritems), end_row + 1):
            ws.cell(row=r, column=7).border = THIN
            merge(r, 8, r, 9)
            ws.cell(row=r, column=8).border = THIN

        current_row = end_row + 1

    # ── Material summary note (sheet count) ─────────────────────────
    mat = data.get("material_summary", {})
    sheets_18 = mat.get("estimated_sheets_18mm", 0)
    sheets_6  = mat.get("estimated_sheets_6mm", 0)
    sheets_8  = mat.get("estimated_sheets_8mm", 0)
    total_sheets = sheets_18 + sheets_6 + sheets_8

    # Write in the DRAWS section equivalent area (right block row 2)
    # Find where the DRAWS block started
    draws_start = 7
    for i, h in enumerate(pair_heights[:2]):
        draws_start += h
    draws_note_row = draws_start  # top of DRAWS pair

    # Just add a note row after the grid
    note_row = current_row
    ws.row_dimensions[note_row].height = 16
    merge(note_row, 1, note_row, 9)
    c = ws.cell(row=note_row, column=1,
                value=f"  {total_sheets} Sheets total  "
                      f"({sheets_18} × 18mm  "
                      f"{'  ' + str(sheets_8) + ' × 8mm' if sheets_8 else ''}"
                      f"  {sheets_6} × 6mm)")
    c.font = font(bold=True, size=9)
    c.alignment = align(h="left", v="center")
    c.fill   = fill(LIGHT_GREY)
    c.border = THIN
    current_row += 1

    # ── Bottom accessories row ────────────────────────────────────────
    acc_row = current_row
    ws.row_dimensions[acc_row].height = 18

    accs = data.get("accessories", [])
    acc_map = {a["name"]: a.get("qty", 0) for a in accs}

    # Fixed boxes: S/Pegs | Hinges | Legs pack | Handles | Soft Close
    boxes = [
        ("S/Pegs",    acc_map.get("Shelf Pegs Plastic", acc_map.get("Shelf Pegs Metal Hafele 282.24.710", ""))),
        ("Hinges",    acc_map.get("Overlay Splung", acc_map.get("Hinge - Overlay Sprung",""))),
        ("Legs pack", acc_map.get("Legs 150", acc_map.get("Legs 100",""))),
        ("Handles",   acc_map.get("sample","")),
        ("Soft Close",acc_map.get("Overlay Softclose","")),
    ]

    col_spans = [(1,2), (3,4), (5,6), (7,8), (9,9)]
    for (label, val), (c1, c2) in zip(boxes, col_spans):
        merge(acc_row, c1, acc_row, c2)
        txt = f"{label}" + (f"\n{val}" if val else "")
        c = ws.cell(row=acc_row, column=c1, value=txt)
        c.font      = font(bold=True, size=8)
        c.alignment = align(h="center", v="center", wrap=True)
        c.fill      = fill(MID_GREY)
        c.border    = THICK

    # ── Page setup ───────────────────────────────────────────────────
    ws.page_setup.orientation = "portrait"
    ws.page_setup.paperSize   = 9   # A4
    ws.page_setup.fitToPage   = True
    ws.page_setup.fitToWidth  = 1
    ws.page_setup.fitToHeight = 1
    ws.print_area = f"A1:I{acc_row}"
    ws.sheet_view.showGridLines = False

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.read()


# ── Quick test ───────────────────────────────────────────────────────
if __name__ == "__main__":
    test_data = {
        "cabinet_type":  "Kitchen",
        "project_name":  "Test Kitchen",
        "customer_name": "NAWAZ",
        "address":       "123 Test Street",
        "fitting_date":  "25/09/2026",
        "outside_wood":  "Grey Nabearcia Oak",
        "carcase_wood":  "U156",
        "door_wood":     "",
        "date":          "19/09/2026",
        "sections": [
            {"category": "GABLE", "items": [
                {"name":"Gable left",  "dimension_l":880,"dimension_w":800,"quantity":4,"notes":""},
                {"name":"Gable right", "dimension_l":865,"dimension_w":1000,"quantity":14,"notes":""},
            ]},
            {"category": "S/H", "items": []},
            {"category": "BACKS", "items": [
                {"name":"Back","dimension_l":600,"dimension_w":764,"quantity":1,"notes":""},
                {"name":"Back","dimension_l":600,"dimension_w":764,"quantity":1,"notes":""},
                {"name":"Back","dimension_l":450,"dimension_w":689,"quantity":2,"notes":""},
                {"name":"Back","dimension_l":450,"dimension_w":764,"quantity":2,"notes":""},
                {"name":"Back","dimension_l":450,"dimension_w":1134,"quantity":1,"notes":""},
                {"name":"Back","dimension_l":450,"dimension_w":884,"quantity":2,"notes":""},
            ]},
            {"category": "END PANELS & INFILLS", "items": []},
            {"category": "T/B & FIX SHELVES", "items": [
                {"name":"Top","dimension_l":764,"dimension_w":981,"quantity":2,"notes":""},
                {"name":"Top","dimension_l":764,"dimension_w":360,"quantity":2,"notes":""},
                {"name":"Top","dimension_l":764,"dimension_w":799,"quantity":2,"notes":""},
                {"name":"Base","dimension_l":689,"dimension_w":981,"quantity":2,"notes":"c15"},
                {"name":"Base","dimension_l":689,"dimension_w":360,"quantity":2,"notes":""},
                {"name":"Base","dimension_l":689,"dimension_w":950,"quantity":2,"notes":""},
                {"name":"Fix","dimension_l":1134,"dimension_w":981,"quantity":1,"notes":""},
                {"name":"Fix","dimension_l":1134,"dimension_w":360,"quantity":1,"notes":""},
                {"name":"Fix","dimension_l":1134,"dimension_w":950,"quantity":1,"notes":""},
                {"name":"Shelf","dimension_l":764,"dimension_w":981,"quantity":2,"notes":""},
                {"name":"Shelf","dimension_l":764,"dimension_w":360,"quantity":2,"notes":""},
                {"name":"Shelf","dimension_l":764,"dimension_w":950,"quantity":2,"notes":""},
                {"name":"Shelf","dimension_l":884,"dimension_w":981,"quantity":2,"notes":""},
                {"name":"Shelf","dimension_l":884,"dimension_w":360,"quantity":2,"notes":""},
                {"name":"Shelf","dimension_l":884,"dimension_w":950,"quantity":2,"notes":""},
            ]},
            {"category": "DRAWS", "items": []},
            {"category": "BRACES", "items": []},
            {"category": "DOORS & DRAW FACES", "items": []},
        ],
        "accessories": [
            {"name":"Shelf Pegs Plastic","qty":8},
            {"name":"Overlay Splung","qty":4},
            {"name":"Legs 150","qty":1},
            {"name":"sample","qty":2},
        ],
        "material_summary": {
            "estimated_sheets_18mm": 6,
            "estimated_sheets_6mm":  1,
            "estimated_sheets_8mm":  0,
        }
    }

    result = generate_cutting_list_xlsx(test_data)
    with open("/home/claude/cutting_list_test.xlsx", "wb") as f:
        f.write(result)
    print(f"Written: {len(result):,} bytes")