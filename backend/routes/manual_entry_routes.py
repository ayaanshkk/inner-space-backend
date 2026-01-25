from flask import Blueprint, request, jsonify
import logging

logger = logging.getLogger('ManualEntryRoutes')

manual_entry_bp = Blueprint('manual_entry', __name__)

# Initialize once
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


@manual_entry_bp.route('/api/manual-entry/extract-dimensions', methods=['POST'])
def extract_dimensions():
    """
    PHASE 1: Extract cabinet dimensions from drawing
    Returns editable cabinet list for user confirmation
    """
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


@manual_entry_bp.route('/api/manual-entry/calculate-cabinets', methods=['POST'])
def calculate_cabinets():
    """
    PHASE 2: Calculate all components from confirmed cabinet list
    User has edited/confirmed the dimensions
    """
    try:
        if not cabinet_calculator:
            return jsonify({
                "success": False,
                "error": "CabinetCalculator not initialized"
            }), 500
        
        data = request.get_json()
        
        if not data or 'cabinets' not in data:
            return jsonify({
                "success": False,
                "error": "No cabinet data provided"
            }), 400
        
        cabinets = data['cabinets']
        
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
            "message": f"Successfully generated cutting list for {len(cabinets)} cabinets"
        }), 200
        
    except Exception as e:
        logger.error(f"Cabinet calculation failed: {str(e)}", exc_info=True)
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@manual_entry_bp.route('/api/manual-entry/cabinet-types', methods=['GET'])
def get_cabinet_types():
    """Get available cabinet types and their descriptions"""
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