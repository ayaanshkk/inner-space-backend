"""
Manual Cabinet Entry Routes - StreemLyne_MT schema
Allows users to manually input cabinet dimensions and auto-calculates all components
Similar to K Carc price generator workflow with DETAILED CUTTING LIST
"""
from flask import Blueprint, request, jsonify
from sqlalchemy import text
from datetime import datetime
import logging
from decimal import Decimal
import math

from ..db import SessionLocal
from .auth_helpers import token_required, get_current_tenant_id

logger = logging.getLogger('ManualCabinetRoutes')

manual_cabinet_bp = Blueprint('manual_cabinet', __name__)


# ==========================================
# CABINET CALCULATION ENGINE
# ==========================================

class CabinetCalculator:
    """
    Calculates all components for a cabinet based on H x W x D dimensions
    Formula-based approach matching K Carc price generator EXACTLY
    NOW WITH DETAILED CUTTING LIST like the paper format
    
    K Carc Formula Reference:
    - Input: Height (C3), Width (D3), Depth (E3)
    - Gables: Panel L = Height, Panel W = Depth
    - Base: Panel L = Width - 36mm, Panel W = Depth - 70mm
    - Top Rail: Panel L = Width - 36mm, Panel W = 100mm (fixed)
    - Back: Panel L = Height, Panel W = Width - 36mm
    - Shelf: Panel L = Width - 36mm, Panel W = Depth - 140mm
    """
    
    # Standard material thickness (18mm for carcass panels)
    CARCASS_THICKNESS = 18
    
    # Standard depths for different cabinet types
    STANDARD_BASE_DEPTH = 500  # K Carc uses 500mm as standard
    STANDARD_WALL_DEPTH = 320  # Standard wall cabinet depth
    
    def calculate_base_cabinet(self, height, width, depth=None):
        """
        Calculate all components for a base cabinet using K Carc formulas
        WITH DETAILED CUTTING LIST
        
        K Carc Formula Logic:
        - Gables: Height × Depth
        - Base: (Width - 36) × (Depth - 70)
        - Top Rail: (Width - 36) × 100
        - Back: Height × (Width - 36)
        - Shelf: (Width - 36) × (Depth - 140)
        
        Args:
            height: Cabinet height (mm) - C3 in K Carc
            width: Cabinet width (mm) - D3 in K Carc
            depth: Cabinet depth (mm) - E3 in K Carc (default 500mm)
            
        Returns:
            dict: All components with quantities, dimensions, AND detailed cutting list
        """
        if depth is None:
            depth = self.STANDARD_BASE_DEPTH  # 500mm like K Carc
            
        components = {
            'carcass': [],
            'backs': [],
            'shelves': [],
            'doors': [],
            'hardware': []
        }
        
        # DETAILED CUTTING LIST (like paper format)
        cutting_list = {
            'GABLE': [],
            'S/H': [],  # Shelves/Horizontals
            'BACKS': [],
            'END PANELS & INFILLS': [],
            'T/B & FIX SHELVES': [],  # Top/Bottom & Fixed Shelves
            'BRACES': [],
            'DOORS & DRAW FACES': [],
            'DRAWS': []
        }
        
        # Line number counter for cutting list
        line_num = {'GABLE': 1, 'S/H': 1, 'BACKS': 1, 'T/B & FIX SHELVES': 1, 
                   'DOORS & DRAW FACES': 1, 'DRAWS': 1}
        
        # ============================================
        # GABLES (2x) - Left and Right sides
        # ============================================
        gable_panel_l = height
        gable_panel_w = depth
        
        components['carcass'].append({
            'name': 'Gable - Right',
            'panel_l': gable_panel_l,
            'panel_w': gable_panel_w,
            'thickness': self.CARCASS_THICKNESS,
            'quantity': 1,
            'edging_length_m': gable_panel_l / 1000,
            'material': '18mm MFC',
            'notes': 'Front edge edging'
        })
        
        components['carcass'].append({
            'name': 'Gable - Left',
            'panel_l': gable_panel_l,
            'panel_w': gable_panel_w,
            'thickness': self.CARCASS_THICKNESS,
            'quantity': 1,
            'edging_length_m': gable_panel_l / 1000,
            'material': '18mm MFC',
            'notes': 'Front edge edging'
        })
        
        # Add to DETAILED cutting list
        cutting_list['GABLE'].append({
            'line_number': line_num['GABLE'],
            'dimension_display': f"{int(gable_panel_l)} × {int(gable_panel_w)} = 2",
            'dimension_l': int(gable_panel_l),
            'dimension_w': int(gable_panel_w),
            'quantity': 2,
            'material_code': 'WL',  # White Laminate
            'edging': 'E12',  # Edge code - 1 edge (front)
            'notes': 'W/LINE',
            'area_m2': self._calc_area_single(gable_panel_l, gable_panel_w, 2)
        })
        line_num['GABLE'] += 1
        
        # ============================================
        # BASE (1x)
        # ============================================
        base_panel_l = width - 36
        base_panel_w = depth - 70
        
        components['carcass'].append({
            'name': 'Base',
            'panel_l': base_panel_l,
            'panel_w': base_panel_w,
            'thickness': self.CARCASS_THICKNESS,
            'quantity': 1,
            'edging_length_m': base_panel_l / 1000,
            'material': '18mm MFC',
            'notes': 'Front edge edging'
        })
        
        cutting_list['T/B & FIX SHELVES'].append({
            'line_number': line_num['T/B & FIX SHELVES'],
            'dimension_display': f"{int(base_panel_l)} × {int(base_panel_w)} = 1",
            'dimension_l': int(base_panel_l),
            'dimension_w': int(base_panel_w),
            'quantity': 1,
            'material_code': 'WL',
            'edging': 'E12',
            'notes': 'BASE',
            'area_m2': self._calc_area_single(base_panel_l, base_panel_w, 1)
        })
        line_num['T/B & FIX SHELVES'] += 1
        
        # ============================================
        # TOP RAIL (1x)
        # ============================================
        top_rail_panel_l = width - 36
        top_rail_panel_w = 100
        
        components['carcass'].append({
            'name': 'Top Rail',
            'panel_l': top_rail_panel_l,
            'panel_w': top_rail_panel_w,
            'thickness': self.CARCASS_THICKNESS,
            'quantity': 1,
            'edging_length_m': top_rail_panel_l / 1000,
            'material': '18mm MFC',
            'notes': 'Front edge edging'
        })
        
        cutting_list['T/B & FIX SHELVES'].append({
            'line_number': line_num['T/B & FIX SHELVES'],
            'dimension_display': f"{int(top_rail_panel_l)} × {int(top_rail_panel_w)} = 1",
            'dimension_l': int(top_rail_panel_l),
            'dimension_w': int(top_rail_panel_w),
            'quantity': 1,
            'material_code': 'WL',
            'edging': 'E12',
            'notes': 'TOP RAIL',
            'area_m2': self._calc_area_single(top_rail_panel_l, top_rail_panel_w, 1)
        })
        line_num['T/B & FIX SHELVES'] += 1
        
        # ============================================
        # BACK PANEL (1x)
        # ============================================
        back_panel_l = height
        back_panel_w = width - 36
        
        components['backs'].append({
            'name': 'Back',
            'panel_l': back_panel_l,
            'panel_w': back_panel_w,
            'thickness': 6,
            'quantity': 1,
            'edging_length_m': 0,
            'material': '6mm MDF',
            'notes': 'No edging'
        })
        
        cutting_list['BACKS'].append({
            'line_number': line_num['BACKS'],
            'dimension_display': f"{int(back_panel_l)} × {int(back_panel_w)} = 1",
            'dimension_l': int(back_panel_l),
            'dimension_w': int(back_panel_w),
            'quantity': 1,
            'material_code': '',
            'edging': '',
            'notes': '6MM BACK',
            'area_m2': self._calc_area_single(back_panel_l, back_panel_w, 1)
        })
        line_num['BACKS'] += 1
        
        # ============================================
        # ADJUSTABLE SHELF (1x)
        # ============================================
        shelf_panel_l = width - 36
        shelf_panel_w = depth - 140
        
        components['shelves'].append({
            'name': 'Shelf',
            'panel_l': shelf_panel_l,
            'panel_w': shelf_panel_w,
            'thickness': self.CARCASS_THICKNESS,
            'quantity': 1,
            'edging_length_m': shelf_panel_l / 1000,
            'material': '18mm MFC',
            'notes': 'Front edge edging'
        })
        
        cutting_list['S/H'].append({
            'line_number': line_num['S/H'],
            'dimension_display': f"{int(shelf_panel_l)} × {int(shelf_panel_w)} = 1",
            'dimension_l': int(shelf_panel_l),
            'dimension_w': int(shelf_panel_w),
            'quantity': 1,
            'material_code': 'WL',
            'edging': 'E12',
            'notes': 'ADJ SHELF',
            'area_m2': self._calc_area_single(shelf_panel_l, shelf_panel_w, 1)
        })
        line_num['S/H'] += 1
        
        # ============================================
        # DOORS - Based on width
        # ============================================
        door_height = height - 6  # 3mm top/bottom gap
        
        if width < 600:
            # Single door
            door_width = width - 6
            components['doors'].append({
                'name': 'Door',
                'panel_l': door_height,
                'panel_w': door_width,
                'thickness': 18,
                'quantity': 1,
                'edging_length_m': ((door_height * 2) + (door_width * 2)) / 1000,
                'material': '18mm Door Panel',
                'notes': 'All edges edged'
            })
            
            cutting_list['DOORS & DRAW FACES'].append({
                'line_number': line_num['DOORS & DRAW FACES'],
                'dimension_display': f"{int(door_height)} × {int(door_width)} = 1",
                'dimension_l': int(door_height),
                'dimension_w': int(door_width),
                'quantity': 1,
                'material_code': 'DOOR',
                'edging': 'E33',  # All edges
                'notes': 'SINGLE DOOR',
                'area_m2': self._calc_area_single(door_height, door_width, 1)
            })
            
            components['hardware'].append({
                'name': 'Hinge - Overlay Sprung',
                'quantity': 2,
                'notes': '2 hinges for single door'
            })
        else:
            # Double doors
            door_width = (width / 2) - 4.5
            components['doors'].extend([{
                'name': 'Door - Left',
                'panel_l': door_height,
                'panel_w': door_width,
                'thickness': 18,
                'quantity': 1,
                'edging_length_m': ((door_height * 2) + (door_width * 2)) / 1000,
                'material': '18mm Door Panel',
                'notes': 'All edges edged'
            }, {
                'name': 'Door - Right',
                'panel_l': door_height,
                'panel_w': door_width,
                'thickness': 18,
                'quantity': 1,
                'edging_length_m': ((door_height * 2) + (door_width * 2)) / 1000,
                'material': '18mm Door Panel',
                'notes': 'All edges edged'
            }])
            
            cutting_list['DOORS & DRAW FACES'].append({
                'line_number': line_num['DOORS & DRAW FACES'],
                'dimension_display': f"{int(door_height)} × {int(door_width)} = 2",
                'dimension_l': int(door_height),
                'dimension_w': int(door_width),
                'quantity': 2,
                'material_code': 'DOOR',
                'edging': 'E33',
                'notes': 'DOUBLE DOORS',
                'area_m2': self._calc_area_single(door_height, door_width, 2)
            })
            
            components['hardware'].append({
                'name': 'Hinge - Overlay Sprung',
                'quantity': 4,
                'notes': '2 hinges per door'
            })
        
        # ============================================
        # HARDWARE
        # ============================================
        components['hardware'].extend([
            {
                'name': 'Legs 150',
                'quantity': 1,
                'notes': 'Set of 4 adjustable legs'
            },
            {
                'name': 'Shelf Pegs Plastic',
                'quantity': 8,
                'notes': '4 pegs per shelf position'
            }
        ])
        
        # Calculate material summary (like "4 Sheets" at bottom)
        material_summary = self._calculate_material_summary(cutting_list)
        
        # Calculate total area
        total_area = self._calculate_total_area_kcarc(components)
        
        return {
            'cabinet_type': 'Kitchen Base',
            'dimensions': {
                'height': height,
                'width': width,
                'depth': depth
            },
            'components': components,
            'cutting_list': cutting_list,  # NEW - Detailed cutting list
            'cutting_list_formatted': self._format_cutting_list_display(cutting_list),  # NEW - For display
            'material_summary': material_summary,  # NEW - Material totals
            'summary': {
                'total_panels': self._count_panels(components),
                'total_area_m2': round(total_area, 3),
                'door_count': 1 if width < 600 else 2
            }
        }
    
    def calculate_wall_cabinet(self, height, width, depth=None):
        """
        Calculate components for a wall cabinet (similar to base but shallower)
        Uses same formulas as base cabinet with different default depth
        """
        if depth is None:
            depth = self.STANDARD_WALL_DEPTH
        
        # Use base cabinet calculation with wall depth
        result = self.calculate_base_cabinet(height, width, depth)
        result['cabinet_type'] = 'Kitchen Wall Cabinet'
        
        # Replace legs with wall brackets in hardware
        for i, item in enumerate(result['components']['hardware']):
            if item['name'] == 'Legs 150':
                result['components']['hardware'][i] = {
                    'name': 'Wall Mounting Bracket',
                    'quantity': 2,
                    'notes': 'Heavy duty wall brackets'
                }
        
        return result
    
    def _calc_area_single(self, length, width, quantity):
        """Calculate area for a single component (K Carc formula)"""
        area_per_item = math.ceil(((length * width) / 1_000_000) * 100) / 100
        return round(area_per_item * quantity, 2)
    
    def _calculate_total_area_kcarc(self, components):
        """
        Calculate total area in m² using K Carc formula
        Formula: ROUNDUP((Panel_L * Panel_W)/(1000*1000), 2)
        """
        total_area = 0
        
        for category in ['carcass', 'backs', 'shelves', 'doors']:
            for item in components.get(category, []):
                panel_l = item.get('panel_l', 0)
                panel_w = item.get('panel_w', 0)
                quantity = item.get('quantity', 1)
                
                # K Carc formula: ROUNDUP((L * W)/(1000*1000), 2)
                area_per_item = math.ceil(((panel_l * panel_w) / 1_000_000) * 100) / 100
                total_area += area_per_item * quantity
        
        return total_area
    
    def _count_panels(self, components):
        """Count total number of panels/components"""
        count = 0
        for category in ['carcass', 'backs', 'shelves', 'doors']:
            for item in components.get(category, []):
                count += item.get('quantity', 1)
        return count
    
    def _calculate_material_summary(self, cutting_list):
        """
        Calculate material sheet requirements
        Similar to "4 Sheets" summary at bottom of cutting list
        Groups by material type and calculates total sheets needed
        """
        summary = {
            'sheets_18mm': {},  # e.g., {'WL': 3, 'OH': 1}
            'sheets_6mm': {},
            'total_edging_m': 0,
            'material_breakdown': []
        }
        
        # Count materials
        material_count = {}
        total_area_18mm = 0
        total_area_6mm = 0
        
        for category, items in cutting_list.items():
            for item in items:
                material = item.get('material_code', '')
                qty = item.get('quantity', 0)
                area = item.get('area_m2', 0)
                
                if material and material != '':
                    if material not in material_count:
                        material_count[material] = {'count': 0, 'area': 0}
                    material_count[material]['count'] += qty
                    material_count[material]['area'] += area
                    
                    # Track 18mm vs 6mm
                    if '6MM' in item.get('notes', ''):
                        total_area_6mm += area
                    else:
                        total_area_18mm += area
        
        # Convert to summary
        for material, data in material_count.items():
            summary['material_breakdown'].append({
                'material': material,
                'pieces': data['count'],
                'area_m2': round(data['area'], 2)
            })
        
        # Estimate sheet count (assuming 2.88 m² per sheet standard)
        SHEET_AREA = 2.88
        summary['estimated_sheets_18mm'] = math.ceil(total_area_18mm / SHEET_AREA)
        summary['estimated_sheets_6mm'] = math.ceil(total_area_6mm / SHEET_AREA)
        
        return summary
    
    def _format_cutting_list_display(self, cutting_list):
        """
        Format cutting list for display - matches paper cutting list format
        Returns structured data ready for table rendering
        """
        formatted = []
        
        # Order of sections (like on paper)
        section_order = ['GABLE', 'S/H', 'BACKS', 'T/B & FIX SHELVES', 
                        'END PANELS & INFILLS', 'BRACES', 
                        'DOORS & DRAW FACES', 'DRAWS']
        
        for category in section_order:
            items = cutting_list.get(category, [])
            if not items:
                continue
            
            section_data = {
                'category': category,
                'items': []
            }
            
            for item in items:
                section_data['items'].append({
                    'line_number': item['line_number'],
                    'dimension_display': item['dimension_display'],
                    'dimension_l': item['dimension_l'],
                    'dimension_w': item['dimension_w'],
                    'quantity': item['quantity'],
                    'material': item.get('material_code', ''),
                    'edging': item.get('edging', ''),
                    'notes': item.get('notes', ''),
                    'area_m2': item.get('area_m2', 0)
                })
            
            formatted.append(section_data)
        
        return formatted


# Initialize calculator
calculator = CabinetCalculator()


# ==========================================
# API ROUTES
# ==========================================

@manual_cabinet_bp.route('/api/manual-cabinet/calculate', methods=['POST', 'OPTIONS'])
@token_required
def calculate_cabinet():
    """
    Calculate cabinet components from manual dimensions (K Carc style)
    NOW RETURNS DETAILED CUTTING LIST
    
    Request body:
    {
        "cabinet_type": "base" | "wall",
        "height": 400,
        "width": 1200,
        "depth": 500 (optional, defaults: base=500mm, wall=320mm),
        "project_name": "Kitchen Project",
        "save": true (optional - save to database)
    }
    """
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    
    try:
        data = request.get_json()
        
        # Validate required fields
        if not data:
            return jsonify({"success": False, "error": "No data provided"}), 400
        
        cabinet_type = data.get('cabinet_type', 'base').lower()
        height = data.get('height')
        width = data.get('width')
        depth = data.get('depth')
        project_name = data.get('project_name', 'Unnamed Project')
        should_save = data.get('save', False)
        
        # Validate dimensions
        if not height or not width:
            return jsonify({
                "success": False,
                "error": "Height and width are required"
            }), 400
        
        try:
            height = float(height)
            width = float(width)
            if depth:
                depth = float(depth)
        except ValueError:
            return jsonify({
                "success": False,
                "error": "Invalid dimensions - must be numbers"
            }), 400
        
        # Calculate based on cabinet type
        if cabinet_type == 'base':
            result = calculator.calculate_base_cabinet(height, width, depth)
        elif cabinet_type == 'wall':
            result = calculator.calculate_wall_cabinet(height, width, depth)
        else:
            return jsonify({
                "success": False,
                "error": f"Unknown cabinet type: {cabinet_type}. Use 'base' or 'wall'"
            }), 400
        
        # Optionally save to database
        saved_id = None
        if should_save:
            tenant_id = get_current_tenant_id()
            
            # Save cabinet calculation
            insert_query = text("""
                INSERT INTO "StreemLyne_MT"."Manual_Cabinet_Calculations" (
                    tenant_id,
                    project_name,
                    cabinet_type,
                    height,
                    width,
                    depth,
                    total_panels,
                    total_area_m2,
                    calculation_data,
                    created_at
                ) VALUES (
                    :tenant_id,
                    :project_name,
                    :cabinet_type,
                    :height,
                    :width,
                    :depth,
                    :total_panels,
                    :total_area_m2,
                    :calculation_data,
                    :created_at
                )
                RETURNING id
            """)
            
            import json
            result_insert = session.execute(insert_query, {
                'tenant_id': tenant_id,
                'project_name': project_name,
                'cabinet_type': cabinet_type,
                'height': height,
                'width': width,
                'depth': result['dimensions']['depth'],
                'total_panels': result['summary']['total_panels'],
                'total_area_m2': result['summary']['total_area_m2'],
                'calculation_data': json.dumps(result),
                'created_at': datetime.utcnow()
            })
            
            saved_id = result_insert.fetchone()[0]
            session.commit()
            logger.info(f"Saved cabinet calculation ID: {saved_id}")
        
        return jsonify({
            "success": True,
            "result": result,
            "cutting_list_formatted": result['cutting_list_formatted'],  # NEW
            "material_summary": result['material_summary'],  # NEW
            "saved_id": saved_id,
            "message": f"Successfully calculated {result['cabinet_type']}"
        }), 200
        
    except Exception as e:
        session.rollback()
        logger.error(f"Cabinet calculation failed: {str(e)}", exc_info=True)
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500
    finally:
        session.close()


@manual_cabinet_bp.route('/api/manual-cabinet/history', methods=['GET', 'OPTIONS'])
@token_required
def get_calculation_history():
    """Get saved cabinet calculations"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    
    try:
        tenant_id = get_current_tenant_id()
        
        query = text("""
            SELECT 
                id,
                project_name,
                cabinet_type,
                height,
                width,
                depth,
                drawer_count,
                total_panels,
                total_area_m2,
                created_at
            FROM "StreemLyne_MT"."Manual_Cabinet_Calculations"
            WHERE tenant_id = :tenant_id
            ORDER BY created_at DESC
            LIMIT 50
        """)
        
        result = session.execute(query, {'tenant_id': tenant_id})
        calculations = result.fetchall()
        
        history = [{
            'id': calc.id,
            'project_name': calc.project_name,
            'cabinet_type': calc.cabinet_type,
            'height': float(calc.height),
            'width': float(calc.width),
            'depth': float(calc.depth),
            'drawer_count': calc.drawer_count,
            'total_panels': calc.total_panels,
            'total_area_m2': float(calc.total_area_m2),
            'created_at': calc.created_at.isoformat()
        } for calc in calculations]
        
        return jsonify({
            "success": True,
            "history": history
        }), 200
        
    except Exception as e:
        logger.error(f"Error fetching history: {e}", exc_info=True)
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500
    finally:
        session.close()


@manual_cabinet_bp.route('/api/manual-cabinet/<int:calculation_id>', methods=['GET', 'DELETE', 'OPTIONS'])
@token_required
def manage_calculation(calculation_id):
    """Get or delete a specific calculation"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    
    try:
        tenant_id = get_current_tenant_id()
        
        if request.method == 'GET':
            query = text("""
                SELECT calculation_data
                FROM "StreemLyne_MT"."Manual_Cabinet_Calculations"
                WHERE id = :id AND tenant_id = :tenant_id
            """)
            
            result = session.execute(query, {
                'id': calculation_id,
                'tenant_id': tenant_id
            })
            
            row = result.fetchone()
            
            if not row:
                return jsonify({
                    "success": False,
                    "error": "Calculation not found"
                }), 404
            
            import json
            calculation_data = json.loads(row.calculation_data)
            
            return jsonify({
                "success": True,
                "calculation": calculation_data
            }), 200
        
        elif request.method == 'DELETE':
            delete_query = text("""
                DELETE FROM "StreemLyne_MT"."Manual_Cabinet_Calculations"
                WHERE id = :id AND tenant_id = :tenant_id
            """)
            
            session.execute(delete_query, {
                'id': calculation_id,
                'tenant_id': tenant_id
            })
            session.commit()
            
            return jsonify({
                "success": True,
                "message": "Calculation deleted"
            }), 200
            
    except Exception as e:
        session.rollback()
        logger.error(f"Error managing calculation: {e}", exc_info=True)
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500
    finally:
        session.close()