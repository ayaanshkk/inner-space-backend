from flask import Blueprint, request, jsonify
from ..models import Customer, Project, CustomerFormData, User, Job, DrawingDocument, FormDocument, ProductionNotification
from functools import wraps
from flask import current_app
import uuid
from datetime import datetime
import json

# 👈 NEW IMPORT: Required for all database write operations
from ..db import SessionLocal 
from .notification_routes import create_activity_notification  # ✅ ADD THIS IMPORT


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
    "Accepted": 7,  # ✅ MAKE SURE THIS EXISTS
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
    
    # Filter out None values and get hierarchy values
    valid_stages = [s for s in stages if s and s in STAGE_HIERARCHY]
    if not valid_stages:
        return "Lead"
    
    # Return the stage with highest hierarchy value
    return max(valid_stages, key=lambda s: STAGE_HIERARCHY.get(s, 0))


# Token authentication decorator
def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if request.method == 'OPTIONS':
            return f(*args, **kwargs)
        
        token = None
        
        if 'Authorization' in request.headers:
            auth_header = request.headers['Authorization']
            try:
                token = auth_header.split(" ")[1]
            except IndexError:
                return jsonify({'error': 'Invalid token format'}), 401
        
        if not token:
            return jsonify({'error': 'Token is missing'}), 401
        
        try:
            current_user = User.verify_jwt_token(token, current_app.config['SECRET_KEY'])
            if not current_user:
                return jsonify({'error': 'Token is invalid or expired'}), 401
            
            request.current_user = current_user
            
        except Exception as e:
            return jsonify({'error': 'Token verification failed'}), 401
        
        return f(*args, **kwargs)
    
    return decorated


# ==========================================
# CUSTOMER ENDPOINTS
# ==========================================

@customer_bp.route('/customers', methods=['GET', 'OPTIONS'])
@token_required
def get_customers():
    """Get all customers with their project counts, form counts, drawing counts, and MOST ADVANCED PROJECT STAGE."""
    
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        from sqlalchemy.orm import joinedload
        from sqlalchemy import func
        
        # ✅ FIX 1: Load customers with projects in one query
        customers = session.query(Customer).options(
            joinedload(Customer.projects)
        ).all()
        
        current_app.logger.info(f"📊 Fetching data for {len(customers)} customers")
        
        # ✅ FIX 2: Get ALL counts in bulk queries (not one-by-one)
        customer_ids = [c.id for c in customers]
        
        # Bulk count forms
        form_counts = dict(
            session.query(CustomerFormData.customer_id, func.count(CustomerFormData.id))
            .filter(CustomerFormData.customer_id.in_(customer_ids))
            .group_by(CustomerFormData.customer_id)
            .all()
        ) if customer_ids else {}
        
        # Bulk count drawings
        drawing_counts = dict(
            session.query(DrawingDocument.customer_id, func.count(DrawingDocument.id))
            .filter(DrawingDocument.customer_id.in_(customer_ids))
            .group_by(DrawingDocument.customer_id)
            .all()
        ) if customer_ids else {}
        
        # Bulk count form documents
        form_doc_counts = dict(
            session.query(FormDocument.customer_id, func.count(FormDocument.id))
            .filter(FormDocument.customer_id.in_(customer_ids))
            .group_by(FormDocument.customer_id)
            .all()
        ) if customer_ids else {}
        
        result = []
        for customer in customers:
            # ✅ Use pre-loaded projects
            customer_projects = customer.projects
            total_project_count = len(customer_projects)
            
            # ✅ Use bulk-loaded counts (default to 0 if customer not in dict)
            form_count = form_counts.get(customer.id, 0)
            drawing_count = drawing_counts.get(customer.id, 0)
            form_doc_count = form_doc_counts.get(customer.id, 0)
            
            # Collect stages ONLY from projects
            all_stages = [customer.stage] if customer.stage else []
            all_stages.extend([project.stage for project in customer_projects if project.stage])
            
            # Get the most advanced stage
            display_stage = get_most_advanced_stage(all_stages)
            
            # Ensure stage is always a string, never None
            if not display_stage or display_stage == 'None':
                display_stage = 'Lead'
            
            # Calculate total document count
            total_documents = int(drawing_count) + int(form_count) + int(form_doc_count)
            
            customer_data = {
                'id': customer.id,
                'name': customer.name,
                'phone': customer.phone or '',
                'email': customer.email or '',
                'address': customer.address or '',
                'postcode': customer.postcode or '',
                'salesperson': customer.salesperson or '',
                'contact_made': customer.contact_made or 'Unknown',
                'preferred_contact_method': customer.preferred_contact_method or 'Phone',
                'marketing_opt_in': bool(customer.marketing_opt_in),
                'notes': customer.notes or '',
                'status': customer.status or 'Active',
                'date_of_measure': customer.date_of_measure.isoformat() if customer.date_of_measure else None,
                'created_at': customer.created_at.isoformat() if customer.created_at else None,
                'updated_at': customer.updated_at.isoformat() if customer.updated_at else None,
                'created_by': customer.created_by,
                'updated_by': customer.updated_by,
                'stage': display_stage,
                'project_count': total_project_count,
                'form_count': int(form_count),
                'drawing_count': int(drawing_count),
                'form_document_count': int(form_doc_count),
                'total_documents': total_documents,
                'has_documents': total_documents > 0,
                'has_drawings': drawing_count > 0,
                'has_forms': form_count > 0 or form_doc_count > 0,
            }
            
            # Handle project_types
            project_types_value = customer.project_types
            if project_types_value is None:
                project_types_value = []
            elif isinstance(project_types_value, str):
                import json
                try:
                    project_types_value = json.loads(project_types_value)
                except:
                    project_types_value = []
            elif not isinstance(project_types_value, list):
                project_types_value = []
            
            customer_data['project_types'] = project_types_value
            result.append(customer_data)

        current_app.logger.info(f"✅ Returning {len(result)} customers")
        
        return jsonify(result), 200

    except Exception as e:
        current_app.logger.exception(f"❌ Error fetching customers: {e}")
        return jsonify({'error': 'Failed to fetch customers'}), 500
    finally:
        session.close()


@customer_bp.route('/customers', methods=['POST', 'OPTIONS'])
@token_required
def create_customer():
    """Create a new customer"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        data = request.get_json()
        
        current_app.logger.info(f"📝 Creating new customer with data: {data}")
        
        # Validate required fields
        if not data.get('name'):
            return jsonify({'error': 'Name is required'}), 400
        if not data.get('phone'):
            return jsonify({'error': 'Phone is required'}), 400
        if not data.get('address'):
            return jsonify({'error': 'Address is required'}), 400
        
        # ✅ CRITICAL FIX: Set default stage to 'Lead'
        customer_id = str(uuid.uuid4())
        
        # Create new customer
        new_customer = Customer(
            id=customer_id,
            name=data.get('name'),
            phone=data.get('phone'),
            email=data.get('email', ''),
            address=data.get('address'),
            postcode=data.get('postcode', ''),
            salesperson=data.get('salesperson', ''),
            marketing_opt_in=data.get('marketing_opt_in', False),
            notes=data.get('notes', ''),
            contact_made='No',
            preferred_contact_method='Phone',
            stage='Lead',  # ✅ CRITICAL: Set default stage
            status='Active',  # ✅ CRITICAL: Set default status
            created_at=datetime.utcnow(),
            created_by=str(request.current_user.id),
            updated_at=datetime.utcnow(),
            updated_by=str(request.current_user.id)
        )
        
        session.add(new_customer)
        session.commit()
        session.refresh(new_customer)  # ✅ Refresh to get all fields
        
        current_app.logger.info(f"✅ Customer {new_customer.id} created successfully by user {request.current_user.id}")
        
        # Return customer data in the same format as get_customers
        return jsonify({
            'success': True,
            'message': 'Customer created successfully',
            'customer': {
                'id': new_customer.id,
                'name': new_customer.name,
                'phone': new_customer.phone,
                'email': new_customer.email or '',
                'address': new_customer.address,
                'postcode': new_customer.postcode or '',
                'salesperson': new_customer.salesperson or '',
                'contact_made': new_customer.contact_made,
                'preferred_contact_method': new_customer.preferred_contact_method,
                'marketing_opt_in': new_customer.marketing_opt_in,
                'notes': new_customer.notes or '',
                'status': new_customer.status,
                'stage': new_customer.stage,
                'created_at': new_customer.created_at.isoformat(),
                'updated_at': new_customer.updated_at.isoformat(),
                'created_by': new_customer.created_by,
                'updated_by': new_customer.updated_by,
                'project_count': 0,
                'form_count': 0,
                'drawing_count': 0,
                'form_document_count': 0,
                'total_documents': 0,
                'has_documents': False,
                'has_drawings': False,
                'has_forms': False,
                'project_types': []
            }
        }), 201
        
    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"❌ Error creating customer: {e}")
        return jsonify({'error': f'Failed to create customer: {str(e)}'}), 500
    finally:
        session.close()


@customer_bp.route('/customers/<string:customer_id>', methods=['GET', 'OPTIONS'])
@token_required
def get_customer(customer_id):
    """Get a single customer by ID with all their projects AND form submissions"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        customer = session.get(Customer, customer_id)
        if not customer:
            return jsonify({'error': 'Customer not found'}), 404
        
        # Check access permissions
        if request.current_user.role == 'Sales':
            if customer.created_by != str(request.current_user.id) and customer.salesperson != request.current_user.full_name:
                return jsonify({'error': 'You do not have permission to view this customer'}), 403
        elif request.current_user.role == 'Staff':
            if customer.created_by != str(request.current_user.id) and customer.salesperson != request.current_user.full_name:
                return jsonify({'error': 'You do not have permission to view this customer'}), 403
        
        # ✅ Return customer with BOTH projects AND forms
        return jsonify(customer.to_dict(include_projects=True, include_forms=True)), 200
        
    except Exception as e:
        current_app.logger.exception(f"Error fetching customer {customer_id}: {e}")
        return jsonify({'error': 'Failed to fetch customer'}), 500
    finally:
        session.close()


@customer_bp.route('/customers/<string:customer_id>', methods=['PUT', 'OPTIONS'])
@token_required
def update_customer(customer_id):
    """Update a customer"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        customer = session.get(Customer, customer_id)
        if not customer:
            return jsonify({'error': 'Customer not found'}), 404
        
        # Check permissions
        if request.current_user.role == 'Sales':
            if customer.created_by != str(request.current_user.id) and customer.salesperson != request.current_user.full_name:
                return jsonify({'error': 'You do not have permission to edit this customer'}), 403
        
        data = request.get_json()
        
        # Update customer fields
        if 'name' in data:
            customer.name = data['name']
        if 'phone' in data:
            customer.phone = data['phone']
        if 'email' in data:
            customer.email = data['email']
        if 'address' in data:
            customer.address = data['address']
        if 'postcode' in data:
            customer.postcode = data['postcode']
        if 'contact_made' in data:
            customer.contact_made = data['contact_made']
        if 'preferred_contact_method' in data:
            customer.preferred_contact_method = data['preferred_contact_method']
        if 'marketing_opt_in' in data:
            customer.marketing_opt_in = data['marketing_opt_in']
        if 'notes' in data:
            customer.notes = data['notes']
        if 'salesperson' in data:
            customer.salesperson = data['salesperson']
        
        customer.updated_by = str(request.current_user.id)
        customer.updated_at = datetime.utcnow()
        
        session.commit()
        
        customer_dict = customer.to_dict(include_projects=True)
        
        return jsonify({
            'success': True,
            'message': 'Customer updated successfully',
            'customer': customer_dict
        }), 200
        
    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"Error updating customer {customer_id}: {e}")
        return jsonify({'error': f'Failed to update customer: {str(e)}'}), 500
    finally:
        session.close()

@customer_bp.route('/customers/<string:customer_id>/stage', methods=['PATCH', 'OPTIONS'])
@token_required
def update_customer_stage_direct(customer_id):
    """Update customer stage directly - WITH NOTIFICATIONS AND ACTION ITEMS"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        customer = session.get(Customer, customer_id)
        if not customer:
            return jsonify({'error': 'Customer not found'}), 404

        data = request.get_json()
        new_stage = data.get('stage')
        
        if not new_stage:
            return jsonify({'error': 'Stage is required'}), 400

        current_app.logger.info(f"🔄 Updating customer {customer_id} stage to {new_stage}")
        
        old_stage = customer.stage
        customer.stage = new_stage
        customer.updated_by = str(request.current_user.id)
        customer.updated_at = datetime.utcnow()
        
        # ✅ CRITICAL: Commit customer update FIRST
        session.commit()
        session.refresh(customer)
        
        current_app.logger.info(f"✅ Customer stage updated: {old_stage} → {new_stage}")
        
        # ✅ Create action item when moved to Accepted
        if new_stage == 'Accepted' and old_stage != 'Accepted':
            try:
                from ..models import ActionItem
                import uuid
                
                # Check if action item already exists
                existing = session.query(ActionItem).filter(
                    ActionItem.customer_id == customer_id,
                    ActionItem.stage == 'Accepted',
                    ActionItem.completed == False
                ).first()
                
                if not existing:
                    action_item = ActionItem(
                        id=str(uuid.uuid4()),
                        customer_id=customer_id,
                        stage='Accepted',
                        priority='High',
                        completed=False
                    )
                    session.add(action_item)
                    session.commit()
                    current_app.logger.info(f"✅ Created action item for customer {customer.name}")
            except Exception as action_error:
                current_app.logger.error(f"⚠️ Failed to create action item: {action_error}")
                # Don't fail the request if action item creation fails
        
        # ✅ Create notification for important stages
        important_stages = ['Accepted', 'Production', 'Delivery', 'Installation', 'Complete']
        
        if new_stage in important_stages and old_stage != new_stage:
            try:
                stage_emoji = {
                    'Accepted': '✅',
                    'Production': '🏭',
                    'Delivery': '🚚',
                    'Installation': '🔧',
                    'Complete': '🎉'
                }
                emoji = stage_emoji.get(new_stage, '🔄')
                
                user_name = request.current_user.full_name if hasattr(request.current_user, 'full_name') else request.current_user.email
                
                notification_message = f"{emoji} Customer '{customer.name}' moved to {new_stage} stage"
                
                # Use the helper function to create notification
                create_activity_notification(
                    session=session,
                    message=notification_message,
                    customer_id=customer_id,
                    moved_by=user_name
                )
                
                current_app.logger.info(f"✅ Created {new_stage} stage notification for customer {customer.name}")
                
            except Exception as notif_error:
                current_app.logger.error(f"⚠️ Failed to create notification: {notif_error}")
                # Don't fail the request if notification fails
        
        return jsonify({
            'success': True,
            'customer_id': customer.id,
            'old_stage': old_stage,
            'new_stage': customer.stage,
        }), 200
        
    except Exception as e:
        session.rollback()
        current_app.logger.error(f"❌ Error updating customer stage: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()

@customer_bp.route('/customers/<string:customer_id>', methods=['DELETE', 'OPTIONS'])
@token_required
def delete_customer(customer_id):
    """Delete a customer (Manager/HR only)"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        # Only Manager and HR can delete
        if request.current_user.role not in ['Manager', 'HR']:
            return jsonify({'error': 'You do not have permission to delete customers'}), 403
        
        customer = session.get(Customer, customer_id)
        if not customer:
            return jsonify({'error': 'Customer not found'}), 404
        
        # Check if customer has projects - warn if they do
        if customer.projects:
            return jsonify({
                'error': f'Cannot delete customer with {len(customer.projects)} project(s). Delete projects first.'
            }), 400
        
        session.delete(customer)
        session.commit()
        
        current_app.logger.info(f"Customer {customer_id} deleted by user {request.current_user.id}")
        
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
# PROJECT ENDPOINTS
# ==========================================

@customer_bp.route('/customers/<string:customer_id>/projects', methods=['GET', 'OPTIONS'])
@token_required
def get_customer_projects(customer_id):
    """Get all projects for a specific customer with full details."""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        customer = session.get(Customer, customer_id)
        if not customer:
            return jsonify({'error': 'Customer not found'}), 404
        
        # Get all projects for this customer
        projects = session.query(Project).filter_by(customer_id=customer_id).all()
        
        projects_list = []
        for project in projects:
            project_data = {
                'id': project.id,
                'project_name': project.project_name,
                'project_type': project.project_type,
                'stage': project.stage,
                'date_of_measure': project.date_of_measure.isoformat() if project.date_of_measure else None,
                'notes': project.notes,
                'created_at': project.created_at.isoformat() if project.created_at else None,
                'updated_at': project.updated_at.isoformat() if project.updated_at else None
            }
            projects_list.append(project_data)
        
        return jsonify({
            'customer': {
                'id': customer.id,
                'name': customer.name,
                'phone': customer.phone,
                'email': customer.email
            },
            'projects': projects_list
        }), 200
        
    except Exception as e:
        current_app.logger.exception(f"Error fetching customer projects: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()

@customer_bp.route('/customers/<string:customer_id>/projects', methods=['POST', 'OPTIONS'])
@token_required
def create_project(customer_id):
    """Create a new project for a customer."""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        customer = session.get(Customer, customer_id)
        if not customer:
            return jsonify({'error': 'Customer not found'}), 404
        
        # Check permissions
        allowed_roles = ['Manager', 'HR', 'Sales']
        
        if request.current_user.role not in allowed_roles:
            return jsonify({
                'error': f'You do not have permission to create projects. Only {", ".join(allowed_roles)} can create projects.'
            }), 403
        
        data = request.get_json()
        
        # Validate required fields
        if not data.get('project_name'):
            return jsonify({'error': 'Project name is required'}), 400
        if not data.get('project_type'):
            return jsonify({'error': 'Project type is required'}), 400
        
        # Create new project
        new_project = Project(
            id=str(uuid.uuid4()),
            customer_id=customer_id,
            project_name=data.get('project_name'),
            project_type=data.get('project_type'),
            stage=data.get('stage', 'Lead'),
            date_of_measure=datetime.fromisoformat(data['date_of_measure']) if data.get('date_of_measure') else None,
            notes=data.get('notes', ''),
            created_at=datetime.utcnow(),
            created_by=str(request.current_user.id)
        )
        
        session.add(new_project)
        session.flush()  # Get the project ID
        
        # ✅ Get user name
        user_name = request.current_user.full_name if hasattr(request.current_user, 'full_name') else request.current_user.email
        
        # ✅ CRITICAL FIX: Use the imported helper function
        try:
            notification_message = f"➕ New {data.get('project_type', 'project')} project created for customer '{customer.name}' - {data.get('project_name')}"
            
            create_activity_notification(
                session=session,
                message=notification_message,
                customer_id=customer_id,
                moved_by=user_name
            )
            
            current_app.logger.info(f"✅ Created project creation notification")
            
        except Exception as notif_error:
            current_app.logger.warning(f"⚠️ Failed to create notification: {notif_error}")
        
        # Update customer stage if this is the first project
        old_customer_stage = customer.stage
        new_stage = new_project.stage
        
        existing_project_count = session.query(Project).filter_by(customer_id=customer_id).count()
        existing_job_count = session.query(Job).filter_by(customer_id=customer_id).count()
        
        if existing_project_count == 1 and existing_job_count == 0 and new_stage:
            customer.stage = new_stage
            customer.updated_at = datetime.utcnow()
            
            # ✅ CRITICAL FIX: Create notification for stage changes using helper function
            important_stages = ['Accepted', 'Production', 'Delivery', 'Installation', 'Complete']
            
            if new_stage in important_stages and old_customer_stage != new_stage:
                try:
                    stage_emoji = {
                        'Accepted': '✅',
                        'Production': '🏭',
                        'Delivery': '🚚',
                        'Installation': '🔧',
                        'Complete': '🎉'
                    }
                    emoji = stage_emoji.get(new_stage, '🔄')
                    
                    stage_message = f"{emoji} Customer '{customer.name}' moved from {old_customer_stage} to {new_stage} stage"
                    
                    create_activity_notification(
                        session=session,
                        message=stage_message,
                        customer_id=customer_id,
                        moved_by=user_name
                    )
                    
                    current_app.logger.info(f"✅ Created {new_stage} stage notification")
                    
                except Exception as stage_notif_error:
                    current_app.logger.warning(f"⚠️ Failed to create stage notification: {stage_notif_error}")
        
        session.commit()
        
        current_app.logger.info(f"✅ Project {new_project.id} created for customer {customer_id}")
        
        return jsonify({
            'success': True,
            'message': 'Project created successfully',
            'project': new_project.to_dict()
        }), 201
        
    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"❌ Error creating project: {e}")
        return jsonify({'error': f'Failed to create project: {str(e)}'}), 500
    finally:
        session.close()


@customer_bp.route('/projects/<string:project_id>', methods=['GET', 'OPTIONS'])
@token_required
def get_project(project_id):
    """Get a specific project with all its details"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        project = session.get(Project, project_id)
        if not project:
            return jsonify({'error': 'Project not found'}), 404
            
        customer = project.customer
        
        # Check permissions
        if request.current_user.role in ['Sales', 'Staff']:
            if customer.created_by != str(request.current_user.id) and customer.salesperson != request.current_user.full_name:
                return jsonify({'error': 'You do not have permission to view this project'}), 403
        
        return jsonify(project.to_dict(include_forms=True)), 200
        
    except Exception as e:
        current_app.logger.exception(f"Error fetching project {project_id}: {e}")
        return jsonify({'error': 'Failed to fetch project'}), 500
    finally:
        session.close()


@customer_bp.route('/projects/<string:project_id>', methods=['PUT', 'OPTIONS'])
@token_required
def update_project(project_id):
    """Update a project."""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        project = session.get(Project, project_id)
        if not project:
            return jsonify({'error': 'Project not found'}), 404
            
        customer = project.customer
        
        # Check permissions
        if request.current_user.role in ['Sales', 'Staff']:
            if customer.created_by != str(request.current_user.id) and customer.salesperson != request.current_user.full_name:
                return jsonify({'error': 'You do not have permission to edit this project'}), 403
        
        data = request.get_json()
        
        old_stage = project.stage
        
        # Update fields
        if 'project_name' in data:
            project.project_name = data['project_name']
        if 'project_type' in data:
            project.project_type = data['project_type']
        if 'stage' in data:
            project.stage = data['stage']
        if 'date_of_measure' in data:
            project.date_of_measure = datetime.fromisoformat(data['date_of_measure']) if data['date_of_measure'] else None
        if 'notes' in data:
            project.notes = data['notes']
        
        project.updated_by = str(request.current_user.id)
        project.updated_at = datetime.utcnow()
        
        # Count existing linked entities
        total_other_linked_entities = session.query(Project).filter(Project.customer_id==customer.id, Project.id != project_id).count() + \
                                      session.query(Job).filter_by(customer_id=customer.id).count()
        
        if 'stage' in data and project.stage != old_stage and total_other_linked_entities == 0:
            old_customer_stage = customer.stage
            customer.stage = project.stage
            
            # ✅ CREATE ACTION ITEM when project moves to Accepted
            if project.stage == 'Accepted' and old_stage != 'Accepted':
                current_app.logger.info(f"🎯 Project moved to Accepted, creating action item for customer {customer.name}...")
                try:
                    from ..models import ActionItem
                    
                    # Check if action item already exists for this customer
                    existing = session.query(ActionItem).filter(
                        ActionItem.customer_id == customer.id,
                        ActionItem.stage == 'Accepted',
                        ActionItem.completed == False
                    ).first()
                    
                    if existing:
                        current_app.logger.info(f"⏭️ Action item already exists for customer {customer.name}")
                    else:
                        action_item = ActionItem(
                            id=str(uuid.uuid4()),
                            customer_id=customer.id,
                            stage='Accepted',
                            priority='High',
                            completed=False
                        )
                        session.add(action_item)
                        session.flush()  # Get the ID without committing
                        current_app.logger.info(f"✅ Successfully created action item {action_item.id} for customer {customer.name}")
                except Exception as action_error:
                    current_app.logger.error(f"❌ Failed to create action item: {str(action_error)}")
                    import traceback
                    current_app.logger.error(traceback.format_exc())
                    # Don't fail the request if action item creation fails
            
            # Existing Production notification code
            if project.stage == 'Production' and old_customer_stage != 'Production':
                notification = ProductionNotification(
                    id=str(uuid.uuid4()),
                    customer_id=customer.id,
                    message=f"Customer '{customer.name}' moved to Production stage",
                    created_at=datetime.utcnow(),
                    moved_by=request.current_user.email,
                    read=False
                )
                session.add(notification)
        
        session.commit()
        
        current_app.logger.info(f"Project {project_id} updated")
        
        return jsonify({
            'success': True,
            'message': 'Project updated successfully',
            'project': project.to_dict(include_forms=True)
        }), 200
        
    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"Error updating project: {e}")
        return jsonify({'error': f'Failed to update project: {str(e)}'}), 500
    finally:
        session.close()


@customer_bp.route('/projects/<string:project_id>', methods=['DELETE', 'OPTIONS'])
@token_required
def delete_project(project_id):
    """Delete a project (Manager/HR only)"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        if request.current_user.role not in ['Manager', 'HR']:
            return jsonify({'error': 'You do not have permission to delete projects'}), 403
        
        project = session.get(Project, project_id)
        if not project:
            return jsonify({'error': 'Project not found'}), 404
        
        customer_id = project.customer_id
        
        session.delete(project)
        session.commit()
        
        # Check if customer has remaining projects or jobs
        remaining_projects_count = session.query(Project).filter_by(customer_id=customer_id).count()
        remaining_jobs_count = session.query(Job).filter_by(customer_id=customer_id).count()
        
        if remaining_projects_count == 0 and remaining_jobs_count == 0:
             customer = session.get(Customer, customer_id)
             if customer:
                 customer.stage = 'Lead' 
                 session.commit()

        current_app.logger.info(f"Project {project_id} deleted")
        
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
# PROJECT FORMS ENDPOINTS
# ==========================================

@customer_bp.route('/projects/<string:project_id>/forms', methods=['GET', 'OPTIONS'])
@token_required
def get_project_forms(project_id):
    """Get all forms for a specific project"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        project = session.get(Project, project_id)
        if not project:
            return jsonify({'error': 'Project not found'}), 404
            
        customer = project.customer
        
        # Check permissions
        if request.current_user.role in ['Sales', 'Staff']:
            if customer.created_by != str(request.current_user.id) and customer.salesperson != request.current_user.full_name:
                return jsonify({'error': 'You do not have permission to view forms for this project'}), 403
        
        forms = session.query(CustomerFormData).filter_by(project_id=project_id).order_by(CustomerFormData.submitted_at.desc()).all()
        
        return jsonify([form.to_dict() for form in forms]), 200
        
    except Exception as e:
        current_app.logger.exception(f"Error fetching forms: {e}")
        return jsonify({'error': 'Failed to fetch forms'}), 500
    finally:
        session.close()

    
# ==========================================
# DRAWING DOCUMENTS ENDPOINTS
# ==========================================

@customer_bp.route('/drawings', methods=['GET', 'OPTIONS'])
@token_required
def get_drawing_documents():
    """Get all drawing documents for a specific customer"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        customer_id = request.args.get('customer_id')
        if not customer_id:
            return jsonify({'error': 'Customer ID is required'}), 400
        
        customer = session.get(Customer, customer_id)
        if not customer:
            return jsonify({'error': 'Customer not found'}), 404
        
        # Check permissions
        if request.current_user.role in ['Sales', 'Staff']:
            if customer.created_by != str(request.current_user.id) and customer.salesperson != request.current_user.full_name:
                return jsonify({'error': 'You do not have permission to view documents for this customer'}), 403
        
        drawings = session.query(DrawingDocument).filter_by(customer_id=customer_id).order_by(DrawingDocument.created_at.desc()).all()
        
        return jsonify([drawing.to_dict() for drawing in drawings]), 200
        
    except Exception as e:
        current_app.logger.exception(f"Error fetching drawings: {e}")
        return jsonify({'error': 'Failed to fetch drawing documents'}), 500
    finally:
        session.close()


@customer_bp.route('/drawings/<string:drawing_id>', methods=['DELETE', 'OPTIONS'])
@token_required
def delete_drawing_document(drawing_id):
    """Delete a drawing document (Manager/HR only)"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        if request.current_user.role not in ['Manager', 'HR']:
            return jsonify({'error': 'You do not have permission to delete documents'}), 403
        
        drawing = session.get(DrawingDocument, drawing_id)
        if not drawing:
            return jsonify({'error': 'Document not found'}), 404
        
        session.delete(drawing)
        session.commit()
        
        current_app.logger.info(f"Drawing document {drawing_id} deleted")
        
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

@customer_bp.route('/customers/debug-accepted', methods=['GET', 'OPTIONS'])
# @token_required
def debug_accepted_customers():
    """Debug endpoint to see what's going on with Accepted stage"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        # Get all customers in Accepted stage
        customers_in_accepted = session.query(Customer).filter(
            Customer.stage == 'Accepted'
        ).all()
        
        debug_info = []
        
        for customer in customers_in_accepted:
            # Get all projects for this customer
            projects = session.query(Project).filter_by(customer_id=customer.id).all()
            
            project_info = []
            for project in projects:
                project_info.append({
                    'id': project.id,
                    'name': project.project_name,
                    'type': project.project_type,
                    'stage': project.stage
                })
            
            debug_info.append({
                'customer_id': customer.id,
                'customer_name': customer.name,
                'customer_stage': customer.stage,
                'projects': project_info,
                'projects_in_accepted': len([p for p in projects if p.stage == 'Accepted'])
            })
        
        current_app.logger.info(f"🔍 Debug: Found {len(customers_in_accepted)} customers with stage='Accepted'")
        
        return jsonify({
            'total_customers_in_accepted': len(customers_in_accepted),
            'details': debug_info
        }), 200
        
    except Exception as e:
        current_app.logger.exception(f"❌ Debug error: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()

@customer_bp.route('/customers/<string:customer_id>/forms', methods=['GET', 'OPTIONS'])
@token_required
def get_customer_forms(customer_id):
    """Get all form submissions for a specific customer"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        customer = session.get(Customer, customer_id)
        if not customer:
            return jsonify({'error': 'Customer not found'}), 404
        
        # Check permissions
        if request.current_user.role in ['Sales', 'Staff']:
            if customer.created_by != str(request.current_user.id) and customer.salesperson != request.current_user.full_name:
                return jsonify({'error': 'You do not have permission to view forms for this customer'}), 403
        
        # Get all form submissions for this customer
        forms = session.query(CustomerFormData).filter_by(
            customer_id=customer_id
        ).order_by(CustomerFormData.submitted_at.desc()).all()
        
        current_app.logger.info(f"📋 Found {len(forms)} form submissions for customer {customer_id}")
        
        result = []
        for form in forms:
            try:
                form_data = json.loads(form.form_data) if form.form_data else {}
                
                result.append({
                    'id': form.id,
                    'submitted_at': form.submitted_at.isoformat() if form.submitted_at else None,
                    'form_type': form_data.get('form_type', 'unknown'),
                    'is_invoice': form_data.get('is_invoice', False),
                    'is_receipt': form_data.get('is_receipt', False),
                    'checklist_type': form_data.get('checklistType'),
                    'approval_status': form.approval_status or 'approved',
                    'form_data': form_data
                })
            except Exception as e:
                current_app.logger.error(f"Error processing form {form.id}: {e}")
                continue
        
        return jsonify(result), 200
        
    except Exception as e:
        current_app.logger.exception(f"Error fetching customer forms: {e}")
        return jsonify({'error': 'Failed to fetch forms'}), 500
    finally:
        session.close()