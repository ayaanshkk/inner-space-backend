"""
Manual Entry Routes - Adapted for StreemLyne_MT schema
Handles cabinet dimension extraction and cutting list calculation
"""
from flask import Blueprint, request, jsonify, current_app
from sqlalchemy import text
from datetime import datetime
import logging

from ..db import SessionLocal
from .auth_helpers import token_required, get_current_tenant_id, get_current_employee_id

logger = logging.getLogger('ManualEntryRoutes')

manual_entry_bp = Blueprint('manual_entry', __name__)

# Initialize calculators once
dimension_extractor = None
cabinet_calculator = None

try:
    from backend.dimension_extractor import DimensionExtractor
    dimension_extractor = DimensionExtractor()
    logger.info("✅ DimensionExtractor initialized")
except Exception as e:
    logger.error(f"Failed to initialize DimensionExtractor: {e}")

try:
    from backend.cabinet_calculator import CabinetCalculator
    cabinet_calculator = CabinetCalculator()
    logger.info("✅ CabinetCalculator initialized")
except Exception as e:
    logger.error(f"Failed to initialize CabinetCalculator: {e}")


# ==========================================
# DIMENSION EXTRACTION (PHASE 1)
# ==========================================

@manual_entry_bp.route('/api/manual-entry/extract-dimensions', methods=['POST', 'OPTIONS'])
@token_required
def extract_dimensions():
    """
    PHASE 1: Extract cabinet dimensions from drawing
    Returns editable cabinet list for user confirmation
    """
    if request.method == 'OPTIONS':
        return jsonify({}), 200
        
    try:
        if not dimension_extractor:
            return jsonify({
                "success": False,
                "error": "DimensionExtractor not initialized"
            }), 500
        
        if 'file' not in request.files:
            return jsonify({"success": False, "error": "No file uploaded"}), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({"success": False, "error": "No file selected"}), 400
        
        # Read file
        image_bytes = file.read()
        
        if len(image_bytes) == 0:
            return jsonify({"success": False, "error": "Empty file"}), 400
        
        logger.info(f"Extracting dimensions from: {file.filename}")
        
        # Extract dimensions
        result = dimension_extractor.extract_dimensions_from_layout(image_bytes)
        
        if result.get('error'):
            return jsonify({
                "success": False,
                "error": result['error']
            }), 500
        
        # Return editable cabinet list
        return jsonify({
            "success": True,
            "total_width": result.get('total_width'),
            "cabinets": result.get('cabinets', []),
            "layout_notes": result.get('layout_notes', ''),
            "message": "Dimensions extracted successfully. Please review and edit if needed."
        }), 200
        
    except Exception as e:
        logger.error(f"Dimension extraction failed: {str(e)}", exc_info=True)
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


# ==========================================
# CABINET CALCULATION (PHASE 2)
# ==========================================

@manual_entry_bp.route('/api/manual-entry/calculate-cabinets', methods=['POST', 'OPTIONS'])
@token_required
def calculate_cabinets():
    """
    PHASE 2: Calculate all components from confirmed cabinet list
    User has edited/confirmed the dimensions
    Optionally saves to database if document_id is provided
    """
    if request.method == 'OPTIONS':
        return jsonify({}), 200
        
    session = SessionLocal()
    try:
        if not cabinet_calculator:
            return jsonify({
                "success": False,
                "error": "CabinetCalculator not initialized"
            }), 500
        
        tenant_id = get_current_tenant_id()
        
        data = request.get_json()
        
        if not data or 'cabinets' not in data:
            return jsonify({
                "success": False,
                "error": "No cabinet data provided"
            }), 400
        
        cabinets = data['cabinets']
        document_id = data.get('document_id')  # Optional: save to database
        
        if not isinstance(cabinets, list) or len(cabinets) == 0:
            return jsonify({
                "success": False,
                "error": "Invalid cabinet list"
            }), 400
        
        logger.info(f"Calculating components for {len(cabinets)} cabinets")
        
        # Calculate all components
        components = cabinet_calculator.calculate_complete_kitchen(cabinets)
        
        # Format for frontend
        results = cabinet_calculator.format_for_frontend(components)
        
        # Calculate summary
        total_pieces = sum(cat.get('total_pieces', 0) for cat in results.values())
        total_area = sum(cat.get('total_area', 0) for cat in results.values())
        categories_with_items = len([c for c in results.values() if c.get('total_pieces', 0) > 0])
        
        # Save to database if document_id provided
        if document_id:
            try:
                # Delete existing cutting list items for this document
                delete_query = text("""
                    DELETE FROM "StreemLyne_MT"."Drawing_Cutting_List"
                    WHERE document_id = :document_id
                """)
                session.execute(delete_query, {'document_id': int(document_id)})
                
                # Insert new cutting list items
                insert_query = text("""
                    INSERT INTO "StreemLyne_MT"."Drawing_Cutting_List" (
                        document_id,
                        tenant_id,
                        component_type,
                        part_name,
                        width,
                        height,
                        depth,
                        quantity,
                        thickness,
                        edge_banding,
                        area_m2,
                        section_index,
                        created_at
                    ) VALUES (
                        :document_id,
                        :tenant_id,
                        :component_type,
                        :part_name,
                        :width,
                        :height,
                        :depth,
                        :quantity,
                        :thickness,
                        :edge_banding,
                        :area_m2,
                        :section_index,
                        :created_at
                    )
                """)
                
                section_index = 0
                for category_name, category_data in results.items():
                    items = category_data.get('items', [])
                    for item in items:
                        session.execute(insert_query, {
                            'document_id': int(document_id),
                            'tenant_id': tenant_id,
                            'component_type': category_name,
                            'part_name': item.get('description', ''),
                            'width': item.get('width', 0),
                            'height': item.get('height', 0),
                            'depth': item.get('depth'),
                            'quantity': item.get('quantity', 1),
                            'thickness': item.get('thickness'),
                            'edge_banding': item.get('edge_banding'),
                            'area_m2': item.get('area', 0),
                            'section_index': section_index,
                            'created_at': datetime.utcnow()
                        })
                        section_index += 1
                
                session.commit()
                logger.info(f"Saved {section_index} cutting list items for document {document_id}")
                
            except Exception as save_error:
                session.rollback()
                logger.error(f"Failed to save cutting list: {save_error}", exc_info=True)
                # Don't fail the request if save fails - still return the calculated results
        
        logger.info(f"Generated {total_pieces} total components across {categories_with_items} categories")
        
        return jsonify({
            "success": True,
            "summary": {
                "total_pieces": total_pieces,
                "total_area": round(total_area, 2),
                "categories": categories_with_items,
                "cabinet_count": len(cabinets)
            },
            "results": results,
            "dxf_content": None,  # TODO: Generate DXF if needed
            "message": f"Successfully generated cutting list for {len(cabinets)} cabinets",
            "saved_to_database": bool(document_id)
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


# ==========================================
# CUTTING LIST RETRIEVAL
# ==========================================

@manual_entry_bp.route('/api/manual-entry/cutting-list/<int:document_id>', methods=['GET', 'OPTIONS'])
@token_required
def get_cutting_list(document_id):
    """Get saved cutting list for a document"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
        
    session = SessionLocal()
    try:
        tenant_id = get_current_tenant_id()
        
        query = text("""
            SELECT 
                id,
                component_type,
                part_name,
                width,
                height,
                depth,
                quantity,
                thickness,
                edge_banding,
                area_m2,
                section_index,
                created_at
            FROM "StreemLyne_MT"."Drawing_Cutting_List"
            WHERE document_id = :document_id
            ORDER BY section_index
        """)
        
        result = session.execute(query, {'document_id': document_id})
        items = result.fetchall()
        
        if not items:
            return jsonify({
                "success": True,
                "items": [],
                "message": "No cutting list found for this document"
            }), 200
        
        # Group by component type
        grouped = {}
        for item in items:
            component_type = item.component_type
            if component_type not in grouped:
                grouped[component_type] = {
                    'component_type': component_type,
                    'items': [],
                    'total_pieces': 0,
                    'total_area': 0
                }
            
            grouped[component_type]['items'].append({
                'id': item.id,
                'description': item.part_name,
                'width': float(item.width) if item.width else 0,
                'height': float(item.height) if item.height else 0,
                'depth': float(item.depth) if item.depth else None,
                'quantity': item.quantity,
                'thickness': float(item.thickness) if item.thickness else None,
                'edge_banding': item.edge_banding,
                'area': float(item.area_m2) if item.area_m2 else 0
            })
            
            grouped[component_type]['total_pieces'] += item.quantity or 1
            grouped[component_type]['total_area'] += float(item.area_m2) if item.area_m2 else 0
        
        return jsonify({
            "success": True,
            "results": grouped,
            "total_items": len(items)
        }), 200
        
    except Exception as e:
        logger.error(f"Error fetching cutting list: {e}", exc_info=True)
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500
    finally:
        session.close()


# ==========================================
# REFERENCE DATA
# ==========================================

@manual_entry_bp.route('/api/manual-entry/cabinet-types', methods=['GET', 'OPTIONS'])
def get_cabinet_types():
    """Get available cabinet types and their descriptions"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
        
    cabinet_types = {
        'standard_base': {
            'name': 'Standard Base',
            'description': 'Regular base cabinet with doors and shelf',
            'typical_width': '700-1000mm'
        },
        'sink_base': {
            'name': 'Sink Base',
            'description': 'Base cabinet for sink (no shelf, lower back)',
            'typical_width': '600-900mm'
        },
        'drawer_base': {
            'name': 'Drawer Base',
            'description': 'Cabinet with multiple drawers',
            'typical_width': '400-600mm'
        },
        'narrow': {
            'name': 'Narrow Cabinet',
            'description': 'Slim cabinet for spices/bottles',
            'typical_width': '200-400mm'
        },
        'wide_base': {
            'name': 'Wide Base',
            'description': 'Extra wide cabinet',
            'typical_width': '1000mm+'
        },
        'filler': {
            'name': 'Filler Panel',
            'description': 'Decorative filler piece',
            'typical_width': '< 150mm'
        },
        'corner_l': {
            'name': 'L-Corner',
            'description': 'L-shaped corner cabinet (special)',
            'typical_width': 'Variable'
        }
    }
    
    return jsonify({
        "success": True,
        "cabinet_types": cabinet_types
    }), 200