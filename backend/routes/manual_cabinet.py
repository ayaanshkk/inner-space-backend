"""
Manual Cabinet Entry Routes - StreemLyne_MT schema
Allows users to manually input cabinet dimensions and auto-calculates all components
Based on K Carc + B Carc price generator workflows from Excel
Corrected against exact Excel formulas, board names, edging names, and pricing tiers.
"""
from flask import Blueprint, request, jsonify
from sqlalchemy import text
from datetime import datetime
import logging
from decimal import Decimal
import math
import json

from ..db import SessionLocal
from .auth_helpers import token_required, get_current_tenant_id

logger = logging.getLogger('ManualCabinetRoutes')

manual_cabinet_bp = Blueprint('manual_cabinet', __name__)


# ==========================================
# PRICING TIERS (from Customer sheet)
# KEYS = exact Excel display strings used in VLOOKUP(J21, Customer[], 2, FALSE)
# ==========================================

PRICING_TIERS = {
    'Trade Min':  2.0,
    'Trade 2.5':  2.5,
    'Retail 3':   3.0,
    'Retail 3.5': 3.5,
    'Retail 4':   4.0,
    'Retail 5':   5.0,
}

# ==========================================
# BOARD COSTS per m² (from Boards sheet)
# KEYS = exact Excel strings used in INDEX(Board[Resale Price], MATCH(B3, Board[Description], 0))
# All 34 boards included. Birch Plywood corrected to £15.62 (was £15.63).
# ==========================================

BOARD_COSTS = {
    'MDF 12mm Coffin':                     10.42,
    'Acrylic    White / Cream   G1':       30.33,
    'Acrylic       Colours            G2': 33.06,
    'Acrylic     Metalics            G3':  35.25,
    'EGGER    White MFC G 2-3':             9.66,
    'Egger         MFC G 4-5':             11.21,
    'Egger         MFC G 6-7':             12.59,
    'Egger         MFC G 8-9':             15.36,
    'Egger         MFC G 10':              17.08,
    'Egger         MFC G 11':              18.46,
    'Egger      Perfect Gloss':            27.61,
    'Egger      Perfect Matt':             29.16,
    'Saviola          G1':                 14.29,
    'Saviola          G2':                 15.65,
    'Saviola          G3':                 16.67,
    'Saviola          G4':                 19.39,
    'Saviola          G5':                 20.58,
    'Unillin           G1':                13.46,
    'Unillin           G2':                14.84,
    'Unillin           G3':                15.87,
    'Xylocleaf       G1':                  27.61,
    'Xylocleaf       G2':                  31.06,
    'Xylocleaf       G3':                  35.54,
    'Xylocleaf       G4':                  39.68,
    'Xylocleaf       G5':                  57.11,
    'Sibu Leather':                       113.46,
    'Querkus Smoked Robusta Oak':          50.00,
    'Birch Plywood':                       15.62,
    '12mm MR MDF':                         10.08,
    '6mm MR MDF':                           6.72,
    'NEY ACRYLIC  WHITE CREAM GREY':       23.89,
    'Emporio Skins':                       17.43,
    '22mm Hidrofugo MDF':                  19.44,
    'Alvic':                               55.65,
}

# ==========================================
# EDGING COSTS per metre (from Edgings sheet)
# KEYS = exact Excel strings. Precision: 4dp (0.5333 not 0.533, 1.1333 not 1.133)
# All 9 edgings included.
# ==========================================

EDGING_COSTS = {
    'Acrylic  Duo Edging':               1.1333,
    'Acrylic Metalic Duo':               1.1333,
    'Egger White MFC G3-7':              0.5333,
    'Egger White MFC G8':                0.5333,
    'Egger White MFC G9-10   luton 69':  0.5333,
    'Egger White MFC G11-12':            0.5333,
    'Egger    Perfect  Gloss':           1.1333,
    'Egger    Perfect  Matt':            1.1333,
    'Saviola':                           1.1333,
}

# ==========================================
# ACCESSORY RESALE PRICES (from Accessories sheet)
# KEYS = exact Excel strings used in IFNA(INDEX(Accessory[Resale Price], MATCH(B15,...)), 0)
# NOTE: 'LED Groving Per Gable' — Excel typo (missing 'o') preserved intentionally
# ==========================================

ACCESSORY_RESALE = {
    'Hanging Rail':                        10.00,
    'Shelf Pegs Metal Hafele 282.24.710':   0.147,
    'Shelf Pegs Plastic':                   0.12,
    'Legs 150':                             5.00,
    'Legs 100':                             4.00,
    'Hanger plate':                         0.40,
    'Cabinet hanger set':                   2.00,
    'Shelf Holes Row Per Gable':           15.00,
    'LED Groving Per Gable':               20.00,  # Excel typo preserved
    'Cable Tidy 80mm    429.99.511':        6.00,
}

# Hinges (from Hinges sheet) — all £5.00 resale
HINGE_RESALE = {
    'Overlay Splung':    5.00,
    'Overlay Unsprung':  5.00,
    'Overlay Softclose': 5.00,
    'Inset Sprung':      5.00,
    'Inset Unsprung':    5.00,
    'Inset Softclose':   5.00,
}

# Handles (from Handles sheet)
HANDLE_RESALE = {
    'sample': 5.00,
}

# Standard board for 6mm kitchen backs (K Carc)
BACK_6MM_BOARD = '6mm MR MDF'

# Standard sheet area for sheet-count estimates
SHEET_AREA_M2 = 2.88


# ══════════════════════════════════════════════════════════════════════
# CORE FORMULA HELPERS — exact Excel ROUNDUP replication
# ══════════════════════════════════════════════════════════════════════

def _roundup(x, dp=2):
    """
    Excel ROUNDUP(x, dp) — always rounds away from zero.
    e.g. ROUNDUP(1.381, 2) = 1.39
    """
    factor = 10 ** dp
    return math.ceil(x * factor) / factor


def _panel_price(panel_l, panel_w, edging_l, qty, board_cost, edging_cost):
    """
    Exact Excel panel cost formula (B Carc / K Carc):
        m2         = ROUNDUP((panel_l * panel_w) / 1_000_000, 2)
        panel_cost = ROUNDUP(m2 * board_cost, 2)
        edging_c   = ROUNDUP((edging_l * edging_cost) / 1000, 2)
        item_cost  = panel_cost + edging_c
        price      = ROUNDUP(item_cost * qty, 2)
    Returns (price, m2_per_item)
    """
    m2  = _roundup((panel_l * panel_w) / 1_000_000, 2)
    pc  = _roundup(m2 * board_cost, 2)
    ec  = _roundup((edging_l * edging_cost) / 1000, 2)
    return _roundup((pc + ec) * qty, 2), m2


def _accessory_price(name, qty):
    """
    Excel: ROUNDUP(IFNA(INDEX(Accessory[Resale Price], MATCH(name,...)), 0) * qty, 2)
    """
    unit = ACCESSORY_RESALE.get(name, 0)
    return _roundup(unit * qty, 2)


def _resale(material_cost, tier_name):
    """
    Excel: K20 * VLOOKUP(J21, Customer[], 2, FALSE)
    Returns (resale_price, multiplier)
    """
    mult = PRICING_TIERS.get(tier_name, 3.5)
    return round(material_cost * mult, 2), mult


def _total_area_m2(panels):
    return round(sum(p['area_m2'] * p['quantity'] for p in panels), 3)


def _sheet_counts(panels):
    a18 = sum(p.get('area_m2', 0) * p.get('quantity', 1) for p in panels if p.get('thickness', 18) == 18)
    a8  = sum(p.get('area_m2', 0) * p.get('quantity', 1) for p in panels if p.get('thickness') == 8)
    a6  = sum(p.get('area_m2', 0) * p.get('quantity', 1) for p in panels if p.get('thickness') == 6)
    return {
        'total_area_18mm':        round(a18, 3),
        'total_area_8mm':         round(a8, 3),
        'total_area_6mm':         round(a6, 3),
        'estimated_sheets_18mm':  math.ceil(a18 / SHEET_AREA_M2) if a18 else 0,
        'estimated_sheets_8mm':   math.ceil(a8  / SHEET_AREA_M2) if a8  else 0,
        'estimated_sheets_6mm':   math.ceil(a6  / SHEET_AREA_M2) if a6  else 0,
    }


# ══════════════════════════════════════════════════════════════════════
# DRAWER SYSTEM CALCULATOR
# ══════════════════════════════════════════════════════════════════════

class DrawerCalculator:
    """
    Drawer box width formulas (from transcript + K Carc / New Kitchen sheet):
      Hettich:           internal_width - 60mm  (30mm each side)
      Ball bearing:      internal_width - 24mm  (12mm each side)
      Blum / Slyder:     internal_width - 24mm  (12mm each side)
    """

    DRAWER_SYSTEMS = {
        'hettich': {
            'name': 'Hettich Drawer System',
            'side_deduction_each': 30,
            'total_deduction': 60,
            'notes': 'Hettich system — internal width minus 30mm per side'
        },
        'ball_bearing': {
            'name': 'Ball Bearing Runner',
            'side_deduction_each': 12,
            'total_deduction': 24,
            'notes': 'Ball bearing runner — 12mm per side'
        },
        'blum_bottom_fix': {
            'name': 'Blum Bottom Fix',
            'side_deduction_each': 12,
            'total_deduction': 24,
            'notes': 'Blum bottom fix — standard 12mm per side'
        },
        'blum_motion_tip_on': {
            'name': 'Blum Motion / Tip On',
            'side_deduction_each': 12,
            'total_deduction': 24,
            'notes': 'Blum Motion soft close — 12mm per side'
        },
        'slyder_twin_wall': {
            'name': 'Slyder Twin Wall SC',
            'side_deduction_each': 12,
            'total_deduction': 24,
            'notes': 'Slyder twin wall soft close — 12mm per side'
        }
    }

    # Standard face heights from New Kitchen sheet
    STANDARD_FACE_HEIGHTS = [140, 283, 355]

    def calculate_drawer(self, internal_width, system_type, drawer_count=1,
                         cabinet_height=None, face_height=None):
        system = self.DRAWER_SYSTEMS.get(system_type)
        if not system:
            raise ValueError(
                f"Unknown drawer system '{system_type}'. "
                f"Valid: {list(self.DRAWER_SYSTEMS.keys())}"
            )

        drawer_box_width = internal_width - system['total_deduction']

        if face_height is None and cabinet_height is not None:
            usable = cabinet_height - 6
            raw_fh = usable / drawer_count
            face_height = self._nearest_face_height(raw_fh)

        face_width = internal_width - 3  # 1.5mm gap each side

        return {
            'system': system_type,
            'system_name': system['name'],
            'drawer_box_width': int(drawer_box_width),
            'face_width': int(face_width),
            'face_height': int(face_height) if face_height else None,
            'quantity': drawer_count,
            'side_deduction_each': system['side_deduction_each'],
            'total_deduction': system['total_deduction'],
            'notes': system['notes']
        }

    def _nearest_face_height(self, height):
        return min(self.STANDARD_FACE_HEIGHTS, key=lambda h: abs(h - height))


# ══════════════════════════════════════════════════════════════════════
# CABINET CALCULATION ENGINE
# ══════════════════════════════════════════════════════════════════════


def _panel_price_wall(panel_l, panel_w, edging_l, qty, board_cost, edging_cost):
    """
    Wall carcass panel formula — K Carc rows 78-83:
    E78 = (C78*D78)/(1000*1000)  — plain division, NO ROUNDUP on m2.
    Panel cost and edging cost still use ROUNDUP.
    """
    m2 = (panel_l * panel_w) / 1_000_000
    pc = _roundup(m2 * board_cost, 2)
    ec = _roundup((edging_l * edging_cost) / 1000, 2) if edging_l else 0
    return _roundup((pc + ec) * qty, 2), m2



class CabinetCalculator:
    """
    Calculates all components for a cabinet based on H × W × D.

    K Carc panel formulas:
        Gables:   Panel L = Height,       Panel W = Depth
        Base:     Panel L = Width - 36,   Panel W = Depth - 70
        Top Rail: Panel L = Width - 36,   Panel W = 100 (fixed)
        Back:     Panel L = Height,       Panel W = Width - 36  (6mm MDF, no edging)
        Shelf:    Panel L = Width - 36,   Panel W = Depth - 140

    B Carc Full Back formulas:
        Gable:    Panel L = Height,       Panel W = Depth
        Top/Base/Shelf: Panel L = Width-36, Panel W = Depth-18-service_gap
        Back:     Panel L = Height,       Panel W = Width-36   (no edging)

    B Carc 8mm Back formulas:
        Gable:    Panel L = Height,       Panel W = Depth
        Top/Base/Shelf: Panel L = Width-36, Panel W = Depth-12-service_gap
        8mm Back: Panel L = Height,       Panel W = Width-20   (NOT Width-36)
        Shelf qty = 2 (Excel J35=2)
    """

    CARCASS_THICKNESS   = 18
    BACK_THICKNESS_FULL = 18
    BACK_THICKNESS_8MM  = 8
    BACK_THICKNESS_6MM  = 6

    STANDARD_BASE_DEPTH   = 500
    STANDARD_WALL_DEPTH   = 320
    STANDARD_LARDER_DEPTH = 400

    drawer_calc = DrawerCalculator()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _count_panels(self, components):
        total = 0
        for cat in ['carcass', 'backs', 'shelves', 'doors', 'drawers']:
            for item in components.get(cat, []):
                total += item.get('quantity', 1)
        return total

    def _total_area(self, components):
        total = 0.0
        for cat in ['carcass', 'backs', 'shelves', 'doors', 'drawers']:
            for item in components.get(cat, []):
                pl = item.get('panel_l', 0)
                pw = item.get('panel_w', 0)
                m2 = _roundup((pl * pw) / 1_000_000, 2) if pl and pw else 0
                total += m2 * item.get('quantity', 1)
        return round(total, 3)

    def _hardware_cost(self, hardware_list):
        """
        Excel: ROUNDUP(IFNA(INDEX(Accessory/Hinge/Handle[Resale Price], MATCH(...)), 0) * qty, 2)
        Checks Accessory, then Hinge, then Handle sheets in order.
        """
        total = 0.0
        for hw in hardware_list:
            if 'total' in hw:
                total += hw['total']
            else:
                name = hw.get('name', '')
                qty  = hw.get('quantity', 0)
                unit = (ACCESSORY_RESALE.get(name)
                        or HINGE_RESALE.get(name)
                        or HANDLE_RESALE.get(name)
                        or 0)
                total += _roundup(unit * qty, 2)
        return round(total, 2)

    def _calc_material_cost_total(self, components, board_name, edging_name):
        """
        Sum panel costs using exact Excel ROUNDUP formula per panel.
        Each panel uses _panel_price() which replicates ROUNDUP at every step.
        """
        total = 0.0
        board_rate  = BOARD_COSTS.get(board_name, 0)
        edging_rate = EDGING_COSTS.get(edging_name, 0)

        for cat in ['carcass', 'backs', 'shelves', 'doors', 'drawers']:
            for item in components.get(cat, []):
                # Use the item's own board name if it differs (e.g. 6mm back)
                item_board = BOARD_COSTS.get(item.get('material', board_name), board_rate)
                edging_m_total = item.get('edging_length_m', 0) * 1000  # back to mm for formula
                price, _ = _panel_price(
                    item['panel_l'], item['panel_w'],
                    edging_m_total,
                    item.get('quantity', 1),
                    item_board,
                    edging_rate
                )
                total += price
        return round(total, 2)

    def _build_cutting_section(self, name, panel_l, panel_w, quantity,
                                board_name, edging_name, notes,
                                line_num, thickness=18):
        """Build a single cutting list entry with exact Excel area formula."""
        m2 = _roundup((panel_l * panel_w) / 1_000_000, 2)
        area = round(m2 * quantity, 3)
        edging_m = (panel_l / 1000) * quantity
        return {
            'line_number':        line_num,
            'name':               name,
            'dimension_display':  f"{int(panel_l)} × {int(panel_w)} = {quantity}",
            'dimension_l':        int(panel_l),
            'dimension_w':        int(panel_w),
            'thickness':          thickness,
            'quantity':           quantity,
            'material_code':      board_name,   # full Excel string
            'edging_code':        edging_name,  # full Excel string
            'notes':              notes,
            'area_m2':            area,
            'edging_m':           round(edging_m, 3)
        }

    def _format_cutting_list(self, cutting_list):
        # Order matches Excel B Carc exactly:
        # Gable left, Gable right → Top, Base (T/B) → Shelf (S/H) → Back (BACKS)
        order = ['GABLE', 'T/B & FIX SHELVES', 'S/H', 'BACKS',
                 'END PANELS & INFILLS', 'BRACES', 'DOORS & DRAW FACES', 'DRAWS']
        return [{'category': cat, 'items': cutting_list[cat]}
                for cat in order if cutting_list.get(cat)]

    def _material_summary(self, cutting_list, panels_flat):
        sc = _sheet_counts(panels_flat)
        material_count = {}
        for items in cutting_list.values():
            for item in items:
                code = item.get('material_code', '')
                if code:
                    if code not in material_count:
                        material_count[code] = {'pieces': 0, 'area_m2': 0.0}
                    material_count[code]['pieces']  += item.get('quantity', 0)
                    material_count[code]['area_m2'] += item.get('area_m2', 0)
        return {
            'material_breakdown': [
                {'material': k, 'pieces': v['pieces'], 'area_m2': round(v['area_m2'], 3)}
                for k, v in material_count.items()
            ],
            **sc,
        }

    # ------------------------------------------------------------------
    # BASE CABINET  (K Carc — Kitchen Base 720)
    # ------------------------------------------------------------------

    def calculate_base_cabinet(self, height, width, depth=None,
                                board_name='Egger         MFC G 4-5',
                                edging_name='Egger White MFC G8',
                                drawer_system=None, drawer_count=0,
                                adjustable_shelves=1,
                                accessories=None,
                                pricing_tier='Retail 3.5'):
        """
        Kitchen base cabinet — K Carc formulas (updated per client spec):
            Gable W:  570mm FIXED (overall carcass depth — not user depth)
            Base:     (Width-36) × 510   [570 - 40 service gap - 20 back = 510 internal]
            Top Rail: (Width-36) × 100
            Back:     Height × (Width-36)  — 6mm MDF, no edging
            Shelf:    (Width-36) × 510   [same as base — full internal depth]

            The user depth input is IGNORED for gable/base/shelf — these are
            fixed at 570 overall / 510 internal to standardise across all
            drawer runner systems (5mm tolerance absorbed by service gap).
        """
        # Fixed depths per client spec — independent of user depth input
        GABLE_DEPTH    = 570   # overall carcass depth (fixed)
        INTERNAL_DEPTH = 510   # 570 - 40 service gap - 20mm back = 510

        if depth is None:
            depth = self.STANDARD_BASE_DEPTH

        if board_name not in BOARD_COSTS:
            raise ValueError(f"Unknown board '{board_name}'")
        if edging_name not in EDGING_COSTS:
            raise ValueError(f"Unknown edging '{edging_name}'")

        bc = BOARD_COSTS[board_name]
        ec = EDGING_COSTS[edging_name]
        bc_back = BOARD_COSTS[BACK_6MM_BOARD]

        internal_width       = width - 36
        internal_depth_base  = INTERNAL_DEPTH   # fixed 510
        internal_depth_shelf = INTERNAL_DEPTH   # fixed 510

        components   = {'carcass': [], 'backs': [], 'shelves': [],
                        'doors': [], 'drawers': [], 'hardware': []}
        cutting_list = {k: [] for k in ['GABLE', 'S/H', 'T/B & FIX SHELVES', 'BACKS',
                                         'END PANELS & INFILLS', 'BRACES',
                                         'DOORS & DRAW FACES', 'DRAWS']}
        panels_flat  = []
        ln = {k: 1 for k in cutting_list}

        def add(section, name, pl, pw, el_mm, qty, board_cost=None,
                edging_cost=None, thickness=18, notes=''):
            _bc = board_cost  if board_cost  is not None else bc
            _ec = edging_cost if edging_cost is not None else ec
            price, m2 = _panel_price(pl, pw, el_mm, qty, _bc, _ec)
            entry = self._build_cutting_section(
                name, pl, pw, qty, board_name, edging_name, notes, ln[section], thickness
            )
            if board_cost is not None:  # back uses different board
                entry['material_code'] = BACK_6MM_BOARD
                entry['edging_code']   = ''
            cutting_list[section].append(entry)
            ln[section] += 1
            panel = {'name': name, 'panel_l': int(pl), 'panel_w': int(pw),
                     'thickness': thickness, 'quantity': qty,
                     'area_m2': _roundup((pl * pw) / 1_000_000, 2),
                     'edging_length_m': round((el_mm / 1000) * qty, 3),
                     'material': BACK_6MM_BOARD if board_cost is not None else board_name,
                     'notes': notes}
            panels_flat.append(panel)
            for lst in [components['carcass'] if section == 'GABLE' or notes in ('BASE', 'TOP RAIL')
                        else components['backs'] if section == 'BACKS'
                        else components['shelves'] if section == 'S/H'
                        else components['carcass']]:
                lst.append(panel)
                break
            return price

        wood = 0
        # Gables — W = GABLE_DEPTH (570mm fixed per client spec, not user depth)
        wood += add('GABLE', 'Gable - Right', height, GABLE_DEPTH, height, 1, notes='Front edge edging')
        wood += add('GABLE', 'Gable - Left',  height, GABLE_DEPTH, height, 1, notes='Front edge edging')
        # Base
        wood += add('T/B & FIX SHELVES', 'Base',     internal_width, internal_depth_base,  internal_width, 1, notes='BASE')
        # Top Rail
        wood += add('T/B & FIX SHELVES', 'Top Rail', internal_width, 100,                  internal_width, 1, notes='TOP RAIL')
        # Back — 6mm MDF, no edging
        back_price, back_m2 = _panel_price(height, internal_width, 0, 1, bc_back, 0)
        wood += back_price
        back_panel = {'name': 'Back', 'panel_l': int(height), 'panel_w': int(internal_width),
                      'thickness': 6, 'quantity': 1,
                      'area_m2': _roundup((height * internal_width) / 1_000_000, 2),
                      'edging_length_m': 0, 'material': BACK_6MM_BOARD, 'notes': 'No edging'}
        components['backs'].append(back_panel)
        panels_flat.append(back_panel)
        back_entry = self._build_cutting_section(
            'Back', height, internal_width, 1, BACK_6MM_BOARD, '',
            '6MM BACK — no edging', ln['BACKS'], thickness=6
        )
        cutting_list['BACKS'].append(back_entry)
        ln['BACKS'] += 1

        # Adjustable shelves
        if adjustable_shelves > 0:
            shelf_price, _ = _panel_price(internal_width, internal_depth_shelf,
                                          internal_width, adjustable_shelves, bc, ec)
            wood += shelf_price
            shelf_entry = self._build_cutting_section(
                'Adjustable Shelf', internal_width, internal_depth_shelf,
                adjustable_shelves, board_name, edging_name,
                f'ADJ SHELF × {adjustable_shelves}', ln['S/H']
            )
            cutting_list['S/H'].append(shelf_entry)
            ln['S/H'] += 1
            shelf_panel = {'name': f'Shelf (×{adjustable_shelves})',
                           'panel_l': int(internal_width), 'panel_w': int(internal_depth_shelf),
                           'thickness': 18, 'quantity': adjustable_shelves,
                           'area_m2': _roundup((internal_width * internal_depth_shelf) / 1_000_000, 2),
                           'edging_length_m': (internal_width / 1000) * adjustable_shelves,
                           'material': board_name, 'notes': 'Front edge edging'}
            components['shelves'].append(shelf_panel)
            panels_flat.append(shelf_panel)

        # Drawers or Doors
        door_count = 0
        if drawer_system and drawer_count > 0:
            drawer_info = self.drawer_calc.calculate_drawer(
                internal_width, drawer_system, drawer_count, height
            )
            components['drawers'].append({
                'name': f"Drawer Box — {drawer_info['system_name']}",
                'panel_l': drawer_info['face_width'],
                'panel_w': drawer_info['drawer_box_width'],
                'thickness': self.CARCASS_THICKNESS,
                'quantity': drawer_count,
                'material': board_name,
                'notes': drawer_info['notes'],
                'drawer_detail': drawer_info
            })
            if drawer_info.get('face_height'):
                face_price, _ = _panel_price(drawer_info['face_width'],
                                             drawer_info['face_height'],
                                             0, drawer_count, bc, ec)
                wood += face_price
                face_entry = self._build_cutting_section(
                    'Drawer Face', drawer_info['face_width'], drawer_info['face_height'],
                    drawer_count, board_name, edging_name,
                    f"DRAWER FACE × {drawer_count}", ln['DOORS & DRAW FACES']
                )
                cutting_list['DOORS & DRAW FACES'].append(face_entry)
                ln['DOORS & DRAW FACES'] += 1
        else:
            door_h = height - 6
            if width < 600:
                door_count = 1
                door_w = width - 6
                door_price, _ = _panel_price(door_h, door_w,
                                             (door_h * 2 + door_w * 2), 1, bc, ec)
                wood += door_price
                components['doors'].append({
                    'name': 'Door', 'panel_l': int(door_h), 'panel_w': int(door_w),
                    'thickness': 18, 'quantity': 1,
                    'area_m2': _roundup((door_h * door_w) / 1_000_000, 2),
                    'edging_length_m': (door_h * 2 + door_w * 2) / 1000,
                    'material': board_name, 'notes': 'All edges edged'
                })
                panels_flat.append(components['doors'][-1])
                cutting_list['DOORS & DRAW FACES'].append(self._build_cutting_section(
                    'Door', door_h, door_w, 1, board_name, edging_name,
                    'SINGLE DOOR — all edges', ln['DOORS & DRAW FACES']
                ))
                ln['DOORS & DRAW FACES'] += 1
                components['hardware'].append({
                    'name': 'Hinge - Overlay Sprung', 'quantity': 2,
                    'notes': '2 hinges — single door'
                })
            else:
                door_count = 2
                door_w = (width / 2) - 4.5
                door_price, _ = _panel_price(door_h, door_w,
                                             (door_h * 2 + door_w * 2), 2, bc, ec)
                wood += door_price
                for side in ['Left', 'Right']:
                    dp = {'name': f'Door - {side}', 'panel_l': int(door_h),
                          'panel_w': int(door_w), 'thickness': 18, 'quantity': 1,
                          'area_m2': _roundup((door_h * door_w) / 1_000_000, 2),
                          'edging_length_m': (door_h * 2 + door_w * 2) / 1000,
                          'material': board_name, 'notes': 'All edges edged'}
                    components['doors'].append(dp)
                    panels_flat.append(dp)
                cutting_list['DOORS & DRAW FACES'].append(self._build_cutting_section(
                    'Doors', door_h, door_w, 2, board_name, edging_name,
                    'DOUBLE DOORS — all edges', ln['DOORS & DRAW FACES']
                ))
                ln['DOORS & DRAW FACES'] += 1
                components['hardware'].append({
                    'name': 'Hinge - Overlay Sprung', 'quantity': 4,
                    'notes': '2 hinges per door'
                })

        # Hardware — use passed accessories list or K Carc defaults
        if accessories:
            for acc in accessories:
                unit = (ACCESSORY_RESALE.get(acc['name'])
                        or HINGE_RESALE.get(acc['name'])
                        or HANDLE_RESALE.get(acc['name']) or 0)
                components['hardware'].append({
                    'name': acc['name'], 'quantity': int(acc.get('qty', 0)),
                    'unit_price': unit,
                    'total': _roundup(unit * int(acc.get('qty', 0)), 2),
                    'notes': acc.get('type', 'accessory'),
                })
        else:
            components['hardware'].extend([
                {'name': 'Legs 150',          'quantity': 1,
                 'unit_price': 5.0, 'total': 5.0, 'notes': 'Set of 4 adjustable legs'},
                {'name': 'Shelf Pegs Plastic', 'quantity': adjustable_shelves * 4,
                 'unit_price': 0.12, 'total': _roundup(0.12 * adjustable_shelves * 4, 2),
                 'notes': '4 pegs per shelf'},
            ])

        hw_cost       = self._hardware_cost(components['hardware'])
        total_cost    = round(wood + hw_cost, 2)
        sell, mult    = _resale(total_cost, pricing_tier)
        mat_summary   = self._material_summary(cutting_list, panels_flat)

        return {
            'cabinet_type': 'Kitchen Base',
            'dimensions':   {'height': height, 'width': width, 'depth': depth},
            'internal_dimensions': {
                'width':         int(internal_width),
                'gable_depth':   570,   # fixed overall depth
                'depth_internal': 510,  # fixed internal (570 - 40 svc - 20 back)
                'depth_base':    int(internal_depth_base),
                'depth_shelf':   int(internal_depth_shelf),
            },
            'components':             components,
            'cutting_list':           cutting_list,
            'cutting_list_formatted': self._format_cutting_list(cutting_list),
            'material_summary':       mat_summary,
            'pricing': {
                'board_name':       board_name,
                'board_cost_m2':    bc,
                'edging_name':      edging_name,
                'edging_cost_m':    ec,
                'pricing_tier':     pricing_tier,
                'multiplier':       mult,
                'material_cost':    wood,
                'hardware_cost':    hw_cost,
                'total_cost_price': total_cost,
                'resale_price':     sell,
            },
            'summary': {
                'total_panels':  self._count_panels(components),
                'total_area_m2': self._total_area(components),
                'door_count':    door_count,
                'drawer_count':  drawer_count if drawer_system else 0,
                'shelf_count':   adjustable_shelves,
            }
        }

    # ------------------------------------------------------------------
    # WALL CABINET
    # ------------------------------------------------------------------

    def calculate_wall_cabinet(self, height, width, depth=None,
                                board_name='Emporio Skins',
                                edging_name='Saviola',
                                adjustable_shelves=2,
                                accessories=None,
                                pricing_tier='Retail 3'):
        """
        Wall unit differences vs base:
          - No base panel — both top AND bottom are 100mm rails
          - No legs — cabinet hangers + hanger plates
          - Shelf depth: Depth - 140 (same deduction as base)
        """
        if depth is None:
            depth = self.STANDARD_WALL_DEPTH

        if board_name not in BOARD_COSTS:
            raise ValueError(f"Unknown board '{board_name}'")
        if edging_name not in EDGING_COSTS:
            raise ValueError(f"Unknown edging '{edging_name}'")

        bc      = BOARD_COSTS[board_name]
        ec      = EDGING_COSTS[edging_name]
        bc_back = BOARD_COSTS[BACK_6MM_BOARD]

        internal_width        = width - 36
        # K Carc Wall — fixed depths per client spec (same principle as base):
        # Gable W = 320mm fixed (overall wall depth)
        # Internal = 320 - 20 (back) = 300mm
        # Back: inverted — L=Width-36, W=Height
        WALL_GABLE_DEPTH    = 320   # fixed overall wall depth
        WALL_INTERNAL_DEPTH = 300   # 320 - 20mm back = 300 internal

        internal_depth_base  = WALL_INTERNAL_DEPTH
        internal_depth_shelf = WALL_INTERNAL_DEPTH

        components   = {'carcass': [], 'backs': [], 'shelves': [],
                        'doors': [], 'drawers': [], 'hardware': []}
        cutting_list = {k: [] for k in ['GABLE', 'S/H', 'T/B & FIX SHELVES', 'BACKS',
                                         'END PANELS & INFILLS', 'BRACES',
                                         'DOORS & DRAW FACES', 'DRAWS']}
        panels_flat  = []
        ln = {k: 1 for k in cutting_list}

        wood = 0

        # Gables
        for side in ['Left', 'Right']:
            # Wall gable: W = WALL_GABLE_DEPTH (320mm fixed per client spec)
            p, m2 = _panel_price_wall(height, WALL_GABLE_DEPTH, height, 1, bc, ec)
            wood += p
            panel = {'name': f'Gable {side}', 'panel_l': int(height),
                     'panel_w': int(WALL_GABLE_DEPTH), 'thickness': 18, 'quantity': 1,
                     'area_m2': m2, 'edging_length_m': height / 1000,
                     'material': board_name, 'notes': 'Front edge edging'}
            components['carcass'].append(panel)
            panels_flat.append(panel)
            cutting_list['GABLE'].append(self._build_cutting_section(
                f'Gable {side}', height, WALL_GABLE_DEPTH, 1, board_name, edging_name,
                'Front edge edging', ln['GABLE']
            ))
            ln['GABLE'] += 1

        # K Carc Wall 720 — Base and Top use Depth-30, plain m2 formula
        for label in ['Base', 'Top']:
            p, m2 = _panel_price_wall(internal_width, internal_depth_base, internal_width, 1, bc, ec)
            wood += p
            panel = {'name': label, 'panel_l': int(internal_width),
                     'panel_w': int(internal_depth_base),
                     'thickness': 18, 'quantity': 1, 'area_m2': m2,
                     'edging_length_m': internal_width / 1000,
                     'material': board_name, 'notes': 'Front edge edging'}
            components['carcass'].append(panel)
            panels_flat.append(panel)
            cutting_list['T/B & FIX SHELVES'].append(self._build_cutting_section(
                label, internal_width, internal_depth_base, 1, board_name, edging_name,
                label.upper(), ln['T/B & FIX SHELVES']
            ))
            ln['T/B & FIX SHELVES'] += 1

        # Back — K Carc Wall: L=Width-36, W=Height (inverted vs base), same board, no edging
        back_p, back_m2 = _panel_price_wall(internal_width, height, 0, 1, bc, 0)
        wood += back_p
        back_panel = {'name': 'Back', 'panel_l': int(internal_width), 'panel_w': int(height),
                      'thickness': 18, 'quantity': 1, 'area_m2': back_m2,
                      'edging_length_m': 0, 'material': board_name, 'notes': 'No edging'}
        components['backs'].append(back_panel)
        panels_flat.append(back_panel)
        cutting_list['BACKS'].append(self._build_cutting_section(
            'Back', internal_width, height, 1, board_name, '',
            'BACK — no edging', ln['BACKS'], thickness=18
        ))
        ln['BACKS'] += 1

        # Shelves — K Carc Wall: Depth-50, qty=2 (default)
        shelf_qty = adjustable_shelves if adjustable_shelves > 0 else 2
        if shelf_qty > 0:
            sp, sm2 = _panel_price_wall(internal_width, internal_depth_shelf,
                                   internal_width, shelf_qty, bc, ec)
            wood += sp
            shelf_panel = {'name': f'Shelf (×{shelf_qty})',
                           'panel_l': int(internal_width), 'panel_w': int(internal_depth_shelf),
                           'thickness': 18, 'quantity': shelf_qty, 'area_m2': sm2,
                           'edging_length_m': (internal_width / 1000) * shelf_qty,
                           'material': board_name, 'notes': 'Front edge edging'}
            components['shelves'].append(shelf_panel)
            panels_flat.append(shelf_panel)
            cutting_list['S/H'].append(self._build_cutting_section(
                'Shelf', internal_width, internal_depth_shelf,
                shelf_qty, board_name, edging_name,
                f'ADJ SHELF × {shelf_qty}', ln['S/H']
            ))
            ln['S/H'] += 1

        # Doors
        door_h = height - 6
        if width < 600:
            door_count = 1
            door_w = width - 6
            dp, _ = _panel_price(door_h, door_w, door_h * 2 + door_w * 2, 1, bc, ec)
            wood += dp
            components['doors'].append({
                'name': 'Door', 'panel_l': int(door_h), 'panel_w': int(door_w),
                'thickness': 18, 'quantity': 1,
                'area_m2': _roundup((door_h * door_w) / 1_000_000, 2),
                'edging_length_m': (door_h * 2 + door_w * 2) / 1000,
                'material': board_name, 'notes': 'All edges edged'
            })
            cutting_list['DOORS & DRAW FACES'].append(self._build_cutting_section(
                'Door', door_h, door_w, 1, board_name, edging_name,
                'SINGLE DOOR — all edges', ln['DOORS & DRAW FACES']
            ))
            components['hardware'].append({'name': 'Hinge - Overlay Sprung',
                                           'quantity': 2, 'notes': '2 hinges — single door'})
        else:
            door_count = 2
            door_w = (width / 2) - 4.5
            dp, _ = _panel_price(door_h, door_w, door_h * 2 + door_w * 2, 2, bc, ec)
            wood += dp
            for side in ['Left', 'Right']:
                components['doors'].append({
                    'name': f'Door - {side}', 'panel_l': int(door_h),
                    'panel_w': int(door_w), 'thickness': 18, 'quantity': 1,
                    'area_m2': _roundup((door_h * door_w) / 1_000_000, 2),
                    'edging_length_m': (door_h * 2 + door_w * 2) / 1000,
                    'material': board_name, 'notes': 'All edges edged'
                })
            cutting_list['DOORS & DRAW FACES'].append(self._build_cutting_section(
                'Doors', door_h, door_w, 2, board_name, edging_name,
                'DOUBLE DOORS — all edges', ln['DOORS & DRAW FACES']
            ))
            components['hardware'].append({'name': 'Hinge - Overlay Sprung',
                                           'quantity': 4, 'notes': '2 hinges per door'})
        ln['DOORS & DRAW FACES'] += 1

        # Hardware — use passed accessories or wall defaults (no legs)
        if accessories:
            for acc in accessories:
                unit = (ACCESSORY_RESALE.get(acc['name'])
                        or HINGE_RESALE.get(acc['name'])
                        or HANDLE_RESALE.get(acc['name']) or 0)
                components['hardware'].append({
                    'name': acc['name'], 'quantity': int(acc.get('qty', 0)),
                    'unit_price': unit,
                    'total': _roundup(unit * int(acc.get('qty', 0)), 2),
                    'notes': acc.get('type', 'accessory'),
                })
        else:
            components['hardware'].extend([
                {'name': 'Shelf Pegs Plastic', 'quantity': shelf_qty * 4,
                 'unit_price': 0.12, 'total': _roundup(0.12 * shelf_qty * 4, 2),
                 'notes': '4 pegs per shelf'},
                {'name': 'Hanger plate',       'quantity': 2,
                 'unit_price': 0.40, 'total': 0.80, 'notes': 'Pair'},
                {'name': 'Cabinet hanger set', 'quantity': 2,
                 'unit_price': 2.00, 'total': 4.00, 'notes': 'Wall hanging'},
            ])

        hw_cost    = self._hardware_cost(components['hardware'])
        total_cost = round(wood + hw_cost, 2)
        sell, mult = _resale(total_cost, pricing_tier)
        mat_summary = self._material_summary(cutting_list, panels_flat)

        return {
            'cabinet_type': 'Kitchen Wall Cabinet',
            'dimensions':   {'height': height, 'width': width, 'depth': depth},
            'internal_dimensions': {'width': int(internal_width),
                                    'depth_shelf': int(internal_depth_shelf)},
            'components':             components,
            'cutting_list':           cutting_list,
            'cutting_list_formatted': self._format_cutting_list(cutting_list),
            'material_summary':       mat_summary,
            'pricing': {
                'board_name': board_name, 'board_cost_m2': bc,
                'edging_name': edging_name, 'edging_cost_m': ec,
                'pricing_tier': pricing_tier, 'multiplier': mult,
                'material_cost': wood, 'hardware_cost': hw_cost,
                'total_cost_price': total_cost, 'resale_price': sell,
            },
            'summary': {
                'total_panels': self._count_panels(components),
                'total_area_m2': self._total_area(components),
                'door_count': door_count, 'shelf_count': adjustable_shelves,
            }
        }

    # ------------------------------------------------------------------
    # LARDER / TALL UNIT
    # ------------------------------------------------------------------

    def calculate_larder_cabinet(self, height, width, depth=None,
                                  board_name='EGGER    White MFC G 2-3',
                                  edging_name='Egger White MFC G3-7',
                                  shelf_count=6,
                                  accessories=None,
                                  pricing_tier='Retail 3.5'):
        """K Carc Larder 1970: 6 shelves default, Depth-140 shelf deduction."""
        if depth is None:
            depth = self.STANDARD_LARDER_DEPTH

        if board_name not in BOARD_COSTS:
            raise ValueError(f"Unknown board '{board_name}'")
        if edging_name not in EDGING_COSTS:
            raise ValueError(f"Unknown edging '{edging_name}'")

        bc      = BOARD_COSTS[board_name]
        ec      = EDGING_COSTS[edging_name]
        bc_back = BOARD_COSTS[BACK_6MM_BOARD]

        internal_width = width - 36
        internal_depth = depth - 140

        components   = {'carcass': [], 'backs': [], 'shelves': [],
                        'doors': [], 'drawers': [], 'hardware': []}
        cutting_list = {k: [] for k in ['GABLE', 'S/H', 'T/B & FIX SHELVES', 'BACKS',
                                         'END PANELS & INFILLS', 'BRACES',
                                         'DOORS & DRAW FACES', 'DRAWS']}
        panels_flat  = []
        ln = {k: 1 for k in cutting_list}
        wood = 0

        # Gables
        # K Carc Larder: Gable W = WIDTH (D26), not depth
        # C31=C26=Height, D31=D26=Width  (different from base where D8=E3=Depth)
        for side in ['Right', 'Left']:
            p, m2 = _panel_price(height, width, height, 1, bc, ec)
            wood += p
            panel = {'name': f'Gable - {side}', 'panel_l': int(height),
                     'panel_w': int(width), 'thickness': 18, 'quantity': 1,
                     'area_m2': m2, 'edging_length_m': height / 1000,
                     'material': board_name, 'notes': 'Front edge edging'}
            components['carcass'].append(panel)
            panels_flat.append(panel)
        cutting_list['GABLE'].append(self._build_cutting_section(
            'Gable Right', height, width, 1, board_name, edging_name,
            'Front edge edging', ln['GABLE']
        ))
        ln['GABLE'] += 1
        cutting_list['GABLE'].append(self._build_cutting_section(
            'Gable Left', height, width, 1, board_name, edging_name,
            'Front edge edging', ln['GABLE']
        ))
        ln['GABLE'] += 1

        # Base — K Carc: L=Width-36, W=Depth-70 (same deductions as base unit)
        p, m2 = _panel_price(internal_width, internal_depth, internal_width, 1, bc, ec)
        wood += p
        panel = {'name': 'Base', 'panel_l': int(internal_width), 'panel_w': int(internal_depth),
                 'thickness': 18, 'quantity': 1, 'area_m2': m2,
                 'edging_length_m': internal_width / 1000, 'material': board_name, 'notes': 'BASE'}
        components['carcass'].append(panel); panels_flat.append(panel)
        cutting_list['T/B & FIX SHELVES'].append(self._build_cutting_section(
            'Base', internal_width, internal_depth, 1, board_name, edging_name, 'BASE', ln['T/B & FIX SHELVES']
        ))
        ln['T/B & FIX SHELVES'] += 1

        # Top Rail
        p, m2 = _panel_price(internal_width, 100, internal_width, 1, bc, ec)
        wood += p
        panel = {'name': 'Top Rail', 'panel_l': int(internal_width), 'panel_w': 100,
                 'thickness': 18, 'quantity': 1, 'area_m2': m2,
                 'edging_length_m': internal_width / 1000, 'material': board_name, 'notes': 'TOP RAIL'}
        components['carcass'].append(panel); panels_flat.append(panel)
        cutting_list['T/B & FIX SHELVES'].append(self._build_cutting_section(
            'Top Rail', internal_width, 100, 1, board_name, edging_name, 'TOP RAIL', ln['T/B & FIX SHELVES']
        ))
        ln['T/B & FIX SHELVES'] += 1

        # Back — 6mm MDF
        back_p, back_m2 = _panel_price(height, internal_width, 0, 1, bc_back, 0)
        wood += back_p
        back_panel = {'name': 'Back', 'panel_l': int(height), 'panel_w': int(internal_width),
                      'thickness': 6, 'quantity': 1, 'area_m2': back_m2,
                      'edging_length_m': 0, 'material': BACK_6MM_BOARD, 'notes': 'No edging'}
        components['backs'].append(back_panel); panels_flat.append(back_panel)
        cutting_list['BACKS'].append(self._build_cutting_section(
            'Back', height, internal_width, 1, BACK_6MM_BOARD, '',
            '6MM BACK — no edging', ln['BACKS'], thickness=6
        ))
        ln['BACKS'] += 1

        # Shelves (default 6)
        sp, sm2 = _panel_price(internal_width, internal_depth, internal_width, shelf_count, bc, ec)
        wood += sp
        shelf_panel = {'name': f'Shelf (×{shelf_count})',
                       'panel_l': int(internal_width), 'panel_w': int(internal_depth),
                       'thickness': 18, 'quantity': shelf_count, 'area_m2': sm2,
                       'edging_length_m': (internal_width / 1000) * shelf_count,
                       'material': board_name, 'notes': 'Front edge edging'}
        components['shelves'].append(shelf_panel); panels_flat.append(shelf_panel)
        cutting_list['S/H'].append(self._build_cutting_section(
            f'Shelves ×{shelf_count}', internal_width, internal_depth,
            shelf_count, board_name, edging_name,
            f'ADJ SHELVES × {shelf_count}', ln['S/H']
        ))
        ln['S/H'] += 1

        # Hardware — use passed accessories or larder defaults
        if accessories:
            for acc in accessories:
                unit = (ACCESSORY_RESALE.get(acc['name'])
                        or HINGE_RESALE.get(acc['name'])
                        or HANDLE_RESALE.get(acc['name']) or 0)
                components['hardware'].append({
                    'name': acc['name'], 'quantity': int(acc.get('qty', 0)),
                    'unit_price': unit,
                    'total': _roundup(unit * int(acc.get('qty', 0)), 2),
                    'notes': acc.get('type', 'accessory'),
                })
        else:
            components['hardware'].extend([
                {'name': 'Legs 150',          'quantity': 1,
                 'unit_price': 5.0,  'total': 5.0,  'notes': 'Set of 4 legs'},
                {'name': 'Shelf Pegs Plastic', 'quantity': shelf_count * 4,
                 'unit_price': 0.12, 'total': _roundup(0.12 * shelf_count * 4, 2),
                 'notes': '4 pegs per shelf'},
                {'name': 'Overlay Splung',     'quantity': 2,
                 'unit_price': 5.0,  'total': 10.0, 'notes': 'Hinges'},
            ])

        hw_cost    = self._hardware_cost(components['hardware'])
        total_cost = round(wood + hw_cost, 2)
        sell, mult = _resale(total_cost, pricing_tier)
        mat_summary = self._material_summary(cutting_list, panels_flat)

        return {
            'cabinet_type': 'Kitchen Larder / Tall Unit',
            'dimensions':   {'height': height, 'width': width, 'depth': depth},
            'internal_dimensions': {'width': int(internal_width), 'depth_shelf': int(internal_depth)},
            'components':             components,
            'cutting_list':           cutting_list,
            'cutting_list_formatted': self._format_cutting_list(cutting_list),
            'material_summary':       mat_summary,
            'pricing': {
                'board_name': board_name, 'board_cost_m2': bc,
                'edging_name': edging_name, 'edging_cost_m': ec,
                'pricing_tier': pricing_tier, 'multiplier': mult,
                'material_cost': wood, 'hardware_cost': hw_cost,
                'total_cost_price': total_cost, 'resale_price': sell,
            },
            'summary': {
                'total_panels': self._count_panels(components),
                'total_area_m2': self._total_area(components),
                'door_count': 2, 'shelf_count': shelf_count,
            }
        }

    # ------------------------------------------------------------------
    # BEDROOM CARCASS  (B Carc sheet — exact formulas)
    # ------------------------------------------------------------------

    def calculate_bedroom_carcass(self, height, width, depth=None,
                                   back_type='full',
                                   service_gap=0,
                                   board_name='Egger         MFC G 4-5',
                                   edging_name='Egger White MFC G8',
                                   shelf_count=1,
                                   accessories=None,
                                   pricing_tier='Retail 3.5'):
        """
        B Carc Full Back (service_gap default=0):
            Gable:    H × D
            Top/Base/Shelf: (W-36) × (D-18-service_gap)
            Back:     H × (W-36)   no edging

        B Carc 8mm Back (service_gap default=18):
            Gable:    H × D
            Top/Base/Shelf: (W-36) × (D-12-service_gap)
            8mm Back: H × (W-20)   NOT W-36
            Shelf qty = 2 (Excel J35=2)

        Hanging rail cut length = internal_width - 7mm (from transcript)
        """
        if depth is None:
            depth = 600

        if board_name not in BOARD_COSTS:
            raise ValueError(f"Unknown board '{board_name}'")
        if edging_name not in EDGING_COSTS:
            raise ValueError(f"Unknown edging '{edging_name}'")

        bc = BOARD_COSTS[board_name]
        ec = EDGING_COSTS[edging_name]

        internal_width = width - 36

        components   = {'carcass': [], 'backs': [], 'shelves': [],
                        'doors': [], 'drawers': [], 'hardware': []}
        cutting_list = {k: [] for k in ['GABLE', 'S/H', 'T/B & FIX SHELVES', 'BACKS',
                                         'END PANELS & INFILLS', 'BRACES',
                                         'DOORS & DRAW FACES', 'DRAWS']}
        panels_flat  = []
        ln = {k: 1 for k in cutting_list}
        wood = 0

        if back_type == 'full':
            # ── Full Back ─────────────────────────────────────────
            # D10: =E5-18-E3  (Depth - 18 - service_gap)
            top_w    = depth - 18 - service_gap
            back_w   = internal_width
            back_thickness = 18
            shelf_qty = shelf_count
        else:
            # ── 8mm Back ──────────────────────────────────────────
            # D33: =E28-12-E26  (Depth - 12 - service_gap)
            # D36: =D28-20      (Width - 20, NOT Width-36)
            top_w    = depth - 12 - service_gap
            back_w   = width - 20
            back_thickness = 8
            shelf_qty = max(shelf_count, 2)  # Excel J35=2

        top_l = internal_width  # Width - 36

        # Gables
        for side in ['left', 'right']:
            p, m2 = _panel_price(height, depth, height, 1, bc, ec)
            wood += p
            panel = {'name': f'Gable {side}', 'panel_l': int(height), 'panel_w': int(depth),
                     'thickness': 18, 'quantity': 1, 'area_m2': m2,
                     'edging_length_m': height / 1000, 'material': board_name,
                     'notes': 'Front edge edging'}
            components['carcass'].append(panel); panels_flat.append(panel)
        cutting_list['GABLE'].append(self._build_cutting_section(
            'Gable left', height, depth, 1, board_name, edging_name,
            'Front edge edging', ln['GABLE']
        ))
        ln['GABLE'] += 1
        cutting_list['GABLE'].append(self._build_cutting_section(
            'Gable right', height, depth, 1, board_name, edging_name,
            'Front edge edging', ln['GABLE']
        ))
        ln['GABLE'] += 1

        # Top
        p, m2 = _panel_price(top_l, top_w, top_l, 1, bc, ec)
        wood += p
        panel = {'name': 'Top', 'panel_l': int(top_l), 'panel_w': int(top_w),
                 'thickness': 18, 'quantity': 1, 'area_m2': m2,
                 'edging_length_m': top_l / 1000, 'material': board_name, 'notes': 'TOP'}
        components['carcass'].append(panel); panels_flat.append(panel)
        cutting_list['T/B & FIX SHELVES'].append(self._build_cutting_section(
            'Top', top_l, top_w, 1, board_name, edging_name, 'TOP', ln['T/B & FIX SHELVES']
        ))
        ln['T/B & FIX SHELVES'] += 1

        # Base
        p, m2 = _panel_price(top_l, top_w, top_l, 1, bc, ec)
        wood += p
        panel = {'name': 'Base', 'panel_l': int(top_l), 'panel_w': int(top_w),
                 'thickness': 18, 'quantity': 1, 'area_m2': m2,
                 'edging_length_m': top_l / 1000, 'material': board_name, 'notes': 'BASE'}
        components['carcass'].append(panel); panels_flat.append(panel)
        cutting_list['T/B & FIX SHELVES'].append(self._build_cutting_section(
            'Base', top_l, top_w, 1, board_name, edging_name, 'BASE', ln['T/B & FIX SHELVES']
        ))
        ln['T/B & FIX SHELVES'] += 1

        # Shelves
        if shelf_qty > 0:
            sp, sm2 = _panel_price(top_l, top_w, top_l, shelf_qty, bc, ec)
            wood += sp
            shelf_panel = {'name': f'Shelf (×{shelf_qty})',
                           'panel_l': int(top_l), 'panel_w': int(top_w),
                           'thickness': 18, 'quantity': shelf_qty, 'area_m2': sm2,
                           'edging_length_m': (top_l / 1000) * shelf_qty,
                           'material': board_name, 'notes': 'Front edge edging'}
            components['shelves'].append(shelf_panel); panels_flat.append(shelf_panel)
            cutting_list['S/H'].append(self._build_cutting_section(
                'Shelf', top_l, top_w, shelf_qty, board_name, edging_name,
                f'ADJ SHELF × {shelf_qty}', ln['S/H']
            ))
            ln['S/H'] += 1

        # Back — no edging (G13=0 / G36=0 in Excel)
        back_p, back_m2 = _panel_price(height, back_w, 0, 1, bc, 0)
        wood += back_p
        back_label = 'Back'
        back_notes = f'{"18mm" if back_type == "full" else "8mm"} back — no edging'
        back_panel = {'name': back_label, 'panel_l': int(height), 'panel_w': int(back_w),
                      'thickness': back_thickness, 'quantity': 1, 'area_m2': back_m2,
                      'edging_length_m': 0, 'material': board_name, 'notes': 'No edging'}
        components['backs'].append(back_panel); panels_flat.append(back_panel)
        cutting_list['BACKS'].append(self._build_cutting_section(
            back_label, height, back_w, 1, board_name, '',
            back_notes, ln['BACKS'], thickness=back_thickness
        ))
        ln['BACKS'] += 1

        # ── Accessories — generic list matching Excel row-based approach ──────
        # Each entry: {name: <exact Excel string>, qty: <int>}
        # Defaults match Excel B Carc defaults (full back: HR=2,SP=0,L100=1,SH=0,LED=0)
        #                                       (8mm back:  HR=2,SPM=1,L100=1,SH=0,LED=2)
        if accessories is None:
            if back_type == 'full':
                accessories = [
                    {'name': 'Hanging Rail',           'qty': 2},
                    {'name': 'Shelf Pegs Plastic',     'qty': 0},
                    {'name': 'Legs 100',               'qty': 1},
                    {'name': 'Shelf Holes Row Per Gable', 'qty': 0},
                    {'name': 'LED Groving Per Gable',  'qty': 0},
                ]
            else:
                accessories = [
                    {'name': 'Hanging Rail',                       'qty': 2},
                    {'name': 'Shelf Pegs Metal Hafele 282.24.710', 'qty': 1},
                    {'name': 'Legs 100',                           'qty': 1},
                    {'name': 'Shelf Holes Row Per Gable',          'qty': 0},
                    {'name': 'LED Groving Per Gable',              'qty': 2},
                ]

        # Hanging rail cut length = internal_width - 7mm (from transcript)
        hanging_rail_qty = next((a['qty'] for a in accessories
                                 if a['name'] == 'Hanging Rail'), 0)
        hanging_rail_cut = int(internal_width - 7) if hanging_rail_qty > 0 else None

        components['hardware'] = []
        for acc in accessories:
            name = acc['name']
            qty  = int(acc.get('qty', 0))
            unit = ACCESSORY_RESALE.get(name, 0)
            total = _roundup(unit * qty, 2)
            note = ''
            if name == 'Hanging Rail' and qty > 0:
                note = f'Cut length: {hanging_rail_cut}mm (internal {int(internal_width)}mm − 7mm)'
            components['hardware'].append({
                'name':       name,
                'quantity':   qty,
                'unit_price': unit,
                'total':      total,
                'notes':      note,
            })

        hw_cost    = self._hardware_cost(components['hardware'])
        total_cost = round(wood + hw_cost, 2)
        sell, mult = _resale(total_cost, pricing_tier)
        mat_summary = self._material_summary(cutting_list, panels_flat)

        return {
            'cabinet_type': f'Bedroom Carcass — {"Full 18mm" if back_type == "full" else "8mm"} Back',
            'dimensions':   {'height': height, 'width': width, 'depth': depth},
            'internal_dimensions': {
                'width':   int(internal_width),
                'top_l':   int(top_l),
                'top_w':   int(top_w),
                'back_w':  int(back_w),
            },
            'components':             components,
            'cutting_list':           cutting_list,
            'cutting_list_formatted': self._format_cutting_list(cutting_list),
            'material_summary':       mat_summary,
            'pricing': {
                'board_name':       board_name,
                'board_cost_m2':    bc,
                'edging_name':      edging_name,
                'edging_cost_m':    ec,
                'pricing_tier':     pricing_tier,
                'multiplier':       mult,
                'material_cost':    wood,
                'hardware_cost':    hw_cost,
                'total_cost_price': total_cost,
                'resale_price':     sell,
            },
            'summary': {
                'total_panels':            self._count_panels(components),
                'total_area_m2':           self._total_area(components),
                'shelf_count':             shelf_qty,
                'hanging_rails':           hanging_rail_qty,
                'hanging_rail_cut_length': hanging_rail_cut,
                'back_type':               back_type,
                'service_gap':             service_gap,
                'accessories':             accessories,
            }
        }

    # ------------------------------------------------------------------
    # STANDALONE DRAWER CALCULATOR
    # ------------------------------------------------------------------

    def calculate_drawers_only(self, internal_width, system_type,
                                drawer_count, cabinet_height=None,
                                face_height=None):
        return self.drawer_calc.calculate_drawer(
            internal_width, system_type, drawer_count,
            cabinet_height, face_height
        )


# ══════════════════════════════════════════════════════════════════════
# DOOR PRICE CALCULATOR  (B Carc — "Door Prices" section, rows 47-57)
# ══════════════════════════════════════════════════════════════════════

def calculate_door_price(
    height,
    width,
    depth=18,
    board_name='Egger         MFC G 4-5',
    edging_name='Egger    Perfect  Gloss',
    quantity=1,
    tier_name='Retail 5',
    include_edging_cost=False,
):
    """
    Standalone door price calculator — B Carc rows 47-57.

    Excel formulas:
        m2          = ROUNDUP((H * W) / 1_000_000, 2)
        panel_cost  = ROUNDUP(m2 * board_cost, 2)
        edging_l    = ((H*2) + (W*2)) / 1000  (in metres)
        edging_cost = edging_l * F98 = 0       (F98 is empty — deliberately no charge)
        item_cost   = panel_cost + 0
        total       = ROUNDUP(item_cost * quantity, 2)
        resale      = total * VLOOKUP(tier, Customer[], 2)  (default Retail 5 = ×5.0)

    Note: edging dropdown (B51) selects the finish description only.
    The edging cost is always £0 in this section — door edging is billed
    by the door supplier separately, not through the carcass calculator.
    """
    if board_name not in BOARD_COSTS:
        raise ValueError(f"Unknown board '{{board_name}}'")
    if edging_name not in EDGING_COSTS:
        raise ValueError(f"Unknown edging '{{edging_name}}'")
    if tier_name not in PRICING_TIERS:
        raise ValueError(f"Unknown tier '{{tier_name}}'")

    bc         = BOARD_COSTS[board_name]
    ec         = EDGING_COSTS[edging_name] if include_edging_cost else 0
    m2         = _roundup((height * width) / 1_000_000, 2)
    panel_cost = _roundup(m2 * bc, 2)
    edging_l   = round(((height * 2) + (width * 2)) / 1000, 3)
    # B Carc door: F98 is empty → edging_cost = 0
    # K Carc door: F98 = Saviola edging → edging_cost included
    edging_cost_val = _roundup(edging_l * ec, 2) if include_edging_cost else 0
    item_cost  = panel_cost + edging_cost_val
    total_cost = _roundup(item_cost * quantity, 2)
    multiplier = PRICING_TIERS[tier_name]
    resale     = round(total_cost * multiplier, 2)

    return {
        'type':              'door',
        'dimensions':        {'height': height, 'width': width, 'depth': depth},
        'board_name':        board_name,
        'board_cost_m2':     bc,
        'edging_name':       edging_name,
        'edging_length_m':   edging_l,
        'edging_cost':       edging_cost_val,
        'edging_note':       'Edging included in cost' if include_edging_cost else 'Door edging billed by supplier — £0 here per B Carc Excel',
        'area_m2':           m2,
        'panel_cost':        panel_cost,
        'item_cost':         item_cost,
        'quantity':          quantity,
        'total_cost_price':  total_cost,
        'tier_name':         tier_name,
        'multiplier':        multiplier,
        'resale_price':      resale,
        'cutting_list_row': {
            'name':              'Door',
            'dimension_display': f"{{int(height)}} × {{int(width)}} = {{quantity}}",
            'dimension_l':       int(height),
            'dimension_w':       int(width),
            'quantity':          quantity,
            'area_m2':           m2,
            'material':          board_name,
            'edging':            edging_name,
            'notes':             'All edges — edging cost via supplier',
        },
    }



# ══════════════════════════════════════════════════════════════════════
# KITCHEN BASE L CORNER  (K Carc — "Kitchen Base L Corner" rows 47-68)
# ══════════════════════════════════════════════════════════════════════

def calculate_l_corner_cabinet(
    height,
    l_width,  l_depth,
    r_width,  r_depth,
    board_name='Egger         MFC G 4-5',      # F$3 — base section board
    edging_name='Egger White MFC G3-7',         # F$28 — larder section edging
    tier_name='Retail 3',
    accessories=None,
):
    """
    Kitchen Base L Corner — K Carc rows 47-68.

    Two separate width+depth inputs (L side and R side):
        C49=Height, D49=L_Width, E49=L_Depth
        D51=R_Width, E51=R_Depth

    Panel formulas:
        Gable Left:  L=C49=Height,      W=E49=L_Depth
        Gable Right: L=C49=Height,      W=E51=R_Depth
        Base:        L=D49-88,          W=D51-88        (deduction = 88, not 36)
        Top:         L=D49-88,          W=D51-88
        Back Left:   L=C49=Height,      W=D49-88,   edging_l=0
        Back Right:  L=C49=Height,      W=D51-70,   edging_l=0
        Shelf:       L=D49-88,          W=D51-88

    Deduction of 88mm = two 36mm gables + 16mm joining strip.
    Default tier: Retail 3 (matching J68 in Excel).
    """
    if board_name not in BOARD_COSTS:
        raise ValueError(f"Unknown board '{board_name}'")
    if edging_name not in EDGING_COSTS:
        raise ValueError(f"Unknown edging '{edging_name}'")
    if tier_name not in PRICING_TIERS:
        raise ValueError(f"Unknown tier '{tier_name}'")

    bc      = BOARD_COSTS[board_name]
    ec      = EDGING_COSTS[edging_name]
    bc_back = BOARD_COSTS[BACK_6MM_BOARD]

    # Derived dimensions
    base_l  = l_width - 88   # D49-88
    base_w  = r_width - 88   # D51-88
    br_w    = r_width - 70   # D51-70 (back right)
    bl_w    = l_width - 88   # D49-88 (back left)

    panels_flat  = []
    components   = {'carcass': [], 'backs': [], 'shelves': [],
                    'doors': [], 'drawers': [], 'hardware': []}
    cutting_list = {k: [] for k in ['GABLE', 'S/H', 'T/B & FIX SHELVES', 'BACKS',
                                     'END PANELS & INFILLS', 'BRACES',
                                     'DOORS & DRAW FACES', 'DRAWS']}
    ln = {k: 1 for k in cutting_list}
    wood = 0

    def add_panel(section, name, pl, pw, el_mm, qty, use_back_board=False, thickness=18, notes=''):
        _bc = bc_back if use_back_board else bc
        _ec = ec
        price, m2 = _panel_price(pl, pw, el_mm, qty, _bc, _ec)
        entry = {
            'name': name, 'dimension_display': f"{int(pl)} × {int(pw)} = {qty}",
            'dimension_l': int(pl), 'dimension_w': int(pw),
            'thickness': thickness, 'quantity': qty, 'area_m2': round(m2, 3),
            'edging_m': round((el_mm / 1000) * qty, 3) if el_mm else 0,
            'price': price, 'notes': notes,
            'material_code': BACK_6MM_BOARD if use_back_board else board_name,
            'edging_code': '' if use_back_board else edging_name,
        }
        panels_flat.append({**entry, 'material': entry['material_code'],
                             'edging_length_m': entry['edging_m']})
        cutting_list[section].append({**entry, 'line_number': ln[section]})
        ln[section] += 1
        return price

    # Gable Left: H × L_Depth
    wood += add_panel('GABLE', 'Gable Left',  height, l_depth, height, 1, notes='Front edge edging')
    # Gable Right: H × R_Depth
    wood += add_panel('GABLE', 'Gable Right', height, r_depth, height, 1, notes='Front edge edging')
    # Base: (L_Width-88) × (R_Width-88)
    wood += add_panel('T/B & FIX SHELVES', 'Base', base_l, base_w, base_l, 1, notes='BASE')
    # Top: same as base
    wood += add_panel('T/B & FIX SHELVES', 'Top', base_l, base_w, base_l, 1, notes='TOP')
    # Back Left: H × (L_Width-88), no edging
    wood += add_panel('BACKS', 'Back Left',  height, bl_w, 0, 1, notes='BACK LEFT — no edging')
    # Back Right: H × (R_Width-70), no edging
    wood += add_panel('BACKS', 'Back Right', height, br_w, 0, 1, notes='BACK RIGHT — no edging')
    # Shelf: (L_Width-88) × (R_Width-88)
    wood += add_panel('S/H', 'Shelf', base_l, base_w, base_l, 1, notes='ADJ SHELF')

    # Accessories
    if accessories is None:
        accessories = [
            {'name': 'Legs 150',          'qty': 1},
            {'name': 'Shelf Pegs Plastic', 'qty': 0},
        ]

    hw_items = []
    for acc in accessories:
        name = acc['name']
        qty  = int(acc.get('qty', 0))
        unit = ACCESSORY_RESALE.get(name, 0)
        hw_items.append({
            'name': name, 'quantity': qty,
            'unit_price': unit,
            'total': _roundup(unit * qty, 2),
            'notes': '',
        })
    components['hardware'] = hw_items

    hw_cost    = sum(h['total'] for h in hw_items)
    total_cost = round(wood + hw_cost, 2)
    sell, mult = _resale(total_cost, tier_name)

    # Build component lists from panels_flat
    for p in panels_flat:
        if 'Gable' in p['name']:
            components['carcass'].append(p)
        elif 'Back' in p['name']:
            components['backs'].append(p)
        elif 'Shelf' in p['name']:
            components['shelves'].append(p)
        else:
            components['carcass'].append(p)

    sc = _sheet_counts(panels_flat)

    return {
        'cabinet_type': 'Kitchen Base L Corner',
        'dimensions': {
            'height': height,
            'l_width': l_width, 'l_depth': l_depth,
            'r_width': r_width, 'r_depth': r_depth,
        },
        'internal_dimensions': {
            'base_l': int(base_l), 'base_w': int(base_w),
            'back_left_w': int(bl_w), 'back_right_w': int(br_w),
        },
        'panels': panels_flat,
        'hardware': hw_items,
        'components': components,
        'cutting_list': cutting_list,
        'cutting_list_formatted': _format_cutting_list_standalone(cutting_list),
        'material_summary': {
            'material_breakdown': [
                {'material': board_name,
                 'pieces': sum(p['quantity'] for p in panels_flat),
                 'area_m2': sum(p['area_m2'] * p['quantity'] for p in panels_flat)}
            ],
            **sc,
        },
        'pricing': {
            'board_name': board_name, 'board_cost_m2': bc,
            'edging_name': edging_name, 'edging_cost_m': ec,
            'tier_name': tier_name, 'multiplier': mult,
            'wood_cost': round(wood, 2), 'accessory_cost': round(hw_cost, 2),
            'total_cost_price': total_cost, 'resale_price': sell,
        },
        'summary': {
            'total_panels': sum(p['quantity'] for p in panels_flat),
            'total_area_m2': round(sum(p['area_m2'] * p['quantity'] for p in panels_flat), 3),
        },
    }


def _format_cutting_list_standalone(cutting_list):
    order = ['GABLE', 'T/B & FIX SHELVES', 'S/H', 'BACKS',
             'END PANELS & INFILLS', 'BRACES', 'DOORS & DRAW FACES', 'DRAWS']
    return [{'category': c, 'items': cutting_list[c]} for c in order if cutting_list.get(c)]



# Singleton
calculator = CabinetCalculator()

VALID_CABINET_TYPES = {
    'base':     calculator.calculate_base_cabinet,
    'wall':     calculator.calculate_wall_cabinet,
    'larder':   calculator.calculate_larder_cabinet,
    'bedroom':  calculator.calculate_bedroom_carcass,
    'l_corner': None,  # handled separately — has different input shape
}


# ══════════════════════════════════════════════════════════════════════
# API ROUTES
# ══════════════════════════════════════════════════════════════════════

@manual_cabinet_bp.route('/api/manual-cabinet/calculate', methods=['POST', 'OPTIONS'])
@token_required
def calculate_cabinet():
    """
    POST body:
    {
        "cabinet_type":    "base" | "wall" | "larder" | "bedroom",
        "height":          2300,
        "width":           525,
        "depth":           600,
        "board_name":      "Egger         MFC G 4-5",   // exact Excel string
        "edging_name":     "Egger White MFC G8",         // exact Excel string
        "pricing_tier":    "Retail 3.5",                 // exact Excel string
        "project_name":    "Master Bedroom",
        "save":            false,

        // Base / Wall only
        "adjustable_shelves": 1,
        "drawer_system":   "hettich" | "ball_bearing" | ...,
        "drawer_count":    2,

        // Larder only
        "shelf_count": 6,

        // Bedroom only
        "back_type":           "full" | "8mm",
        "service_gap":         0,        // 0, 12, or 22
        "hanging_rails":       2,
        "shelf_pegs_type":     "Shelf Pegs Plastic",
        "qty_shelf_pegs":      0,
        "qty_legs":            1,
        "shelf_count":         1,
        "include_shelf_holes":  false,
        "include_led_grooving": false
    }
    """
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    session = SessionLocal()

    try:
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "error": "No data provided"}), 400

        cabinet_type = data.get('cabinet_type', 'base').lower()
        if cabinet_type not in VALID_CABINET_TYPES:
            return jsonify({
                "success": False,
                "error": f"Unknown cabinet type '{cabinet_type}'. Valid: {list(VALID_CABINET_TYPES.keys())}"
            }), 400

        height = data.get('height')
        width  = data.get('width')
        if not height or not width:
            return jsonify({"success": False, "error": "height and width are required"}), 400

        try:
            height = float(height)
            width  = float(width)
            depth  = float(data['depth']) if data.get('depth') else None
        except (ValueError, TypeError):
            return jsonify({"success": False, "error": "Dimensions must be numbers"}), 400

        # Shared params — accept exact Excel strings
        board_name   = data.get('board_name',   'Egger         MFC G 4-5').strip()
        edging_name  = data.get('edging_name',  'Egger White MFC G8').strip()
        pricing_tier = data.get('pricing_tier', 'Retail 3.5').strip()

        # Build a stripped-key lookup so frontend whitespace variants still resolve
        board_lookup  = {k.strip(): k for k in BOARD_COSTS}
        edging_lookup = {k.strip(): k for k in EDGING_COSTS}
        tier_lookup   = {k.strip(): k for k in PRICING_TIERS}

        board_name   = board_lookup.get(board_name, board_name)
        edging_name  = edging_lookup.get(edging_name, edging_name)
        pricing_tier = tier_lookup.get(pricing_tier, pricing_tier)
        project_name = data.get('project_name', f'{cabinet_type.title()} {width}mm')
        should_save  = data.get('save', False)

        # Validate all lookups upfront
        if board_name not in BOARD_COSTS:
            return jsonify({"success": False,
                            "error": f"Unknown board_name '{board_name}'. "
                                     f"Use /api/manual-cabinet/reference to see valid values."}), 400
        if edging_name not in EDGING_COSTS:
            return jsonify({"success": False,
                            "error": f"Unknown edging_name '{edging_name}'."}), 400
        if pricing_tier not in PRICING_TIERS:
            return jsonify({"success": False,
                            "error": f"Unknown pricing_tier '{pricing_tier}'. "
                                     f"Valid: {list(PRICING_TIERS.keys())}"}), 400

        kwargs = dict(height=height, width=width,
                      board_name=board_name, edging_name=edging_name,
                      pricing_tier=pricing_tier)
        if depth is not None:
            kwargs['depth'] = depth

        if cabinet_type in ('base', 'wall'):
            kwargs['adjustable_shelves'] = int(data.get('adjustable_shelves', 1))
            if cabinet_type == 'base' and data.get('drawer_system'):
                kwargs['drawer_system'] = data['drawer_system']
                kwargs['drawer_count']  = int(data.get('drawer_count', 1))

        if cabinet_type == 'larder':
            kwargs['shelf_count'] = int(data.get('shelf_count', 6))

        # Kitchen accessories — passed as list of {name, qty, type}
        # type: 'accessory' | 'hinge' | 'handle'
        if cabinet_type in ('base', 'wall', 'larder') and data.get('accessories'):
            kwargs['accessories'] = data['accessories']

        if cabinet_type == 'bedroom':
            kwargs['back_type']   = data.get('back_type', 'full')
            kwargs['service_gap'] = int(data.get('service_gap', 0))
            kwargs['shelf_count'] = int(data.get('shelf_count', 1))
            if data.get('accessories'):
                raw_accs = data['accessories']
                validated = []
                for acc in raw_accs:
                    name = str(acc.get('name', '')).strip()
                    qty  = int(acc.get('qty', 0))
                    if name not in ACCESSORY_RESALE:
                        return jsonify({"success": False,
                                        "error": f"Unknown accessory '{name}'. "
                                                 f"Use /api/manual-cabinet/reference to see valid names."}), 400
                    validated.append({'name': name, 'qty': qty})
                kwargs['accessories'] = validated

        # L Corner has a different input shape — handle separately
        if cabinet_type == 'l_corner':
            try:
                l_width = float(data.get('l_width', data.get('width', 0)))
                r_width = float(data.get('r_width', data.get('width', 0)))
                l_depth = float(data.get('l_depth', data.get('depth', 600)))
                r_depth = float(data.get('r_depth', data.get('depth', 600)))
            except (TypeError, ValueError):
                return jsonify({"success": False,
                                "error": "l_corner requires l_width, r_width, l_depth, r_depth"}), 400
            accs = data.get('accessories', None)
            result = calculate_l_corner_cabinet(
                height=height,
                l_width=l_width, l_depth=l_depth,
                r_width=r_width, r_depth=r_depth,
                board_name=board_name, edging_name=edging_name,
                tier_name=pricing_tier, accessories=accs,
            )
        else:
            result = VALID_CABINET_TYPES[cabinet_type](**kwargs)

        saved_id = None
        if should_save:
            tenant_id = get_current_tenant_id()
            insert_query = text("""
                INSERT INTO "StreemLyne_MT"."Drawing_Cutting_List" (
                    tenant_id, project_name, cabinet_type,
                    height, width, depth,
                    quantity, area_m2,
                    material_code, edging_code,
                    cost_price, resale_price, pricing_tier,
                    notes, created_at
                ) VALUES (
                    :tid, :proj, :ctype,
                    :h, :w, :d,
                    :qty, :area,
                    :board, :edging,
                    :cost, :resale, :tier,
                    :notes, :now
                ) RETURNING id
            """)
            row = session.execute(insert_query, {
                'tid':   tenant_id,
                'proj':  project_name,
                'ctype': cabinet_type,
                'h':     height,
                'w':     width,
                'd':     result['dimensions']['depth'],
                'qty':   result['summary']['total_panels'],
                'area':  result['summary']['total_area_m2'],
                'board': board_name,
                'edging': edging_name,
                'cost':  result['pricing']['total_cost_price'],
                'resale': result['pricing']['resale_price'],
                'tier':  pricing_tier,
                'notes': json.dumps(result['summary']),
                'now':   datetime.utcnow(),
            })
            saved_id = row.fetchone()[0]
            session.commit()
            logger.info(f"Saved cabinet calculation ID: {saved_id}")

        return jsonify({
            "success": True,
            "result":  result,
            "cutting_list_formatted": result['cutting_list_formatted'],
            "material_summary":       result['material_summary'],
            "pricing":                result['pricing'],
            "saved_id":               saved_id,
            "message": f"Successfully calculated {result['cabinet_type']}"
        }), 200

    except ValueError as ve:
        return jsonify({"success": False, "error": str(ve)}), 400
    except Exception as e:
        session.rollback()
        logger.error(f"Cabinet calculation failed: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        session.close()


@manual_cabinet_bp.route('/api/manual-cabinet/drawers', methods=['POST', 'OPTIONS'])
@token_required
def calculate_drawers():
    """
    Standalone drawer calculator.
    {
        "internal_width": 564,
        "system_type":    "hettich" | "ball_bearing" | "blum_bottom_fix" | ...,
        "drawer_count":   2,
        "cabinet_height": 720,
        "face_height":    283
    }
    """
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    try:
        data = request.get_json() or {}
        result = calculator.calculate_drawers_only(
            float(data['internal_width']),
            data['system_type'],
            int(data.get('drawer_count', 1)),
            float(data['cabinet_height']) if data.get('cabinet_height') else None,
            float(data['face_height'])    if data.get('face_height')    else None,
        )
        return jsonify({"success": True, "drawer": result}), 200
    except (KeyError, ValueError) as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500




@manual_cabinet_bp.route('/api/manual-cabinet/door-price', methods=['POST', 'OPTIONS'])
@token_required
def calculate_door_price_endpoint():
    """
    Standalone door price calculator — mirrors B Carc "Door Prices" section.

    POST body:
    {
        "height":      2600,
        "width":       550,
        "quantity":    1,
        "board_name":  "Egger         MFC G 4-5",      // optional, exact Excel string
        "edging_name": "Egger    Perfect  Gloss",       // optional — sets finish label only
        "tier_name":   "Retail 5"                       // optional, default Retail 5
    }

    Note: edging cost is always £0 per Excel (F98 is empty in B Carc).
    Door edging is billed by the door supplier separately.
    """
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    try:
        data = request.get_json() or {}

        height   = float(data.get('height', 0))
        width    = float(data.get('width', 0))
        depth    = float(data.get('depth', 18))
        quantity = int(data.get('quantity', 1))

        if not height or not width:
            return jsonify({"success": False, "error": "height and width are required"}), 400

        # Strip + resolve board/edging names (tolerant of whitespace variants)
        board_name  = data.get('board_name',  'Egger         MFC G 4-5').strip()
        edging_name = data.get('edging_name', 'Egger    Perfect  Gloss').strip()
        tier_name   = data.get('tier_name',   'Retail 5').strip()

        board_lookup  = {k.strip(): k for k in BOARD_COSTS}
        edging_lookup = {k.strip(): k for k in EDGING_COSTS}
        tier_lookup   = {k.strip(): k for k in PRICING_TIERS}

        board_name  = board_lookup.get(board_name,  board_name)
        edging_name = edging_lookup.get(edging_name, edging_name)
        tier_name   = tier_lookup.get(tier_name,   tier_name)

        if board_name not in BOARD_COSTS:
            return jsonify({"success": False,
                            "error": f"Unknown board_name '{board_name}'"}), 400
        if edging_name not in EDGING_COSTS:
            return jsonify({"success": False,
                            "error": f"Unknown edging_name '{edging_name}'"}), 400
        if tier_name not in PRICING_TIERS:
            return jsonify({"success": False,
                            "error": f"Unknown tier_name '{tier_name}'. "
                                     f"Valid: {list(PRICING_TIERS.keys())}"}), 400

        include_edging = bool(data.get('include_edging_cost', False))
        result = calculate_door_price(
            height=height, width=width, depth=depth,
            board_name=board_name, edging_name=edging_name,
            quantity=quantity, tier_name=tier_name,
            include_edging_cost=include_edging,
        )

        return jsonify({"success": True, "result": result}), 200

    except ValueError as ve:
        return jsonify({"success": False, "error": str(ve)}), 400
    except Exception as e:
        logger.error(f"Door price calculation failed: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500



@manual_cabinet_bp.route('/api/manual-cabinet/export-cutting-list-b64', methods=['POST', 'OPTIONS'])
@token_required
def export_cutting_list_b64():
    """
    Same as export-cutting-list but returns base64-encoded xlsx.
    Use this when the frontend api utility can't handle binary streams.
    Frontend decodes and triggers download client-side.
    """
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    try:
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "error": "No data provided"}), 400

        import base64
        xlsx_bytes = generate_cutting_list_xlsx(data)
        b64 = base64.b64encode(xlsx_bytes).decode('utf-8')
        project = data.get("project_name") or data.get("customer_name") or "cutting_list"
        return jsonify({
            "success":  True,
            "filename": f"{project.replace(' ','_')}_cutting_list.xlsx",
            "data":     b64,
            "mimetype": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        })
    except Exception as e:
        logger.error(f"Export b64 failed: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500



@manual_cabinet_bp.route('/api/manual-cabinet/cutting-list-preview', methods=['POST', 'OPTIONS'])
@token_required
def cutting_list_preview():
    """
    Returns HTML string of the cutting list preview page with data injected.
    Frontend opens this as a blob URL in a new tab.
    User can edit all fields and print to PDF.
    """
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    try:
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "error": "No data provided"}), 400

        # Load the preview HTML template
        import os
        template_path = os.path.join(
            os.path.dirname(__file__), 'cutting_list_preview.html'
        )
        with open(template_path, 'r', encoding='utf-8') as f:
            html = f.read()

        # Inject the data as a JS variable before </script> closing tag
        data_json = json.dumps(data, ensure_ascii=False)
        inject = f"""<script>
  window.__CUTTING_DATA__ = {data_json};
</script>
"""
        # Insert just before </head>
        html = html.replace('</head>', inject + '</head>', 1)

        return jsonify({"success": True, "html": html})

    except Exception as e:
        logger.error(f"Preview failed: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500



# ══════════════════════════════════════════════════════════════════════════════
# COMBINED KITCHEN CALCULATOR
# Accepts multiple units (base/wall/larder/l_corner), merges all panels into
# one cutting list grouped by section, one cost summary for the whole kitchen.
# ══════════════════════════════════════════════════════════════════════════════

@manual_cabinet_bp.route('/api/manual-cabinet/calculate-kitchen', methods=['POST', 'OPTIONS'])
@token_required
def calculate_kitchen():
    """
    POST body:
    {
        "project_name":  str,
        "board_name":    str,
        "edging_name":   str,
        "pricing_tier":  str,
        "units": [
            {
                "type":             "base" | "wall" | "larder" | "l_corner",
                "label":            str,          // user-given name e.g. "Boiler Room"
                "height":           number,
                "width":            number,
                // l_corner only:
                "l_width":          number,
                "r_width":          number,
                "l_depth":          number,
                "r_depth":          number,
                // optional overrides:
                "adjustable_shelves": number,
                "shelf_count":       number,
                "drawer_system":     str,
                "drawer_count":      number,
                "accessories":       [{name, qty}]
            }
        ],
        "save": bool
    }

    Returns:
    {
        "success": true,
        "result": {
            "project_name":        str,
            "unit_count":          int,
            "unit_summaries":      [{label, type, width, height, cost_price, resale_price}],
            "cutting_list_formatted": [...merged sections...],
            "material_summary":    {...},
            "pricing": {
                "total_cost_price": float,
                "total_resale_price": float,
                "board_name": str,
                "board_cost_m2": float,
                "edging_name": str,
                "edging_cost_m": float,
                "pricing_tier": str,
                "multiplier": float
            }
        }
    }
    """
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    try:
        data = request.get_json() or {}

        # ── Resolve board/edging/tier with strip-whitespace tolerance ──────────
        board_name   = data.get('board_name',   'Egger         MFC G 4-5').strip()
        edging_name  = data.get('edging_name',  'Egger White MFC G8').strip()
        pricing_tier = data.get('pricing_tier', 'Retail 3.5').strip()
        project_name = data.get('project_name', 'Kitchen')

        board_lookup  = {k.strip(): k for k in BOARD_COSTS}
        edging_lookup = {k.strip(): k for k in EDGING_COSTS}
        tier_lookup   = {k.strip(): k for k in PRICING_TIERS}
        board_name   = board_lookup.get(board_name,  board_name)
        edging_name  = edging_lookup.get(edging_name, edging_name)
        pricing_tier = tier_lookup.get(pricing_tier,  pricing_tier)

        if board_name   not in BOARD_COSTS:   return jsonify({"success": False, "error": f"Unknown board '{board_name}'"}), 400
        if edging_name  not in EDGING_COSTS:  return jsonify({"success": False, "error": f"Unknown edging '{edging_name}'"}), 400
        if pricing_tier not in PRICING_TIERS: return jsonify({"success": False, "error": f"Unknown tier '{pricing_tier}'"}), 400

        units = data.get('units', [])
        if not units:
            return jsonify({"success": False, "error": "At least one unit is required"}), 400

        # ── Section order for merged cutting list ──────────────────────────────
        SECTION_ORDER = ['GABLE', 'T/B & FIX SHELVES', 'S/H', 'BACKS',
                         'END PANELS & INFILLS', 'BRACES', 'DOORS & DRAW FACES', 'DRAWS']

        # Merged cutting list — global line numbers across all units
        merged_sections = {s: [] for s in SECTION_ORDER}
        global_line = 1

        unit_summaries  = []
        all_panels_flat = []
        total_cost      = 0.0
        multiplier      = PRICING_TIERS[pricing_tier]

        # ── Process each unit ──────────────────────────────────────────────────
        for i, unit in enumerate(units):
            unit_type  = unit.get('type', 'base')
            unit_label = unit.get('label') or f"Unit {i+1}"
            height     = float(unit.get('height', 720))
            width      = float(unit.get('width',  1200))

            # Build kwargs common to all kitchen types
            depth = float(unit.get('depth', 0)) or None  # None = use fixed default
            kwargs = dict(
                height       = height,
                width        = width,
                depth        = depth,
                board_name   = board_name,
                edging_name  = edging_name,
                pricing_tier = pricing_tier,
            )

            if unit.get('accessories'):
                kwargs['accessories'] = unit['accessories']

            # Call the right calculator
            if unit_type == 'base':
                kwargs['adjustable_shelves'] = int(unit.get('adjustable_shelves', 1))
                if unit.get('drawer_system'):
                    kwargs['drawer_system'] = unit['drawer_system']
                    kwargs['drawer_count']  = int(unit.get('drawer_count', 1))
                result = calculator.calculate_base_cabinet(**kwargs)

            elif unit_type == 'wall':
                kwargs['adjustable_shelves'] = int(unit.get('adjustable_shelves', 2))
                result = calculator.calculate_wall_cabinet(**kwargs)

            elif unit_type == 'larder':
                kwargs['shelf_count'] = int(unit.get('shelf_count', 6))
                result = calculator.calculate_larder_cabinet(**kwargs)

            elif unit_type == 'l_corner':
                result = calculate_l_corner_cabinet(
                    height     = height,
                    l_width    = float(unit.get('l_width', width)),
                    r_width    = float(unit.get('r_width', width)),
                    l_depth    = float(unit.get('l_depth', 570)),
                    r_depth    = float(unit.get('r_depth', 570)),
                    board_name = board_name,
                    edging_name= edging_name,
                    tier_name  = pricing_tier,
                    accessories= unit.get('accessories'),
                )
            else:
                return jsonify({"success": False, "error": f"Unknown unit type '{unit_type}'"}), 400

            unit_cost   = result['pricing']['total_cost_price']
            unit_resale = result['pricing']['resale_price']
            total_cost += unit_cost

            # ── Merge this unit's cutting list into global merged list ─────────
            # Re-number rows with global line numbers and tag with unit label
            unit_cl = result.get('cutting_list') or {}
            # Handle both dict-of-lists and formatted list
            if isinstance(unit_cl, dict):
                sections_dict = unit_cl
            else:
                sections_dict = {}
                for sec in (result.get('cutting_list_formatted') or []):
                    sections_dict[sec['category']] = sec['items']

            for section_name in SECTION_ORDER:
                items = sections_dict.get(section_name, [])
                for item in items:
                    row = dict(item)
                    row['line_number']  = global_line
                    row['unit_label']   = unit_label
                    row['unit_index']   = i + 1
                    merged_sections[section_name].append(row)
                    global_line += 1

            # Track panels for material summary
            all_panels_flat.extend(result.get('panels', []))

            unit_summaries.append({
                'index':        i + 1,
                'label':        unit_label,
                'type':         unit_type,
                'height':       int(height),
                'width':        int(width),
                'cost_price':   unit_cost,
                'resale_price': unit_resale,
                'door_count':   result.get('summary', {}).get('door_count', 0),
                'shelf_count':  result.get('summary', {}).get('shelf_count', 0),
            })

        # ── Build merged formatted cutting list ────────────────────────────────
        cutting_list_formatted = [
            {'category': cat, 'items': merged_sections[cat]}
            for cat in SECTION_ORDER
            if merged_sections[cat]
        ]

        # ── Material summary across all units ──────────────────────────────────
        sc = _sheet_counts(all_panels_flat)
        material_count = {}
        for panels in [merged_sections[s] for s in SECTION_ORDER]:
            for item in panels:
                code = item.get('material_code', item.get('material', ''))
                if code:
                    if code not in material_count:
                        material_count[code] = {'pieces': 0, 'area_m2': 0.0}
                    material_count[code]['pieces']  += item.get('quantity', 0)
                    material_count[code]['area_m2'] += _roundup(
                        (item.get('dimension_l', 0) * item.get('dimension_w', 0)) / 1_000_000, 2
                    ) * item.get('quantity', 0)

        material_breakdown = [
            {'material': k, 'pieces': v['pieces'], 'area_m2': round(v['area_m2'], 3)}
            for k, v in material_count.items()
        ]

        total_resale = round(total_cost * multiplier, 2)
        total_cost   = round(total_cost, 2)

        return jsonify({
            "success": True,
            "result": {
                "project_name":           project_name,
                "unit_count":             len(units),
                "unit_summaries":         unit_summaries,
                "cutting_list_formatted": cutting_list_formatted,
                "material_summary": {
                    "material_breakdown":    material_breakdown,
                    **sc,
                },
                "pricing": {
                    "board_name":        board_name,
                    "board_cost_m2":     BOARD_COSTS[board_name],
                    "edging_name":       edging_name,
                    "edging_cost_m":     EDGING_COSTS[edging_name],
                    "pricing_tier":      pricing_tier,
                    "multiplier":        multiplier,
                    "total_cost_price":  total_cost,
                    "total_resale_price":total_resale,
                    "unit_breakdown":    unit_summaries,
                },
            }
        })

    except Exception as e:
        logger.error(f"Kitchen calculation failed: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500

@manual_cabinet_bp.route('/api/manual-cabinet/reference', methods=['GET', 'OPTIONS'])
@token_required
def get_reference_data():
    """All valid dropdown values — exact Excel strings for frontend selects."""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    return jsonify({
        "success": True,
        "board_codes":    {k: f"£{v:.2f}/m²" for k, v in BOARD_COSTS.items()},
        "edging_codes":   {k: f"£{v:.4f}/m"  for k, v in EDGING_COSTS.items()},
        "pricing_tiers":  PRICING_TIERS,
        "drawer_systems": {k: v['name'] for k, v in DrawerCalculator.DRAWER_SYSTEMS.items()},
        "cabinet_types":  list(VALID_CABINET_TYPES.keys()),
        "l_corner_defaults": {
            "board_name":  'EGGER    White MFC G 2-3',
            "edging_name": 'Egger White MFC G9-10   luton 69',
            "tier_name":   'Retail 3',
            "deduction":   88,
            "note":        "L-corner: panel L = Width-88, panel W = Width-88",
        },
        "standard_face_heights": DrawerCalculator.STANDARD_FACE_HEIGHTS,
        "accessories":    {k: f"£{v:.3f}" for k, v in ACCESSORY_RESALE.items()},
        "hinges":         {k: f"£{v:.2f}" for k, v in HINGE_RESALE.items()},
        "handles":        {k: f"£{v:.2f}" for k, v in HANDLE_RESALE.items()},
        "service_gap_options": {
            '0':  'None (full back default)',
            '12': '12mm — off floor',
            '22': '22mm — on floor / skirting',
        },
        "door_defaults": {
            "board_name":  'Egger         MFC G 4-5',
            "edging_name": 'Egger    Perfect  Gloss',
            "tier_name":   'Retail 5',
            "note":        "Edging cost is £0 — door edging billed by supplier separately",
        },
    }), 200


@manual_cabinet_bp.route('/api/manual-cabinet/history', methods=['GET', 'OPTIONS'])
@token_required
def get_calculation_history():
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    session = SessionLocal()
    try:
        tenant_id = get_current_tenant_id()
        rows = session.execute(text("""
            SELECT id, project_name, cabinet_type,
                   height, width, depth,
                   area_m2, cost_price, resale_price, pricing_tier, created_at
            FROM "StreemLyne_MT"."Drawing_Cutting_List"
            WHERE tenant_id = :tenant_id
            ORDER BY created_at DESC
            LIMIT 50
        """), {'tenant_id': tenant_id}).fetchall()

        return jsonify({"success": True, "history": [{
            'id':            r.id,
            'project_name':  r.project_name,
            'cabinet_type':  r.cabinet_type,
            'height':        float(r.height),
            'width':         float(r.width),
            'depth':         float(r.depth),
            'total_area_m2': float(r.area_m2)      if r.area_m2      else None,
            'cost_price':    float(r.cost_price)   if r.cost_price   else None,
            'resale_price':  float(r.resale_price) if r.resale_price else None,
            'pricing_tier':  r.pricing_tier,
            'created_at':    r.created_at.isoformat(),
        } for r in rows]}), 200

    except Exception as e:
        logger.error(f"Error fetching history: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        session.close()


@manual_cabinet_bp.route('/api/manual-cabinet/<int:calculation_id>',
                          methods=['GET', 'DELETE', 'OPTIONS'])
@token_required
def manage_calculation(calculation_id):
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    session = SessionLocal()
    try:
        tenant_id = get_current_tenant_id()

        if request.method == 'GET':
            row = session.execute(text("""
                SELECT notes FROM "StreemLyne_MT"."Drawing_Cutting_List"
                WHERE id = :id AND tenant_id = :tenant_id
            """), {'id': calculation_id, 'tenant_id': tenant_id}).fetchone()
            if not row:
                return jsonify({"success": False, "error": "Not found"}), 404
            return jsonify({"success": True,
                            "calculation": json.loads(row.notes)}), 200

        elif request.method == 'DELETE':
            session.execute(text("""
                DELETE FROM "StreemLyne_MT"."Drawing_Cutting_List"
                WHERE id = :id AND tenant_id = :tenant_id
            """), {'id': calculation_id, 'tenant_id': tenant_id})
            session.commit()
            return jsonify({"success": True, "message": "Deleted"}), 200

    except Exception as e:
        session.rollback()
        logger.error(f"Error managing calculation: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        session.close()