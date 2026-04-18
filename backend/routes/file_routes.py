"""
File Routes - Adapted for StreemLyne_MT schema
Handles document uploads to Cloudinary and file management
"""
from flask import request, jsonify, send_file, Blueprint, current_app, redirect, Response
from werkzeug.utils import secure_filename
from datetime import datetime
from sqlalchemy import text
import os
import uuid
import requests
import cloudinary
import cloudinary.uploader
import cloudinary.api

from ..db import SessionLocal
from .auth_helpers import token_required, get_current_tenant_id, get_current_employee_id

file_bp = Blueprint('file_routes', __name__)

# ==========================================
# Cloudinary Configuration
# ==========================================

def configure_cloudinary():
    """Configure Cloudinary with environment variables"""
    cloudinary.config(
        cloud_name=os.environ.get('CLOUDINARY_CLOUD_NAME'),
        api_key=os.environ.get('CLOUDINARY_API_KEY'),
        api_secret=os.environ.get('CLOUDINARY_API_SECRET'),
        secure=True
    )

# Initialize Cloudinary configuration
configure_cloudinary()


def upload_file_to_cloudinary(file, filename, client_id, file_type='documents'):
    """
    Upload file to Cloudinary and return URLs
    
    Args:
        file: The file object to upload
        filename: The secure filename
        client_id: Client ID for organizing files
        file_type: 'documents' or other category
    
    Returns:
        tuple: (backend_view_url, cloudinary_url)
    """
    try:
        # Create folder structure in Cloudinary
        folder = f"streemlyne/{file_type}/{client_id}"
        
        # Reset file pointer
        file.seek(0)
        
        # Determine file type
        file_extension = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
        original_extension = file.filename.rsplit('.', 1)[-1].lower() if hasattr(file, 'filename') and '.' in file.filename else ''
        mime_type = file.mimetype if hasattr(file, 'mimetype') else ''
        
        extension = file_extension or original_extension
        
        current_app.logger.info(f"File upload - filename: {filename}, extension: {extension}, mime: {mime_type}")
        
        # Determine resource type for Cloudinary
        if extension in ['pdf', 'xlsx', 'xls', 'csv', 'doc', 'docx', 'txt', 'zip'] or \
           'pdf' in mime_type.lower() or \
           'spreadsheet' in mime_type.lower() or \
           'excel' in mime_type.lower() or \
           'document' in mime_type.lower():
            resource_type = 'raw'
        elif extension in ['png', 'jpg', 'jpeg', 'gif', 'webp', 'svg', 'bmp'] or \
             'image' in mime_type.lower():
            resource_type = 'image'
        else:
            resource_type = 'raw'
        
        current_app.logger.info(f"Uploading {filename} as resource_type='{resource_type}'")
        
        # Upload to Cloudinary
        upload_params = {
            'folder': folder,
            'public_id': filename.rsplit('.', 1)[0],
            'resource_type': resource_type,
            'overwrite': False,
            'unique_filename': True
        }
        
        upload_result = cloudinary.uploader.upload(file, **upload_params)
        
        cloudinary_url = upload_result['secure_url']
        public_id = upload_result['public_id']
        
        current_app.logger.info(f"File uploaded to Cloudinary: {public_id}")
        
        # Backend view URL for serving through our API
        backend_view_url = f"/files/view/{filename}"
        
        return backend_view_url, cloudinary_url
        
    except Exception as e:
        current_app.logger.error(f"Error uploading to Cloudinary: {e}", exc_info=True)
        raise Exception(f"Failed to upload file to Cloudinary: {str(e)}")


def delete_file_from_cloudinary(cloudinary_url):
    """Delete a file from Cloudinary using its URL"""
    try:
        # Extract public_id from URL
        # URL format: https://res.cloudinary.com/{cloud}/resource_type/upload/v{version}/{public_id}
        if not cloudinary_url or 'cloudinary' not in cloudinary_url:
            return False
        
        # Get the public_id (everything after /upload/)
        if '/upload/' in cloudinary_url:
            parts = cloudinary_url.split('/upload/')
            if len(parts) == 2:
                # Remove version if present (v1234567890/)
                public_id_part = parts[1]
                if public_id_part.startswith('v'):
                    # Skip version number
                    public_id_part = '/'.join(public_id_part.split('/')[1:])
                
                # Remove file extension for public_id
                public_id = public_id_part.rsplit('.', 1)[0]
                
                # Try to delete as 'raw' first
                result = cloudinary.uploader.destroy(public_id, resource_type='raw')
                
                # If raw deletion failed, try as image
                if result.get('result') != 'ok':
                    result = cloudinary.uploader.destroy(public_id, resource_type='image')
                
                # If still failed, try as video
                if result.get('result') != 'ok':
                    result = cloudinary.uploader.destroy(public_id, resource_type='video')
                
                success = result.get('result') == 'ok' or result.get('result') == 'not found'
                
                if success:
                    current_app.logger.info(f"File deleted from Cloudinary: {public_id}")
                else:
                    current_app.logger.warning(f"Could not delete from Cloudinary: {public_id}")
                
                return success
        
        return False
        
    except Exception as e:
        current_app.logger.error(f"Error deleting from Cloudinary: {e}", exc_info=True)
        return False


# ==========================================
# DOCUMENT ROUTES
# ==========================================

@file_bp.route('/files/documents', methods=['GET', 'POST', 'OPTIONS'])
@token_required
def handle_customer_documents():
    """
    GET: Fetch documents for a customer
    POST: Upload a document and save metadata
    """
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    session = SessionLocal()
    try:
        tenant_id = get_current_tenant_id()
        employee_id = get_current_employee_id()
        
        # --- Handle GET Request ---
        if request.method == 'GET':
            client_id = request.args.get('customer_id') or request.args.get('client_id')
            if not client_id:
                return jsonify({'error': 'Client ID is required'}), 400

            query = text("""
                SELECT 
                    id,
                    file_name,
                    file_url,
                    cloudinary_url,
                    document_category,
                    uploaded_at,
                    uploaded_by_employee_id
                FROM "StreemLyne_MT"."Customer_Documents"
                WHERE client_id = :client_id
                ORDER BY uploaded_at DESC
            """)
            
            result = session.execute(query, {'client_id': int(client_id)})
            documents = result.fetchall()
            
            docs_list = [{
                'id': doc.id,
                'file_name': doc.file_name,
                'file_url': doc.file_url,
                'cloudinary_url': doc.cloudinary_url,
                'category': doc.document_category,
                'uploaded_at': doc.uploaded_at.isoformat() if doc.uploaded_at else None,
                'uploaded_by': doc.uploaded_by_employee_id
            } for doc in documents]
            
            return jsonify(docs_list), 200

        # --- Handle POST Request ---
        elif request.method == 'POST':
            client_id = request.form.get('customer_id') or request.form.get('client_id')

            if not client_id:
                return jsonify({'error': 'Client ID is required'}), 400

            if 'file' not in request.files:
                return jsonify({'error': 'No file in request'}), 400

            file = request.files['file']
            if file.filename == '':
                return jsonify({'error': 'No file selected'}), 400

            # Security
            filename = secure_filename(file.filename)
            unique_filename = f"{client_id}_{str(uuid.uuid4())}_{filename}"
            
            # Upload to Cloudinary
            backend_view_url, cloudinary_url = upload_file_to_cloudinary(
                file, unique_filename, client_id, 'documents'
            )
            
            # Determine category
            mime_type = file.mimetype
            if 'image' in mime_type:
                category = 'Image'
            elif 'pdf' in mime_type:
                category = 'PDF'
            elif 'spreadsheet' in mime_type or 'excel' in mime_type:
                category = 'Spreadsheet'
            else:
                category = 'Other'
            
            # Insert into database
            insert_query = text("""
                INSERT INTO "StreemLyne_MT"."Customer_Documents" (
                    client_id,
                    file_name,
                    file_url,
                    cloudinary_url,
                    document_category,
                    uploaded_by_employee_id,
                    uploaded_at
                ) VALUES (
                    :client_id,
                    :file_name,
                    :file_url,
                    :cloudinary_url,
                    :category,
                    :employee_id,
                    :uploaded_at
                )
                RETURNING id
            """)
            
            result = session.execute(insert_query, {
                'client_id': int(client_id),
                'file_name': filename,
                'file_url': backend_view_url,
                'cloudinary_url': cloudinary_url,
                'category': category,
                'employee_id': employee_id,
                'uploaded_at': datetime.utcnow()
            })
            
            doc_id = result.fetchone()[0]
            session.commit()
            
            current_app.logger.info(f"Document saved for client {client_id}: {filename}")
            
            return jsonify({
                'success': True,
                'message': 'File uploaded successfully',
                'document': {
                    'id': doc_id,
                    'file_name': filename,
                    'file_url': backend_view_url,
                    'category': category
                }
            }), 201

    except Exception as e:
        session.rollback()
        current_app.logger.error(f"Error handling documents: {e}", exc_info=True)
        return jsonify({'error': f'Operation failed: {str(e)}'}), 500
    finally:
        session.close()


@file_bp.route('/files/documents/<int:document_id>', methods=['DELETE', 'OPTIONS'])
@token_required
def delete_customer_document(document_id):
    """Delete a document from Cloudinary and database"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    session = SessionLocal()
    try:
        # Get document info
        query = text("""
            SELECT cloudinary_url
            FROM "StreemLyne_MT"."Customer_Documents"
            WHERE id = :document_id
        """)
        
        result = session.execute(query, {'document_id': document_id})
        doc = result.fetchone()
        
        if not doc:
            return jsonify({'error': 'Document not found'}), 404

        # Delete from Cloudinary
        if doc.cloudinary_url:
            delete_file_from_cloudinary(doc.cloudinary_url)

        # Delete from database
        delete_query = text("""
            DELETE FROM "StreemLyne_MT"."Customer_Documents"
            WHERE id = :document_id
        """)
        
        session.execute(delete_query, {'document_id': document_id})
        session.commit()
        
        return jsonify({'success': True, 'message': 'Document deleted successfully'}), 200

    except Exception as e:
        session.rollback()
        current_app.logger.error(f"Error deleting document {document_id}: {e}", exc_info=True)
        return jsonify({'error': f'Failed to delete: {str(e)}'}), 500
    finally:
        session.close()


@file_bp.route('/files/view/<filename>', methods=['GET'])
def view_customer_document(filename):
    """Serve document via Cloudinary or proxy for PDFs"""
    session = SessionLocal()
    try:
        # Look up document
        query = text("""
            SELECT 
                file_name,
                cloudinary_url,
                document_category
            FROM "StreemLyne_MT"."Customer_Documents"
            WHERE file_name LIKE :filename
            OR cloudinary_url LIKE :filename_pattern
            LIMIT 1
        """)
        
        result = session.execute(query, {
            'filename': f"%{filename}%",
            'filename_pattern': f"%{filename}%"
        })
        doc = result.fetchone()
        
        if not doc or not doc.cloudinary_url:
            return jsonify({'error': 'File not found'}), 404
        
        cloudinary_url = doc.cloudinary_url
        
        # Check if it's a PDF
        is_pdf = '.pdf' in cloudinary_url.lower() or doc.document_category == 'PDF'
        
        if is_pdf:
            # Fetch PDF from Cloudinary and serve with inline disposition
            response = requests.get(cloudinary_url, timeout=30)
            
            if response.status_code == 200:
                return Response(
                    response.content,
                    mimetype='application/pdf',
                    headers={
                        'Content-Disposition': f'inline; filename="{doc.file_name}"',
                        'Content-Type': 'application/pdf',
                        'Cache-Control': 'public, max-age=3600'
                    }
                )
            else:
                return jsonify({'error': 'Failed to fetch PDF'}), 500
        else:
            # For images and other files, redirect to Cloudinary
            return redirect(cloudinary_url)
        
    except Exception as e:
        current_app.logger.error(f"Error serving document {filename}: {e}", exc_info=True)
        return jsonify({'error': f'Failed to retrieve file: {str(e)}'}), 500
    finally:
        session.close()


# ==========================================
# LEGACY COMPATIBILITY ROUTES
# ==========================================

# Drawings endpoints (alias for documents)
@file_bp.route('/files/drawings', methods=['GET', 'POST', 'OPTIONS'])
@token_required
def handle_customer_drawings():
    """Legacy endpoint - redirects to documents"""
    return handle_customer_documents()


@file_bp.route('/files/drawings/<int:drawing_id>', methods=['DELETE', 'OPTIONS'])
@token_required
def delete_customer_drawing(drawing_id):
    """Legacy endpoint - redirects to documents"""
    return delete_customer_document(drawing_id)


@file_bp.route('/files/drawings/view/<filename>', methods=['GET'])
def view_customer_drawing(filename):
    """Legacy endpoint - redirects to documents"""
    return view_customer_document(filename)


# Forms endpoints (returns empty for compatibility)
@file_bp.route('/files/forms', methods=['GET', 'POST', 'OPTIONS'])
@token_required
def handle_form_documents():
    """Legacy endpoint - forms not implemented in StreemLyne_MT"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    if request.method == 'GET':
        return jsonify([]), 200
    
    return jsonify({'error': 'Form documents not implemented'}), 501


@file_bp.route('/files/forms/view/<filename>', methods=['GET'])
def view_form_document(filename):
    """Legacy endpoint - forms not implemented"""
    return jsonify({'error': 'Form documents not implemented'}), 501


@file_bp.route('/files/forms/<form_doc_id>', methods=['DELETE', 'OPTIONS'])
@token_required
def delete_form_document(form_doc_id):
    """Legacy endpoint - forms not implemented"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    return jsonify({'error': 'Form documents not implemented'}), 501