from flask import request, jsonify, send_file, Blueprint, current_app, redirect, Response
from werkzeug.utils import secure_filename
from datetime import datetime
import os
import uuid 
import requests
import cloudinary
import cloudinary.uploader
import cloudinary.api
from ..utils.file_utils import allowed_file
from ..models import DrawingDocument, FormDocument
from .auth_helpers import token_required 
from ..db import SessionLocal 
from sqlalchemy import or_

try:
    from pdf_generator import generate_pdf
    from excel_exporter import export_to_excel
except ImportError as e:
    print(f"Warning: Could not import PDF/Excel generators: {e}")
    def generate_pdf(data, filename):
        print("PDF generator not available")
        return f"generated_pdfs/{filename}"
    def export_to_excel(data, customer_name):
        print("Excel exporter not available")
        return f"generated_excel/{customer_name}_data.xlsx"

file_bp = Blueprint('file_routes', __name__)

latest_structured_data = {}

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

def upload_file_to_cloudinary(file, filename, customer_id, file_type='drawings'):
    """
    Upload file to Cloudinary and return the URL and public_id
    
    Args:
        file: The file object to upload
        filename: The secure filename
        customer_id: Customer ID for organizing files
        file_type: 'drawings' or 'forms'
    
    Returns:
        tuple: (view_url, public_id)
    """
    try:
        # Create folder structure in Cloudinary
        folder = f"aztec-interiors/{file_type}/{customer_id}"
        
        # Reset file pointer to beginning
        file.seek(0)
        
        # Determine resource type based on file extension and MIME type
        # Check both the filename and the original file.filename
        file_extension = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
        original_extension = file.filename.rsplit('.', 1)[-1].lower() if hasattr(file, 'filename') and '.' in file.filename else ''
        mime_type = file.mimetype if hasattr(file, 'mimetype') else ''
        
        # Use either extension
        extension = file_extension or original_extension
        
        current_app.logger.info(f"File upload details - filename: {filename}, original: {getattr(file, 'filename', 'N/A')}, extension: {extension}, mime: {mime_type}")
        
        # PDFs, Excel, Word docs, and other documents should be 'raw'
        # Images should be 'image'
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
            # Default to 'raw' for unknown types
            resource_type = 'raw'
        
        current_app.logger.info(f"Uploading {filename} as resource_type='{resource_type}' (extension: {extension}, mime: {mime_type})")
        
        # Upload to Cloudinary
        upload_params = {
            'folder': folder,
            'public_id': filename.rsplit('.', 1)[0],  # Use filename without extension
            'resource_type': resource_type,
            'overwrite': False,
            'unique_filename': True
        }
        
        upload_result = cloudinary.uploader.upload(file, **upload_params)
        
        cloudinary_url = upload_result['secure_url']
        public_id = upload_result['public_id']
        
        current_app.logger.info(f"File uploaded to Cloudinary: {public_id} at {cloudinary_url}")
        
        # IMPORTANT: For the database, store the backend view URL, not the Cloudinary URL
        # This ensures all files go through our backend which handles PDFs correctly
        # We store the Cloudinary URL in storage_path for reference
        backend_view_url = f"/files/{file_type}/view/{filename}"
        
        # Return backend URL (not Cloudinary URL) so it gets stored in file_url
        return backend_view_url, cloudinary_url  # Return both: backend URL and Cloudinary URL
        
    except Exception as e:
        current_app.logger.error(f"Error uploading to Cloudinary: {e}", exc_info=True)
        raise Exception(f"Failed to upload file to Cloudinary: {str(e)}")

def delete_file_from_cloudinary(public_id):
    """Delete a file from Cloudinary"""
    try:
        # Try to delete as 'raw' first (PDFs, Excel, etc.)
        result = cloudinary.uploader.destroy(public_id, resource_type='raw')
        
        # If raw deletion failed, try as image
        if result.get('result') != 'ok':
            result = cloudinary.uploader.destroy(public_id, resource_type='image')
        
        # If still failed, try as video (just in case)
        if result.get('result') != 'ok':
            result = cloudinary.uploader.destroy(public_id, resource_type='video')
        
        success = result.get('result') == 'ok' or result.get('result') == 'not found'
        
        if success:
            current_app.logger.info(f"File deleted from Cloudinary: {public_id}")
        else:
            current_app.logger.warning(f"Could not delete from Cloudinary: {public_id}, result: {result}")
        
        return success
        
    except Exception as e:
        current_app.logger.error(f"Error deleting from Cloudinary: {e}", exc_info=True)
        return False

def fix_pdf_url_for_inline_display(url):
    """
    Convert a Cloudinary PDF URL to display inline instead of download
    Uses proper Cloudinary transformation syntax with fl_attachment flag
    """
    if not url or 'cloudinary' not in url:
        return url
    
    # Check if it's a PDF URL (either has .pdf or is in /raw/ path)
    if '.pdf' not in url.lower() and '/raw/' not in url:
        return url
    
    # If already has the flag, return as-is
    if 'fl_attachment' in url:
        return url
    
    # Cloudinary URL structure: 
    # https://res.cloudinary.com/{cloud_name}/{resource_type}/upload/{transformations}/{version}/{path}
    
    # Add the inline display flag using proper transformation syntax
    if '/upload/' in url:
        # Split the URL at /upload/
        parts = url.split('/upload/')
        if len(parts) == 2:
            # Reconstruct with transformation
            # Use fl_attachment (not fl_attachment:false) to force inline display
            url = f"{parts[0]}/upload/fl_attachment/{parts[1]}"
    
    return url

# ==========================================
# Helper Function for Local Folders (for non-S3 files)
# ==========================================

def get_drawing_folder():
    """Gets the configured drawing upload folder path (for legacy/local storage)"""
    folder = current_app.config.get('DRAWING_UPLOAD_FOLDER')
    if not folder:
        folder = os.path.join(current_app.root_path, 'customer_drawings')
    os.makedirs(folder, exist_ok=True)
    return folder

def get_form_document_folder():
    """Gets the configured form document upload folder path (for legacy/local storage)"""
    folder = current_app.config.get('FORM_DOCUMENT_UPLOAD_FOLDER')
    if not folder:
        folder = os.path.join(current_app.root_path, 'form_documents')
    os.makedirs(folder, exist_ok=True)
    return folder

# ==========================================
# CUSTOMER DRAWINGS ROUTES
# ==========================================

@file_bp.route('/files/drawings', methods=['GET', 'POST', 'OPTIONS'])
@token_required
def handle_customer_drawings():
    """
    GET: Fetch drawing documents for a customer.
    POST: Upload a drawing/layout image or PDF and save its metadata to S3.
    """
    if request.method == 'OPTIONS':
        response = jsonify()
        response.headers.add("Access-Control-Allow-Origin", "*")
        response.headers.add('Access-Control-Allow-Headers', "Content-Type, Authorization")
        response.headers.add('Access-Control-Allow-Methods', "GET, POST, OPTIONS")
        return response

    # --- Handle GET Request ---
    if request.method == 'GET':
        customer_id = request.args.get('customer_id')
        if not customer_id:
            return jsonify({'error': 'Customer ID query parameter is required'}), 400

        session = SessionLocal()
        try:
            drawings = session.query(DrawingDocument)\
                               .filter(DrawingDocument.customer_id == customer_id)\
                               .order_by(DrawingDocument.created_at.desc())\
                               .all()

            result = [d.to_dict() for d in drawings]
            return jsonify(result), 200

        except Exception as e:
            current_app.logger.error(f"Error fetching drawings for customer {customer_id}: {e}", exc_info=True)
            return jsonify({'error': f'Failed to fetch drawings: {str(e)}'}), 500
        finally:
            session.close()

    # --- Handle POST Request ---
    elif request.method == 'POST':
        session = SessionLocal()
        try:
            customer_id = request.form.get('customer_id')
            project_id = request.form.get('project_id')

            if not customer_id:
                return jsonify({'error': 'Customer ID is missing from form data'}), 400

            if 'file' not in request.files:
                return jsonify({'error': 'No file part in the request'}), 400

            file = request.files['file']
            if file.filename == '':
                return jsonify({'error': 'No file selected for upload'}), 400

            # Security
            filename = secure_filename(file.filename)
            unique_filename = f"{customer_id}_{str(uuid.uuid4())}_{filename}"
            
            # Upload to Cloudinary - returns backend view URL and Cloudinary URL
            backend_view_url, cloudinary_url = upload_file_to_cloudinary(file, unique_filename, customer_id, 'drawings')
            
            # Determine file category
            mime_type = file.mimetype
            if 'image' in mime_type:
                category = 'image'
            elif 'pdf' in mime_type:
                category = 'pdf'
            else:
                category = 'other'
            
            # Safely determine uploaded_by name
            uploaded_by = 'System'
            if hasattr(request, 'current_user') and request.current_user:
                if hasattr(request.current_user, 'full_name'):
                    uploaded_by = request.current_user.full_name
                elif hasattr(request.current_user, 'email'):
                    uploaded_by = request.current_user.email

            # Create database record
            new_drawing = DrawingDocument(
                id=str(uuid.uuid4()),
                customer_id=customer_id,
                project_id=project_id if project_id else None,
                file_name=filename,
                storage_path=cloudinary_url,  # Store actual Cloudinary URL for backend reference
                file_url=backend_view_url,     # Store backend view URL (what user clicks)
                mime_type=mime_type,
                category=category,
                uploaded_by=uploaded_by
            )

            session.add(new_drawing)
            session.commit()

            current_app.logger.info(f"Drawing saved for customer {customer_id}: {filename} to Cloudinary")

            return jsonify({
                'success': True,
                'message': 'File uploaded and metadata saved successfully',
                'drawing': new_drawing.to_dict()
            }), 201

        except Exception as e:
            session.rollback()
            current_app.logger.error(f"Error processing drawing upload: {str(e)}", exc_info=True)
            return jsonify({'error': f'Upload failed: {str(e)}'}), 500
        finally:
            session.close()

    return jsonify({'error': 'Method Not Allowed'}), 405


@file_bp.route('/files/drawings/<drawing_id>', methods=['DELETE', 'OPTIONS'])
@token_required
def delete_customer_drawing(drawing_id):
    """Delete a drawing from both Cloudinary and database"""
    if request.method == 'OPTIONS':
        resp = jsonify()
        resp.headers.add('Access-Control-Allow-Origin', '*')
        resp.headers.add('Access-Control-Allow-Headers', 'Content-Type, Authorization')
        resp.headers.add('Access-Control-Allow-Methods', 'DELETE, OPTIONS')
        return resp

    session = SessionLocal()
    try:
        drawing = session.get(DrawingDocument, drawing_id)
        if not drawing:
            return jsonify({'error': 'Drawing not found'}), 404

        # Delete from Cloudinary
        if drawing.storage_path:
            delete_file_from_cloudinary(drawing.storage_path)

        # Delete from database
        session.delete(drawing)
        session.commit()

        return jsonify({'success': True, 'message': 'Drawing deleted successfully'}), 200

    except Exception as e:
        session.rollback()
        current_app.logger.error(f"Error deleting drawing {drawing_id}: {e}", exc_info=True)
        return jsonify({'error': f'Failed to delete. Server error: {str(e)}'}), 500
    finally:
        session.close()


@file_bp.route('/files/drawings/view/<filename>', methods=['GET'])
def view_customer_drawing(filename):
    """Serve the uploaded file via Cloudinary URL or fetch and serve with inline headers for PDFs"""
    session = SessionLocal()
    try:
        # Look up the drawing record
        drawing_record = session.query(DrawingDocument).filter(
            or_(
                DrawingDocument.storage_path.like(f"%{filename}"),
                DrawingDocument.file_url.like(f"%{filename}"),
                DrawingDocument.file_name.like(f"%{filename}")
            )
        ).first()

        if not drawing_record:
            return jsonify({'error': 'File not found in database'}), 404
        
        # Get the actual Cloudinary URL from storage_path
        cloudinary_url = drawing_record.storage_path
        
        # Check if it's a PDF
        is_pdf = cloudinary_url and ('.pdf' in cloudinary_url.lower() or 
                                      drawing_record.mime_type == 'application/pdf')
        
        if is_pdf:
            # For PDFs, fetch from Cloudinary and serve with inline disposition
            response = requests.get(cloudinary_url, timeout=30)
            
            if response.status_code == 200:
                return Response(
                    response.content,
                    mimetype='application/pdf',
                    headers={
                        'Content-Disposition': 'inline; filename="' + drawing_record.file_name + '"',
                        'Content-Type': 'application/pdf',
                        'Cache-Control': 'public, max-age=3600'
                    }
                )
            else:
                current_app.logger.error(f"Failed to fetch PDF from Cloudinary: {response.status_code}")
                return jsonify({'error': f'Failed to fetch PDF from storage (status: {response.status_code})'}), 500
        else:
            # For images and other files, just redirect to Cloudinary
            return redirect(cloudinary_url)
        
    except Exception as e:
        current_app.logger.error(f"Error serving drawing {filename}: {e}", exc_info=True)
        return jsonify({'error': f'Failed to retrieve file: {str(e)}'}), 500
    finally:
        session.close()


# ==========================================
# FORM DOCUMENTS ROUTES
# ==========================================

@file_bp.route('/files/forms', methods=['GET', 'POST', 'OPTIONS'])
@token_required
def handle_form_documents():
    """
    GET: Fetch form documents for a customer.
    POST: Upload a form document (Excel/PDF) and save its metadata to S3.
    """
    if request.method == 'OPTIONS':
        response = jsonify()
        response.headers.add("Access-Control-Allow-Origin", "*")
        response.headers.add('Access-Control-Allow-Headers', "Content-Type, Authorization")
        response.headers.add('Access-Control-Allow-Methods', "GET, POST, OPTIONS")
        return response

    # --- Handle GET Request ---
    if request.method == 'GET':
        customer_id = request.args.get('customer_id')
        if not customer_id:
            return jsonify({'error': 'Customer ID query parameter is required'}), 400

        session = SessionLocal()
        try:
            form_docs = session.query(FormDocument)\
                               .filter(FormDocument.customer_id == customer_id)\
                               .order_by(FormDocument.created_at.desc())\
                               .all()

            result = [d.to_dict() for d in form_docs]
            return jsonify(result), 200

        except Exception as e:
            current_app.logger.error(f"Error fetching form documents for customer {customer_id}: {e}", exc_info=True)
            return jsonify({'error': f'Failed to fetch form documents: {str(e)}'}), 500
        finally:
            session.close()

    # --- Handle POST Request ---
    elif request.method == 'POST':
        session = SessionLocal()
        try:
            customer_id = request.form.get('customer_id')

            if not customer_id:
                return jsonify({'error': 'Customer ID is missing from form data'}), 400

            if 'file' not in request.files:
                return jsonify({'error': 'No file part in the request'}), 400

            file = request.files['file']
            if file.filename == '':
                return jsonify({'error': 'No file selected for upload'}), 400

            # Security
            filename = secure_filename(file.filename)
            unique_filename = f"{customer_id}_{str(uuid.uuid4())}_{filename}"
            
            # Upload to Cloudinary - returns backend view URL and Cloudinary URL
            backend_view_url, cloudinary_url = upload_file_to_cloudinary(file, unique_filename, customer_id, 'forms')

            # Determine file category
            mime_type = file.mimetype
            file_extension = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
            
            if 'pdf' in mime_type or file_extension == 'pdf':
                category = 'pdf'
            elif file_extension in ['xlsx', 'xls', 'csv'] or 'spreadsheet' in mime_type or 'excel' in mime_type:
                category = 'excel'
            else:
                category = 'other'
            
            # Safely determine uploaded_by name
            uploaded_by = 'System'
            if hasattr(request, 'current_user') and request.current_user:
                if hasattr(request.current_user, 'full_name'):
                    uploaded_by = request.current_user.full_name
                elif hasattr(request.current_user, 'email'):
                    uploaded_by = request.current_user.email

            # Create database record
            new_form_doc = FormDocument(
                id=str(uuid.uuid4()),
                customer_id=customer_id,
                file_name=filename,
                storage_path=cloudinary_url,  # Store actual Cloudinary URL for backend reference
                file_url=backend_view_url,     # Store backend view URL (what user clicks)
                mime_type=mime_type,
                category=category,
                uploaded_by=uploaded_by
            )

            session.add(new_form_doc)
            session.commit()

            current_app.logger.info(f"Form document saved for customer {customer_id}: {filename} to Cloudinary")

            return jsonify({
                'success': True,
                'message': 'File uploaded and metadata saved successfully',
                'form_document': new_form_doc.to_dict()
            }), 201

        except Exception as e:
            session.rollback()
            current_app.logger.error(f"Error processing form document upload: {str(e)}", exc_info=True)
            return jsonify({'error': f'Upload failed: {str(e)}'}), 500
        finally:
            session.close()

    return jsonify({'error': 'Method Not Allowed'}), 405


@file_bp.route('/files/forms/view/<filename>', methods=['GET'])
def view_form_document(filename):
    """Serve the uploaded form document via Cloudinary URL or fetch and serve with inline headers for PDFs"""
    session = SessionLocal()
    try:
        form_doc = session.query(FormDocument).filter(
            or_(
                FormDocument.storage_path.like(f"%{filename}"),
                FormDocument.file_url.like(f"%{filename}"),
                FormDocument.file_name.like(f"%{filename}")
            )
        ).first()

        if not form_doc:
            return jsonify({'error': 'File not found in database'}), 404
        
        # Get the actual Cloudinary URL from storage_path
        cloudinary_url = form_doc.storage_path
        
        # Check if it's a PDF
        is_pdf = cloudinary_url and ('.pdf' in cloudinary_url.lower() or 
                                     form_doc.mime_type == 'application/pdf')
        
        if is_pdf:
            # For PDFs, fetch from Cloudinary and serve with inline disposition
            response = requests.get(cloudinary_url, timeout=30)
            
            if response.status_code == 200:
                return Response(
                    response.content,
                    mimetype='application/pdf',
                    headers={
                        'Content-Disposition': 'inline; filename="' + form_doc.file_name + '"',
                        'Content-Type': 'application/pdf',
                        'Cache-Control': 'public, max-age=3600'
                    }
                )
            else:
                current_app.logger.error(f"Failed to fetch PDF from Cloudinary: {response.status_code}")
                return jsonify({'error': f'Failed to fetch PDF from storage (status: {response.status_code})'}), 500
        else:
            # For other files, just redirect to Cloudinary
            return redirect(cloudinary_url)
        
    except Exception as e:
        current_app.logger.error(f"Error serving form document {filename}: {e}", exc_info=True)
        return jsonify({'error': f'Failed to retrieve file: {str(e)}'}), 500
    finally:
        session.close()


@file_bp.route('/files/forms/<form_doc_id>', methods=['DELETE', 'OPTIONS'])
@token_required
def delete_form_document(form_doc_id):
    """Delete a form document from both Cloudinary and database"""
    if request.method == 'OPTIONS':
        resp = jsonify()
        resp.headers.add('Access-Control-Allow-Origin', '*')
        resp.headers.add('Access-Control-Allow-Headers', 'Content-Type, Authorization')
        resp.headers.add('Access-Control-Allow-Methods', 'DELETE, OPTIONS')
        return resp

    session = SessionLocal()
    try:
        form_doc = session.get(FormDocument, form_doc_id)
        if not form_doc:
            return jsonify({'error': 'Form document not found'}), 404

        # Delete from Cloudinary
        if form_doc.storage_path:
            delete_file_from_cloudinary(form_doc.storage_path)

        # Delete from database
        session.delete(form_doc)
        session.commit()

        return jsonify({'success': True, 'message': 'Form document deleted successfully'}), 200

    except Exception as e:
        session.rollback()
        current_app.logger.error(f"Error deleting form document {form_doc_id}: {e}", exc_info=True)
        return jsonify({'error': f'Failed to delete. Server error: {str(e)}'}), 500
    finally:
        session.close()


# ==========================================
# LEGACY ROUTES (Keep for backwards compatibility)
# ==========================================

@file_bp.route('/upload', methods=['POST', 'OPTIONS'])
def upload_image():
    if request.method == 'OPTIONS':
        response = jsonify()
        response.headers.add("Access-Control-Allow-Origin", "*")
        response.headers.add('Access-Control-Allow-Headers', "Content-Type")
        response.headers.add('Access-Control-Allow-Methods', "POST,OPTIONS")
        return response

    try:
        if 'image' not in request.files:
            return jsonify({'error': 'No file uploaded'}), 400

        file = request.files['image']
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        if not allowed_file(file.filename):
            return jsonify({'error': 'Invalid file type'}), 400

        filename = secure_filename(file.filename)
        file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)

        structured_data = {'customer_name': 'DemoCustomer', 'data': 'Processed successfully'}
        
        pdf_filename = filename.rsplit('.', 1)[0] + '.pdf'
        pdf_path = generate_pdf(structured_data, pdf_filename)

        customer_name = structured_data.get('customer_name', 'N/A')
        excel_path = export_to_excel(structured_data, customer_name)

        os.remove(file_path)

        global latest_structured_data
        latest_structured_data.update(structured_data)

        return jsonify({
            'success': True,
            'structured_data': structured_data,
            'pdf_download_url': f'/download/{os.path.basename(pdf_path)}',
            'excel_download_url': f'/download-excel/{os.path.basename(excel_path)}',
            'view_data_url': '/view-data'
        })

    except Exception as e:
        current_app.logger.error(f"Error processing upload: {e}", exc_info=True)
        return jsonify({'error': f'Processing failed: {str(e)}'}), 500


@file_bp.route('/generate-pdf', methods=['POST', 'OPTIONS'])
def generate_pdf_from_form():
    if request.method == 'OPTIONS':
        response = jsonify()
        response.headers.add("Access-Control-Allow-Origin", "*")
        response.headers.add('Access-Control-Allow-Headers', "Content-Type")
        response.headers.add('Access-Control-Allow-Methods', "POST,OPTIONS")
        return response

    try:
        data = request.json.get('data', {})
        if not data:
            return jsonify({'error': 'No form data provided'}), 400

        customer_name = data.get('customer_name', 'Unknown')
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        clean_name = "".join(c for c in customer_name if c.isalnum() or c in (' ', '-', '_')).rstrip().replace(' ', '_')
        pdf_filename = f"{clean_name}_{timestamp}.pdf" if customer_name != 'Unknown' else f"form_{timestamp}.pdf"

        pdf_path = generate_pdf(data, pdf_filename)

        global latest_structured_data
        latest_structured_data.update(data)

        return jsonify({
            'success': True,
            'pdf_download_url': f'/download/{os.path.basename(pdf_path)}',
            'message': 'PDF generated successfully'
        })

    except Exception as e:
        current_app.logger.error(f"Error generating PDF: {e}", exc_info=True)
        return jsonify({'error': f'PDF generation failed: {str(e)}'}), 500


@file_bp.route('/generate-excel', methods=['POST', 'OPTIONS'])
def generate_excel_from_form():
    if request.method == 'OPTIONS':
        response = jsonify()
        response.headers.add("Access-Control-Allow-Origin", "*")
        response.headers.add('Access-Control-Allow-Headers', "Content-Type")
        response.headers.add('Access-Control-Allow-Methods', "POST,OPTIONS")
        return response

    try:
        data = request.json.get('data', {})
        if not data:
            return jsonify({'error': 'No form data provided'}), 400

        customer_name = data.get('customer_name', 'Unknown')
        excel_path = export_to_excel(data, customer_name)

        return jsonify({
            'success': True,
            'excel_download_url': f'/download-excel/{os.path.basename(excel_path)}',
            'message': 'Excel file generated successfully'
        })

    except Exception as e:
        current_app.logger.error(f"Error generating Excel: {e}", exc_info=True)
        return jsonify({'error': f'Excel generation failed: {str(e)}'}), 500


@file_bp.route('/download/<filename>')
def download_file(filename):
    try:
        pdf_folder = os.path.join(current_app.root_path, 'generated_pdfs')
        return send_file(os.path.join(pdf_folder, filename), as_attachment=True)
    except FileNotFoundError:
        return jsonify({'error': 'File not found'}), 404
    except Exception as e:
        current_app.logger.error(f"Error downloading: {e}", exc_info=True)
        return jsonify({'error': f'Download failed: {str(e)}'}), 500


@file_bp.route('/download-excel/<filename>')
def download_excel_file(filename):
    try:
        excel_folder = os.path.join(current_app.root_path, 'generated_excel')
        return send_file(os.path.join(excel_folder, filename), as_attachment=True)
    except FileNotFoundError:
        return jsonify({'error': 'File not found'}), 404
    except Exception as e:
        current_app.logger.error(f"Error downloading: {e}", exc_info=True)
        return jsonify({'error': f'Download failed: {str(e)}'}), 500