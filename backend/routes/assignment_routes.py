"""
Assignment Routes - Adapted for StreemLyne_MT schema
Manages scheduling and task assignments
"""
from flask import Blueprint, request, jsonify, current_app
from datetime import datetime
from sqlalchemy import text
from ..db import SessionLocal
from .auth_helpers import (
    token_required, 
    get_current_tenant_id, 
    get_current_employee_id
)

assignment_bp = Blueprint('assignments', __name__)

# Valid assignment fields based on StreemLyne schema
VALID_ASSIGNMENT_FIELDS = [
    'type', 'title', 'date', 'start_date', 'end_date', 'customer_name',
    'assigned_employee_id', 'team_member', 'opportunity_id', 'client_id', 
    'job_type', 'start_time', 'end_time', 'estimated_hours',
    'notes', 'priority', 'status'
]


def filter_assignment_data(data):
    """Filter request data to only include valid Assignment fields"""
    filtered = {}
    for key in VALID_ASSIGNMENT_FIELDS:
        if key in data:
            filtered[key] = data[key]
    return filtered


@assignment_bp.route('/assignments', methods=['GET', 'POST'])
@token_required
def handle_assignments():
    """Handle assignments (stored in Notification_Master as tasks)"""
    
    if request.method == 'POST':
        session = SessionLocal()
        
        try:
            tenant_id = get_current_tenant_id()
            employee_id = get_current_employee_id()
            
            if not tenant_id:
                return jsonify({'error': 'Tenant ID not found in session'}), 401
            
            data = request.json
            current_app.logger.info(f"📥 RAW data received: {data}")
            
            # Filter out invalid fields
            data = filter_assignment_data(data)
            current_app.logger.info(f"📥 Creating assignment with filtered data: {data}")
            
            # Parse date fields
            date_value = None
            start_date_value = None
            end_date_value = None
            
            if data.get('start_date'):
                try:
                    start_date_value = datetime.strptime(data['start_date'], '%Y-%m-%d').date()
                    date_value = start_date_value
                except Exception as e:
                    current_app.logger.error(f"❌ Error parsing start_date: {e}")
                    return jsonify({'error': 'Invalid start_date format'}), 400
            elif data.get('date'):
                try:
                    date_value = datetime.strptime(data['date'], '%Y-%m-%d').date()
                    start_date_value = date_value
                except Exception as e:
                    current_app.logger.error(f"❌ Error parsing date: {e}")
                    return jsonify({'error': 'Invalid date format'}), 400
            else:
                return jsonify({'error': 'start_date or date is required'}), 400
            
            if data.get('end_date'):
                try:
                    end_date_value = datetime.strptime(data['end_date'], '%Y-%m-%d').date()
                except Exception as e:
                    current_app.logger.error(f"❌ Error parsing end_date: {e}")
                    return jsonify({'error': 'Invalid end_date format'}), 400
            else:
                end_date_value = start_date_value
            
            # Get customer name
            customer_name = data.get('customer_name')
            client_id = data.get('client_id')
            
            if client_id and not customer_name:
                client_query = text("""
                    SELECT client_company_name, client_contact_name
                    FROM "StreemLyne_MT"."Client_Master"
                    WHERE client_id = :client_id AND tenant_id = :tenant_id
                """)
                result = session.execute(client_query, {
                    'client_id': client_id,
                    'tenant_id': tenant_id
                })
                client = result.fetchone()
                if client:
                    customer_name = client.client_company_name or client.client_contact_name
            
            # Parse times if provided
            start_time = None
            end_time = None
            if data.get('start_time'):
                try:
                    start_time = datetime.strptime(data['start_time'], '%H:%M').time()
                except ValueError:
                    current_app.logger.warning(f"Invalid start_time format: {data['start_time']}")
            
            if data.get('end_time'):
                try:
                    end_time = datetime.strptime(data['end_time'], '%H:%M').time()
                except ValueError:
                    current_app.logger.warning(f"Invalid end_time format: {data['end_time']}")
            
            # Calculate hours
            estimated_hours = data.get('estimated_hours')
            if isinstance(estimated_hours, str):
                try:
                    estimated_hours = float(estimated_hours) if estimated_hours else None
                except ValueError:
                    estimated_hours = None
            
            # Get assigned employee info
            assigned_employee_id = data.get('assigned_employee_id')
            team_member_name = data.get('team_member')
            
            if assigned_employee_id and not team_member_name:
                emp_query = text("""
                    SELECT employee_name
                    FROM "StreemLyne_MT"."Employee_Master"
                    WHERE employee_id = :employee_id AND tenant_id = :tenant_id
                """)
                result = session.execute(emp_query, {
                    'employee_id': assigned_employee_id,
                    'tenant_id': tenant_id
                })
                emp = result.fetchone()
                if emp:
                    team_member_name = emp.employee_name
            
            # Build assignment message
            assignment_type = data.get('type', 'task')
            title = data.get('title', '')
            priority = data.get('priority', 'medium').lower()
            status = data.get('status', 'scheduled')
            
            message = f"{assignment_type.upper()}: {title}"
            if customer_name:
                message += f" - {customer_name}"
            if start_time:
                message += f" at {start_time.strftime('%H:%M')}"
            if data.get('notes'):
                message += f" | Notes: {data.get('notes')}"
            
            # Store as notification/task
            insert_query = text("""
                INSERT INTO "StreemLyne_MT"."Notification_Master" (
                    tenant_id,
                    employee_id,
                    client_id,
                    property_id,
                    contract_id,
                    notification_type,
                    priority,
                    message,
                    read,
                    dismissed,
                    created_at
                ) VALUES (
                    :tenant_id,
                    :employee_id,
                    :client_id,
                    :property_id,
                    :contract_id,
                    :notification_type,
                    :priority,
                    :message,
                    false,
                    false,
                    :created_at
                )
                RETURNING notification_id
            """)
            
            result = session.execute(insert_query, {
                'tenant_id': tenant_id,
                'employee_id': assigned_employee_id,
                'client_id': client_id,
                'property_id': data.get('property_id'),
                'contract_id': data.get('opportunity_id'),
                'notification_type': 'task',
                'priority': priority,
                'message': message,
                'created_at': datetime.utcnow()
            })
            
            notification_id = result.fetchone()[0]
            session.commit()
            
            current_app.logger.info(f"✅ Assignment created: {notification_id}")
            
            # Build response
            response = {
                'id': notification_id,
                'type': assignment_type,
                'title': title,
                'date': start_date_value.isoformat() if start_date_value else None,
                'start_date': start_date_value.isoformat() if start_date_value else None,
                'end_date': end_date_value.isoformat() if end_date_value else None,
                'customer_name': customer_name,
                'assigned_employee_id': assigned_employee_id,
                'team_member': team_member_name,
                'start_time': start_time.strftime('%H:%M') if start_time else None,
                'end_time': end_time.strftime('%H:%M') if end_time else None,
                'estimated_hours': estimated_hours,
                'notes': data.get('notes'),
                'priority': priority,
                'status': status,
                'created_at': datetime.utcnow().isoformat()
            }
            
            return jsonify({
                'message': 'Assignment created successfully',
                'assignment': response
            }), 201
            
        except Exception as e:
            session.rollback()
            current_app.logger.error(f"Error creating assignment: {e}")
            import traceback
            traceback.print_exc()
            return jsonify({'error': str(e)}), 500
        finally:
            session.close()
    
    # GET - Fetch all assignments for tenant
    if request.method == 'GET':
        session = SessionLocal()
        try:
            tenant_id = get_current_tenant_id()
            
            current_app.logger.info(f"📋 Fetching assignments for tenant: {tenant_id}")
            
            # Query task-type notifications as assignments
            query = text("""
                SELECT 
                    n.notification_id,
                    n.notification_type,
                    n.priority,
                    n.message,
                    n.created_at,
                    n.read_at,
                    n.employee_id,
                    n.client_id,
                    n.property_id,
                    n.contract_id,
                    e.employee_name as team_member,
                    c.client_company_name,
                    c.client_contact_name
                FROM "StreemLyne_MT"."Notification_Master" n
                LEFT JOIN "StreemLyne_MT"."Employee_Master" e ON n.employee_id = e.employee_id
                LEFT JOIN "StreemLyne_MT"."Client_Master" c ON n.client_id = c.client_id
                WHERE n.tenant_id = :tenant_id
                AND n.notification_type = 'task'
                AND n.dismissed = false
                ORDER BY n.created_at DESC
            """)
            
            result = session.execute(query, {'tenant_id': tenant_id})
            notifications = result.fetchall()
            
            current_app.logger.info(f"✅ Returning {len(notifications)} assignments")
            
            assignments = []
            for n in notifications:
                # Parse message to extract details
                # Message format: "TYPE: Title - Customer | Notes: ..."
                message = n.message
                parts = message.split(' | ')
                main_part = parts[0] if parts else message
                notes = parts[1].replace('Notes: ', '') if len(parts) > 1 else ''
                
                type_and_title = main_part.split(': ', 1)
                assignment_type = type_and_title[0].lower() if len(type_and_title) > 1 else 'task'
                title_customer = type_and_title[1] if len(type_and_title) > 1 else message
                
                title_parts = title_customer.split(' - ')
                title = title_parts[0] if title_parts else title_customer
                
                assignments.append({
                    'id': n.notification_id,
                    'type': assignment_type,
                    'title': title,
                    'customer_name': n.client_company_name or n.client_contact_name,
                    'assigned_employee_id': n.employee_id,
                    'team_member': n.team_member,
                    'client_id': n.client_id,
                    'property_id': n.property_id,
                    'opportunity_id': n.contract_id,
                    'priority': n.priority,
                    'status': 'completed' if n.read_at else 'scheduled',
                    'notes': notes,
                    'created_at': n.created_at.isoformat() if n.created_at else None
                })
            
            return jsonify(assignments)
            
        except Exception as e:
            current_app.logger.error(f"Error in GET assignments: {e}")
            import traceback
            traceback.print_exc()
            return jsonify({'error': str(e)}), 500
        finally:
            session.close()


@assignment_bp.route('/assignments/<int:notification_id>', methods=['GET', 'PUT', 'DELETE'])
@token_required
def handle_single_assignment(notification_id):
    """Handle single assignment operations"""
    
    session = SessionLocal()
    try:
        tenant_id = get_current_tenant_id()
        employee_id = get_current_employee_id()
        
        # Verify assignment exists and belongs to tenant
        verify_query = text("""
            SELECT 
                n.notification_id,
                n.notification_type,
                n.priority,
                n.message,
                n.employee_id,
                n.client_id,
                n.read,
                n.dismissed
            FROM "StreemLyne_MT"."Notification_Master" n
            WHERE n.notification_id = :notification_id
            AND n.tenant_id = :tenant_id
            AND n.notification_type = 'task'
        """)
        
        result = session.execute(verify_query, {
            'notification_id': notification_id,
            'tenant_id': tenant_id
        })
        assignment = result.fetchone()
        
        if not assignment:
            return jsonify({'error': 'Assignment not found'}), 404
        
        # GET
        if request.method == 'GET':
            return jsonify({
                'id': assignment.notification_id,
                'priority': assignment.priority,
                'message': assignment.message,
                'assigned_employee_id': assignment.employee_id,
                'client_id': assignment.client_id,
                'status': 'completed' if assignment.read else 'scheduled'
            })
        
        # PUT - Update assignment
        elif request.method == 'PUT':
            data = request.json
            current_app.logger.info(f"📝 Updating assignment {notification_id}: {data}")
            
            data = filter_assignment_data(data)
            
            # Build updated message
            updates = {}
            
            if 'priority' in data:
                updates['priority'] = data['priority'].lower()
            
            if 'status' in data:
                if data['status'] == 'completed':
                    updates['read'] = True
                    updates['read_at'] = datetime.utcnow()
                else:
                    updates['read'] = False
            
            if 'assigned_employee_id' in data:
                updates['employee_id'] = data['assigned_employee_id']
            
            if 'client_id' in data:
                updates['client_id'] = data['client_id']
            
            # Rebuild message if title/notes changed
            if 'title' in data or 'notes' in data:
                assignment_type = data.get('type', 'task')
                title = data.get('title', '')
                notes = data.get('notes', '')
                
                new_message = f"{assignment_type.upper()}: {title}"
                if notes:
                    new_message += f" | Notes: {notes}"
                updates['message'] = new_message
            
            if updates:
                # Build UPDATE query dynamically
                set_clauses = []
                params = {'notification_id': notification_id, 'tenant_id': tenant_id}
                
                for key, value in updates.items():
                    set_clauses.append(f"{key} = :{key}")
                    params[key] = value
                
                update_query = text(f"""
                    UPDATE "StreemLyne_MT"."Notification_Master"
                    SET {', '.join(set_clauses)}
                    WHERE notification_id = :notification_id
                    AND tenant_id = :tenant_id
                """)
                
                session.execute(update_query, params)
                session.commit()
                
                current_app.logger.info(f"✅ Assignment {notification_id} updated")
            
            return jsonify({
                'message': 'Assignment updated successfully',
                'assignment': {'id': notification_id}
            })
        
        # DELETE
        elif request.method == 'DELETE':
            delete_query = text("""
                UPDATE "StreemLyne_MT"."Notification_Master"
                SET dismissed = true
                WHERE notification_id = :notification_id
                AND tenant_id = :tenant_id
            """)
            
            session.execute(delete_query, {
                'notification_id': notification_id,
                'tenant_id': tenant_id
            })
            session.commit()
            
            current_app.logger.info(f"✅ Assignment {notification_id} deleted")
            
            return jsonify({
                'message': 'Assignment deleted successfully',
                'id': notification_id
            }), 200
        
    except Exception as e:
        session.rollback()
        current_app.logger.error(f"Error in handle_single_assignment: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@assignment_bp.route('/jobs/available', methods=['GET'])
@token_required
def get_available_jobs():
    """Get opportunities that are ready to be scheduled"""
    
    session = SessionLocal()
    try:
        tenant_id = get_current_tenant_id()
        
        current_app.logger.info("📋 Fetching available jobs/opportunities...")
        
        # Query opportunities in schedulable stages
        query = text("""
            SELECT 
                o.opportunity_id,
                o.opportunity_title,
                o.client_id,
                o.process_stage,
                o.service_id,
                o.display_id,
                c.client_company_name,
                c.client_contact_name,
                s.service_title
            FROM "StreemLyne_MT"."Opportunity_Details" o
            LEFT JOIN "StreemLyne_MT"."Client_Master" c ON o.client_id = c.client_id
            LEFT JOIN "StreemLyne_MT"."Services_Master" s ON o.service_id = s.service_id
            WHERE o.tenant_id = :tenant_id
            AND o.deleted_at IS NULL
            AND o.process_stage IN ('Not Started', 'In Progress', 'Survey', 'Delivery', 'Installation')
            ORDER BY o.created_at DESC
        """)
        
        result = session.execute(query, {'tenant_id': tenant_id})
        opportunities = result.fetchall()
        
        current_app.logger.info(f"✅ Found {len(opportunities)} available jobs")
        
        jobs = []
        for opp in opportunities:
            jobs.append({
                'id': opp.opportunity_id,
                'job_reference': f"OPP-{opp.display_id}" if opp.display_id else f"OPP-{opp.opportunity_id}",
                'customer_name': opp.client_company_name or opp.client_contact_name or 'Unknown',
                'customer_id': opp.client_id,
                'job_type': opp.service_title or 'Service',
                'stage': opp.process_stage or 'Not Started',
                'work_stage': opp.process_stage or 'Survey'
            })
        
        return jsonify(jobs)
        
    except Exception as e:
        current_app.logger.error(f"❌ Error in get_available_jobs: {e}")
        import traceback
        traceback.print_exc()
        return jsonify([]), 200
    finally:
        session.close()


@assignment_bp.route('/customers/active', methods=['GET'])
@token_required
def get_active_customers():
    """Get active clients for assignments"""
    
    session = SessionLocal()
    try:
        tenant_id = get_current_tenant_id()
        
        current_app.logger.info("📋 Fetching active customers...")
        
        query = text("""
            SELECT 
                client_id,
                client_company_name,
                client_contact_name,
                address,
                client_phone,
                stage,
                is_deleted
            FROM "StreemLyne_MT"."Client_Master"
            WHERE tenant_id = :tenant_id
            AND is_deleted = false
            ORDER BY client_company_name, client_contact_name
        """)
        
        result = session.execute(query, {'tenant_id': tenant_id})
        clients = result.fetchall()
        
        current_app.logger.info(f"✅ Found {len(clients)} customers")
        
        customers = []
        for c in clients:
            customers.append({
                'id': c.client_id,
                'name': c.client_company_name or c.client_contact_name or 'Unknown',
                'address': c.address or '',
                'phone': c.client_phone or '',
                'stage': c.stage or 'Lead',
                'status': 'Deleted' if c.is_deleted else 'Active'
            })
        
        return jsonify(customers)
        
    except Exception as e:
        current_app.logger.error(f"❌ Error in get_active_customers: {e}")
        import traceback
        traceback.print_exc()
        return jsonify([]), 200
    finally:
        session.close()


@assignment_bp.route('/jobs/work-stages', methods=['GET'])
@token_required
def get_job_work_stages():
    """Get all job work stages with metadata"""
    
    work_stages = [
        {
            'value': 'Not Started',
            'label': 'Not Started',
            'description': 'Opportunity created, not yet started',
            'color': '#6B7280',
            'icon': '📋',
            'order': 0
        },
        {
            'value': 'Survey',
            'label': 'Survey',
            'description': 'Site survey and measurements',
            'color': '#8B5CF6',
            'icon': '📏',
            'order': 1
        },
        {
            'value': 'In Progress',
            'label': 'In Progress',
            'description': 'Work in progress',
            'color': '#F59E0B',
            'icon': '⚙️',
            'order': 2
        },
        {
            'value': 'Delivery',
            'label': 'Delivery',
            'description': 'Items being delivered',
            'color': '#06B6D4',
            'icon': '🚚',
            'order': 3
        },
        {
            'value': 'Installation',
            'label': 'Installation',
            'description': 'On-site installation',
            'color': '#14B8A6',
            'icon': '🏗️',
            'order': 4
        }
    ]
    
    return jsonify(work_stages), 200