"""
Job Routes - Adapted for StreemLyne_MT schema
Handles job/opportunity management (jobs are represented as Opportunity_Details)
"""
from flask import Blueprint, request, jsonify, current_app
from sqlalchemy import text, func
from datetime import datetime
import uuid

from ..db import SessionLocal
from .auth_helpers import token_required, get_current_tenant_id, get_current_employee_id

job_bp = Blueprint('jobs', __name__)


def generate_job_reference(session, tenant_id):
    """Generate sequential job reference like AZ-JOB001"""
    # Get count of opportunities for this tenant
    count_query = text("""
        SELECT COUNT(*) FROM "StreemLyne_MT"."Opportunity_Details"
        WHERE tenant_id = :tenant_id
    """)
    
    result = session.execute(count_query, {'tenant_id': tenant_id})
    job_count = result.scalar()
    
    # Generate reference with zero-padded number
    reference_number = job_count + 1
    job_reference = f"AZ-JOB{reference_number:03d}"
    
    # Ensure uniqueness
    check_query = text("""
        SELECT opportunity_id FROM "StreemLyne_MT"."Opportunity_Details"
        WHERE opportunity_reference = :reference AND tenant_id = :tenant_id
    """)
    
    while session.execute(check_query, {'reference': job_reference, 'tenant_id': tenant_id}).fetchone():
        reference_number += 1
        job_reference = f"AZ-JOB{reference_number:03d}"
    
    return job_reference


# ==========================================
# JOB/OPPORTUNITY CRUD
# ==========================================

@job_bp.route('/jobs', methods=['GET', 'OPTIONS'])
@token_required
def get_jobs():
    """Get all jobs with optional filtering"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
        
    session = SessionLocal()
    try:
        tenant_id = get_current_tenant_id()
        
        customer_id = request.args.get('customer_id')
        stage = request.args.get('stage')
        job_type = request.args.get('type')
        
        # Build query
        query_parts = ["""
            SELECT 
                o.opportunity_id,
                o.opportunity_reference,
                o.opportunity_title,
                o.client_id,
                o.process_stage,
                o.priority,
                o.created_at,
                o.process_stage_updated_at,
                c.client_company_name,
                c.client_contact_name
            FROM "StreemLyne_MT"."Opportunity_Details" o
            JOIN "StreemLyne_MT"."Client_Master" c ON o.client_id = c.client_id
            WHERE o.tenant_id = :tenant_id
            AND o.deleted_at IS NULL
        """]
        
        params = {'tenant_id': tenant_id}
        
        if customer_id:
            query_parts.append("AND o.client_id = :client_id")
            params['client_id'] = int(customer_id)
        
        if stage:
            query_parts.append("AND o.process_stage = :stage")
            params['stage'] = stage
        
        # Note: job_type would need a custom field in Opportunity_Details
        # For now, we'll skip this filter
        
        query_parts.append("ORDER BY o.created_at DESC")
        
        query = text(' '.join(query_parts))
        result = session.execute(query, params)
        jobs = result.fetchall()
        
        job_list = [{
            'id': job.opportunity_id,
            'job_reference': job.opportunity_reference,
            'job_name': job.opportunity_title,
            'customer_id': job.client_id,
            'customer_name': job.client_company_name or job.client_contact_name,
            'stage': job.process_stage or 'Not Started',
            'priority': job.priority or 'Medium',
            'created_at': job.created_at.isoformat() if job.created_at else None,
            'updated_at': job.process_stage_updated_at.isoformat() if job.process_stage_updated_at else None
        } for job in jobs]
        
        return jsonify(job_list), 200
        
    except Exception as e:
        current_app.logger.error(f"Error fetching jobs: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@job_bp.route('/jobs/<int:job_id>', methods=['GET', 'OPTIONS'])
@token_required
def get_job(job_id):
    """Get a specific job by ID"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
        
    session = SessionLocal()
    try:
        tenant_id = get_current_tenant_id()
        
        query = text("""
            SELECT 
                o.opportunity_id,
                o.opportunity_reference,
                o.opportunity_title,
                o.client_id,
                o.process_stage,
                o.priority,
                o.created_at,
                o.process_stage_updated_at,
                c.client_company_name,
                c.client_contact_name
            FROM "StreemLyne_MT"."Opportunity_Details" o
            JOIN "StreemLyne_MT"."Client_Master" c ON o.client_id = c.client_id
            WHERE o.opportunity_id = :opportunity_id 
            AND o.tenant_id = :tenant_id
            AND o.deleted_at IS NULL
        """)
        
        result = session.execute(query, {
            'opportunity_id': job_id,
            'tenant_id': tenant_id
        })
        job = result.fetchone()
        
        if not job:
            return jsonify({'error': 'Job not found'}), 404
        
        return jsonify({
            'id': job.opportunity_id,
            'job_reference': job.opportunity_reference,
            'job_name': job.opportunity_title,
            'customer_id': job.client_id,
            'customer_name': job.client_company_name or job.client_contact_name,
            'stage': job.process_stage or 'Not Started',
            'priority': job.priority or 'Medium',
            'created_at': job.created_at.isoformat() if job.created_at else None,
            'updated_at': job.process_stage_updated_at.isoformat() if job.process_stage_updated_at else None
        }), 200
        
    except Exception as e:
        current_app.logger.error(f"Error fetching job {job_id}: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@job_bp.route('/jobs', methods=['POST'])
@token_required
def create_job():
    """Create a new job"""
    session = SessionLocal()
    try:
        tenant_id = get_current_tenant_id()
        employee_id = get_current_employee_id()
        
        data = request.get_json()
        current_app.logger.info(f"Creating job with data: {data}")
        
        # Validate required fields
        if not data.get('customer_id'):
            return jsonify({'error': 'Customer ID is required'}), 400
        
        # Verify customer exists
        check_customer = text("""
            SELECT client_id FROM "StreemLyne_MT"."Client_Master"
            WHERE client_id = :client_id AND tenant_id = :tenant_id
        """)
        
        result = session.execute(check_customer, {
            'client_id': int(data['customer_id']),
            'tenant_id': tenant_id
        })
        
        if not result.fetchone():
            return jsonify({'error': 'Customer not found'}), 400
        
        # Generate job reference
        job_reference = generate_job_reference(session, tenant_id)
        current_app.logger.info(f"Generated job reference: {job_reference}")
        
        # Create opportunity
        insert_query = text("""
            INSERT INTO "StreemLyne_MT"."Opportunity_Details" (
                tenant_id,
                client_id,
                opportunity_reference,
                opportunity_title,
                process_stage,
                priority,
                opportunity_owner_employee_id,
                stage_id,
                created_at
            ) VALUES (
                :tenant_id,
                :client_id,
                :reference,
                :title,
                :stage,
                :priority,
                :employee_id,
                1,
                :created_at
            )
            RETURNING opportunity_id
        """)
        
        result = session.execute(insert_query, {
            'tenant_id': tenant_id,
            'client_id': int(data['customer_id']),
            'reference': job_reference,
            'title': data.get('job_name', f"Job {job_reference}"),
            'stage': data.get('stage', 'Lead'),
            'priority': data.get('priority', 'Medium'),
            'employee_id': employee_id,
            'created_at': datetime.utcnow()
        })
        
        opportunity_id = result.fetchone()[0]
        
        # Create notification
        try:
            notify_query = text("""
                INSERT INTO "StreemLyne_MT"."Notification_Master" (
                    tenant_id,
                    employee_id,
                    client_id,
                    contract_id,
                    notification_type,
                    priority,
                    message,
                    read,
                    dismissed
                ) VALUES (
                    :tenant_id,
                    :employee_id,
                    :client_id,
                    :contract_id,
                    'task',
                    'medium',
                    :message,
                    false,
                    false
                )
            """)
            
            session.execute(notify_query, {
                'tenant_id': tenant_id,
                'employee_id': employee_id,
                'client_id': int(data['customer_id']),
                'contract_id': opportunity_id,
                'message': f"💼 New job created: {data.get('job_name', job_reference)} - Ref: {job_reference}"
            })
            
            current_app.logger.info(f"✅ Notification created for job {opportunity_id}")
            
        except Exception as notif_error:
            current_app.logger.warning(f"⚠️ Failed to create notification: {notif_error}")
        
        session.commit()
        
        current_app.logger.info(f"✅ Created job with ID: {opportunity_id}, Reference: {job_reference}")
        
        return jsonify({
            'id': opportunity_id,
            'job_reference': job_reference,
            'job_name': data.get('job_name', f"Job {job_reference}"),
            'customer_id': data['customer_id'],
            'stage': data.get('stage', 'Lead'),
            'priority': data.get('priority', 'Medium')
        }), 201
        
    except Exception as e:
        session.rollback()
        current_app.logger.error(f"❌ Error creating job: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@job_bp.route('/jobs/<int:job_id>', methods=['PUT', 'OPTIONS'])
@token_required
def update_job(job_id):
    """Update an existing job"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
        
    session = SessionLocal()
    try:
        tenant_id = get_current_tenant_id()
        employee_id = get_current_employee_id()
        
        data = request.get_json()
        
        # Build dynamic update
        update_fields = []
        params = {'opportunity_id': job_id, 'tenant_id': tenant_id}
        
        if 'job_name' in data:
            update_fields.append('opportunity_title = :title')
            params['title'] = data['job_name']
        
        if 'stage' in data:
            update_fields.append('process_stage = :stage')
            params['stage'] = data['stage']
        
        if 'priority' in data:
            update_fields.append('priority = :priority')
            params['priority'] = data['priority']
        
        if not update_fields:
            return jsonify({'error': 'No fields to update'}), 400
        
        update_fields.append('process_stage_updated_at = :updated_at')
        update_fields.append('process_stage_updated_by = :updated_by')
        params['updated_at'] = datetime.utcnow()
        params['updated_by'] = employee_id
        
        update_query = text(f"""
            UPDATE "StreemLyne_MT"."Opportunity_Details"
            SET {', '.join(update_fields)}
            WHERE opportunity_id = :opportunity_id AND tenant_id = :tenant_id
        """)
        
        session.execute(update_query, params)
        session.commit()
        
        return jsonify({'message': 'Job updated successfully'}), 200
        
    except Exception as e:
        session.rollback()
        current_app.logger.error(f"Error updating job {job_id}: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@job_bp.route('/jobs/<int:job_id>', methods=['DELETE', 'OPTIONS'])
@token_required
def delete_job(job_id):
    """Delete a job (soft delete)"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
        
    session = SessionLocal()
    try:
        tenant_id = get_current_tenant_id()
        
        current_app.logger.info(f"Attempting to delete job {job_id}")
        
        # Soft delete
        delete_query = text("""
            UPDATE "StreemLyne_MT"."Opportunity_Details"
            SET deleted_at = :deleted_at
            WHERE opportunity_id = :opportunity_id AND tenant_id = :tenant_id
        """)
        
        session.execute(delete_query, {
            'deleted_at': datetime.utcnow(),
            'opportunity_id': job_id,
            'tenant_id': tenant_id
        })
        
        session.commit()
        
        current_app.logger.info(f"✅ Successfully deleted job {job_id}")
        return jsonify({'message': 'Job deleted successfully'}), 200
        
    except Exception as e:
        session.rollback()
        current_app.logger.error(f"❌ Error deleting job {job_id}: {e}", exc_info=True)
        return jsonify({'error': 'Failed to delete job'}), 500
    finally:
        session.close()


# ==========================================
# JOB STAGE MANAGEMENT
# ==========================================

@job_bp.route('/jobs/<int:job_id>/stage', methods=['PATCH', 'OPTIONS'])
@token_required
def update_job_stage(job_id):
    """Update job stage"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
        
    session = SessionLocal()
    try:
        tenant_id = get_current_tenant_id()
        employee_id = get_current_employee_id()
        
        data = request.get_json()
        
        if not data.get('stage'):
            return jsonify({'error': 'Stage is required'}), 400
        
        # Get old stage
        get_stage_query = text("""
            SELECT process_stage FROM "StreemLyne_MT"."Opportunity_Details"
            WHERE opportunity_id = :opportunity_id AND tenant_id = :tenant_id
        """)
        
        result = session.execute(get_stage_query, {
            'opportunity_id': job_id,
            'tenant_id': tenant_id
        })
        old_stage_row = result.fetchone()
        
        if not old_stage_row:
            return jsonify({'error': 'Job not found'}), 404
        
        old_stage = old_stage_row.process_stage
        
        # Update stage
        update_query = text("""
            UPDATE "StreemLyne_MT"."Opportunity_Details"
            SET 
                process_stage = :stage,
                process_stage_updated_at = :updated_at,
                process_stage_updated_by = :updated_by
            WHERE opportunity_id = :opportunity_id AND tenant_id = :tenant_id
        """)
        
        session.execute(update_query, {
            'stage': data['stage'],
            'updated_at': datetime.utcnow(),
            'updated_by': employee_id,
            'opportunity_id': job_id,
            'tenant_id': tenant_id
        })
        
        session.commit()
        
        return jsonify({
            'message': 'Stage updated successfully',
            'old_stage': old_stage,
            'new_stage': data['stage']
        }), 200
        
    except Exception as e:
        session.rollback()
        current_app.logger.error(f"Error updating stage for job {job_id}: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


# ==========================================
# JOB STATISTICS
# ==========================================

@job_bp.route('/jobs/stats', methods=['GET', 'OPTIONS'])
@token_required
def get_job_stats():
    """Get job statistics"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
        
    session = SessionLocal()
    try:
        tenant_id = get_current_tenant_id()
        
        # Total count
        total_query = text("""
            SELECT COUNT(*) FROM "StreemLyne_MT"."Opportunity_Details"
            WHERE tenant_id = :tenant_id AND deleted_at IS NULL
        """)
        
        total_result = session.execute(total_query, {'tenant_id': tenant_id})
        total_jobs = total_result.scalar()
        
        # By stage
        stage_query = text("""
            SELECT 
                process_stage,
                COUNT(*) as count
            FROM "StreemLyne_MT"."Opportunity_Details"
            WHERE tenant_id = :tenant_id AND deleted_at IS NULL
            GROUP BY process_stage
        """)
        
        stage_result = session.execute(stage_query, {'tenant_id': tenant_id})
        by_stage = {row.process_stage or 'Not Started': row.count for row in stage_result}
        
        # By priority
        priority_query = text("""
            SELECT 
                priority,
                COUNT(*) as count
            FROM "StreemLyne_MT"."Opportunity_Details"
            WHERE tenant_id = :tenant_id AND deleted_at IS NULL
            GROUP BY priority
        """)
        
        priority_result = session.execute(priority_query, {'tenant_id': tenant_id})
        by_priority = {row.priority or 'Medium': row.count for row in priority_result}
        
        stats = {
            'total_jobs': total_jobs,
            'by_stage': by_stage,
            'by_priority': by_priority,
            'by_type': {}  # Not implemented in StreemLyne_MT
        }
        
        return jsonify(stats), 200
        
    except Exception as e:
        current_app.logger.error(f"Error fetching job stats: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


# ==========================================
# LEGACY/COMPATIBILITY ENDPOINTS
# ==========================================

@job_bp.route('/teams', methods=['GET', 'OPTIONS'])
@token_required
def get_teams():
    """Get all active teams (from Employee_Master)"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
        
    session = SessionLocal()
    try:
        tenant_id = get_current_tenant_id()
        
        # Return employees with production/team roles
        query = text("""
            SELECT 
                employee_id,
                employee_name
            FROM "StreemLyne_MT"."Employee_Master"
            WHERE tenant_id = :tenant_id
            AND role_ids LIKE '%5%'  -- Production role
            ORDER BY employee_name
        """)
        
        result = session.execute(query, {'tenant_id': tenant_id})
        teams = result.fetchall()
        
        return jsonify([{
            'id': team.employee_id,
            'name': team.employee_name
        } for team in teams]), 200
        
    except Exception as e:
        current_app.logger.error(f"Error fetching teams: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@job_bp.route('/fitters', methods=['GET', 'OPTIONS'])
@token_required
def get_fitters():
    """Get all active fitters (from Employee_Master)"""
    return get_teams()  # Same as teams for now


@job_bp.route('/salespeople', methods=['GET', 'OPTIONS'])
@token_required
def get_salespeople():
    """Get all active salespeople"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
        
    session = SessionLocal()
    try:
        tenant_id = get_current_tenant_id()
        
        query = text("""
            SELECT 
                employee_id,
                employee_name,
                email
            FROM "StreemLyne_MT"."Employee_Master"
            WHERE tenant_id = :tenant_id
            AND role_ids LIKE '%4%'  -- Sales role
            ORDER BY employee_name
        """)
        
        result = session.execute(query, {'tenant_id': tenant_id})
        salespeople = result.fetchall()
        
        return jsonify([{
            'id': person.employee_id,
            'name': person.employee_name,
            'email': person.email
        } for person in salespeople]), 200
        
    except Exception as e:
        current_app.logger.error(f"Error fetching salespeople: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()