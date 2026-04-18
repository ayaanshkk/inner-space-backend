"""
Database Routes - Adapted for StreemLyne_MT schema
Handles pipeline management, stage updates, and related operations
"""
import os
import uuid
from typing import Optional
from flask import Blueprint, request, jsonify, current_app
import json
from datetime import datetime, date, timedelta
from sqlalchemy import text, func
from sqlalchemy.exc import OperationalError

from ..db import SessionLocal
from .auth_helpers import token_required, get_current_tenant_id, get_current_employee_id

db_bp = Blueprint('database', __name__)

# Define stage hierarchy
PIPELINE_STAGE_ORDER = [
    "Lead", "Survey", "Design", "Quote",
    "Accepted", "Rejected", "Ordered",
    "Production", "Delivery", "Installation",
    "Complete", "Remedial", "Cancelled"
]


def _extract_stage_from_payload(data: dict) -> Optional[str]:
    """Extract stage from payload"""
    
    if not isinstance(data, dict):
        return None

    # Check for direct 'stage' field
    stage = data.get('stage')
    if stage and isinstance(stage, str):
        stage = stage.strip()
        if stage in PIPELINE_STAGE_ORDER:
            return stage
    
    # Check for object format
    if isinstance(stage, dict):
        for key in ('value', 'label', 'stage'):
            inner = stage.get(key)
            if isinstance(inner, str) and inner.strip() in PIPELINE_STAGE_ORDER:
                return inner.strip()
    
    # Check alternative field names
    for field in ('target_stage', 'targetStage', 'new_stage', 'newStage', 'process_stage'):
        alt_stage = data.get(field)
        if alt_stage and isinstance(alt_stage, str):
            alt_stage = alt_stage.strip()
            if alt_stage in PIPELINE_STAGE_ORDER:
                return alt_stage
    
    return None


# ==========================================
# CLIENT/CUSTOMER STAGE UPDATES
# ==========================================

@db_bp.route('/customers/<int:customer_id>/stage', methods=['PATCH', 'OPTIONS'])
@token_required
def update_customer_stage(customer_id):
    """Update customer/client stage"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        tenant_id = get_current_tenant_id()
        employee_id = get_current_employee_id()
        
        # Get current stage
        get_stage_query = text("""
            SELECT stage, client_company_name, client_contact_name
            FROM "StreemLyne_MT"."Client_Master"
            WHERE client_id = :client_id AND tenant_id = :tenant_id
        """)
        
        result = session.execute(get_stage_query, {
            'client_id': customer_id,
            'tenant_id': tenant_id
        })
        client = result.fetchone()
        
        if not client:
            return jsonify({'error': 'Customer not found'}), 404

        data = request.json
        new_stage = _extract_stage_from_payload(data)
        
        current_app.logger.info(f"🔄 Stage update request for customer {customer_id}: {client.stage} → {new_stage}")
        
        if not new_stage:
            return jsonify({'error': 'Stage is required'}), 400

        if new_stage not in PIPELINE_STAGE_ORDER:
            return jsonify({'error': f'Invalid stage: {new_stage}'}), 400

        old_stage = client.stage
        
        if old_stage == new_stage:
            return jsonify({
                'message': 'Stage not changed',
                'stage_updated': False,
                'customer_id': customer_id,
                'new_stage': new_stage,
                'old_stage': old_stage
            }), 200

        # Update client stage
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
        notification_created = False
        if new_stage in ['Accepted', 'Production', 'Delivery', 'Installation', 'Complete']:
            try:
                stage_emoji = {
                    'Accepted': '✅',
                    'Production': '🏭',
                    'Delivery': '🚚',
                    'Installation': '🔧',
                    'Complete': '🎉'
                }
                
                client_name = client.client_company_name or client.client_contact_name
                emoji = stage_emoji.get(new_stage, '🔄')
                message = f"{emoji} Customer '{client_name}' moved to {new_stage} stage"
                
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
                    'client_id': customer_id,
                    'notification_type': 'stage_change',
                    'priority': 'high' if new_stage == 'Accepted' else 'medium',
                    'message': message
                })
                
                notification_created = True
                current_app.logger.info(f"✅ Created {new_stage} notification")
                
            except Exception as notif_error:
                current_app.logger.error(f"⚠️ Failed to create notification: {notif_error}")
        
        session.commit()
        
        current_app.logger.info(f"✅ Customer {customer_id} stage updated: {old_stage} → {new_stage}")
        
        return jsonify({
            'message': 'Stage updated successfully',
            'customer_id': customer_id,
            'old_stage': old_stage,
            'new_stage': new_stage,
            'stage_updated': True,
            'notification_sent': notification_created
        }), 200

    except Exception as e:
        session.rollback()
        current_app.logger.error(f"❌ Error updating customer stage: {e}")
        import traceback
        current_app.logger.error(traceback.format_exc())
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


# ==========================================
# OPPORTUNITY/PROJECT STAGE UPDATES
# ==========================================

@db_bp.route('/projects/<int:project_id>/stage', methods=['PATCH', 'OPTIONS'])
@token_required
def update_project_stage(project_id):
    """Update opportunity/project stage"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        tenant_id = get_current_tenant_id()
        employee_id = get_current_employee_id()
        
        # Get current stage
        get_stage_query = text("""
            SELECT 
                o.process_stage,
                o.opportunity_title,
                o.client_id,
                c.client_company_name,
                c.client_contact_name
            FROM "StreemLyne_MT"."Opportunity_Details" o
            JOIN "StreemLyne_MT"."Client_Master" c ON o.client_id = c.client_id
            WHERE o.opportunity_id = :opportunity_id AND o.tenant_id = :tenant_id
        """)
        
        result = session.execute(get_stage_query, {
            'opportunity_id': project_id,
            'tenant_id': tenant_id
        })
        opp = result.fetchone()
        
        if not opp:
            return jsonify({'error': 'Project not found'}), 404

        data = request.json
        new_stage = _extract_stage_from_payload(data)
        
        if not new_stage:
            return jsonify({'error': 'Stage is required'}), 400

        if new_stage not in PIPELINE_STAGE_ORDER:
            return jsonify({'error': 'Invalid stage'}), 400

        old_stage = opp.process_stage or 'Not Started'
        
        if old_stage == new_stage:
            return jsonify({
                'message': 'Stage not changed',
                'project_id': project_id,
                'new_stage': new_stage
            }), 200

        # Update opportunity stage
        update_query = text("""
            UPDATE "StreemLyne_MT"."Opportunity_Details"
            SET process_stage = :stage,
                process_stage_updated_at = :updated_at,
                process_stage_updated_by = :updated_by
            WHERE opportunity_id = :opportunity_id AND tenant_id = :tenant_id
        """)
        
        session.execute(update_query, {
            'stage': new_stage,
            'updated_at': datetime.utcnow(),
            'updated_by': employee_id,
            'opportunity_id': project_id,
            'tenant_id': tenant_id
        })
        
        # Create notification for important stages
        if new_stage in ['Accepted', 'Production', 'Delivery', 'Installation', 'Complete']:
            try:
                stage_emoji = {
                    'Accepted': '✅',
                    'Production': '🏭',
                    'Delivery': '🚚',
                    'Installation': '🔧',
                    'Complete': '🎉'
                }
                
                client_name = opp.client_company_name or opp.client_contact_name
                emoji = stage_emoji.get(new_stage, '🔄')
                message = f"{emoji} Project '{opp.opportunity_title}' for {client_name} moved to {new_stage}"
                
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
                    'client_id': opp.client_id,
                    'contract_id': project_id,
                    'notification_type': 'stage_change',
                    'priority': 'high' if new_stage == 'Accepted' else 'medium',
                    'message': message
                })
                
                current_app.logger.info(f"📢 Created {new_stage} notification for project {project_id}")
                
            except Exception as notif_error:
                current_app.logger.warning(f"⚠️ Failed to create notification: {notif_error}")

        session.commit()

        return jsonify({
            'message': 'Stage updated successfully',
            'project_id': project_id,
            'old_stage': old_stage,
            'new_stage': new_stage
        }), 200

    except Exception as e:
        session.rollback()
        current_app.logger.error(f"Error updating project stage: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


# ==========================================
# PIPELINE DATA
# ==========================================

@db_bp.route('/pipeline', methods=['GET', 'OPTIONS'])
@token_required
def get_pipeline_data():
    """Get all pipeline items (clients and opportunities)"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        tenant_id = get_current_tenant_id()
        
        current_app.logger.info("📊 Fetching pipeline data...")
        
        # Get all clients with their opportunities
        query = text("""
            SELECT 
                c.client_id,
                c.client_company_name,
                c.client_contact_name,
                c.client_phone,
                c.client_email,
                c.address,
                c.post_code,
                c.stage as client_stage,
                c.created_at as client_created_at,
                o.opportunity_id,
                o.opportunity_title,
                o.process_stage,
                o.created_at as opp_created_at
            FROM "StreemLyne_MT"."Client_Master" c
            LEFT JOIN "StreemLyne_MT"."Opportunity_Details" o 
                ON c.client_id = o.client_id AND o.deleted_at IS NULL
            WHERE c.tenant_id = :tenant_id
            AND c.is_deleted = false
            ORDER BY c.created_at DESC, o.created_at DESC
        """)
        
        result = session.execute(query, {'tenant_id': tenant_id})
        rows = result.fetchall()
        
        # Group by client
        clients_map = {}
        for row in rows:
            client_id = row.client_id
            
            if client_id not in clients_map:
                clients_map[client_id] = {
                    'id': client_id,
                    'name': row.client_company_name or row.client_contact_name,
                    'phone': row.client_phone or '',
                    'email': row.client_email or '',
                    'address': row.address or '',
                    'postcode': row.post_code or '',
                    'stage': row.client_stage or 'Lead',
                    'created_at': row.client_created_at.isoformat() if row.client_created_at else None,
                    'opportunities': []
                }
            
            # Add opportunity if exists
            if row.opportunity_id:
                clients_map[client_id]['opportunities'].append({
                    'id': row.opportunity_id,
                    'title': row.opportunity_title,
                    'stage': row.process_stage or 'Not Started',
                    'created_at': row.opp_created_at.isoformat() if row.opp_created_at else None
                })
        
        # Build pipeline items
        pipeline_items = []
        total_projects = 0
        clients_with_projects = 0
        clients_without_projects = 0
        
        for client_data in clients_map.values():
            has_opportunities = len(client_data['opportunities']) > 0
            
            if has_opportunities:
                clients_with_projects += 1
                # Create item for each opportunity
                for opp in client_data['opportunities']:
                    total_projects += 1
                    pipeline_items.append({
                        'id': f"project-{opp['id']}",
                        'type': 'project',
                        'stage': opp['stage'],
                        'customer': {
                            'id': client_data['id'],
                            'name': client_data['name'],
                            'phone': client_data['phone'],
                            'email': client_data['email'],
                            'address': client_data['address'],
                            'postcode': client_data['postcode']
                        },
                        'project': {
                            'id': opp['id'],
                            'customer_id': client_data['id'],
                            'project_name': opp['title'],
                            'stage': opp['stage'],
                            'created_at': opp['created_at']
                        }
                    })
            else:
                clients_without_projects += 1
                # Client with no opportunities - pure lead
                pipeline_items.append({
                    'id': f"customer-{client_data['id']}",
                    'type': 'customer',
                    'stage': client_data['stage'],
                    'customer': {
                        'id': client_data['id'],
                        'name': client_data['name'],
                        'phone': client_data['phone'],
                        'email': client_data['email'],
                        'address': client_data['address'],
                        'postcode': client_data['postcode'],
                        'created_at': client_data['created_at']
                    }
                })
        
        current_app.logger.info(f"✅ Pipeline data fetched: {len(pipeline_items)} items")
        current_app.logger.info(
            f"   📊 Breakdown: {clients_with_projects} clients with projects ({total_projects} projects), "
            f"{clients_without_projects} clients without projects"
        )
        
        # Log stage distribution
        stage_counts = {}
        for item in pipeline_items:
            stage = item.get('stage', 'Unknown')
            stage_counts[stage] = stage_counts.get(stage, 0) + 1
        current_app.logger.info(f"📊 Stage distribution: {stage_counts}")
        
        return jsonify(pipeline_items)
        
    except Exception as e:
        current_app.logger.error(f"❌ Error fetching pipeline: {e}")
        import traceback
        current_app.logger.error(traceback.format_exc())
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


# ==========================================
# PROJECT/OPPORTUNITY CRUD
# ==========================================

@db_bp.route('/projects/<int:project_id>', methods=['GET', 'PUT', 'DELETE', 'OPTIONS'])
@token_required
def handle_single_project(project_id):
    """Handle single project/opportunity operations"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        tenant_id = get_current_tenant_id()
        
        if request.method == 'GET':
            query = text("""
                SELECT 
                    o.opportunity_id,
                    o.opportunity_title,
                    o.process_stage,
                    o.created_at,
                    o.client_id,
                    c.client_company_name,
                    c.client_contact_name
                FROM "StreemLyne_MT"."Opportunity_Details" o
                JOIN "StreemLyne_MT"."Client_Master" c ON o.client_id = c.client_id
                WHERE o.opportunity_id = :opportunity_id AND o.tenant_id = :tenant_id
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
                'customer_id': opp.client_id,
                'customer_name': opp.client_company_name or opp.client_contact_name
            })

        elif request.method == 'PUT':
            data = request.json
            
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
                RETURNING process_stage
            """)
            
            params['updated_at'] = datetime.utcnow()
            
            result = session.execute(update_query, params)
            new_stage_row = result.fetchone()
            session.commit()
            
            return jsonify({
                'message': 'Project updated successfully',
                'id': project_id,
                'new_stage': new_stage_row[0] if new_stage_row else None
            })

        elif request.method == 'DELETE':
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
            
            return jsonify({'message': 'Project deleted successfully'})

    except Exception as e:
        session.rollback()
        current_app.logger.error(f"Error handling project {project_id}: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()