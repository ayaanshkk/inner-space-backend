"""
Analysis Routes - Adapted for StreemLyne_MT schema
Flask API endpoints for cutting list calculation
"""
from flask import Blueprint, request, jsonify, send_file, g
from werkzeug.utils import secure_filename
import os
import uuid
from datetime import datetime
import logging
from sqlalchemy import text

# Import database
try:
    from backend.db import SessionLocal
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
    width = component.get('width') or component.get('component_width') or 0
    height = component.get('height') or 0
    depth = component.get('depth') or 0
    quantity = component.get('quantity', 1)
    
    area_mm2 = 0
    
    if width > 0 and height > 0:
        area_mm2 = width * height * quantity
    elif width > 0 and depth > 0:
        area_mm2 = width * depth * quantity
    
    return area_mm2 / 1_000_000


def get_current_tenant_id():
    """Get tenant_id from current user context"""
    if hasattr(g, 'user'):
        return g.user.get('tenant_id')
    return None


def get_current_employee_id():
    """Get employee_id from current user context"""
    if hasattr(g, 'user'):
        return g.user.get('employee_id')
    return None


@analysis_bp.route('/api/drawing-analyser/upload', methods=['POST'])
def upload_drawing():
    """
    Upload a technical drawing and extract cutting list using AI pipeline
    Uses Customer_Documents table for file storage
    """
    
    logger.info("=" * 70)
    logger.info("🚀 NEW DRAWING UPLOAD")
    logger.info("=" * 70)
    
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
        tenant_id = get_current_tenant_id()
        employee_id = get_current_employee_id()
        
        if not tenant_id:
            return jsonify({'error': 'Tenant ID not found in session'}), 401
        
        # Generate unique filename
        file_ext = file.filename.rsplit('.', 1)[1].lower()
        unique_filename = f"{uuid.uuid4()}.{file_ext}"
        file_path = os.path.join(UPLOAD_FOLDER, unique_filename)
        
        # Save file temporarily
        file.save(file_path)
        logger.info(f"📁 File saved: {file_path}")
        
        # Read file bytes for processing
        with open(file_path, 'rb') as f:
            image_bytes = f.read()
        
        # Get client_id from request (optional)
        client_id = request.form.get('client_id')
        property_id = request.form.get('property_id')
        opportunity_id = request.form.get('opportunity_id')
        
        # Create document record
        document_id = None
        if HAS_DATABASE and session:
            # Upload to blob storage (placeholder - implement based on your blob storage)
            # TODO: Upload to Vercel Blob or your blob storage and get blob_url
            blob_url = f"/uploads/drawings/{unique_filename}"  # Placeholder
            
            insert_doc = text("""
                INSERT INTO "StreemLyne_MT"."Customer_Documents" (
                    client_id,
                    opportunity_id,
                    property_id,
                    file_url,
                    file_name,
                    document_category
                ) VALUES (
                    :client_id,
                    :opportunity_id,
                    :property_id,
                    :file_url,
                    :file_name,
                    :document_category
                )
                RETURNING id
            """)
            
            result = session.execute(insert_doc, {
                'client_id': client_id,
                'opportunity_id': opportunity_id,
                'property_id': property_id,
                'file_url': blob_url,
                'file_name': file.filename,
                'document_category': 'technical_drawing'
            })
            
            document_id = result.fetchone()[0]
            session.flush()
        
        # STEP 1: Preprocess image
        logger.info("\n📸 STEP 1: Preprocessing image...")
        processed_bytes, preprocess_meta = preprocessor.process(image_bytes)
        
        # STEP 2: Extract dimensions using Claude API
        logger.info("\n🤖 STEP 2: Extracting dimensions with Claude API...")
        extraction_result = extractor.extract_dimensions(processed_bytes)
        
        if not extraction_result.get('success'):
            logger.error("❌ Extraction failed")
            return jsonify({
                'success': False,
                'error': extraction_result.get('error', 'Extraction failed'),
                'document_id': document_id
            }), 400
        
        logger.info(f"✅ Extracted {len(extraction_result['cabinets'])} cabinets")
        
        # STEP 3: Validate and transform extraction
        logger.info("\n🔍 STEP 3: Validating extraction...")
        validation = analyzer.validate_extraction(extraction_result)
        
        if not validation['valid']:
            logger.error(f"❌ Validation failed: {validation['errors']}")
            return jsonify({
                'success': False,
                'error': 'Extraction validation failed',
                'validation': validation,
                'document_id': document_id
            }), 400
        
        # Transform to cabinet format
        logger.info("\n🔄 STEP 4: Transforming extraction...")
        cabinets = analyzer.transform_extraction(extraction_result)
        
        # STEP 4: Parse construction style
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
        
        # Store cutting list items in Drawing_Cutting_List table
        if HAS_DATABASE and session:
            # Update document category
            update_doc = text("""
                UPDATE "StreemLyne_MT"."Customer_Documents"
                SET document_category = 'technical_drawing_analyzed'
                WHERE id = :document_id
            """)
            
            session.execute(update_doc, {'document_id': document_id})
            
            # Insert cutting list items
            for comp in components:
                area = _calculate_area(comp)
                
                insert_cutting = text("""
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
                        section_index
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
                        :section_index
                    )
                """)
                
                session.execute(insert_cutting, {
                    'document_id': document_id,
                    'tenant_id': tenant_id,
                    'component_type': comp.get('component_type'),
                    'part_name': comp.get('part_name'),
                    'width': comp.get('width'),
                    'height': comp.get('height'),
                    'depth': comp.get('depth'),
                    'quantity': comp.get('quantity', 1),
                    'thickness': comp.get('thickness', 18),
                    'edge_banding': comp.get('edge_banding'),
                    'area_m2': area,
                    'section_index': comp.get('section_index')
                })
            
            logger.info(f"✅ Stored {len(components)} cutting list items")
            
            # Create notification for the analysis completion
            if client_id:
                notify_query = text("""
                    INSERT INTO "StreemLyne_MT"."Notification_Master" (
                        tenant_id,
                        employee_id,
                        client_id,
                        notification_type,
                        priority,
                        message,
                        read,
                        dismissed
                    ) VALUES (
                        :tenant_id,
                        :employee_id,
                        :client_id,
                        :notification_type,
                        :priority,
                        :message,
                        false,
                        false
                    )
                """)
                
                session.execute(notify_query, {
                    'tenant_id': tenant_id,
                    'employee_id': employee_id,
                    'client_id': client_id,
                    'notification_type': 'document_processed',
                    'priority': 'medium',
                    'message': f'Technical drawing "{file.filename}" has been analyzed. {len(components)} components extracted.'
                })
            
            session.commit()
            logger.info(f"✅ Document saved to database: {document_id}")

        # Add area to all components
        components_with_area = []
        for comp in components:
            comp_copy = comp.copy()
            if 'area_m2' not in comp_copy or comp_copy['area_m2'] is None:
                comp_copy['area_m2'] = _calculate_area(comp)
            components_with_area.append(comp_copy)
        
        response = {
            'success': True,
            'document_id': document_id,
            'status': 'completed',
            'ocr_method': extraction_result.get('method'),
            'cutting_list': components_with_area,
            'preview_url': f'/api/drawing-analyser/{document_id}/preview',
            'total_pieces': summary['total_pieces'],
            'total_area_m2': summary['total_area_m2'],
            'total_cabinets': summary['total_cabinets'],
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


@analysis_bp.route('/api/drawing-analyser/<int:document_id>', methods=['GET'])
def get_drawing(document_id: int):
    """Get drawing details and cutting list"""
    
    if not HAS_DATABASE:
        return jsonify({'error': 'Database not configured'}), 501
    
    session = SessionLocal()
    
    try:
        tenant_id = get_current_tenant_id()
        
        # Get document info
        query = text("""
            SELECT 
                cd.id,
                cd.file_name,
                cd.file_url,
                cd.uploaded_at,
                cd.document_category,
                cd.client_id,
                cd.opportunity_id,
                cd.property_id,
                c.client_company_name,
                c.client_contact_name
            FROM "StreemLyne_MT"."Customer_Documents" cd
            LEFT JOIN "StreemLyne_MT"."Client_Master" c ON cd.client_id = c.client_id
            WHERE cd.id = :document_id
        """)
        
        result = session.execute(query, {'document_id': document_id})
        row = result.fetchone()
        
        if not row:
            return jsonify({'error': 'Drawing not found'}), 404
        
        # Get cutting list items
        cutting_query = text("""
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
            WHERE document_id = :document_id AND tenant_id = :tenant_id
            ORDER BY section_index, id
        """)
        
        cutting_result = session.execute(cutting_query, {
            'document_id': document_id,
            'tenant_id': tenant_id
        })
        
        cutting_list = [{
            'id': item.id,
            'component_type': item.component_type,
            'part_name': item.part_name,
            'width': float(item.width) if item.width else None,
            'height': float(item.height) if item.height else None,
            'depth': float(item.depth) if item.depth else None,
            'quantity': item.quantity,
            'thickness': float(item.thickness) if item.thickness else None,
            'edge_banding': item.edge_banding,
            'area_m2': float(item.area_m2) if item.area_m2 else None,
            'section_index': item.section_index
        } for item in cutting_result]
        
        # Calculate summary
        total_pieces = sum(item['quantity'] for item in cutting_list)
        total_area = sum(item.get('area_m2', 0) or 0 for item in cutting_list)
        
        return jsonify({
            'id': row.id,
            'file_name': row.file_name,
            'file_url': row.file_url,
            'uploaded_at': row.uploaded_at.isoformat() if row.uploaded_at else None,
            'document_category': row.document_category,
            'client_id': row.client_id,
            'client_name': row.client_company_name or row.client_contact_name,
            'opportunity_id': row.opportunity_id,
            'property_id': row.property_id,
            'cutting_list': cutting_list,
            'total_pieces': total_pieces,
            'total_area_m2': total_area
        })
        
    finally:
        session.close()


@analysis_bp.route('/api/drawing-analyser', methods=['GET'])
def list_drawings():
    """List all technical drawings for current tenant"""
    
    if not HAS_DATABASE:
        return jsonify({
            'total': 0,
            'limit': 50,
            'offset': 0,
            'drawings': []
        })
    
    session = SessionLocal()
    
    try:
        tenant_id = get_current_tenant_id()
        limit = int(request.args.get('limit', 50))
        offset = int(request.args.get('offset', 0))
        
        # Count query
        count_query = text("""
            SELECT COUNT(*) 
            FROM "StreemLyne_MT"."Customer_Documents" cd
            LEFT JOIN "StreemLyne_MT"."Client_Master" c ON cd.client_id = c.client_id
            WHERE (c.tenant_id = :tenant_id OR cd.client_id IS NULL)
            AND cd.document_category LIKE '%technical_drawing%'
        """)
        
        total = session.execute(count_query, {'tenant_id': tenant_id}).scalar()
        
        # Data query with cutting list summary
        query = text("""
            SELECT 
                cd.id,
                cd.file_name,
                cd.file_url,
                cd.uploaded_at,
                cd.document_category,
                cd.client_id,
                c.client_company_name,
                c.client_contact_name,
                COUNT(dcl.id) as component_count,
                SUM(dcl.quantity) as total_pieces,
                SUM(dcl.area_m2) as total_area_m2
            FROM "StreemLyne_MT"."Customer_Documents" cd
            LEFT JOIN "StreemLyne_MT"."Client_Master" c ON cd.client_id = c.client_id
            LEFT JOIN "StreemLyne_MT"."Drawing_Cutting_List" dcl ON cd.id = dcl.document_id
            WHERE (c.tenant_id = :tenant_id OR cd.client_id IS NULL)
            AND cd.document_category LIKE '%technical_drawing%'
            GROUP BY cd.id, c.client_company_name, c.client_contact_name
            ORDER BY cd.uploaded_at DESC
            LIMIT :limit OFFSET :offset
        """)
        
        result = session.execute(query, {
            'tenant_id': tenant_id,
            'limit': limit,
            'offset': offset
        })
        
        drawings = [{
            'id': row.id,
            'file_name': row.file_name,
            'file_url': row.file_url,
            'uploaded_at': row.uploaded_at.isoformat() if row.uploaded_at else None,
            'document_category': row.document_category,
            'client_id': row.client_id,
            'client_name': row.client_company_name or row.client_contact_name,
            'component_count': row.component_count or 0,
            'total_pieces': row.total_pieces or 0,
            'total_area_m2': float(row.total_area_m2) if row.total_area_m2 else 0
        } for row in result]
        
        return jsonify({
            'total': total,
            'limit': limit,
            'offset': offset,
            'drawings': drawings
        })
        
    finally:
        session.close()


@analysis_bp.route('/api/drawing-analyser/<int:document_id>/preview', methods=['GET'])
def preview_drawing(document_id: int):
    """Get drawing image file"""
    
    if not HAS_DATABASE:
        return jsonify({'error': 'Database not configured'}), 501
    
    session = SessionLocal()
    
    try:
        query = text("""
            SELECT file_url, file_name
            FROM "StreemLyne_MT"."Customer_Documents"
            WHERE id = :document_id
        """)
        
        result = session.execute(query, {'document_id': document_id})
        row = result.fetchone()
        
        if not row:
            return jsonify({'error': 'Drawing not found'}), 404
        
        # Extract filename from blob URL
        file_url = row.file_url
        
        # If it's a local path
        if file_url.startswith('/uploads/'):
            filepath = os.path.join(
                os.path.dirname(os.path.dirname(__file__)),
                file_url.lstrip('/')
            )
            
            if not os.path.exists(filepath):
                return jsonify({'error': 'File not found on disk'}), 404
            
            file_ext = os.path.splitext(filepath)[1].lower()
            mimetype_map = {
                '.png': 'image/png',
                '.jpg': 'image/jpeg',
                '.jpeg': 'image/jpeg',
                '.pdf': 'application/pdf',
                '.webp': 'image/webp'
            }
            
            mimetype = mimetype_map.get(file_ext, 'image/jpeg')
            
            return send_file(
                filepath,
                mimetype=mimetype,
                as_attachment=False,
                download_name=row.file_name
            )
        else:
            # If it's a blob URL, redirect to it
            from flask import redirect
            return redirect(file_url)
        
    finally:
        session.close()


@analysis_bp.route('/api/drawing-analyser/<int:document_id>', methods=['DELETE'])
def delete_drawing(document_id: int):
    """Delete drawing document and associated cutting list"""
    
    if not HAS_DATABASE:
        return jsonify({'error': 'Database not configured'}), 501
    
    session = SessionLocal()
    
    try:
        tenant_id = get_current_tenant_id()
        
        # Get file info first
        select_query = text("""
            SELECT cd.file_url, cd.file_name
            FROM "StreemLyne_MT"."Customer_Documents" cd
            LEFT JOIN "StreemLyne_MT"."Client_Master" c ON cd.client_id = c.client_id
            WHERE cd.id = :document_id 
            AND (c.tenant_id = :tenant_id OR cd.client_id IS NULL)
        """)
        
        result = session.execute(select_query, {
            'document_id': document_id,
            'tenant_id': tenant_id
        })
        row = result.fetchone()
        
        if not row:
            return jsonify({'error': 'Drawing not found'}), 404
        
        # Delete file from disk if local
        if row.file_url.startswith('/uploads/'):
            filepath = os.path.join(
                os.path.dirname(os.path.dirname(__file__)),
                row.file_url.lstrip('/')
            )
            if os.path.exists(filepath):
                try:
                    os.remove(filepath)
                    logger.info(f"🗑️ Deleted file: {filepath}")
                except Exception as e:
                    logger.warning(f"Failed to delete file {filepath}: {e}")
        
        # Delete cutting list items (cascade should handle this, but being explicit)
        delete_cutting = text("""
            DELETE FROM "StreemLyne_MT"."Drawing_Cutting_List"
            WHERE document_id = :document_id AND tenant_id = :tenant_id
        """)
        session.execute(delete_cutting, {
            'document_id': document_id,
            'tenant_id': tenant_id
        })
        
        # Delete document
        delete_query = text("""
            DELETE FROM "StreemLyne_MT"."Customer_Documents"
            WHERE id = :document_id
        """)
        
        session.execute(delete_query, {'document_id': document_id})
        session.commit()
        
        return jsonify({'success': True, 'message': 'Drawing deleted'})
        
    except Exception as e:
        session.rollback()
        logger.error(f"Delete error: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@analysis_bp.route('/api/drawing-analyser/<int:document_id>', methods=['PUT'])
def update_drawing(document_id: int):
    """Update drawing cutting list (after user edits)"""
    
    if not HAS_DATABASE:
        return jsonify({'error': 'Database not configured'}), 501
    
    session = SessionLocal()
    
    try:
        tenant_id = get_current_tenant_id()
        data = request.get_json()
        
        # Verify document exists and belongs to tenant
        verify_query = text("""
            SELECT cd.id
            FROM "StreemLyne_MT"."Customer_Documents" cd
            LEFT JOIN "StreemLyne_MT"."Client_Master" c ON cd.client_id = c.client_id
            WHERE cd.id = :document_id 
            AND (c.tenant_id = :tenant_id OR cd.client_id IS NULL)
        """)
        
        result = session.execute(verify_query, {
            'document_id': document_id,
            'tenant_id': tenant_id
        })
        
        if not result.fetchone():
            return jsonify({'error': 'Drawing not found'}), 404
        
        if 'cutting_list' in data:
            # Delete existing cutting list items
            delete_query = text("""
                DELETE FROM "StreemLyne_MT"."Drawing_Cutting_List"
                WHERE document_id = :document_id AND tenant_id = :tenant_id
            """)
            session.execute(delete_query, {
                'document_id': document_id,
                'tenant_id': tenant_id
            })
            
            # Add new cutting list items
            for item_data in data['cutting_list']:
                insert_cutting = text("""
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
                        section_index
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
                        :section_index
                    )
                """)
                
                session.execute(insert_cutting, {
                    'document_id': document_id,
                    'tenant_id': tenant_id,
                    'component_type': item_data.get('component_type'),
                    'part_name': item_data.get('part_name'),
                    'width': item_data.get('width'),
                    'height': item_data.get('height'),
                    'depth': item_data.get('depth'),
                    'quantity': item_data.get('quantity', 1),
                    'thickness': item_data.get('thickness', 18),
                    'edge_banding': item_data.get('edge_banding'),
                    'area_m2': item_data.get('area_m2', 0),
                    'section_index': item_data.get('section_index')
                })
            
            # Update document status
            update_doc = text("""
                UPDATE "StreemLyne_MT"."Customer_Documents"
                SET document_category = 'technical_drawing_edited'
                WHERE id = :document_id
            """)
            session.execute(update_doc, {'document_id': document_id})
        
        session.commit()
        
        # Return updated drawing
        return get_drawing(document_id)
        
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