"""
generate_cutting_list_pdf.py
Generates an A4 cutting list PDF using fpdf2.
Place in backend/routes/ alongside manual_cabinet.py
"""

from fpdf import FPDF
import io

# ── Colours ───────────────────────────────────────────────────────────────────
NAVY  = (30,  58, 100)
WHITE = (255, 255, 255)
BLACK = (0,   0,   0)
GREY  = (245, 245, 245)
LGREY = (200, 200, 200)
MGREY = (120, 120, 120)
DGREY = (170, 170, 170)

SECTIONS_LEFT  = ['GABLE', 'S/H', 'BACKS', 'END PANELS & INFILLS']
SECTIONS_RIGHT = ['T/B & FIX SHELVES', 'DRAWS', 'BRACES', 'DOORS & DRAW FACES']
ALL_SECTIONS   = SECTIONS_LEFT + SECTIONS_RIGHT


def safe(text):
    """Sanitise to latin-1 for Helvetica."""
    return (str(text)
            .replace('\u2014', '-').replace('\u2013', '-')
            .replace('\u2018', "'").replace('\u2019', "'")
            .replace('\u00d7', 'x').replace('\u00a3', 'GBP')
            .encode('latin-1', errors='replace').decode('latin-1'))


def strip_prefix(name):
    """Remove '[Unit Label] ' prefix from panel names."""
    name = str(name or '')
    if name.startswith('['):
        end = name.find('] ')
        if end != -1:
            return name[end + 2:]
    return name


def generate_cutting_list_pdf(data: dict) -> bytes:
    pdf = FPDF(orientation='P', unit='mm', format='A4')
    pdf.set_margins(4, 4, 4)
    pdf.set_auto_page_break(auto=False)
    pdf.add_page()

    PAGE_W = 210
    PAGE_H = 297
    ML = 4          # left margin
    MR = 4          # right margin
    MT = 4          # top margin
    W  = PAGE_W - ML - MR   # 202mm usable width
    # Heights reserved: units strip ~7, header ~27, summary ~6, accessories ~10
    # Remaining for cutting list grid
    UNITS_H = 7     # units info strip
    HDR_H   = 27    # 5 rows × 5.4mm
    SUM_H   = 6
    ACC_H   = 10
    CL_H    = PAGE_H - MT - UNITS_H - HDR_H - SUM_H - ACC_H - 4   # ~239mm

    # ── Column widths for one half of the cutting list ───────────────────────
    # half = 101mm. Fixed absolute offsets from row_x (= x + lbl_w):
    # [label 6] | [num 5] | [badge 5] | [name 30] | [L 14] [x 5] [W 14] [= 5] [qty 10] [pad 7]
    # Total: 6 + 5+5+30+14+5+14+5+10 = 94mm → 7mm slack ✓
    half    = W / 2          # 101mm each
    lbl_w   = 6              # navy section label
    num_w   = 5              # row number
    badge_w = 5              # unit badge column
    name_w  = 30             # panel name
    dim_w   = 14             # L or W value
    sep_w   = 5              # × or =
    qty_w   = 10             # quantity
    # Absolute offsets from row_x:
    OFF_NUM   = 0
    OFF_BADGE = num_w
    OFF_NAME  = num_w + badge_w
    OFF_L     = num_w + badge_w + name_w
    OFF_SEP1  = OFF_L   + dim_w
    OFF_W     = OFF_SEP1 + sep_w
    OFF_SEP2  = OFF_W   + dim_w
    OFF_QTY   = OFF_SEP2 + sep_w

    cur_y = float(MT)

    # ── Build section map ─────────────────────────────────────────────────────
    sec_map = {s: [] for s in ALL_SECTIONS}
    for sec in data.get('sections', []):
        cat = sec.get('category', '')
        if cat in sec_map:
            sec_map[cat] = [i for i in sec.get('items', []) if i]

    # ── UNITS INFO STRIP ──────────────────────────────────────────────────────
    units_info = data.get('units_info', [])
    if units_info:
        pdf.set_fill_color(*GREY)
        pdf.set_draw_color(*DGREY)
        pdf.rect(ML, cur_y, W, UNITS_H, 'FD')
        pdf.set_xy(ML + 2, cur_y + 1.5)
        pdf.set_font('Helvetica', 'B', 7)
        pdf.set_text_color(*NAVY)
        parts = []
        for u in units_info:
            d = f" x D{u.get('depth','')}" if u.get('depth') else ''
            parts.append(f"{u['index']}. {safe(u['label'])}  H{u['height']} x W{u['width']}{d}mm")
        pdf.cell(W - 4, 4, safe('     '.join(parts)), border=0)
        pdf.set_text_color(*BLACK)
        cur_y += UNITS_H

    # ── HEADER GRID ───────────────────────────────────────────────────────────
    left_labels  = ['CUSTOMER NAME', 'HOME ADDRESS', 'KITCHEN', 'MODULAR', 'SLIDING']
    left_values  = [
        data.get('customer_name', ''),
        data.get('address', ''),
        data.get('cabinet_type', ''),
        data.get('project_name', ''),
        '',
    ]
    right_labels = ['FITTING DATE', 'OUTSIDE WOOD', 'CARCASE WOOD', 'DOOR WOOD', 'READYMADE DOOR']
    right_values = [
        data.get('fitting_date', ''),
        data.get('outside_wood', ''),
        data.get('carcase_wood', ''),
        data.get('door_wood', ''),
        '',
    ]
    date_val = safe(data.get('date', ''))

    date_box_w = 26
    col_w      = (W - date_box_w) / 2   # ~88mm per header col
    lbl_col    = 28
    val_col    = col_w - lbl_col
    hdr_row_h  = HDR_H / 5              # 5.4mm per row

    for i in range(5):
        y   = cur_y + i * hdr_row_h
        lbl = left_labels[i]
        val = safe(left_values[i]) or '-'
        rlbl= right_labels[i]
        rval= safe(right_values[i]) or '-'

        # Left label cell
        pdf.set_fill_color(*GREY); pdf.set_draw_color(*DGREY)
        pdf.rect(ML, y, lbl_col, hdr_row_h, 'FD')
        pdf.set_xy(ML + 1, y + 1)
        pdf.set_font('Helvetica', 'B', 5.5); pdf.set_text_color(80, 80, 80)
        pdf.cell(lbl_col - 1, hdr_row_h - 1.5, lbl, border=0)

        # Left value cell
        pdf.set_fill_color(*WHITE)
        pdf.rect(ML + lbl_col, y, val_col, hdr_row_h, 'FD')
        pdf.set_xy(ML + lbl_col + 1, y + 1)
        pdf.set_font('Helvetica', '', 7.5); pdf.set_text_color(*BLACK)
        pdf.cell(val_col - 1, hdr_row_h - 1.5, val, border=0)

        # Right label cell
        rx = ML + col_w
        pdf.set_fill_color(*GREY)
        pdf.rect(rx, y, lbl_col, hdr_row_h, 'FD')
        pdf.set_xy(rx + 1, y + 1)
        pdf.set_font('Helvetica', 'B', 5.5); pdf.set_text_color(80, 80, 80)
        pdf.cell(lbl_col - 1, hdr_row_h - 1.5, rlbl, border=0)

        # Right value cell
        pdf.set_fill_color(*WHITE)
        pdf.rect(rx + lbl_col, y, val_col - date_box_w, hdr_row_h, 'FD')
        pdf.set_xy(rx + lbl_col + 1, y + 1)
        pdf.set_font('Helvetica', '', 7.5); pdf.set_text_color(*BLACK)
        pdf.cell(val_col - date_box_w - 1, hdr_row_h - 1.5, rval, border=0)

    # Date box
    date_x = ML + col_w + lbl_col + (val_col - date_box_w)
    pdf.set_fill_color(*GREY); pdf.set_draw_color(*DGREY)
    pdf.rect(date_x, cur_y, date_box_w, HDR_H, 'FD')
    pdf.set_xy(date_x, cur_y + 3)
    pdf.set_font('Helvetica', 'B', 6); pdf.set_text_color(80, 80, 80)
    pdf.cell(date_box_w, 4, 'DATE', border=0, align='C')
    pdf.set_xy(date_x, cur_y + 8)
    pdf.set_font('Helvetica', 'B', 9); pdf.set_text_color(*NAVY)
    pdf.cell(date_box_w, 5, date_val, border=0, align='C')
    pdf.set_text_color(*BLACK)

    cur_y += HDR_H

    # ── CUTTING LIST GRID ─────────────────────────────────────────────────────
    def n_rows(sec):
        return max(3, len(sec_map.get(sec, [])))

    # Calculate each pair's share of CL_H proportionally
    pairs = list(zip(SECTIONS_LEFT, SECTIONS_RIGHT))
    raw_heights = [max(n_rows(ls), n_rows(rs)) for ls, rs in pairs]
    total_raw   = sum(raw_heights)
    pair_heights = [(r / total_raw) * CL_H for r in raw_heights]

    def draw_half(x, sec_name, band_y, band_h, line_start):
        items    = sec_map.get(sec_name, [])
        nr       = max(3, len(items))
        rh       = band_h / nr          # actual row height

        # Navy section label (vertical text via rotation)
        pdf.set_fill_color(*NAVY); pdf.set_draw_color(*NAVY)
        pdf.rect(x, band_y, lbl_w, band_h, 'F')
        cx = x + lbl_w / 2
        cy = band_y + band_h / 2
        with pdf.local_context():
            pdf.set_text_color(*WHITE)
            pdf.set_font('Helvetica', 'B', 5.5)
            with pdf.rotation(90, cx, cy):
                pdf.set_xy(cx - band_h / 2, cy - 2.5)
                pdf.cell(band_h, 5, sec_name, border=0, align='C')

        # Section outline
        pdf.set_draw_color(*DGREY)
        pdf.rect(x, band_y, half, band_h, 'D')

        row_x = x + lbl_w

        for ri in range(nr):
            ry   = band_y + ri * rh
            item = items[ri] if ri < len(items) else None
            name = strip_prefix(item.get('name', '') if item else '')
            il   = item.get('dimension_l', '') if item else ''
            iw   = item.get('dimension_w', '') if item else ''
            iq   = item.get('quantity', '')    if item else ''
            uidx = (item.get('unit_index', 0) or 0) if item else 0

            # Alternating row bg
            if item and ri % 2 == 0:
                pdf.set_fill_color(249, 250, 251)
                pdf.rect(row_x, ry, half - lbl_w, rh, 'F')

            # Row border
            pdf.set_draw_color(*DGREY)
            pdf.rect(row_x, ry, half - lbl_w, rh, 'D')

            ty   = ry + rh * 0.18   # text baseline y
            ch   = rh * 0.65         # cell height

            # ① Line number — absolute position
            pdf.set_xy(row_x + OFF_NUM, ty)
            pdf.set_font('Helvetica', '', 5.5)
            pdf.set_text_color(*LGREY)
            pdf.cell(num_w, ch, str(line_start + ri), border=0, align='C')

            # ② Unit badge — fixed column, never overlaps name/dims
            if uidx and item:
                bx = row_x + OFF_BADGE + 0.5
                by = ry + rh * 0.15
                br = min(rh * 0.32, 2.5)
                pdf.set_fill_color(*NAVY)
                pdf.ellipse(bx, by, br * 2, br * 2, 'F')
                pdf.set_xy(bx - 0.2, by - 0.2)
                pdf.set_font('Helvetica', 'B', 4.5)
                pdf.set_text_color(*WHITE)
                pdf.cell(br * 2, br * 2 + 0.4, str(uidx), border=0, align='C')

            # ③ Panel name — starts at fixed OFF_NAME
            pdf.set_xy(row_x + OFF_NAME, ty)
            pdf.set_font('Helvetica', 'B' if item else '', 6.5)
            pdf.set_text_color(*BLACK if item else (190, 190, 190))
            pdf.cell(name_w, ch, safe(name[:18]), border=0)

            # ④ L value
            pdf.set_xy(row_x + OFF_L, ty)
            pdf.set_font('Helvetica', 'B' if il else '', 7)
            pdf.set_text_color(*BLACK if il else (190, 190, 190))
            pdf.cell(dim_w, ch, safe(str(int(il)) if il else 'L'), border=0, align='C')

            # ⑤ × separator
            pdf.set_xy(row_x + OFF_SEP1, ty)
            pdf.set_font('Helvetica', '', 6); pdf.set_text_color(*MGREY)
            pdf.cell(sep_w, ch, 'x', border=0, align='C')

            # ⑥ W value
            pdf.set_xy(row_x + OFF_W, ty)
            pdf.set_font('Helvetica', 'B' if iw else '', 7)
            pdf.set_text_color(*BLACK if iw else (190, 190, 190))
            pdf.cell(dim_w, ch, safe(str(int(iw)) if iw else 'W'), border=0, align='C')

            # ⑦ = separator
            pdf.set_xy(row_x + OFF_SEP2, ty)
            pdf.set_font('Helvetica', '', 6); pdf.set_text_color(*MGREY)
            pdf.cell(sep_w, ch, '=', border=0, align='C')

            # ⑧ Qty
            pdf.set_xy(row_x + OFF_QTY, ty)
            pdf.set_font('Helvetica', 'B' if iq else '', 7)
            pdf.set_text_color(*BLACK if iq else (190, 190, 190))
            pdf.cell(qty_w, ch, safe(str(iq) if iq else 'qty'), border=0, align='C')

        return line_start + nr

    # Draw all 4 pairs, each pair = left half + right half at same band_y
    global_line_left  = 1
    global_line_right = 1
    for pi, ((ls, rs), ph) in enumerate(zip(pairs, pair_heights)):
        band_y = cur_y
        global_line_left  = draw_half(ML,          ls, band_y, ph, global_line_left)
        global_line_right = draw_half(ML + half,    rs, band_y, ph, global_line_right)
        cur_y += ph

    # ── SHEET SUMMARY ─────────────────────────────────────────────────────────
    mat   = data.get('material_summary', {}) or {}
    t18   = mat.get('estimated_sheets_18mm', 0) or 0
    t6    = mat.get('estimated_sheets_6mm',  0) or 0
    t8    = mat.get('estimated_sheets_8mm',  0) or 0
    total = t18 + t6 + t8
    parts = []
    if t18: parts.append(f'{t18} x 18mm')
    if t8:  parts.append(f'{t8} x 8mm')
    if t6:  parts.append(f'{t6} x 6mm')
    summary = f'{total} Sheets total  ({" . ".join(parts)})' if total else ''

    pdf.set_fill_color(*GREY); pdf.set_draw_color(*DGREY)
    pdf.rect(ML, cur_y, W, SUM_H, 'FD')
    pdf.set_xy(ML + 2, cur_y + 1.2)
    pdf.set_font('Helvetica', 'B', 7.5); pdf.set_text_color(*NAVY)
    pdf.cell(W - 4, 4, safe(summary))
    pdf.set_text_color(*BLACK)
    cur_y += SUM_H

    # ── ACCESSORIES ROW ───────────────────────────────────────────────────────
    accs    = data.get('accessories', [])
    acc_map = {a['name']: a.get('qty', 0) for a in accs}

    boxes = [
        ('S/Pegs',    acc_map.get('Shelf Pegs Plastic', acc_map.get('Shelf Pegs Metal Hafele 282.24.710', ''))),
        ('Hinges',    acc_map.get('Overlay Splung', acc_map.get('Hinge - Overlay Sprung', ''))),
        ('Legs pack', acc_map.get('Legs 150', acc_map.get('Legs 100', ''))),
        ('Handles',   acc_map.get('sample', '')),
        ('Soft Close',acc_map.get('Overlay Softclose', '')),
    ]

    box_w = W / len(boxes)
    remaining_h = max(ACC_H, PAGE_H - MR - cur_y)
    for i, (label, val) in enumerate(boxes):
        bx = ML + i * box_w
        pdf.set_fill_color(*GREY); pdf.set_draw_color(*DGREY)
        pdf.rect(bx, cur_y, box_w, remaining_h, 'FD')
        pdf.set_xy(bx + 0.5, cur_y + 1.5)
        pdf.set_font('Helvetica', 'B', 6); pdf.set_text_color(80, 80, 80)
        pdf.cell(box_w - 1, 3.5, label, border=0, align='C')
        if val:
            pdf.set_xy(bx + 0.5, cur_y + 5)
            pdf.set_font('Helvetica', 'B', 9); pdf.set_text_color(*NAVY)
            pdf.cell(box_w - 1, 4, safe(str(val)), border=0, align='C')
        pdf.set_text_color(*BLACK)

    buf = io.BytesIO()
    pdf.output(buf)
    buf.seek(0)
    return buf.read()


if __name__ == '__main__':
    test = {
        'project_name': 'Test Kitchen', 'customer_name': 'Mr Smith',
        'cabinet_type': 'Kitchen', 'carcase_wood': 'Egger MFC G4-5',
        'date': '20/09/2026',
        'units_info': [
            {'index': 1, 'label': 'Kitchen Base', 'height': 720, 'width': 1200, 'depth': 570},
            {'index': 2, 'label': 'Kitchen Wall', 'height': 720, 'width': 600,  'depth': 320},
        ],
        'sections': [
            {'category': 'GABLE', 'items': [
                {'name': 'Gable - Right', 'dimension_l': 720, 'dimension_w': 570, 'quantity': 1, 'unit_index': 1},
                {'name': 'Gable - Left',  'dimension_l': 720, 'dimension_w': 570, 'quantity': 1, 'unit_index': 1},
                {'name': 'Gable Left',    'dimension_l': 720, 'dimension_w': 320, 'quantity': 1, 'unit_index': 2},
                {'name': 'Gable Right',   'dimension_l': 720, 'dimension_w': 320, 'quantity': 1, 'unit_index': 2},
            ]},
            {'category': 'T/B & FIX SHELVES', 'items': [
                {'name': 'Base',     'dimension_l': 1164, 'dimension_w': 510, 'quantity': 1, 'unit_index': 1},
                {'name': 'Top Rail', 'dimension_l': 1164, 'dimension_w': 100, 'quantity': 1, 'unit_index': 1},
                {'name': 'Base',     'dimension_l': 1164, 'dimension_w': 300, 'quantity': 1, 'unit_index': 2},
                {'name': 'Top',      'dimension_l': 1164, 'dimension_w': 300, 'quantity': 1, 'unit_index': 2},
            ]},
            {'category': 'S/H', 'items': [
                {'name': 'Adjustable Shelf', 'dimension_l': 1164, 'dimension_w': 510, 'quantity': 1, 'unit_index': 1},
                {'name': 'Shelf',            'dimension_l': 1164, 'dimension_w': 300, 'quantity': 2, 'unit_index': 2},
            ]},
            {'category': 'BACKS', 'items': [
                {'name': 'Back', 'dimension_l': 720,  'dimension_w': 1164, 'quantity': 1, 'unit_index': 1},
                {'name': 'Back', 'dimension_l': 1164, 'dimension_w': 720,  'quantity': 1, 'unit_index': 2},
            ]},
            {'category': 'DOORS & DRAW FACES', 'items': [
                {'name': 'Doors', 'dimension_l': 714, 'dimension_w': 595, 'quantity': 2, 'unit_index': 1},
            ]},
        ],
        'accessories': [{'name': 'Overlay Splung', 'qty': 4}, {'name': 'Legs 150', 'qty': 1}],
        'material_summary': {'estimated_sheets_18mm': 3, 'estimated_sheets_6mm': 1, 'estimated_sheets_8mm': 0},
    }
    data = generate_cutting_list_pdf(test)
    with open('/home/claude/cutting_list_test.pdf', 'wb') as f:
        f.write(data)
    print(f'PDF: {len(data):,} bytes — saved to cutting_list_test.pdf')