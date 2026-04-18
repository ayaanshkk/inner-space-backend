"""
Invitation Routes - Adapted for StreemLyne_MT schema
Handles team member invitation and registration flow
"""
from flask import Blueprint, request, jsonify, current_app
from sqlalchemy import text
from datetime import datetime, timedelta
from functools import wraps
import uuid
import secrets
from werkzeug.security import generate_password_hash

from ..db import SessionLocal
from .auth_helpers import token_required, get_current_tenant_id, get_current_employee_id, generate_token

invite_bp = Blueprint('invites', __name__)


def manager_or_hr_required(f):
    """Decorator to check if user has Manager or HR role"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Use the existing token_required logic
        token = request.headers.get('Authorization')
        if not token:
            return jsonify({'error': 'No token provided'}), 401
        
        try:
            from .auth_helpers import verify_token
            import jwt
            from flask import current_app
            
            token = token.replace('Bearer ', '')
            decoded = jwt.decode(
                token, 
                current_app.config['SECRET_KEY'], 
                algorithms=['HS256']
            )
            
            # Check role_ids (Manager=1, HR=2 typically)
            role_ids = decoded.get('role_ids', '').split(',')
            
            # Allow if user has Manager (1) or HR (2) role
            if '1' not in role_ids and '2' not in role_ids:
                return jsonify({'error': 'Unauthorized - Manager or HR access required'}), 403
            
            return f(decoded, *args, **kwargs)
            
        except jwt.ExpiredSignatureError:
            return jsonify({'error': 'Token expired'}), 401
        except jwt.InvalidTokenError:
            return jsonify({'error': 'Invalid token'}), 401
    
    return decorated_function


# ==========================================
# INVITATION MANAGEMENT
# ==========================================

@invite_bp.route('/api/invites/create', methods=['POST', 'OPTIONS'])
@manager_or_hr_required
def create_invite(current_user):
    """Create a new team member invitation (Manager/HR only)"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        tenant_id = current_user.get('tenant_id')
        creator_employee_id = current_user.get('employee_id')
        
        data = request.get_json()
        email = data.get('email')
        employee_name = data.get('name') or data.get('employee_name')
        role_ids = data.get('role_ids', '3')  # Default to Staff role
        
        if not email or not employee_name:
            return jsonify({'error': 'Email and name are required'}), 400
        
        # Check if email already exists
        check_query = text("""
            SELECT user_id FROM "StreemLyne_MT"."User_Master"
            WHERE email = :email AND tenant_id = :tenant_id
        """)
        
        result = session.execute(check_query, {
            'email': email,
            'tenant_id': tenant_id
        })
        
        if result.fetchone():
            return jsonify({'error': 'User with this email already exists'}), 400
        
        # Check for existing pending invite
        check_invite_query = text("""
            SELECT user_id FROM "StreemLyne_MT"."User_Master"
            WHERE email = :email 
            AND tenant_id = :tenant_id
            AND is_invite_pending = true
            AND invite_token IS NOT NULL
        """)
        
        result = session.execute(check_invite_query, {
            'email': email,
            'tenant_id': tenant_id
        })
        
        if result.fetchone():
            return jsonify({'error': 'An active invite already exists for this email'}), 400
        
        # Generate invite token
        invite_token = secrets.token_urlsafe(32)
        
        # Create employee record
        employee_insert = text("""
            INSERT INTO "StreemLyne_MT"."Employee_Master" (
                tenant_id,
                employee_name,
                email,
                role_ids,
                created_at
            ) VALUES (
                :tenant_id,
                :employee_name,
                :email,
                :role_ids,
                :created_at
            )
            RETURNING employee_id
        """)
        
        emp_result = session.execute(employee_insert, {
            'tenant_id': tenant_id,
            'employee_name': employee_name,
            'email': email,
            'role_ids': role_ids,
            'created_at': datetime.utcnow()
        })
        
        employee_id = emp_result.fetchone()[0]
        
        # Create user record with invite
        user_insert = text("""
            INSERT INTO "StreemLyne_MT"."User_Master" (
                tenant_id,
                employee_id,
                email,
                invite_token,
                invite_created_at,
                invite_expires_at,
                is_invite_pending,
                created_by_employee_id
            ) VALUES (
                :tenant_id,
                :employee_id,
                :email,
                :invite_token,
                :created_at,
                :expires_at,
                true,
                :created_by
            )
            RETURNING user_id
        """)
        
        user_result = session.execute(user_insert, {
            'tenant_id': tenant_id,
            'employee_id': employee_id,
            'email': email,
            'invite_token': invite_token,
            'created_at': datetime.utcnow(),
            'expires_at': datetime.utcnow() + timedelta(days=7),
            'created_by': creator_employee_id
        })
        
        user_id = user_result.fetchone()[0]
        session.commit()
        
        # Generate registration link
        registration_link = f"{request.host_url}register?token={invite_token}"
        
        current_app.logger.info(f"Invite created for {email} by employee {creator_employee_id}")
        
        return jsonify({
            'message': 'Invite created successfully',
            'invite': {
                'id': user_id,
                'email': email,
                'name': employee_name,
                'role_ids': role_ids,
                'token': invite_token,
                'registration_link': registration_link,
                'expires_at': (datetime.utcnow() + timedelta(days=7)).isoformat()
            }
        }), 201
        
    except Exception as e:
        session.rollback()
        current_app.logger.error(f"Error creating invite: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@invite_bp.route('/api/invites', methods=['GET', 'OPTIONS'])
@manager_or_hr_required
def get_invites(current_user):
    """Get all invitations (Manager/HR only)"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        tenant_id = current_user.get('tenant_id')
        
        query = text("""
            SELECT 
                u.user_id,
                u.email,
                u.invite_token,
                u.invite_created_at,
                u.invite_expires_at,
                u.is_invite_pending,
                u.invite_accepted_at,
                e.employee_name,
                e.role_ids,
                creator.employee_name as created_by_name
            FROM "StreemLyne_MT"."User_Master" u
            JOIN "StreemLyne_MT"."Employee_Master" e ON u.employee_id = e.employee_id
            LEFT JOIN "StreemLyne_MT"."Employee_Master" creator ON u.created_by_employee_id = creator.employee_id
            WHERE u.tenant_id = :tenant_id
            AND u.invite_token IS NOT NULL
            ORDER BY u.invite_created_at DESC
        """)
        
        result = session.execute(query, {'tenant_id': tenant_id})
        invites = result.fetchall()
        
        invite_list = []
        for invite in invites:
            is_valid = (
                invite.is_invite_pending and 
                invite.invite_expires_at and 
                invite.invite_expires_at > datetime.utcnow()
            )
            
            invite_list.append({
                'id': invite.user_id,
                'email': invite.email,
                'name': invite.employee_name,
                'role_ids': invite.role_ids,
                'created_by': invite.created_by_name or 'System',
                'created_at': invite.invite_created_at.isoformat() if invite.invite_created_at else None,
                'expires_at': invite.invite_expires_at.isoformat() if invite.invite_expires_at else None,
                'is_pending': invite.is_invite_pending,
                'accepted_at': invite.invite_accepted_at.isoformat() if invite.invite_accepted_at else None,
                'is_valid': is_valid,
                'registration_link': f"{request.host_url}register?token={invite.invite_token}"
            })
        
        return jsonify({'invites': invite_list}), 200
        
    except Exception as e:
        current_app.logger.error(f"Error fetching invites: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@invite_bp.route('/api/invites/<int:invite_id>', methods=['DELETE', 'OPTIONS'])
@manager_or_hr_required
def delete_invite(current_user, invite_id):
    """Delete/revoke an invitation (Manager/HR only)"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        tenant_id = current_user.get('tenant_id')
        
        # Check if invite exists and is still pending
        check_query = text("""
            SELECT 
                u.is_invite_pending,
                u.employee_id
            FROM "StreemLyne_MT"."User_Master" u
            WHERE u.user_id = :user_id AND u.tenant_id = :tenant_id
        """)
        
        result = session.execute(check_query, {
            'user_id': invite_id,
            'tenant_id': tenant_id
        })
        invite = result.fetchone()
        
        if not invite:
            return jsonify({'error': 'Invite not found'}), 404
        
        if not invite.is_invite_pending:
            return jsonify({'error': 'Cannot delete an accepted invite'}), 400
        
        # Delete user record
        delete_user_query = text("""
            DELETE FROM "StreemLyne_MT"."User_Master"
            WHERE user_id = :user_id AND tenant_id = :tenant_id
        """)
        
        session.execute(delete_user_query, {
            'user_id': invite_id,
            'tenant_id': tenant_id
        })
        
        # Delete employee record
        delete_employee_query = text("""
            DELETE FROM "StreemLyne_MT"."Employee_Master"
            WHERE employee_id = :employee_id AND tenant_id = :tenant_id
        """)
        
        session.execute(delete_employee_query, {
            'employee_id': invite.employee_id,
            'tenant_id': tenant_id
        })
        
        session.commit()
        
        return jsonify({'message': 'Invite deleted successfully'}), 200
        
    except Exception as e:
        session.rollback()
        current_app.logger.error(f"Error deleting invite: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


# ==========================================
# PUBLIC REGISTRATION ENDPOINTS
# ==========================================

@invite_bp.route('/api/invites/validate/<token>', methods=['GET', 'OPTIONS'])
def validate_invite(token):
    """Validate an invite token (Public - no auth required)"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        query = text("""
            SELECT 
                u.user_id,
                u.email,
                u.is_invite_pending,
                u.invite_expires_at,
                e.employee_name,
                e.role_ids
            FROM "StreemLyne_MT"."User_Master" u
            JOIN "StreemLyne_MT"."Employee_Master" e ON u.employee_id = e.employee_id
            WHERE u.invite_token = :token
        """)
        
        result = session.execute(query, {'token': token})
        invite = result.fetchone()
        
        if not invite:
            return jsonify({'valid': False, 'error': 'Invalid invite token'}), 404
        
        if not invite.is_invite_pending:
            return jsonify({'valid': False, 'error': 'Invite already used'}), 400
        
        if invite.invite_expires_at and invite.invite_expires_at < datetime.utcnow():
            return jsonify({'valid': False, 'error': 'Invite expired'}), 400
        
        return jsonify({
            'valid': True,
            'email': invite.email,
            'name': invite.employee_name,
            'role_ids': invite.role_ids,
            'expires_at': invite.invite_expires_at.isoformat() if invite.invite_expires_at else None
        }), 200
        
    except Exception as e:
        current_app.logger.error(f"Error validating invite: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@invite_bp.route('/api/register', methods=['POST', 'OPTIONS'])
def register_with_invite():
    """Complete registration with invite token (Public - no auth required)"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        data = request.get_json()
        token = data.get('token')
        password = data.get('password')
        
        if not token or not password:
            return jsonify({'error': 'Token and password are required'}), 400
        
        # Validate invite
        query = text("""
            SELECT 
                u.user_id,
                u.employee_id,
                u.email,
                u.is_invite_pending,
                u.invite_expires_at,
                u.tenant_id,
                e.employee_name,
                e.role_ids
            FROM "StreemLyne_MT"."User_Master" u
            JOIN "StreemLyne_MT"."Employee_Master" e ON u.employee_id = e.employee_id
            WHERE u.invite_token = :token
        """)
        
        result = session.execute(query, {'token': token})
        invite = result.fetchone()
        
        if not invite:
            return jsonify({'error': 'Invalid invite token'}), 404
        
        if not invite.is_invite_pending:
            return jsonify({'error': 'Invite already used'}), 400
        
        if invite.invite_expires_at and invite.invite_expires_at < datetime.utcnow():
            return jsonify({'error': 'Invite expired'}), 400
        
        # Hash password
        hashed_password = generate_password_hash(password)
        
        # Update user record
        update_query = text("""
            UPDATE "StreemLyne_MT"."User_Master"
            SET 
                password_hash = :password_hash,
                is_invite_pending = false,
                invite_accepted_at = :accepted_at,
                invite_token = NULL
            WHERE user_id = :user_id
        """)
        
        session.execute(update_query, {
            'password_hash': hashed_password,
            'accepted_at': datetime.utcnow(),
            'user_id': invite.user_id
        })
        
        session.commit()
        
        # Generate JWT token for immediate login
        auth_token = generate_token(
            employee_id=invite.employee_id,
            tenant_id=invite.tenant_id,
            employee_name=invite.employee_name,
            email=invite.email,
            role_ids=invite.role_ids
        )
        
        current_app.logger.info(f"User {invite.email} completed registration")
        
        return jsonify({
            'message': 'Registration successful',
            'token': auth_token,
            'user': {
                'id': invite.employee_id,
                'name': invite.employee_name,
                'email': invite.email,
                'role_ids': invite.role_ids,
                'tenant_id': invite.tenant_id
            }
        }), 201
        
    except Exception as e:
        session.rollback()
        current_app.logger.error(f"Error completing registration: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()