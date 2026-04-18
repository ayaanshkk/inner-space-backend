"""
Notification Routes - Adapted for StreemLyne_MT schema
Handles notification management using Notification_Master table
"""
from flask import Blueprint, jsonify, request, current_app
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from datetime import datetime
import uuid

from ..db import SessionLocal
from .auth_helpers import token_required, get_current_tenant_id, get_current_employee_id

notification_bp = Blueprint('notification', __name__)


# ============================================================================
# HELPER FUNCTION: Create Activity Notification
# ============================================================================

def create_activity_notification(session, message, job_id=None, customer_id=None, 
                                moved_by=None, form_submission_id=None, form_type=None):
    """
    Create notifications for all eligible users (Manager, HR, Production)
    Each user gets their own copy of the notification
    
    Args:
        session: Active SQLAlchemy session
        message: Notification message text
        job_id: Optional job/contract ID reference
        customer_id: Optional customer/client ID reference
        moved_by: Username or ID of person who performed the action
        form_submission_id: Optional form submission ID
        form_type: Optional form type
    """
    try:
        # Get tenant_id from session or context
        # Note: This is a simplified version - you may need to pass tenant_id as parameter
        from flask import g
        tenant_id = getattr(g, 'tenant_id', None)
        
        if not tenant_id:
            current_app.logger.warning("⚠️ No tenant_id available for notification")
            return
        
        # Get all employees with eligible roles
        eligible_roles = ['1', '2', '5']  # Manager, HR, Production
        
        query = text("""
            SELECT employee_id
            FROM "StreemLyne_MT"."Employee_Master"
            WHERE tenant_id = :tenant_id
            AND (
                role_ids LIKE '%1%' OR  -- Manager
                role_ids LIKE '%2%' OR  -- HR
                role_ids LIKE '%5%'     -- Production
            )
        """)
        
        result = session.execute(query, {'tenant_id': tenant_id})
        employees = result.fetchall()
        
        if not employees:
            current_app.logger.warning("⚠️ No eligible employees found for notifications")
            return
        
        # Create a notification for each eligible employee
        insert_query = text("""
            INSERT INTO "StreemLyne_MT"."Notification_Master" (
                tenant_id,
                employee_id,
                client_id,
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
                :contract_id,
                :notification_type,
                :priority,
                :message,
                false,
                false,
                :created_at
            )
        """)
        
        for emp in employees:
            session.execute(insert_query, {
                'tenant_id': tenant_id,
                'employee_id': emp.employee_id,
                'client_id': customer_id,
                'contract_id': job_id,
                'notification_type': 'activity',
                'priority': 'medium',
                'message': message,
                'created_at': datetime.utcnow()
            })
        
        session.commit()
        current_app.logger.info(f"✅ Created {len(employees)} notifications for eligible employees")
        
    except Exception as e:
        current_app.logger.error(f"❌ Failed to create notifications: {e}")
        session.rollback()
        raise


# ============================================================================
# GET NOTIFICATIONS
# ============================================================================

@notification_bp.route('/notifications/production', methods=['GET', 'OPTIONS'])
@token_required
def get_production_notifications():
    """
    Get notifications for current user (not dismissed)
    Used by notification sidebar
    """
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    session = SessionLocal()
    try:
        tenant_id = get_current_tenant_id()
        employee_id = get_current_employee_id()
        
        query = text("""
            SELECT 
                n.notification_id,
                n.client_id,
                n.contract_id,
                n.property_id,
                n.notification_type,
                n.priority,
                n.message,
                n.read,
                n.dismissed,
                n.created_at,
                n.read_at
            FROM "StreemLyne_MT"."Notification_Master" n
            WHERE n.tenant_id = :tenant_id
            AND n.employee_id = :employee_id
            AND n.dismissed = false
            ORDER BY n.created_at DESC
        """)
        
        result = session.execute(query, {
            'tenant_id': tenant_id,
            'employee_id': employee_id
        })
        notifications = result.fetchall()

        return jsonify([{
            'id': n.notification_id,
            'job_id': n.contract_id,
            'customer_id': n.client_id,
            'property_id': n.property_id,
            'notification_type': n.notification_type,
            'priority': n.priority,
            'message': n.message,
            'created_at': n.created_at.isoformat() if n.created_at else None,
            'read': n.read,
            'dismissed': n.dismissed,
            'read_at': n.read_at.isoformat() if n.read_at else None
        } for n in notifications]), 200
        
    except SQLAlchemyError as e:
        session.rollback()
        current_app.logger.exception(f"Database error fetching notifications: {e}")
        return jsonify({'error': 'Database error occurred'}), 500
    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"Error fetching notifications: {e}")
        return jsonify({'error': 'An unexpected error occurred'}), 500
    finally:
        session.close()


@notification_bp.route('/notifications/production/all', methods=['GET', 'OPTIONS'])
@token_required
def get_all_notifications_including_dismissed():
    """
    Get ALL notifications for current user (including dismissed)
    Used by full notifications page
    """
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    session = SessionLocal()
    try:
        tenant_id = get_current_tenant_id()
        employee_id = get_current_employee_id()
        
        query = text("""
            SELECT 
                n.notification_id,
                n.client_id,
                n.contract_id,
                n.property_id,
                n.notification_type,
                n.priority,
                n.message,
                n.read,
                n.dismissed,
                n.created_at,
                n.read_at
            FROM "StreemLyne_MT"."Notification_Master" n
            WHERE n.tenant_id = :tenant_id
            AND n.employee_id = :employee_id
            ORDER BY n.created_at DESC
        """)
        
        result = session.execute(query, {
            'tenant_id': tenant_id,
            'employee_id': employee_id
        })
        notifications = result.fetchall()

        return jsonify([{
            'id': n.notification_id,
            'job_id': n.contract_id,
            'customer_id': n.client_id,
            'property_id': n.property_id,
            'notification_type': n.notification_type,
            'priority': n.priority,
            'message': n.message,
            'created_at': n.created_at.isoformat() if n.created_at else None,
            'read': n.read,
            'dismissed': n.dismissed,
            'read_at': n.read_at.isoformat() if n.read_at else None
        } for n in notifications]), 200
        
    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"Error fetching all notifications: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


# ============================================================================
# MARK AS READ
# ============================================================================

@notification_bp.route('/notifications/production/<int:notification_id>/read', methods=['PATCH', 'OPTIONS'])
@token_required
def mark_as_read(notification_id):
    """Mark a specific notification as read"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        tenant_id = get_current_tenant_id()
        employee_id = get_current_employee_id()
        
        # Verify ownership and update
        update_query = text("""
            UPDATE "StreemLyne_MT"."Notification_Master"
            SET read = true, read_at = :read_at
            WHERE notification_id = :notification_id
            AND tenant_id = :tenant_id
            AND employee_id = :employee_id
        """)
        
        session.execute(update_query, {
            'read_at': datetime.utcnow(),
            'notification_id': notification_id,
            'tenant_id': tenant_id,
            'employee_id': employee_id
        })
        session.commit()
        
        return jsonify({'message': 'Notification marked as read'}), 200
            
    except SQLAlchemyError as e:
        session.rollback()
        current_app.logger.exception(f"Database error marking notification as read: {e}")
        return jsonify({'error': 'Database error occurred'}), 500
    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"Error marking notification as read: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@notification_bp.route('/notifications/production/mark-all-read', methods=['PATCH', 'OPTIONS'])
@token_required
def mark_all_as_read():
    """Mark all unread notifications as read for current user"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        tenant_id = get_current_tenant_id()
        employee_id = get_current_employee_id()
        
        update_query = text("""
            UPDATE "StreemLyne_MT"."Notification_Master"
            SET read = true, read_at = :read_at
            WHERE tenant_id = :tenant_id
            AND employee_id = :employee_id
            AND read = false
        """)
        
        result = session.execute(update_query, {
            'read_at': datetime.utcnow(),
            'tenant_id': tenant_id,
            'employee_id': employee_id
        })
        session.commit()
        
        return jsonify({
            'message': 'All notifications marked as read',
            'count': result.rowcount
        }), 200
            
    except SQLAlchemyError as e:
        session.rollback()
        current_app.logger.exception(f"Database error marking all as read: {e}")
        return jsonify({'error': 'Database error occurred'}), 500
    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"Error marking all as read: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


# ============================================================================
# DISMISS NOTIFICATIONS
# ============================================================================

@notification_bp.route('/notifications/production/<int:notification_id>/dismiss', methods=['POST', 'OPTIONS'])
@token_required
def dismiss_notification(notification_id):
    """Dismiss notification from sidebar (but keep in full notifications page)"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        tenant_id = get_current_tenant_id()
        employee_id = get_current_employee_id()
        
        update_query = text("""
            UPDATE "StreemLyne_MT"."Notification_Master"
            SET dismissed = true
            WHERE notification_id = :notification_id
            AND tenant_id = :tenant_id
            AND employee_id = :employee_id
        """)
        
        session.execute(update_query, {
            'notification_id': notification_id,
            'tenant_id': tenant_id,
            'employee_id': employee_id
        })
        session.commit()
        
        return jsonify({'success': True, 'message': 'Notification dismissed'}), 200
        
    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"Error dismissing notification: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


# ============================================================================
# DELETE NOTIFICATIONS
# ============================================================================

@notification_bp.route('/notifications/production/<int:notification_id>', methods=['DELETE', 'OPTIONS'])
@token_required
def delete_notification(notification_id):
    """Permanently delete notification"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        tenant_id = get_current_tenant_id()
        employee_id = get_current_employee_id()
        
        delete_query = text("""
            DELETE FROM "StreemLyne_MT"."Notification_Master"
            WHERE notification_id = :notification_id
            AND tenant_id = :tenant_id
            AND employee_id = :employee_id
        """)
        
        session.execute(delete_query, {
            'notification_id': notification_id,
            'tenant_id': tenant_id,
            'employee_id': employee_id
        })
        session.commit()
        
        return jsonify({'message': 'Notification deleted'}), 200
            
    except SQLAlchemyError as e:
        session.rollback()
        current_app.logger.exception(f"Database error deleting notification: {e}")
        return jsonify({'error': 'Database error occurred'}), 500
    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"Error deleting notification: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@notification_bp.route('/notifications/production/clear-all', methods=['DELETE', 'OPTIONS'])
@token_required
def clear_all_notifications():
    """Delete all notifications permanently for current user"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        tenant_id = get_current_tenant_id()
        employee_id = get_current_employee_id()
        
        delete_query = text("""
            DELETE FROM "StreemLyne_MT"."Notification_Master"
            WHERE tenant_id = :tenant_id
            AND employee_id = :employee_id
        """)
        
        result = session.execute(delete_query, {
            'tenant_id': tenant_id,
            'employee_id': employee_id
        })
        session.commit()
        
        return jsonify({
            'message': 'All notifications cleared',
            'count': result.rowcount
        }), 200
            
    except SQLAlchemyError as e:
        session.rollback()
        current_app.logger.exception(f"Database error clearing all notifications: {e}")
        return jsonify({'error': 'Database error occurred'}), 500
    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"Error clearing all notifications: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@notification_bp.route('/notifications/production/clear-dismissed', methods=['POST', 'OPTIONS'])
@token_required
def clear_dismissed_notifications():
    """Clear all dismissed notifications for current user"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        tenant_id = get_current_tenant_id()
        employee_id = get_current_employee_id()
        
        delete_query = text("""
            DELETE FROM "StreemLyne_MT"."Notification_Master"
            WHERE tenant_id = :tenant_id
            AND employee_id = :employee_id
            AND dismissed = true
        """)
        
        result = session.execute(delete_query, {
            'tenant_id': tenant_id,
            'employee_id': employee_id
        })
        session.commit()
        
        return jsonify({
            'success': True,
            'message': f'Cleared {result.rowcount} dismissed notifications',
            'count': result.rowcount
        }), 200
        
    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"Error clearing dismissed notifications: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


# ============================================================================
# STATISTICS
# ============================================================================

@notification_bp.route('/notifications/production/stats', methods=['GET', 'OPTIONS'])
@token_required
def get_notification_stats():
    """Get statistics about notifications for current user"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    session = SessionLocal()
    try:
        tenant_id = get_current_tenant_id()
        employee_id = get_current_employee_id()
        
        stats_query = text("""
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN read = false THEN 1 ELSE 0 END) as unread,
                SUM(CASE WHEN read = true THEN 1 ELSE 0 END) as read,
                SUM(CASE WHEN dismissed = true THEN 1 ELSE 0 END) as dismissed
            FROM "StreemLyne_MT"."Notification_Master"
            WHERE tenant_id = :tenant_id
            AND employee_id = :employee_id
        """)
        
        result = session.execute(stats_query, {
            'tenant_id': tenant_id,
            'employee_id': employee_id
        })
        stats = result.fetchone()
        
        return jsonify({
            'total': stats.total or 0,
            'unread': stats.unread or 0,
            'read': stats.read or 0,
            'dismissed': stats.dismissed or 0
        }), 200
            
    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"Error fetching notification stats: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()