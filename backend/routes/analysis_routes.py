"""
Analysis Routes - Compatible with existing frontend
Flask API endpoints for cutting list calculation
"""
from flask import Blueprint, request, jsonify, send_file, g
from werkzeug.utils import secure_filename
import os
import uuid
from datetime import datetime
import logging

# Import database if you have it
try:
    from backend.db import SessionLocal
    from backend.models import User, Drawing, CuttingListItem
    HAS_DATABASE = True
except ImportError:
    HAS_DATABASE = False
    logger = logging.getLogger(__name__)
    logger.warning("⚠️ Database not available - results will not be persisted")

from backend.services.preprocessing import ImagePreprocessor
from backend.services.ocr_dimension_extractor import AnthropicExtractor
from backend.services.section_analyzer import SectionAnalyzer
from backend.services.cutting_list_builder import CuttingListBuilder
from backend.services.manufacturing_rules import ConstructionStyle

analysis_bp = Blueprint('analysis', __name__)
logger = logging.getLogger(__name__)

# Configuration
UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'uploads', 'drawings')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'pdf', 'webp'}
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Initialize services
preprocessor = ImagePreprocessor(
    max_width=2000,
    max_height=2000,
    target_format="JPEG",
    quality=85,
    grayscale=False
)

try:
    extractor = AnthropicExtractor()
    logger.info("✅ Anthropic API initialized")
except Exception as e:
    logger.error(f"❌ Failed to initialize Anthropic API: {e}")
    extractor = None

analyzer = SectionAnalyzer()


def allowed_file(filename: str) -> bool:
    """Check if file extension is allowed"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def _calculate_area(component: dict) -> float:
    """Calculate area in m² from component dimensions"""
    # Try to get dimensions from different possible field names
    width = component.get('width') or component.get('component_width') or 0
    height = component.get('height') or 0
    depth = component.get('depth') or 0
    quantity = component.get('quantity', 1)
    
    area_mm2 = 0
    
    # Width × Height (most common for panels, doors, shelves)
    if width > 0 and height > 0:
        area_mm2 = width * height * quantity
    # Width × Depth (for horizontal surfaces viewed from above)
    elif width > 0 and depth > 0:
        area_mm2 = width * depth * quantity
    
    return area_mm2 / 1_000_000  # Convert mm² to m²


@analysis_bp.route('/api/drawing-analyser/upload', methods=['POST'])
def upload_drawing():
    """
    Upload a technical drawing and extract cutting list using AI pipeline
    
    This endpoint is compatible with your existing frontend
    """
    
    logger.info("=" * 70)
    logger.info("🚀 NEW DRAWING UPLOAD")
    logger.info("=" * 70)
    
    # Check if API is available
    if extractor is None:
        return jsonify({
            'success': False,
            'error': 'Anthropic API not initialized. Check ANTHROPIC_API_KEY environment variable.'
        }), 500
    
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    
    file = request.files['file']
    
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    
    if not allowed_file(file.filename):
        return jsonify({'error': 'Invalid file type. Allowed: PNG, JPG, PDF'}), 400
    
    session = SessionLocal() if HAS_DATABASE else None
    
    try:
        # Generate unique filename
        file_ext = file.filename.rsplit('.', 1)[1].lower()
        unique_filename = f"{uuid.uuid4()}.{file_ext}"
        file_path = os.path.join(UPLOAD_FOLDER, unique_filename)
        
        # Save file
        file.save(file_path)
        logger.info(f"📁 File saved: {file_path}")
        
        # Read file bytes for processing
        with open(file_path, 'rb') as f:
            image_bytes = f.read()
        
        # Create Drawing record (if database available)
        drawing_id = str(uuid.uuid4())
        if HAS_DATABASE and session:
            drawing = Drawing(
                id=drawing_id,
                project_name=request.form.get('project_name', file.filename.replace(f'.{file_ext}', '')),
                original_filename=file.filename,
                file_path=file_path,
                status='processing',
                uploaded_by=g.user.id if hasattr(g, 'user') else None
            )
            session.add(drawing)
            session.flush()
        
        # STEP 1: Preprocess image
        logger.info("\n📸 STEP 1: Preprocessing image...")
        processed_bytes, preprocess_meta = preprocessor.process(image_bytes)
        
        # STEP 2: Extract dimensions using Claude API
        logger.info("\n🤖 STEP 2: Extracting dimensions with Claude API...")
        extraction_result = extractor.extract_dimensions(processed_bytes)
        
        if not extraction_result.get('success'):
            logger.error("❌ Extraction failed")
            if HAS_DATABASE and session:
                drawing.status = 'failed'
                session.commit()
            
            return jsonify({
                'success': False,
                'error': extraction_result.get('error', 'Extraction failed'),
                'drawing_id': drawing_id
            }), 400
        
        logger.info(f"✅ Extracted {len(extraction_result['cabinets'])} cabinets")
        
        # STEP 3: Validate and transform extraction
        logger.info("\n🔍 STEP 3: Validating extraction...")
        validation = analyzer.validate_extraction(extraction_result)
        
        if not validation['valid']:
            logger.error(f"❌ Validation failed: {validation['errors']}")
            if HAS_DATABASE and session:
                drawing.status = 'failed'
                session.commit()
            
            return jsonify({
                'success': False,
                'error': 'Extraction validation failed',
                'validation': validation,
                'drawing_id': drawing_id
            }), 400
        
        # Transform to cabinet format
        logger.info("\n🔄 STEP 4: Transforming extraction...")
        cabinets = analyzer.transform_extraction(extraction_result)
        
        
        # STEP 4: Parse construction style (if provided)
        construction_style = ConstructionStyle()
        if 'construction_style' in request.form:
            try:
                import json
                style_data = json.loads(request.form['construction_style'])
                construction_style = ConstructionStyle(**style_data)
            except Exception as e:
                logger.warning(f"Failed to parse construction_style: {e}")
        
        # STEP 5: Build cutting list
        logger.info("\n⚙️ STEP 5: Building cutting list...")
        builder = CuttingListBuilder(construction_style)
        cutting_list_result = builder.build_cutting_list(cabinets)
        
        components = cutting_list_result['components']
        summary = cutting_list_result['summary']
        
        logger.info(f"✅ Generated {len(components)} components, {summary['total_pieces']} pieces")
        
        # Update drawing with results (if database available)
        if HAS_DATABASE and session:
            drawing.status = 'completed'
            drawing.ocr_method = extraction_result.get('method', 'anthropic_claude')
            drawing.confidence = extraction_result.get('confidence', 0)
            
            # Save cutting list items
            for comp in components:
                # Calculate area ensuring all fields exist
                area = _calculate_area(comp)
                
                cutting_item = CuttingListItem(
                    id=str(uuid.uuid4()),
                    drawing_id=drawing.id,
                    component_type=comp.get('component_type', 'UNKNOWN'),
                    part_name=comp.get('part_name', 'Unnamed'),
                    overall_unit_width=comp.get('width'),
                    component_width=comp.get('width'),
                    height=comp.get('height'),
                    depth=comp.get('depth'),
                    quantity=comp.get('quantity', 1),
                    material_thickness=comp.get('thickness', 18),
                    edge_banding_notes=comp.get('edge_banding', 'None'),
                    area_m2=area,  # Use calculated area
                    section_index=comp.get('section_index')
                )
                session.add(cutting_item)
            
            session.commit()
            logger.info(f"✅ Drawing saved to database: {drawing.id}")

        components_with_area = []
        for comp in components:
            comp_copy = comp.copy()
            if 'area_m2' not in comp_copy or comp_copy['area_m2'] is None:
                comp_copy['area_m2'] = _calculate_area(comp)
            components_with_area.append(comp_copy)
        
        response = {
            'success': True,
            'drawing_id': drawing_id,
            'status': 'completed',
            'ocr_method': extraction_result.get('method'),
            'cutting_list': components_with_area,  # ← Use this instead
            'preview_url': f'/api/drawing-analyser/{drawing_id}/preview',
            'total_pieces': summary['total_pieces'],
            'total_area_m2': summary['total_area_m2'],
            'confidence': float(extraction_result.get('confidence', 0)),
            'message': 'Drawing analyzed successfully!'
        }
        
        logger.info("\n" + "=" * 70)
        logger.info("✅ ANALYSIS COMPLETE")
        logger.info(f"📦 Cabinets: {summary['total_cabinets']}, "
                   f"Components: {len(components)}, "
                   f"Pieces: {summary['total_pieces']}")
        logger.info(f"🎯 Confidence: {extraction_result.get('confidence', 0):.1%}")
        logger.info("=" * 70)
        
        return jsonify(response), 201
        
    except Exception as e:
        if HAS_DATABASE and session:
            session.rollback()
        logger.error(f"❌ Upload failed: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500
    finally:
        if HAS_DATABASE and session:
            session.close()


@analysis_bp.route('/api/drawing-analyser/<drawing_id>', methods=['GET'])
def get_drawing(drawing_id: str):
    """Get drawing details and cutting list"""
    
    if not HAS_DATABASE:
        return jsonify({'error': 'Database not configured'}), 501
    
    session = SessionLocal()
    
    try:
        drawing = session.query(Drawing).filter_by(id=drawing_id).first()
        
        if not drawing:
            return jsonify({'error': 'Drawing not found'}), 404
        
        return jsonify(drawing.to_dict(include_cutting_list=True))
        
    finally:
        session.close()


@analysis_bp.route('/api/drawing-analyser', methods=['GET'])
def list_drawings():
    """List all drawings"""
    
    if not HAS_DATABASE:
        return jsonify({
            'total': 0,
            'limit': 50,
            'offset': 0,
            'drawings': []
        })
    
    session = SessionLocal()
    
    try:
        limit = int(request.args.get('limit', 50))
        offset = int(request.args.get('offset', 0))
        
        query = session.query(Drawing).order_by(Drawing.created_at.desc())
        
        total = query.count()
        drawings = query.limit(limit).offset(offset).all()
        
        return jsonify({
            'total': total,
            'limit': limit,
            'offset': offset,
            'drawings': [d.to_dict() for d in drawings]
        })
        
    finally:
        session.close()


@analysis_bp.route('/api/drawing-analyser/<drawing_id>/preview', methods=['GET'])
def preview_drawing(drawing_id: str):
    """Get drawing image file - FIXED VERSION"""
    
    if not HAS_DATABASE:
        # Try to find file directly
        for ext in ALLOWED_EXTENSIONS:
            filepath = os.path.join(UPLOAD_FOLDER, f"{drawing_id}.{ext}")
            if os.path.exists(filepath):
                # Determine mimetype
                mimetype_map = {
                    'png': 'image/png',
                    'jpg': 'image/jpeg',
                    'jpeg': 'image/jpeg',
                    'pdf': 'application/pdf',
                    'webp': 'image/webp'
                }
                return send_file(filepath, mimetype=mimetype_map.get(ext, 'image/jpeg'))
        return jsonify({'error': 'Drawing not found'}), 404
    
    session = SessionLocal()
    
    try:
        drawing = session.query(Drawing).filter_by(id=drawing_id).first()
        
        if not drawing:
            return jsonify({'error': 'Drawing not found'}), 404
        
        if not os.path.exists(drawing.file_path):
            return jsonify({'error': 'File not found on disk'}), 404
        
        # ✅ FIX: Determine correct mimetype from file extension
        file_ext = os.path.splitext(drawing.file_path)[1].lower()
        mimetype_map = {
            '.png': 'image/png',
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.pdf': 'application/pdf',
            '.webp': 'image/webp'
        }
        
        mimetype = mimetype_map.get(file_ext, 'image/jpeg')
        
        return send_file(
            drawing.file_path, 
            mimetype=mimetype,
            as_attachment=False,
            download_name=drawing.original_filename
        )
        
    finally:
        session.close()


@analysis_bp.route('/api/drawing-analyser/<drawing_id>', methods=['DELETE'])
def delete_drawing(drawing_id: str):
    """Delete drawing and associated cutting list"""
    
    if not HAS_DATABASE:
        return jsonify({'error': 'Database not configured'}), 501
    
    session = SessionLocal()
    
    try:
        drawing = session.query(Drawing).filter_by(id=drawing_id).first()
        
        if not drawing:
            return jsonify({'error': 'Drawing not found'}), 404
        
        # Delete file from disk
        if os.path.exists(drawing.file_path):
            try:
                os.remove(drawing.file_path)
                logger.info(f"🗑️ Deleted file: {drawing.file_path}")
            except Exception as e:
                logger.warning(f"Failed to delete file {drawing.file_path}: {e}")
        
        # Delete from database (cascade will delete cutting list items)
        session.delete(drawing)
        session.commit()
        
        return jsonify({'success': True, 'message': 'Drawing deleted'})
        
    except Exception as e:
        session.rollback()
        logger.error(f"Delete error: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@analysis_bp.route('/api/drawing-analyser/<drawing_id>', methods=['PUT'])
def update_drawing(drawing_id: str):
    """Update drawing cutting list (after user edits)"""
    
    if not HAS_DATABASE:
        return jsonify({'error': 'Database not configured'}), 501
    
    session = SessionLocal()
    
    try:
        drawing = session.query(Drawing).filter_by(id=drawing_id).first()
        
        if not drawing:
            return jsonify({'error': 'Drawing not found'}), 404
        
        data = request.get_json()
        
        if 'cutting_list' in data:
            # Delete existing cutting list items
            session.query(CuttingListItem).filter_by(drawing_id=drawing_id).delete()
            
            # Add new cutting list items
            for item_data in data['cutting_list']:
                cutting_item = CuttingListItem(
                    id=str(uuid.uuid4()),
                    drawing_id=drawing.id,
                    component_type=item_data.get('component_type'),
                    part_name=item_data.get('part_name'),
                    overall_unit_width=item_data.get('overall_unit_width'),
                    component_width=item_data.get('component_width'),
                    height=item_data.get('height'),
                    depth=item_data.get('depth'),
                    quantity=item_data.get('quantity', 1),
                    material_thickness=item_data.get('material_thickness', 18),
                    edge_banding_notes=item_data.get('edge_banding_notes'),
                    area_m2=item_data.get('area_m2', 0),
                    section_index=item_data.get('section_index')
                )
                session.add(cutting_item)
            
            # Update drawing status
            drawing.status = 'completed'
            drawing.ocr_method = 'manual_edit'
        
        session.commit()
        
        return jsonify(drawing.to_dict(include_cutting_list=True))
        
    except Exception as e:
        session.rollback()
        logger.error(f"Update error: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@analysis_bp.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'services': {
            'anthropic_api': extractor is not None,
            'preprocessing': True,
            'cutting_list_builder': True,
            'database': HAS_DATABASE
        },
        'timestamp': datetime.utcnow().isoformat()
    }), 200


@analysis_bp.route('/api/construction-styles', methods=['GET'])
def get_construction_styles():
    """Get available construction styles and defaults"""
    from backend.services.manufacturing_rules import DEFAULT_STYLE
    
    return jsonify({
        'default': {
            'material_thickness': DEFAULT_STYLE.material_thickness,
            'back_thickness': DEFAULT_STYLE.back_thickness,
            'toe_kick_height': DEFAULT_STYLE.toe_kick_height,
            'door_gap': DEFAULT_STYLE.door_gap,
            'back_construction_mode': DEFAULT_STYLE.back_construction_mode
        },
        'back_construction_modes': [
            {
                'value': 'overlay',
                'label': 'Overlay (Back nailed to rear, full internal depth)',
                'description': 'Back panel attached to the back of carcass. Does not reduce internal depth.'
            },
            {
                'value': 'inset',
                'label': 'Inset (Back fits inside, reduces internal depth)',
                'description': 'Back panel fits inside carcass. Reduces internal depth by back thickness.'
            }
        ]
    }), 200

# Error handlers
@analysis_bp.errorhandler(413)
def request_entity_too_large(error):
    """Handle file too large error"""
    return jsonify({
        'success': False,
        'error': 'File too large. Maximum size: 16MB'
    }), 413


@analysis_bp.errorhandler(500)
def internal_server_error(error):
    """Handle internal errors"""
    logger.error(f"Internal error: {error}", exc_info=True)
    return jsonify({
        'success': False,
        'error': 'Internal server error'
    }), 500