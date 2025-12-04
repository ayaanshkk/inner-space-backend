from flask import Blueprint, jsonify, request, current_app
from ..models import ProductionNotification, User
from .auth_helpers import token_required 
from datetime import datetime
from ..db import SessionLocal
from sqlalchemy.exc import SQLAlchemyError
import uuid

notification_bp = Blueprint('notification', __name__)

# ============================================================================
# HELPER FUNCTION: Create Activity Notification
# ============================================================================

def create_activity_notification(session, message, job_id=None, customer_id=None, 
                                moved_by=None, form_submission_id=None, form_type=None):
    """
    ✅ NEW: Create notifications for ALL eligible users (Manager, HR, Production)
    Each user gets their own copy of the notification
    
    Args:
        session: Active SQLAlchemy session
        message: Notification message text
        job_id: Optional job ID reference
        customer_id: Optional customer ID reference
        moved_by: Username or ID of person who performed the action
        form_submission_id: Optional form submission ID
        form_type: Optional form type (kitchen, bedroom, etc.)
    """
    try:
        # ✅ Get all users who should receive notifications
        eligible_roles = ['Manager', 'HR', 'Production']
        users = session.query(User).filter(
            User.role.in_(eligible_roles),
            User.is_active == True
        ).all()
        
        if not users:
            current_app.logger.warning("⚠️ No eligible users found for notifications")
            return
        
        # ✅ Create a separate notification for EACH user
        for user in users:
            notification = ProductionNotification(
                id=str(uuid.uuid4()),
                user_id=user.id,  # ✅ Assign to specific user
                customer_id=customer_id,
                job_id=job_id,
                form_submission_id=form_submission_id,
                form_type=form_type,
                message=message,
                moved_by=moved_by,
                read=False,
                dismissed=False,  # ✅ Not dismissed initially
                created_at=datetime.utcnow()
            )
            session.add(notification)
        
        session.commit()
        current_app.logger.info(f"✅ Created {len(users)} notifications for eligible users")
        
    except Exception as e:
        current_app.logger.error(f"❌ Failed to create notifications: {e}")
        session.rollback()
        raise


# ============================================================================
# GET ALL NOTIFICATIONS (for current user only)
# ============================================================================

@notification_bp.route('/notifications/production', methods=['GET', 'OPTIONS'])
@token_required
def get_production_notifications():
    """
    ✅ Get notifications for the CURRENT USER ONLY.
    Returns all notifications (not dismissed) sorted by creation date (newest first).
    """
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    session = SessionLocal()
    try:
        # ✅ Filter by current user
        notifications = session.query(ProductionNotification).filter(
            ProductionNotification.user_id == request.current_user.id,
            ProductionNotification.dismissed == False  # ✅ Sidebar doesn't show dismissed
        ).order_by(
            ProductionNotification.created_at.desc()
        ).all()

        return jsonify([
            {
                'id': n.id,
                'job_id': n.job_id,
                'customer_id': n.customer_id,
                'form_submission_id': n.form_submission_id,
                'form_type': n.form_type,
                'message': n.message,
                'created_at': n.created_at.isoformat() if n.created_at else None,
                'moved_by': n.moved_by,
                'read': n.read,
                'dismissed': n.dismissed
            } for n in notifications
        ]), 200
        
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
    ✅ NEW: Get ALL notifications for current user (including dismissed)
    Used by the full notifications page
    """
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    session = SessionLocal()
    try:
        # ✅ Get ALL notifications for current user (including dismissed)
        notifications = session.query(ProductionNotification).filter(
            ProductionNotification.user_id == request.current_user.id
        ).order_by(
            ProductionNotification.created_at.desc()
        ).all()

        return jsonify([
            {
                'id': n.id,
                'job_id': n.job_id,
                'customer_id': n.customer_id,
                'form_submission_id': n.form_submission_id,
                'form_type': n.form_type,
                'message': n.message,
                'created_at': n.created_at.isoformat() if n.created_at else None,
                'moved_by': n.moved_by,
                'read': n.read,
                'dismissed': n.dismissed
            } for n in notifications
        ]), 200
        
    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"Error fetching all notifications: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@notification_bp.route('/notifications/production/<string:notification_id>/read', methods=['PATCH', 'OPTIONS'])
@token_required
def mark_as_read(notification_id):
    """
    Mark a specific notification as read (but don't delete it).
    ✅ Only works for notifications owned by current user
    """
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal() 
    try:
        notification = session.get(ProductionNotification, notification_id)
        if not notification:
            return jsonify({'error': 'Notification not found'}), 404

        # ✅ Check ownership
        if notification.user_id != request.current_user.id:
            return jsonify({'error': 'Unauthorized'}), 403

        notification.read = True
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
    """
    ✅ Mark all unread notifications as read for CURRENT USER ONLY
    """
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        updated_count = session.query(ProductionNotification).filter(
            ProductionNotification.user_id == request.current_user.id,
            ProductionNotification.read == False
        ).update(
            {'read': True},
            synchronize_session='fetch'
        )
        session.commit()
        
        return jsonify({
            'message': 'All notifications marked as read',
            'count': updated_count
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


@notification_bp.route('/notifications/production/<string:notification_id>/dismiss', methods=['POST', 'OPTIONS'])
@token_required
def dismiss_notification(notification_id):
    """
    ✅ NEW: Dismiss notification from sidebar (but keep in full notifications page)
    """
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        notification = session.get(ProductionNotification, notification_id)
        
        if not notification:
            return jsonify({'error': 'Notification not found'}), 404
        
        # ✅ Check ownership
        if notification.user_id != request.current_user.id:
            return jsonify({'error': 'Unauthorized'}), 403
        
        notification.dismissed = True
        session.commit()
        
        return jsonify({'success': True, 'message': 'Notification dismissed'}), 200
        
    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"Error dismissing notification: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@notification_bp.route('/notifications/production/<string:notification_id>', methods=['DELETE', 'OPTIONS'])
@token_required
def delete_notification(notification_id):
    """
    ✅ Permanently delete notification (only for current user)
    """
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        notification = session.get(ProductionNotification, notification_id)
        
        if not notification:
            return jsonify({'error': 'Notification not found'}), 404
        
        # ✅ Check ownership
        if notification.user_id != request.current_user.id:
            return jsonify({'error': 'Unauthorized'}), 403
        
        session.delete(notification)
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
    """
    ✅ Delete all notifications permanently for CURRENT USER ONLY
    """
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        deleted_count = session.query(ProductionNotification).filter(
            ProductionNotification.user_id == request.current_user.id
        ).delete(synchronize_session='fetch')
        session.commit()
        
        return jsonify({
            'message': 'All notifications cleared',
            'count': deleted_count
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
    """
    ✅ NEW: Clear all dismissed notifications for current user
    """
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        deleted_count = session.query(ProductionNotification).filter(
            ProductionNotification.user_id == request.current_user.id,
            ProductionNotification.dismissed == True
        ).delete(synchronize_session='fetch')
        
        session.commit()
        return jsonify({
            'success': True,
            'message': f'Cleared {deleted_count} dismissed notifications',
            'count': deleted_count
        }), 200
        
    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"Error clearing dismissed notifications: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@notification_bp.route('/notifications/production/stats', methods=['GET', 'OPTIONS'])
@token_required
def get_notification_stats():
    """
    ✅ Get statistics about notifications for CURRENT USER ONLY
    """
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    session = SessionLocal()
    try:
        total_count = session.query(ProductionNotification).filter(
            ProductionNotification.user_id == request.current_user.id
        ).count()
        
        unread_count = session.query(ProductionNotification).filter(
            ProductionNotification.user_id == request.current_user.id,
            ProductionNotification.read == False
        ).count()
        
        dismissed_count = session.query(ProductionNotification).filter(
            ProductionNotification.user_id == request.current_user.id,
            ProductionNotification.dismissed == True
        ).count()
        
        read_count = total_count - unread_count
        
        return jsonify({
            'total': total_count,
            'unread': unread_count,
            'read': read_count,
            'dismissed': dismissed_count
        }), 200
            
    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"Error fetching notification stats: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()