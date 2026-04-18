from flask import Blueprint, request, jsonify
from datetime import datetime
import uuid
from sqlalchemy import text
from ..db import SessionLocal
from .auth_helpers import token_required

action_items_bp = Blueprint('action_items', __name__)

@action_items_bp.route('/action-items', methods=['GET'])
@token_required
def get_action_items(current_user):
    """Get all pending action items (notifications)"""
    session = SessionLocal()
    try:
        tenant_id = current_user.get('tenant_id')
        
        # Query notifications that are action items
        query = text("""
            SELECT 
                n.notification_id,
                n.notification_type,
                n.priority,
                n.message,
                n.created_at,
                n.read,
                n.client_id,
                n.property_id,
                n.contract_id,
                c.client_company_name,
                c.client_contact_name
            FROM "StreemLyne_MT"."Notification_Master" n
            LEFT JOIN "StreemLyne_MT"."Client_Master" c ON n.client_id = c.client_id
            WHERE n.tenant_id = :tenant_id
            AND n.dismissed = false
            AND n.notification_type IN ('action_required', 'task', 'follow_up')
            ORDER BY 
                CASE n.priority 
                    WHEN 'high' THEN 1 
                    WHEN 'medium' THEN 2 
                    ELSE 3 
                END,
                n.created_at DESC
        """)
        
        result = session.execute(query, {'tenant_id': tenant_id})
        notifications = result.fetchall()
        
        return jsonify([{
            'id': row.notification_id,
            'customer_name': row.client_company_name or row.client_contact_name or 'Unknown',
            'customer_id': row.client_id,
            'property_id': row.property_id,
            'contract_id': row.contract_id,
            'type': row.notification_type,
            'priority': row.priority,
            'message': row.message,
            'created_at': row.created_at.isoformat() if row.created_at else None,
            'read': row.read
        } for row in notifications])
        
    except Exception as e:
        print(f"Error fetching action items: {str(e)}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@action_items_bp.route('/action-items/<int:notification_id>/complete', methods=['PATCH'])
@token_required
def complete_action_item(current_user, notification_id):
    """Mark an action item (notification) as completed/dismissed"""
    session = SessionLocal()
    try:
        tenant_id = current_user.get('tenant_id')
        
        query = text("""
            UPDATE "StreemLyne_MT"."Notification_Master"
            SET 
                dismissed = true,
                read = true,
                read_at = :read_at
            WHERE notification_id = :notification_id
            AND tenant_id = :tenant_id
            RETURNING notification_id
        """)
        
        result = session.execute(query, {
            'notification_id': notification_id,
            'tenant_id': tenant_id,
            'read_at': datetime.utcnow()
        })
        
        if result.rowcount == 0:
            return jsonify({'error': 'Action item not found'}), 404
        
        session.commit()
        return jsonify({'message': 'Action item marked as completed'})
        
    except Exception as e:
        print(f"Error completing action item: {str(e)}")
        session.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@action_items_bp.route('/action-items', methods=['POST'])
@token_required
def create_action_item(current_user):
    """Create a new action item (notification)"""
    session = SessionLocal()
    try:
        data = request.get_json()
        tenant_id = current_user.get('tenant_id')
        employee_id = current_user.get('employee_id')
        
        # Validate required fields
        if not data.get('message'):
            return jsonify({'error': 'Message is required'}), 400
        
        # Check if similar notification already exists
        check_query = text("""
            SELECT notification_id 
            FROM "StreemLyne_MT"."Notification_Master"
            WHERE tenant_id = :tenant_id
            AND client_id = :client_id
            AND notification_type = :notification_type
            AND dismissed = false
            AND read = false
        """)
        
        existing = session.execute(check_query, {
            'tenant_id': tenant_id,
            'client_id': data.get('client_id'),
            'notification_type': data.get('type', 'action_required')
        }).fetchone()
        
        if existing:
            return jsonify({'message': 'Similar action item already exists'}), 200
        
        # Create new notification
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
            'employee_id': employee_id,
            'client_id': data.get('client_id'),
            'property_id': data.get('property_id'),
            'contract_id': data.get('contract_id'),
            'notification_type': data.get('type', 'action_required'),
            'priority': data.get('priority', 'medium'),
            'message': data['message'],
            'created_at': datetime.utcnow()
        })
        
        session.commit()
        new_id = result.fetchone()[0]
        
        return jsonify({
            'message': 'Action item created successfully',
            'notification_id': new_id
        }), 201
        
    except Exception as e:
        print(f"Error creating action item: {str(e)}")
        session.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@action_items_bp.route('/action-items/<int:notification_id>', methods=['DELETE'])
@token_required
def delete_action_item(current_user, notification_id):
    """Delete an action item"""
    session = SessionLocal()
    try:
        tenant_id = current_user.get('tenant_id')
        
        query = text("""
            DELETE FROM "StreemLyne_MT"."Notification_Master"
            WHERE notification_id = :notification_id
            AND tenant_id = :tenant_id
            RETURNING notification_id
        """)
        
        result = session.execute(query, {
            'notification_id': notification_id,
            'tenant_id': tenant_id
        })
        
        if result.rowcount == 0:
            return jsonify({'error': 'Action item not found'}), 404
        
        session.commit()
        return jsonify({'message': 'Action item deleted successfully'})
        
    except Exception as e:
        print(f"Error deleting action item: {str(e)}")
        session.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()