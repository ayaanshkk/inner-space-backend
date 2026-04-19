"""
Authentication Routes - Adapted for StreemLyne_MT schema
Handles user authentication, registration, and user management
"""
from flask import Blueprint, request, jsonify, current_app, g
from datetime import datetime, timedelta
from functools import wraps
import secrets
import re
import jwt
import os
from sqlalchemy import text
from werkzeug.security import generate_password_hash, check_password_hash

from ..db import SessionLocal

DEV_MODE = os.getenv('DEV_MODE', 'false').lower() == 'true'

auth_bp = Blueprint('auth', __name__)

# --- Configuration and Helpers ---

def get_client_ip():
    """Get client IP address"""
    if request.environ.get('HTTP_X_FORWARDED_FOR') is None:
        return request.environ['REMOTE_ADDR']
    else:
        return request.environ['HTTP_X_FORWARDED_FOR']


def validate_email(email):
    """Validate email format"""
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None


def validate_password(password):
    """Validate password strength"""
    if len(password) < 8:
        return False, "Password must be at least 8 characters long"
    if not re.search(r'[A-Z]', password):
        return False, "Password must contain at least one uppercase letter"
    if not re.search(r'[a-z]', password):
        return False, "Password must contain at least one lowercase letter"
    if not re.search(r'\d', password):
        return False, "Password must contain at least one number"
    return True, "Password is valid"


def generate_token_payload(employee_id, tenant_id, employee_name, email, role_ids):
    """Generate JWT token payload"""
    return {
        'user_id': employee_id,
        'employee_id': employee_id,
        'tenant_id': tenant_id,
        'employee_name': employee_name,
        'email': email,
        'role_ids': role_ids,
        'exp': datetime.utcnow() + timedelta(days=7),
        'iat': datetime.utcnow()
    }


def create_jwt_token(payload):
    """Create JWT token from payload"""
    return jwt.encode(payload, current_app.config['SECRET_KEY'], algorithm='HS256')


# --- Decorators ---

def token_required(f):
    """Decorator to require valid JWT token"""
    @wraps(f)
    def decorated(*args, **kwargs):
        if request.method == 'OPTIONS':
            return f(*args, **kwargs)
        
        token = None
        if 'Authorization' in request.headers:
            try:
                token = request.headers['Authorization'].split(" ")[1]
            except IndexError:
                return jsonify({'error': 'Invalid token format'}), 401

        if not token:
            return jsonify({'error': 'Token is missing'}), 401

        try:
            payload = jwt.decode(token, current_app.config['SECRET_KEY'], algorithms=['HS256'])
            
            # Attach user info to g
            g.user = {
                'user_id': payload.get('user_id'),
                'employee_id': payload.get('employee_id'),
                'tenant_id': payload.get('tenant_id'),
                'employee_name': payload.get('employee_name'),
                'email': payload.get('email'),
                'role_ids': payload.get('role_ids', '')
            }

        except jwt.ExpiredSignatureError:
            return jsonify({'error': 'Token expired'}), 401
        except jwt.InvalidTokenError:
            return jsonify({'error': 'Invalid token'}), 401

        return f(*args, **kwargs)
            
    return decorated


def admin_required(f):
    """Decorator to require admin/manager access"""
    @wraps(f)
    @token_required
    def decorated(*args, **kwargs):
        # Check if user has admin role (role_id 1, adjust as needed)
        role_ids = g.user.get('role_ids', '')
        user_roles = [int(r.strip()) for r in role_ids.split(',') if r.strip()]
        
        # Assuming role_id 1 is admin - adjust based on your Role_Master table
        if 1 not in user_roles:
            return jsonify({'error': 'Admin access required'}), 403
        
        return f(*args, **kwargs)
    return decorated


# --- Routes ---

@auth_bp.route('/health', methods=['GET'])
def health_check():
    return {
        'status': 'ok', 
        'message': 'Backend is running successfully!'
    }, 200


@auth_bp.route('/auth/register', methods=['POST'])
def register():
    """Register a new employee (handles both regular registration and invitation completion)"""
    session = SessionLocal()
    try:
        data = request.get_json() or {}
        
        # Check if this is completing an invitation
        invitation_token = data.get('invitation_token')
        
        if invitation_token:
            # INVITATION COMPLETION FLOW
            # Find employee by invitation token
            query = text("""
                SELECT u.user_id, u.employee_id, e.tenant_id, e.email, e.employee_name, e.role_ids
                FROM "StreemLyne_MT"."User_Master" u
                JOIN "StreemLyne_MT"."Employee_Master" e ON u.employee_id = e.employee_id
                WHERE u.invite_token = :invite_token AND u.is_invite_pending = true
            """)
            
            result = session.execute(query, {'invite_token': invitation_token})
            user_data = result.fetchone()
            
            if not user_data:
                return jsonify({'error': 'Invalid or expired invitation token'}), 400
            
            # Validate password
            password = data.get('password')
            if not password:
                return jsonify({'error': 'Password is required'}), 400
            
            is_valid, message = validate_password(password)
            if not is_valid:
                return jsonify({'error': message}), 400
            
            # Complete the registration
            password_hash = generate_password_hash(password)
            
            update_query = text("""
                UPDATE "StreemLyne_MT"."User_Master"
                SET password = :password_hash,
                    is_invite_pending = false,
                    invite_token = NULL,
                    updated_at = :updated_at
                WHERE user_id = :user_id
            """)
            
            session.execute(update_query, {
                'password_hash': password_hash,
                'updated_at': datetime.utcnow(),
                'user_id': user_data.user_id
            })
            session.commit()
            
            # Generate JWT token
            payload = generate_token_payload(
                user_data.employee_id,
                user_data.tenant_id,
                user_data.employee_name,
                user_data.email,
                user_data.role_ids or ''
            )
            token = create_jwt_token(payload)
            
            current_app.logger.info(f"✅ Invitation registration completed: {user_data.email}")
            
            return jsonify({
                'success': True,
                'message': 'Registration completed successfully',
                'token': token,
                'user': {
                    'id': user_data.employee_id,
                    'email': user_data.email,
                    'name': user_data.employee_name,
                    'tenant_id': user_data.tenant_id
                }
            }), 200
        
        # If no invitation token, return error (regular registration may not be allowed)
        return jsonify({'error': 'Registration requires an invitation token'}), 400
        
    except Exception as e:
        session.rollback()
        current_app.logger.error(f"❌ Registration error: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@auth_bp.route('/auth/login', methods=['POST'])
def login():
    """Login user with username or email"""
    session = SessionLocal()
    try:
        data = request.get_json() or {}
        
        # ✅ Accept either 'username' or 'email' for backwards compatibility
        identifier = data.get('username') or data.get('email')
        password = data.get('password')
        
        if not identifier or not password:
            return jsonify({'error': 'Username/email and password required'}), 400

        identifier = identifier.lower().strip()

        # ✅ Query user by username OR email (handle NULL emails)
        query = text("""
            SELECT 
                u.user_id,
                u.employee_id,
                u.user_name as username,
                u.password,
                e.tenant_id,
                e.employee_name,
                e.email,
                e.role_ids
            FROM "StreemLyne_MT"."User_Master" u
            JOIN "StreemLyne_MT"."Employee_Master" e ON u.employee_id = e.employee_id
            WHERE LOWER(u.user_name) = :identifier 
               OR (e.email IS NOT NULL AND LOWER(e.email) = :identifier)
        """)
        
        result = session.execute(query, {'identifier': identifier})
        user = result.fetchone()

        if not user:
            current_app.logger.warning(f"❌ Login failed - user not found: {identifier}")
            return jsonify({'error': 'Invalid username/email or password'}), 401

        # Verify password
        if not check_password_hash(user.password, password):
            current_app.logger.warning(f"❌ Login failed - invalid password: {identifier}")
            return jsonify({'error': 'Invalid username/email or password'}), 401

        # Generate JWT token
        payload = generate_token_payload(
            user.employee_id,
            user.tenant_id,
            user.employee_name,
            user.email,
            user.role_ids or ''
        )
        token = create_jwt_token(payload)

        current_app.logger.info(f"✅ Login successful: {identifier}")

        return jsonify({
            'success': True,
            'message': 'Login successful',
            'token': token,
            'user': {
                'id': user.employee_id,
                'employee_id': user.employee_id,
                'email': user.email,
                'username': user.username,
                'name': user.employee_name,
                'full_name': user.employee_name,
                'first_name': user.employee_name.split()[0] if user.employee_name else '',
                'last_name': ' '.join(user.employee_name.split()[1:]) if user.employee_name and len(user.employee_name.split()) > 1 else '',
                'role': user.role_ids,
                'tenant_id': user.tenant_id,
                'role_ids': user.role_ids,
                'is_active': True,
                'is_verified': True,
                'created_at': datetime.utcnow().isoformat()
            }
        }), 200
        
    except Exception as e:
        session.rollback()
        current_app.logger.error(f"❌ Login error: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@auth_bp.route('/auth/logout', methods=['POST'])
@token_required
def logout():
    """Logout user"""
    try:
        # In a stateless JWT system, logout is handled client-side by deleting the token
        # You could maintain a blacklist of tokens if needed
        return jsonify({'message': 'Logged out successfully'}), 200
    except Exception as e:
        current_app.logger.exception(f"Error logging out: {e}")
        return jsonify({'error': str(e)}), 500


@auth_bp.route('/auth/me', methods=['GET'])
@token_required
def get_current_user():
    """Get current user information"""
    try:
        return jsonify({'user': g.user}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@auth_bp.route('/users/me', methods=['GET', 'OPTIONS'])
@token_required
def get_user_me():
    """Get current user information - alternative endpoint"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    try:
        return jsonify({
            'id': g.user['employee_id'],
            'name': g.user['employee_name'],
            'email': g.user['email'],
            'role_ids': g.user['role_ids'],
            'tenant_id': g.user['tenant_id']
        }), 200
    except Exception as e:
        current_app.logger.exception(f"Error fetching current user: {e}")
        return jsonify({'error': 'Failed to fetch user information'}), 500


@auth_bp.route('/auth/users/staff', methods=['GET'])
@admin_required
def get_staff_users():
    """Get all staff users"""
    session = SessionLocal()
    try:
        tenant_id = g.user.get('tenant_id')
        
        query = text("""
            SELECT 
                e.employee_id,
                e.employee_name,
                e.email,
                e.role_ids,
                e.employee_designation_id,
                d.designation_description
            FROM "StreemLyne_MT"."Employee_Master" e
            LEFT JOIN "StreemLyne_MT"."Designation_Master" d 
                ON e.employee_designation_id = d.designation_id
            WHERE e.tenant_id = :tenant_id
            ORDER BY e.employee_name
        """)
        
        result = session.execute(query, {'tenant_id': tenant_id})
        employees = result.fetchall()
        
        return jsonify({
            'users': [{
                'id': emp.employee_id,
                'name': emp.employee_name,
                'email': emp.email,
                'role_ids': emp.role_ids,
                'designation': emp.designation_description
            } for emp in employees]
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@auth_bp.route('/auth/users', methods=['GET'])
@admin_required
def get_users():
    """Get all users/employees"""
    session = SessionLocal()
    try:
        tenant_id = g.user.get('tenant_id')
        
        query = text("""
            SELECT 
                e.employee_id,
                e.employee_name,
                e.email,
                e.phone,
                e.role_ids,
                e.created_on,
                e.employee_designation_id,
                d.designation_description,
                u.is_invite_pending
            FROM "StreemLyne_MT"."Employee_Master" e
            LEFT JOIN "StreemLyne_MT"."Designation_Master" d 
                ON e.employee_designation_id = d.designation_id
            LEFT JOIN "StreemLyne_MT"."User_Master" u ON e.employee_id = u.employee_id
            WHERE e.tenant_id = :tenant_id
            ORDER BY e.created_on DESC
        """)
        
        result = session.execute(query, {'tenant_id': tenant_id})
        employees = result.fetchall()
        
        return jsonify({
            'users': [{
                'id': emp.employee_id,
                'name': emp.employee_name,
                'email': emp.email,
                'phone': emp.phone,
                'role_ids': emp.role_ids,
                'designation': emp.designation_description,
                'is_invited': emp.is_invite_pending or False,
                'created_at': emp.created_on.isoformat() if emp.created_on else None
            } for emp in employees]
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@auth_bp.route('/auth/refresh', methods=['POST'])
@token_required
def refresh_token():
    """Refresh JWT token"""
    try:
        user = g.user
        
        # Generate new token with same payload
        payload = generate_token_payload(
            user['employee_id'],
            user['tenant_id'],
            user['employee_name'],
            user['email'],
            user['role_ids']
        )
        new_token = create_jwt_token(payload)
        
        return jsonify({
            'token': new_token,
            'user': user
        }), 200
        
    except Exception as e:
        current_app.logger.exception(f"Error refreshing token: {e}")
        return jsonify({'error': str(e)}), 500


@auth_bp.route('/auth/change-password', methods=['POST'])
@token_required
def change_password():
    """Change password for authenticated user"""
    session = SessionLocal()
    try:
        data = request.get_json()
        
        required_fields = ['current_password', 'new_password']
        for field in required_fields:
            if not data.get(field):
                return jsonify({'error': f'{field} is required'}), 400
        
        current_password = data['current_password']
        new_password = data['new_password']
        employee_id = g.user['employee_id']
        
        # Get current password hash
        query = text("""
            SELECT password FROM "StreemLyne_MT"."User_Master"
            WHERE employee_id = :employee_id
        """)
        
        result = session.execute(query, {'employee_id': employee_id})
        user = result.fetchone()
        
        if not user or not check_password_hash(user.password, current_password):
            return jsonify({'error': 'Current password is incorrect'}), 400
        
        is_valid, message = validate_password(new_password)
        if not is_valid:
            return jsonify({'error': message}), 400
        
        # Update password
        new_password_hash = generate_password_hash(new_password)
        
        update_query = text("""
            UPDATE "StreemLyne_MT"."User_Master"
            SET password = :password_hash,
                updated_at = :updated_at
            WHERE employee_id = :employee_id
        """)
        
        session.execute(update_query, {
            'password_hash': new_password_hash,
            'updated_at': datetime.utcnow(),
            'employee_id': employee_id
        })
        session.commit()
        
        return jsonify({'message': 'Password changed successfully'}), 200
        
    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"Error changing password: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@auth_bp.route('/auth/invite-user', methods=['POST'])
@admin_required
def invite_user():
    """Create an invitation for a new employee"""
    session = SessionLocal()
    try:
        data = request.get_json() or {}
        tenant_id = g.user.get('tenant_id')
        
        # Validate required fields
        required_fields = ['employee_name', 'email']
        for field in required_fields:
            if not data.get(field):
                return jsonify({'error': f'{field} is required'}), 400
        
        email = data['email'].lower().strip()
        employee_name = data['employee_name'].strip()
        phone = data.get('phone', '').strip()
        role_ids = data.get('role_ids', '').strip()
        designation_id = data.get('designation_id')
        
        # Validate email format
        if not validate_email(email):
            return jsonify({'error': 'Invalid email format'}), 400
        
        # Check if email already exists
        check_query = text("""
            SELECT employee_id FROM "StreemLyne_MT"."Employee_Master"
            WHERE email = :email AND tenant_id = :tenant_id
        """)
        
        existing = session.execute(check_query, {
            'email': email,
            'tenant_id': tenant_id
        }).fetchone()
        
        if existing:
            return jsonify({'error': 'An employee with this email already exists'}), 400
        
        # Generate invitation token
        invitation_token = secrets.token_urlsafe(32)
        
        # Create new employee
        insert_employee = text("""
            INSERT INTO "StreemLyne_MT"."Employee_Master" (
                tenant_id,
                employee_name,
                email,
                phone,
                role_ids,
                employee_designation_id,
                created_on
            ) VALUES (
                :tenant_id,
                :employee_name,
                :email,
                :phone,
                :role_ids,
                :designation_id,
                :created_on
            )
            RETURNING employee_id
        """)
        
        result = session.execute(insert_employee, {
            'tenant_id': tenant_id,
            'employee_name': employee_name,
            'email': email,
            'phone': phone,
            'role_ids': role_ids,
            'designation_id': designation_id,
            'created_on': datetime.utcnow()
        })
        
        employee_id = result.fetchone()[0]
        
        # Create user with invitation
        insert_user = text("""
            INSERT INTO "StreemLyne_MT"."User_Master" (
                employee_id,
                user_name,
                is_invite_pending,
                invite_token,
                created_at
            ) VALUES (
                :employee_id,
                :user_name,
                true,
                :invite_token,
                :created_at
            )
        """)
        
        session.execute(insert_user, {
            'employee_id': employee_id,
            'user_name': email.split('@')[0],  # Default username from email prefix
            'invite_token': invitation_token,
            'created_at': datetime.utcnow()
        })
        
        session.commit()
        
        current_app.logger.info(f"✅ Invitation created for: {email}")
        
        return jsonify({
            'success': True,
            'message': 'Invitation created successfully',
            'invitation_token': invitation_token,
            'user': {
                'id': employee_id,
                'name': employee_name,
                'email': email
            }
        }), 201
        
    except Exception as e:
        session.rollback()
        current_app.logger.error(f"❌ Invitation creation error: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@auth_bp.route('/auth/validate-invitation', methods=['POST'])
def validate_invitation():
    """Validate an invitation token and return user info"""
    session = SessionLocal()
    try:
        data = request.get_json() or {}
        
        invitation_token = data.get('invitation_token')
        if not invitation_token:
            return jsonify({'error': 'Invitation token is required'}), 400
        
        query = text("""
            SELECT 
                e.employee_id,
                e.employee_name,
                e.email,
                e.role_ids
            FROM "StreemLyne_MT"."User_Master" u
            JOIN "StreemLyne_MT"."Employee_Master" e ON u.employee_id = e.employee_id
            WHERE u.invite_token = :invite_token AND u.is_invite_pending = true
        """)
        
        result = session.execute(query, {'invite_token': invitation_token})
        user = result.fetchone()
        
        if not user:
            return jsonify({'error': 'Invalid or expired invitation token'}), 400
        
        return jsonify({
            'success': True,
            'user': {
                'id': user.employee_id,
                'email': user.email,
                'name': user.employee_name,
                'role_ids': user.role_ids
            }
        }), 200
        
    except Exception as e:
        current_app.logger.error(f"❌ Validate invitation error: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()