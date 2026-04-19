"""
Manual Cabinet Entry Routes - StreemLyne_MT schema
Allows users to manually input cabinet dimensions and auto-calculates all components
Similar to K Carc price generator workflow
"""
from flask import Blueprint, request, jsonify
from sqlalchemy import text
from datetime import datetime
import logging
from decimal import Decimal

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
            dict: All components with quantities and dimensions
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
        
        # GABLES (2x) - Left and Right sides
        # K Carc Formula: Panel L = C3 (Height), Panel W = E3 (Depth)
        gable_panel_l = height
        gable_panel_w = depth
        
        components['carcass'].append({
            'name': 'Gable - Right',
            'panel_l': gable_panel_l,
            'panel_w': gable_panel_w,
            'thickness': self.CARCASS_THICKNESS,
            'quantity': 1,
            'edging_length_m': gable_panel_l / 1000,  # Panel L in meters
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
        
        # BASE (1x)
        # K Carc Formula: Panel L = D3-36 (Width - 36), Panel W = E3-70 (Depth - 70)
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
        
        # TOP RAIL (1x)
        # K Carc Formula: Panel L = D3-36 (Width - 36), Panel W = 100 (fixed)
        top_rail_panel_l = width - 36
        top_rail_panel_w = 100  # Fixed at 100mm in K Carc
        
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
        
        # BACK PANEL (1x)
        # K Carc Formula: Panel L = C3 (Height), Panel W = D3-36 (Width - 36)
        back_panel_l = height
        back_panel_w = width - 36
        
        components['backs'].append({
            'name': 'Back',
            'panel_l': back_panel_l,
            'panel_w': back_panel_w,
            'thickness': 6,  # Back panels typically 6mm
            'quantity': 1,
            'edging_length_m': 0,  # No edging on backs in K Carc
            'material': '6mm MDF',
            'notes': 'No edging'
        })
        
        # ADJUSTABLE SHELF (1x)
        # K Carc Formula: Panel L = D3-36 (Width - 36), Panel W = E3-140 (Depth - 140)
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
        
        # DOORS - Based on width
        # Single door if width < 600mm, double doors if >= 600mm
        door_height = height - 6  # 3mm top/bottom gap
        
        if width < 600:
            # Single door
            door_width = width - 6  # 3mm gap each side
            components['doors'].append({
                'name': 'Door',
                'panel_l': door_height,
                'panel_w': door_width,
                'thickness': 18,
                'quantity': 1,
                'edging_length_m': ((door_height * 2) + (door_width * 2)) / 1000,  # All edges
                'material': '18mm Door Panel',
                'notes': 'All edges edged'
            })
            components['hardware'].append({
                'name': 'Hinge - Overlay Sprung',
                'quantity': 2,
                'notes': '2 hinges for single door'
            })
        else:
            # Double doors
            door_width = (width / 2) - 4.5  # 3mm sides, 1.5mm center
            components['doors'].append({
                'name': 'Door - Left',
                'panel_l': door_height,
                'panel_w': door_width,
                'thickness': 18,
                'quantity': 1,
                'edging_length_m': ((door_height * 2) + (door_width * 2)) / 1000,
                'material': '18mm Door Panel',
                'notes': 'All edges edged'
            })
            components['doors'].append({
                'name': 'Door - Right',
                'panel_l': door_height,
                'panel_w': door_width,
                'thickness': 18,
                'quantity': 1,
                'edging_length_m': ((door_height * 2) + (door_width * 2)) / 1000,
                'material': '18mm Door Panel',
                'notes': 'All edges edged'
            })
            components['hardware'].append({
                'name': 'Hinge - Overlay Sprung',
                'quantity': 4,
                'notes': '2 hinges per door'
            })
        
        # HARDWARE
        components['hardware'].append({
            'name': 'Legs 150',
            'quantity': 1,
            'notes': 'Set of 4 adjustable legs'
        })
        
        components['hardware'].append({
            'name': 'Shelf Pegs Plastic',
            'quantity': 8,
            'notes': '4 pegs per shelf position'
        })
        
        # Calculate total area using K Carc method: ROUNDUP((Panel_L * Panel_W)/(1000*1000), 2)
        total_area = self._calculate_total_area_kcarc(components)
        
        return {
            'cabinet_type': 'Kitchen Base',
            'dimensions': {
                'height': height,
                'width': width,
                'depth': depth
            },
            'components': components,
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
    
    def _calculate_total_area_kcarc(self, components):
        """
        Calculate total area in m² using K Carc formula
        Formula: ROUNDUP((Panel_L * Panel_W)/(1000*1000), 2)
        """
        import math
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