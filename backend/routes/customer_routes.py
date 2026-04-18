"""
Customer Routes - Adapted for StreemLyne_MT schema
Handles customer/client management and related operations
"""
from flask import Blueprint, request, jsonify, current_app
from sqlalchemy import text, func
from datetime import datetime
import uuid
import json

from ..db import SessionLocal
from .auth_helpers import token_required, get_current_tenant_id, get_current_employee_id

customer_bp = Blueprint('customers', __name__)

# Define stage hierarchy for determining "most advanced" stage
STAGE_HIERARCHY = {
    "Lead": 0,
    "Quote": 1,
    "Consultation": 2,
    "Survey": 3,
    "Measure": 4,
    "Design": 5,
    "Quoted": 6,
    "Accepted": 7,
    "Rejected": 8,
    "Ordered": 9,
    "Production": 10,
    "Delivery": 11,
    "Installation": 12,
    "Complete": 13,
    "Remedial": 14,
    "Cancelled": 15
}


def get_most_advanced_stage(stages):
    """Given a list of stage strings, return the most advanced one"""
    if not stages:
        return "Lead"
    
    valid_stages = [s for s in stages if s and s in STAGE_HIERARCHY]
    if not valid_stages:
        return "Lead"
    
    return max(valid_stages, key=lambda s: STAGE_HIERARCHY.get(s, 0))


# ==========================================
# CLIENT/CUSTOMER ENDPOINTS
# ==========================================

@customer_bp.route('/customers', methods=['GET', 'OPTIONS'])
@token_required
def get_customers():
    """Get all clients/customers with their opportunity counts and document counts"""
    
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        tenant_id = get_current_tenant_id()
        
        # Get all clients for tenant
        query = text("""
            SELECT 
                c.client_id,
                c.client_company_name,
                c.client_contact_name,
                c.client_phone,
                c.client_mobile,
                c.client_email,
                c.address,
                c.post_code,
                c.stage,
                c.created_at,
                c.assigned_employee_id,
                c.is_deleted,
                c.is_archived,
                e.employee_name as salesperson_name,
                COUNT(DISTINCT o.opportunity_id) as opportunity_count,
                COUNT(DISTINCT cd.id) as document_count
            FROM "StreemLyne_MT"."Client_Master" c
            LEFT JOIN "StreemLyne_MT"."Employee_Master" e ON c.assigned_employee_id = e.employee_id
            LEFT JOIN "StreemLyne_MT"."Opportunity_Details" o ON c.client_id = o.client_id AND o.deleted_at IS NULL
            LEFT JOIN "StreemLyne_MT"."Customer_Documents" cd ON c.client_id = cd.client_id
            WHERE c.tenant_id = :tenant_id
            AND c.is_deleted = false
            GROUP BY c.client_id, e.employee_name
            ORDER BY c.created_at DESC
        """)
        
        result = session.execute(query, {'tenant_id': tenant_id})
        clients = result.fetchall()
        
        current_app.logger.info(f"📊 Fetching data for {len(clients)} clients")
        
        customers = []
        for client in clients:
            customer_data = {
                'id': client.client_id,
                'name': client.client_company_name or client.client_contact_name or 'Unknown',
                'phone': client.client_phone or client.client_mobile or '',
                'email': client.client_email or '',
                'address': client.address or '',
                'postcode': client.post_code or '',
                'salesperson': client.salesperson_name or '',
                'stage': client.stage or 'Lead',
                'status': 'Archived' if client.is_archived else 'Active',
                'created_at': client.created_at.isoformat() if client.created_at else None,
                'project_count': client.opportunity_count or 0,
                'total_documents': client.document_count or 0,
                'has_documents': (client.document_count or 0) > 0,
                # Legacy fields for compatibility
                'contact_made': 'Unknown',
                'preferred_contact_method': 'Phone',
                'marketing_opt_in': False,
                'notes': '',
                'form_count': 0,
                'drawing_count': 0,
                'form_document_count': 0,
                'has_drawings': False,
                'has_forms': False,
                'project_types': []
            }
            customers.append(customer_data)
        
        current_app.logger.info(f"✅ Returning {len(customers)} customers")
        
        return jsonify(customers), 200
        
    except Exception as e:
        current_app.logger.exception(f"❌ Error fetching customers: {e}")
        return jsonify({'error': 'Failed to fetch customers'}), 500
    finally:
        session.close()


@customer_bp.route('/customers', methods=['POST', 'OPTIONS'])
@token_required
def create_customer():
    """Create a new client/customer"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        tenant_id = get_current_tenant_id()
        employee_id = get_current_employee_id()
        
        data = request.get_json()
        
        current_app.logger.info(f"📝 Creating new customer with data: {data}")
        
        # Validate required fields
        if not data.get('name'):
            return jsonify({'error': 'Name is required'}), 400
        if not data.get('phone'):
            return jsonify({'error': 'Phone is required'}), 400
        
        # Determine if it's a company or individual
        is_company = bool(data.get('client_company_name'))
        
        # Insert new client
        insert_query = text("""
            INSERT INTO "StreemLyne_MT"."Client_Master" (
                tenant_id,
                client_company_name,
                client_contact_name,
                client_phone,
                client_mobile,
                client_email,
                address,
                post_code,
                stage,
                assigned_employee_id,
                created_at,
                is_deleted,
                is_archived
            ) VALUES (
                :tenant_id,
                :company_name,
                :contact_name,
                :phone,
                :mobile,
                :email,
                :address,
                :postcode,
                :stage,
                :assigned_employee_id,
                :created_at,
                false,
                false
            )
            RETURNING client_id
        """)
        
        name = data.get('name', '')
        
        result = session.execute(insert_query, {
            'tenant_id': tenant_id,
            'company_name': name if is_company else None,
            'contact_name': name if not is_company else data.get('contact_name'),
            'phone': data.get('phone'),
            'mobile': data.get('mobile'),
            'email': data.get('email', ''),
            'address': data.get('address', ''),
            'postcode': data.get('postcode', ''),
            'stage': 'Lead',
            'assigned_employee_id': employee_id,
            'created_at': datetime.utcnow()
        })
        
        client_id = result.fetchone()[0]
        session.commit()
        
        current_app.logger.info(f"✅ Client {client_id} created successfully")
        
        return jsonify({
            'success': True,
            'message': 'Customer created successfully',
            'customer': {
                'id': client_id,
                'name': name,
                'phone': data.get('phone'),
                'email': data.get('email', ''),
                'address': data.get('address', ''),
                'postcode': data.get('postcode', ''),
                'stage': 'Lead',
                'status': 'Active',
                'created_at': datetime.utcnow().isoformat(),
                'project_count': 0,
                'total_documents': 0,
                'has_documents': False
            }
        }), 201
        
    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"❌ Error creating customer: {e}")
        return jsonify({'error': f'Failed to create customer: {str(e)}'}), 500
    finally:
        session.close()


@customer_bp.route('/customers/<int:customer_id>', methods=['GET', 'OPTIONS'])
@token_required
def get_customer(customer_id):
    """Get a single customer by ID with all their opportunities"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        tenant_id = get_current_tenant_id()
        
        # Get customer info
        customer_query = text("""
            SELECT 
                c.client_id,
                c.client_company_name,
                c.client_contact_name,
                c.client_phone,
                c.client_mobile,
                c.client_email,
                c.address,
                c.post_code,
                c.stage,
                c.created_at,
                c.assigned_employee_id,
                c.is_archived,
                e.employee_name as salesperson_name
            FROM "StreemLyne_MT"."Client_Master" c
            LEFT JOIN "StreemLyne_MT"."Employee_Master" e ON c.assigned_employee_id = e.employee_id
            WHERE c.client_id = :client_id AND c.tenant_id = :tenant_id AND c.is_deleted = false
        """)
        
        result = session.execute(customer_query, {
            'client_id': customer_id,
            'tenant_id': tenant_id
        })
        customer = result.fetchone()
        
        if not customer:
            return jsonify({'error': 'Customer not found'}), 404
        
        # Get opportunities for this customer
        opp_query = text("""
            SELECT 
                opportunity_id,
                opportunity_title,
                process_stage as stage,
                service_id,
                created_at
            FROM "StreemLyne_MT"."Opportunity_Details"
            WHERE client_id = :client_id AND tenant_id = :tenant_id AND deleted_at IS NULL
            ORDER BY created_at DESC
        """)
        
        opp_result = session.execute(opp_query, {
            'client_id': customer_id,
            'tenant_id': tenant_id
        })
        opportunities = opp_result.fetchall()
        
        projects = [{
            'id': opp.opportunity_id,
            'project_name': opp.opportunity_title,
            'stage': opp.stage or 'Not Started',
            'created_at': opp.created_at.isoformat() if opp.created_at else None
        } for opp in opportunities]
        
        customer_data = {
            'id': customer.client_id,
            'name': customer.client_company_name or customer.client_contact_name,
            'phone': customer.client_phone or customer.client_mobile or '',
            'email': customer.client_email or '',
            'address': customer.address or '',
            'postcode': customer.post_code or '',
            'salesperson': customer.salesperson_name or '',
            'stage': customer.stage or 'Lead',
            'status': 'Archived' if customer.is_archived else 'Active',
            'created_at': customer.created_at.isoformat() if customer.created_at else None,
            'projects': projects,
            'project_count': len(projects)
        }
        
        return jsonify(customer_data), 200
        
    except Exception as e:
        current_app.logger.exception(f"Error fetching customer {customer_id}: {e}")
        return jsonify({'error': 'Failed to fetch customer'}), 500
    finally:
        session.close()


@customer_bp.route('/customers/<int:customer_id>', methods=['PUT', 'OPTIONS'])
@token_required
def update_customer(customer_id):
    """Update a customer"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        tenant_id = get_current_tenant_id()
        data = request.get_json()
        
        # Build dynamic UPDATE query
        update_fields = []
        params = {'client_id': customer_id, 'tenant_id': tenant_id}
        
        if 'name' in data:
            # Update both company and contact name fields
            update_fields.append('client_company_name = :name')
            update_fields.append('client_contact_name = :name')
            params['name'] = data['name']
        
        if 'phone' in data:
            update_fields.append('client_phone = :phone')
            params['phone'] = data['phone']
        
        if 'email' in data:
            update_fields.append('client_email = :email')
            params['email'] = data['email']
        
        if 'address' in data:
            update_fields.append('address = :address')
            params['address'] = data['address']
        
        if 'postcode' in data:
            update_fields.append('post_code = :postcode')
            params['postcode'] = data['postcode']
        
        if 'stage' in data:
            update_fields.append('stage = :stage')
            params['stage'] = data['stage']
        
        if not update_fields:
            return jsonify({'error': 'No fields to update'}), 400
        
        update_query = text(f"""
            UPDATE "StreemLyne_MT"."Client_Master"
            SET {', '.join(update_fields)}
            WHERE client_id = :client_id AND tenant_id = :tenant_id
        """)
        
        session.execute(update_query, params)
        session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Customer updated successfully'
        }), 200
        
    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"Error updating customer {customer_id}: {e}")
        return jsonify({'error': f'Failed to update customer: {str(e)}'}), 500
    finally:
        session.close()


@customer_bp.route('/customers/<int:customer_id>/stage', methods=['PATCH', 'OPTIONS'])
@token_required
def update_customer_stage_direct(customer_id):
    """Update customer stage directly"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        tenant_id = get_current_tenant_id()
        employee_id = get_current_employee_id()
        
        data = request.get_json()
        new_stage = data.get('stage')
        
        if not new_stage:
            return jsonify({'error': 'Stage is required'}), 400
        
        # Get old stage
        old_stage_query = text("""
            SELECT stage FROM "StreemLyne_MT"."Client_Master"
            WHERE client_id = :client_id AND tenant_id = :tenant_id
        """)
        result = session.execute(old_stage_query, {
            'client_id': customer_id,
            'tenant_id': tenant_id
        })
        old_stage_row = result.fetchone()
        
        if not old_stage_row:
            return jsonify({'error': 'Customer not found'}), 404
        
        old_stage = old_stage_row.stage
        
        # Update stage
        update_query = text("""
            UPDATE "StreemLyne_MT"."Client_Master"
            SET stage = :stage
            WHERE client_id = :client_id AND tenant_id = :tenant_id
        """)
        
        session.execute(update_query, {
            'stage': new_stage,
            'client_id': customer_id,
            'tenant_id': tenant_id
        })
        
        # Create notification for important stages
        if new_stage == 'Accepted' and old_stage != 'Accepted':
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
                    'task',
                    'high',
                    :message,
                    false,
                    false
                )
            """)
            
            session.execute(notify_query, {
                'tenant_id': tenant_id,
                'employee_id': employee_id,
                'client_id': customer_id,
                'message': f'✅ Client moved to Accepted stage - Action required'
            })
        
        session.commit()
        
        current_app.logger.info(f"✅ Customer {customer_id} stage updated: {old_stage} → {new_stage}")
        
        return jsonify({
            'success': True,
            'customer_id': customer_id,
            'old_stage': old_stage,
            'new_stage': new_stage
        }), 200
        
    except Exception as e:
        session.rollback()
        current_app.logger.error(f"❌ Error updating customer stage: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@customer_bp.route('/customers/<int:customer_id>', methods=['DELETE', 'OPTIONS'])
@token_required
def delete_customer(customer_id):
    """Soft delete a customer"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        tenant_id = get_current_tenant_id()
        
        # Soft delete
        delete_query = text("""
            UPDATE "StreemLyne_MT"."Client_Master"
            SET is_deleted = true, deleted_at = :deleted_at
            WHERE client_id = :client_id AND tenant_id = :tenant_id
        """)
        
        session.execute(delete_query, {
            'deleted_at': datetime.utcnow(),
            'client_id': customer_id,
            'tenant_id': tenant_id
        })
        session.commit()
        
        current_app.logger.info(f"Customer {customer_id} soft deleted")
        
        return jsonify({
            'success': True,
            'message': 'Customer deleted successfully'
        }), 200
        
    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"Error deleting customer {customer_id}: {e}")
        return jsonify({'error': 'Failed to delete customer'}), 500
    finally:
        session.close()


# ==========================================
# OPPORTUNITY/PROJECT ENDPOINTS
# ==========================================

@customer_bp.route('/customers/<int:customer_id>/projects', methods=['GET', 'OPTIONS'])
@token_required
def get_customer_projects(customer_id):
    """Get all opportunities for a specific customer"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        tenant_id = get_current_tenant_id()
        
        query = text("""
            SELECT 
                opportunity_id,
                opportunity_title,
                process_stage,
                service_id,
                created_at
            FROM "StreemLyne_MT"."Opportunity_Details"
            WHERE client_id = :client_id 
            AND tenant_id = :tenant_id 
            AND deleted_at IS NULL
            ORDER BY created_at DESC
        """)
        
        result = session.execute(query, {
            'client_id': customer_id,
            'tenant_id': tenant_id
        })
        opportunities = result.fetchall()
        
        projects = [{
            'id': opp.opportunity_id,
            'project_name': opp.opportunity_title,
            'stage': opp.process_stage or 'Not Started',
            'service_id': opp.service_id,
            'created_at': opp.created_at.isoformat() if opp.created_at else None
        } for opp in opportunities]
        
        return jsonify({'projects': projects}), 200
        
    except Exception as e:
        current_app.logger.exception(f"Error fetching customer projects: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@customer_bp.route('/customers/<int:customer_id>/projects', methods=['POST', 'OPTIONS'])
@token_required
def create_project(customer_id):
    """Create a new opportunity for a customer"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        tenant_id = get_current_tenant_id()
        employee_id = get_current_employee_id()
        
        data = request.get_json()
        
        if not data.get('project_name'):
            return jsonify({'error': 'Project name is required'}), 400
        
        # Insert new opportunity
        insert_query = text("""
            INSERT INTO "StreemLyne_MT"."Opportunity_Details" (
                tenant_id,
                client_id,
                opportunity_title,
                process_stage,
                opportunity_owner_employee_id,
                stage_id,
                created_at
            ) VALUES (
                :tenant_id,
                :client_id,
                :title,
                :process_stage,
                :employee_id,
                1,
                :created_at
            )
            RETURNING opportunity_id
        """)
        
        result = session.execute(insert_query, {
            'tenant_id': tenant_id,
            'client_id': customer_id,
            'title': data['project_name'],
            'process_stage': data.get('stage', 'Not Started'),
            'employee_id': employee_id,
            'created_at': datetime.utcnow()
        })
        
        opportunity_id = result.fetchone()[0]
        session.commit()
        
        current_app.logger.info(f"✅ Opportunity {opportunity_id} created for customer {customer_id}")
        
        return jsonify({
            'success': True,
            'message': 'Project created successfully',
            'project': {
                'id': opportunity_id,
                'project_name': data['project_name'],
                'stage': data.get('stage', 'Not Started')
            }
        }), 201
        
    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"❌ Error creating project: {e}")
        return jsonify({'error': f'Failed to create project: {str(e)}'}), 500
    finally:
        session.close()


@customer_bp.route('/projects/<int:project_id>', methods=['GET', 'OPTIONS'])
@token_required
def get_project(project_id):
    """Get a specific opportunity/project"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        tenant_id = get_current_tenant_id()
        
        query = text("""
            SELECT 
                o.opportunity_id,
                o.opportunity_title,
                o.process_stage,
                o.created_at,
                c.client_id,
                c.client_company_name,
                c.client_contact_name
            FROM "StreemLyne_MT"."Opportunity_Details" o
            JOIN "StreemLyne_MT"."Client_Master" c ON o.client_id = c.client_id
            WHERE o.opportunity_id = :opportunity_id 
            AND o.tenant_id = :tenant_id
            AND o.deleted_at IS NULL
        """)
        
        result = session.execute(query, {
            'opportunity_id': project_id,
            'tenant_id': tenant_id
        })
        opp = result.fetchone()
        
        if not opp:
            return jsonify({'error': 'Project not found'}), 404
        
        return jsonify({
            'id': opp.opportunity_id,
            'project_name': opp.opportunity_title,
            'stage': opp.process_stage or 'Not Started',
            'created_at': opp.created_at.isoformat() if opp.created_at else None,
            'customer': {
                'id': opp.client_id,
                'name': opp.client_company_name or opp.client_contact_name
            }
        }), 200
        
    except Exception as e:
        current_app.logger.exception(f"Error fetching project {project_id}: {e}")
        return jsonify({'error': 'Failed to fetch project'}), 500
    finally:
        session.close()


@customer_bp.route('/projects/<int:project_id>', methods=['PUT', 'OPTIONS'])
@token_required
def update_project(project_id):
    """Update an opportunity/project"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        tenant_id = get_current_tenant_id()
        data = request.get_json()
        
        update_fields = []
        params = {'opportunity_id': project_id, 'tenant_id': tenant_id}
        
        if 'project_name' in data:
            update_fields.append('opportunity_title = :title')
            params['title'] = data['project_name']
        
        if 'stage' in data:
            update_fields.append('process_stage = :stage')
            params['stage'] = data['stage']
        
        if not update_fields:
            return jsonify({'error': 'No fields to update'}), 400
        
        update_query = text(f"""
            UPDATE "StreemLyne_MT"."Opportunity_Details"
            SET {', '.join(update_fields)}, process_stage_updated_at = :updated_at
            WHERE opportunity_id = :opportunity_id AND tenant_id = :tenant_id
        """)
        
        params['updated_at'] = datetime.utcnow()
        
        session.execute(update_query, params)
        session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Project updated successfully'
        }), 200
        
    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"Error updating project: {e}")
        return jsonify({'error': f'Failed to update project: {str(e)}'}), 500
    finally:
        session.close()


@customer_bp.route('/projects/<int:project_id>', methods=['DELETE', 'OPTIONS'])
@token_required
def delete_project(project_id):
    """Soft delete a project/opportunity"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        tenant_id = get_current_tenant_id()
        
        delete_query = text("""
            UPDATE "StreemLyne_MT"."Opportunity_Details"
            SET deleted_at = :deleted_at
            WHERE opportunity_id = :opportunity_id AND tenant_id = :tenant_id
        """)
        
        session.execute(delete_query, {
            'deleted_at': datetime.utcnow(),
            'opportunity_id': project_id,
            'tenant_id': tenant_id
        })
        session.commit()
        
        current_app.logger.info(f"Project {project_id} soft deleted")
        
        return jsonify({
            'success': True,
            'message': 'Project deleted successfully'
        }), 200
        
    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"Error deleting project: {e}")
        return jsonify({'error': 'Failed to delete project'}), 500
    finally:
        session.close()


# ==========================================
# DOCUMENTS ENDPOINTS
# ==========================================

@customer_bp.route('/drawings', methods=['GET', 'OPTIONS'])
@token_required
def get_drawing_documents():
    """Get all documents for a specific customer"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        tenant_id = get_current_tenant_id()
        customer_id = request.args.get('customer_id')
        
        if not customer_id:
            return jsonify({'error': 'Customer ID is required'}), 400
        
        query = text("""
            SELECT 
                id,
                file_name,
                file_url,
                document_category,
                uploaded_at
            FROM "StreemLyne_MT"."Customer_Documents"
            WHERE client_id = :client_id
            ORDER BY uploaded_at DESC
        """)
        
        result = session.execute(query, {'client_id': int(customer_id)})
        documents = result.fetchall()
        
        return jsonify([{
            'id': doc.id,
            'file_name': doc.file_name,
            'file_url': doc.file_url,
            'category': doc.document_category,
            'uploaded_at': doc.uploaded_at.isoformat() if doc.uploaded_at else None
        } for doc in documents]), 200
        
    except Exception as e:
        current_app.logger.exception(f"Error fetching drawings: {e}")
        return jsonify({'error': 'Failed to fetch drawing documents'}), 500
    finally:
        session.close()


@customer_bp.route('/drawings/<int:drawing_id>', methods=['DELETE', 'OPTIONS'])
@token_required
def delete_drawing_document(drawing_id):
    """Delete a document"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        delete_query = text("""
            DELETE FROM "StreemLyne_MT"."Customer_Documents"
            WHERE id = :document_id
        """)
        
        session.execute(delete_query, {'document_id': drawing_id})
        session.commit()
        
        current_app.logger.info(f"Document {drawing_id} deleted")
        
        return jsonify({
            'success': True,
            'message': 'Drawing document deleted successfully'
        }), 200
        
    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"Error deleting drawing: {e}")
        return jsonify({'error': 'Failed to delete drawing document'}), 500
    finally:
        session.close()


# ==========================================
# FORMS ENDPOINTS (for compatibility)
# ==========================================

@customer_bp.route('/customers/<int:customer_id>/forms', methods=['GET', 'OPTIONS'])
@token_required
def get_customer_forms(customer_id):
    """Get all form submissions for a customer (returns empty for now)"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    # Forms are not implemented in StreemLyne_MT schema
    # Return empty array for compatibility
    return jsonify([]), 200


@customer_bp.route('/forms/<int:form_id>', methods=['DELETE', 'OPTIONS'])
@token_required
def delete_form_submission(form_id):
    """Delete a form submission (not implemented)"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    return jsonify({'error': 'Forms are not implemented in this version'}), 501