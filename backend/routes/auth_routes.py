from flask import Blueprint, request, jsonify, current_app, g
from ..models import User, LoginAttempt, Session
from datetime import datetime, timedelta
from functools import wraps
import secrets
import re
import jwt
import os

from ..db import SessionLocal # 👈 SessionLocal is required for all native queries

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

def check_rate_limit(email, max_attempts=5, window_minutes=15):
    """Check if user has exceeded login attempts"""
    session = SessionLocal()
    try:
        cutoff_time = datetime.utcnow() - timedelta(minutes=window_minutes)
        
        recent_attempts = session.query(LoginAttempt).filter(
            LoginAttempt.email == email,
            LoginAttempt.attempted_at > cutoff_time,
            LoginAttempt.success == False
        ).count()
        
        return recent_attempts < max_attempts
    except Exception as e:
        current_app.logger.warning(f"Could not check rate limit: {e}")
        return True
    finally:
        session.close()


def log_login_attempt(email, ip_address, success):
    """Log login attempt"""
    session = SessionLocal()
    try:
        attempt = LoginAttempt(
            email=email,
            ip_address=ip_address,
            success=success
        )
        session.add(attempt)
        session.commit()
    except Exception as e:
        session.rollback()
        current_app.logger.warning(f"Could not log login attempt: {e}")
    finally:
        session.close()

# --- Decorators ---

def token_required(f):
    """Decorator to require valid JWT token"""
    @wraps(f)
    def decorated(*args, **kwargs):
        local_session = SessionLocal()
        
        try:
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
                
                user = local_session.get(User, payload['user_id'])
                
                if not user or not user.is_active:
                    return jsonify({'error': 'User not found or inactive'}), 401

                session_record = local_session.query(Session).filter_by(
                    session_token=token, 
                    user_id=user.id
                ).first()
                
                if not session_record or session_record.expires_at < datetime.utcnow():
                    return jsonify({'error': 'Token expired'}), 401

                g.user = user

            except jwt.ExpiredSignatureError:
                return jsonify({'error': 'Token expired'}), 401
            except jwt.InvalidTokenError:
                return jsonify({'error': 'Invalid token'}), 401

            return f(*args, **kwargs)
            
        finally:
            local_session.close()
            
    return decorated

def admin_required(f):
    """Decorator to require Manager or HR access"""
    @wraps(f)
    @token_required
    def decorated(*args, **kwargs):
        ADMIN_ROLES = ['Manager', 'HR']
        if not hasattr(g.user, 'role') or g.user.role not in ADMIN_ROLES:
            return jsonify({'error': 'Manager or HR access required'}), 403
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
    """Register a new user (handles both regular registration and invitation completion)"""
    session = SessionLocal()  # 👈 Start session for transaction
    try:
        data = request.get_json() or {}

        # Check if this is completing an invitation
        invitation_token = data.get('invitation_token')
        
        if invitation_token:
            # INVITATION COMPLETION FLOW
            # Find user by invitation token
            user = session.query(User).filter_by(invitation_token=invitation_token).first()
            
            if not user or not user.is_invited:
                return jsonify({'error': 'Invalid or expired invitation token'}), 400
            
            # Validate password
            password = data.get('password')
            if not password:
                return jsonify({'error': 'Password is required'}), 400
            
            is_valid, message = validate_password(password)
            if not is_valid:
                return jsonify({'error': message}), 400
            
            # Complete the registration
            user.set_password(password)
            user.is_invited = False
            user.invitation_token = None
            user.is_active = True
            user.is_verified = True
            user.updated_at = datetime.utcnow()
            
            session.commit()  # 👈 Commit registration completion
            
            # Generate JWT token for immediate login
            payload = {
                'user_id': user.id,
                'exp': datetime.utcnow() + timedelta(days=7),
                'iat': datetime.utcnow()
            }
            token = jwt.encode(payload, current_app.config['SECRET_KEY'], algorithm='HS256')
            
            # Create session record
            session_record = Session(
                user_id=user.id,
                session_token=token,
                ip_address=get_client_ip(),
                user_agent=request.headers.get('User-Agent', '')[:255],
                expires_at=datetime.utcnow() + timedelta(days=7)
            )
            session.add(session_record)
            session.commit()
            
            log_login_attempt(user.email, get_client_ip(), True)
            
            current_app.logger.info(f"✅ Invitation registration completed: {user.email} as {user.role}")
            
            return jsonify({
                'success': True,
                'message': 'Registration completed successfully',
                'token': token,
                'user': user.to_dict()
            }), 200
        
        # REGULAR REGISTRATION FLOW (if you allow open registration)
        required_fields = ['email', 'password', 'first_name', 'last_name']
        for field in required_fields:
            if not data.get(field):
                return jsonify({'error': f'{field} is required'}), 400

        email = data['email'].lower().strip()
        password = data['password']
        first_name = data['first_name'].strip()
        last_name = data['last_name'].strip()
        role = data.get('role', 'Staff').strip()

        if not validate_email(email):
            return jsonify({'error': 'Invalid email format'}), 400

        is_valid, message = validate_password(password)
        if not is_valid:
            return jsonify({'error': message}), 400

        ALLOWED_ROLES = ['Manager', 'HR', 'Sales', 'Production', 'Staff'] 
        if role not in ALLOWED_ROLES:
            role = 'Staff'

        # Check if user already exists
        if session.query(User).filter_by(email=email).first():
            return jsonify({'error': 'Email already registered'}), 409

        # Create new user 
        user = User(
            email=email,
            first_name=first_name,
            last_name=last_name,
            role=role,
            is_active=True,
            is_verified=True,
            is_invited=False
        )
        user.set_password(password)
        
        # Generate verification token for email verification if needed
        if hasattr(user, 'generate_verification_token'):
            user.generate_verification_token()

        session.add(user)
        session.commit()  # 👈 Commit user creation

        log_login_attempt(email, get_client_ip(), True)
        
        current_app.logger.info(f"✅ User registered: {email} as {role}")

        return jsonify({
            'success': True,
            'message': 'User registered successfully',
            'user': user.to_dict()
        }), 201

    except Exception as e:
        session.rollback()  # 👈 Rollback on error
        current_app.logger.error(f"❌ Registration error: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()  # 👈 Close session

@auth_bp.route('/auth/login', methods=['POST'])
def login():
    session = SessionLocal() # 👈 Start session for transaction
    try:
        data = request.get_json() or {}
        if not data.get('email') or not data.get('password'):
            return jsonify({'error': 'Email and password required'}), 400

        email = data['email'].lower().strip()
        ip = get_client_ip()

        if not check_rate_limit(email):
            return jsonify({'error': 'Too many failed attempts'}), 429
        
        # Query user using the active session
        user = session.query(User).filter_by(email=email).first() 

        if not user or not user.check_password(data['password']):
            log_login_attempt(email, ip, False)
            current_app.logger.warning(f"❌ Login failed for: {email}")
            return jsonify({'error': 'Invalid email or password'}), 401

        if not user.is_active:
            return jsonify({'error': 'Account disabled'}), 401

        user.last_login = datetime.utcnow()

        # Generate JWT token
        payload = {
            'user_id': user.id,
            'exp': datetime.utcnow() + timedelta(days=7),
            'iat': datetime.utcnow()
        }
        token = jwt.encode(payload, current_app.config['SECRET_KEY'], algorithm='HS256')

        # Save session record
        session_record = Session(
            user_id=user.id,
            session_token=token,
            ip_address=ip,
            user_agent=request.headers.get('User-Agent', '')[:255],
            expires_at=datetime.utcnow() + timedelta(days=7)
        )
        
        session.add(user) # Update last_login time
        session.add(session_record)
        session.commit() # 👈 Commit session and last_login update

        log_login_attempt(email, ip, True)
        
        current_app.logger.info(f"✅ Login successful: {email}")

        return jsonify({
            'success': True,
            'message': 'Login successful',
            'token': token,
            'user': user.to_dict()
        }), 200
    except Exception as e:
        session.rollback() # 👈 Rollback on error
        current_app.logger.error(f"❌ Login error: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close() # 👈 Close session

@auth_bp.route('/auth/logout', methods=['POST'])
@token_required
def logout():
    """Logout user"""
    session = SessionLocal() # 👈 Start session for transaction
    try:
        if DEV_MODE:
            return jsonify({'message': 'Logged out successfully (dev mode)'}), 200
        
        token = request.headers.get('Authorization').split(" ")[1]
        
        # Find session record using the current session
        session_record = session.query(Session).filter_by(session_token=token).first()
        
        if session_record:
            session.delete(session_record)
            session.commit() # 👈 Commit deletion
        
        return jsonify({'message': 'Logged out successfully'}), 200
        
    except Exception as e:
        session.rollback() # 👈 Rollback on error
        current_app.logger.exception(f"Error logging out: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close() # 👈 Close session

@auth_bp.route('/auth/me', methods=['GET'])
@token_required
def get_current_user():
    """Get current user information"""
    # This is a read-only endpoint, relies on g.user set by token_required decorator
    try:
        # Use g.user, which is generally a session-managed object
        user_data = g.user.to_dict() if hasattr(g.user, 'to_dict') else {
            'id': g.user.id,
            'email': g.user.email,
            'first_name': g.user.first_name,
            'last_name': g.user.last_name,
            'role': g.user.role
        }
        return jsonify({'user': user_data}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    
@auth_bp.route('/auth/users/staff', methods=['GET'])
@admin_required
def get_staff_users():
    """Get all staff users (FIXED QUERY)"""
    session = SessionLocal() # Start session for read-only query
    try:
        staff_roles = ['Sales', 'Production', 'Staff']
        # FIXED: Use session.query(User).filter(...) instead of User.query.filter(...)
        staff_users = session.query(User).filter(
            User.role.in_(staff_roles)
        ).order_by(User.first_name).all()
        
        return jsonify({
            'users': [user.to_dict() for user in staff_users]
        }), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        session.close() # Close session for read-only route

@auth_bp.route('/auth/refresh', methods=['POST'])
@token_required
def refresh_token():
    """Refresh JWT token"""
    session = SessionLocal() # 👈 Start session for transaction
    try:
        user = g.user
        
        if DEV_MODE:
             # Dev mode refresh is read-only
            return jsonify({
                'token': 'mock-jwt-token-123',
                'user': user.to_dict() if hasattr(user, 'to_dict') else {}
            }), 200
        
        # PRODUCTION MODE
        
        # 1. Generate new token
        payload = {
            'user_id': user.id,
            'exp': datetime.utcnow() + timedelta(days=7),
            'iat': datetime.utcnow()
        }
        new_token = jwt.encode(payload, current_app.config['SECRET_KEY'], algorithm='HS256')
        
        # 2. Find old session record using the active session
        old_token = request.headers.get('Authorization').split(" ")[1]
        session_record = session.query(Session).filter_by(session_token=old_token).first()

        # 3. Update session record
        if session_record:
            session_record.session_token = new_token
            session_record.expires_at = datetime.utcnow() + timedelta(days=7)
            session.commit() # 👈 Commit update
        
        return jsonify({
            'token': new_token,
            'user': user.to_dict()
        }), 200
        
    except Exception as e:
        session.rollback() # 👈 Rollback on error
        current_app.logger.exception(f"Error refreshing token: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close() # 👈 Close session

@auth_bp.route('/auth/forgot-password', methods=['POST'])
def forgot_password():
    """Request password reset"""
    session = SessionLocal() # 👈 Start session for transaction
    try:
        data = request.get_json()
        
        if not data.get('email'):
            return jsonify({'error': 'Email is required'}), 400
        
        email = data['email'].lower().strip()
        user = session.query(User).filter_by(email=email).first() # Query using active session
        
        if user:
            reset_token = user.generate_reset_token() # Updates user object
            session.add(user)
            session.commit() # 👈 Commit token save
            current_app.logger.info(f"Password reset token for {email}: {reset_token}")
        
        return jsonify({
            'message': 'If the email exists, a password reset link has been sent.'
        }), 200
        
    except Exception as e:
        session.rollback() # 👈 Rollback on error
        current_app.logger.exception(f"Error requesting password reset: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close() # 👈 Close session

@auth_bp.route('/auth/reset-password', methods=['POST'])
def reset_password():
    """Reset password with token"""
    session = SessionLocal() # 👈 Start session for transaction
    try:
        data = request.get_json()
        
        required_fields = ['token', 'password']
        for field in required_fields:
            if not data.get(field):
                return jsonify({'error': f'{field} is required'}), 400
        
        token = data['token']
        password = data['password']
        
        is_valid, message = validate_password(password)
        if not is_valid:
            return jsonify({'error': message}), 400
        
        # Query user using the active session
        user = session.query(User).filter(
            User.reset_token == token,
            User.reset_token_expires > datetime.utcnow()
        ).first()
        
        if not user:
            return jsonify({'error': 'Invalid or expired reset token'}), 400
        
        user.set_password(password)
        user.reset_token = None
        user.reset_token_expires = None
        
        session.add(user)
        session.commit() # 👈 Commit password change
        
        return jsonify({'message': 'Password reset successful'}), 200
        
    except Exception as e:
        session.rollback() # 👈 Rollback on error
        current_app.logger.exception(f"Error resetting password: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close() # 👈 Close session

@auth_bp.route('/auth/change-password', methods=['POST'])
@token_required
def change_password():
    """Change password for authenticated user"""
    session = SessionLocal() # 👈 Start session for transaction
    try:
        data = request.get_json()
        
        required_fields = ['current_password', 'new_password']
        for field in required_fields:
            if not data.get(field):
                return jsonify({'error': f'{field} is required'}), 400
        
        current_password = data['current_password']
        new_password = data['new_password']
        user = g.user # User is fetched by token_required, but may need re-attaching/fetching within session
        
        # Re-fetch user in the current session context if necessary, or just use g.user if it's still valid/attached
        user = session.merge(user)
        
        if not user.check_password(current_password):
            return jsonify({'error': 'Current password is incorrect'}), 400
        
        is_valid, message = validate_password(new_password)
        if not is_valid:
            return jsonify({'error': message}), 400
        
        user.set_password(new_password)
        user.updated_at = datetime.utcnow()
        
        session.commit() # 👈 Commit password change
        
        return jsonify({'message': 'Password changed successfully'}), 200
        
    except Exception as e:
        session.rollback() # 👈 Rollback on error
        current_app.logger.exception(f"Error changing password: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close() # 👈 Close session

@auth_bp.route('/auth/users', methods=['GET'])
@admin_required
def get_users():
    """Get all users (FIXED QUERY)"""
    session = SessionLocal() # Start session for read-only query
    try:
        # FIXED: Use session.query(User).order_by(...) instead of User.query.order_by(...)
        users = session.query(User).order_by(User.created_at.desc()).all() 
        
        return jsonify({
            'users': [user.to_dict() for user in users]
        }), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        session.close() # Close session for read-only route

@auth_bp.route('/users/me', methods=['GET', 'OPTIONS'])
@token_required
def get_user_me():
    """Get current user information - alternative endpoint"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    try:
        return jsonify({
            'id': g.user.id,
            'name': g.user.full_name if hasattr(g.user, 'full_name') else f"{g.user.first_name} {g.user.last_name}",
            'email': g.user.email,
            'role': g.user.role,
            'username': g.user.username if hasattr(g.user, 'username') else g.user.email
        }), 200
    except Exception as e:
        current_app.logger.exception(f"Error fetching current user: {e}")
        return jsonify({'error': 'Failed to fetch user information'}), 500

@auth_bp.route('/auth/users/<int:user_id>/toggle-status', methods=['POST'])
@admin_required
def toggle_user_status(user_id):
    """Toggle user active status"""
    session = SessionLocal() # 👈 Start session for transaction
    try:
        # Get user using the active session's .get method
        user = session.get(User, user_id)
        if not user:
            return jsonify({'error': 'User not found'}), 404
        
        # Get the new status from request body if provided
        data = request.get_json() or {}
        if 'is_active' in data:
            user.is_active = data['is_active']
        else:
            user.is_active = not user.is_active
            
        user.updated_at = datetime.utcnow()
        
        session.commit() # 👈 Commit status toggle
        
        return jsonify({
            'message': f'User {"activated" if user.is_active else "deactivated"} successfully',
            'user': user.to_dict()
        }), 200
        
    except Exception as e:
        session.rollback() # 👈 Rollback on error
        current_app.logger.exception(f"Error toggling user status: {e}")
        return jsonify({'error': 'Failed to toggle user status'}), 500
    finally:
        session.close() # 👈 Close session

@auth_bp.route('/auth/invite-user', methods=['POST'])
@admin_required
def invite_user():
    """Create an invitation for a new user"""
    session = SessionLocal()  # 👈 Start session for transaction
    try:
        data = request.get_json() or {}
        
        # Validate required fields
        required_fields = ['first_name', 'last_name', 'email', 'role']
        for field in required_fields:
            if not data.get(field):
                return jsonify({'error': f'{field} is required'}), 400
        
        email = data['email'].lower().strip()
        first_name = data['first_name'].strip()
        last_name = data['last_name'].strip()
        role = data['role'].strip()
        
        # Validate email format
        if not validate_email(email):
            return jsonify({'error': 'Invalid email format'}), 400
        
        # Validate role
        ALLOWED_ROLES = ['Manager', 'HR', 'Sales', 'Production', 'Staff']
        if role not in ALLOWED_ROLES:
            return jsonify({'error': f'Role must be one of: {", ".join(ALLOWED_ROLES)}'}), 400
        
        # Check if email already exists
        existing_user = session.query(User).filter_by(email=email).first()
        if existing_user:
            return jsonify({'error': 'A user with this email already exists'}), 400
        
        # Generate invitation token
        invitation_token = secrets.token_urlsafe(32)
        
        # Create new user with invitation
        new_user = User(
            first_name=first_name,
            last_name=last_name,
            email=email,
            role=role,
            is_active=False,  # Not active until they complete registration
            is_invited=True,
            invitation_token=invitation_token,
            invited_at=datetime.utcnow()
        )
        
        session.add(new_user)
        session.commit()  # 👈 Commit user creation
        
        current_app.logger.info(f"✅ Invitation created for: {email} as {role}")
        
        return jsonify({
            'success': True,
            'message': 'Invitation created successfully',
            'invitation_token': invitation_token,
            'user': new_user.to_dict()
        }), 201
        
    except Exception as e:
        session.rollback()  # 👈 Rollback on error
        current_app.logger.error(f"❌ Invitation creation error: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()  # 👈 Close session


@auth_bp.route('/auth/resend-invitation/<int:user_id>', methods=['POST'])
@admin_required
def resend_invitation(user_id):
    """Generate a new invitation token for a user"""
    session = SessionLocal()  # 👈 Start session for transaction
    try:
        user = session.get(User, user_id)
        if not user:
            return jsonify({'error': 'User not found'}), 404
        
        if not user.is_invited:
            return jsonify({'error': 'User has already completed registration'}), 400
        
        # Generate new invitation token
        user.invitation_token = secrets.token_urlsafe(32)
        user.invited_at = datetime.utcnow()
        
        session.commit()  # 👈 Commit token update
        
        current_app.logger.info(f"✅ Invitation resent for: {user.email}")
        
        return jsonify({
            'success': True,
            'message': 'New invitation link generated',
            'invitation_token': user.invitation_token
        }), 200
        
    except Exception as e:
        session.rollback()  # 👈 Rollback on error
        current_app.logger.error(f"❌ Resend invitation error: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()  # 👈 Close session


@auth_bp.route('/auth/users/<int:user_id>', methods=['PUT'])
@admin_required
def update_user(user_id):
    """Update user details"""
    session = SessionLocal()  # 👈 Start session for transaction
    try:
        user = session.get(User, user_id)
        if not user:
            return jsonify({'error': 'User not found'}), 404
        
        data = request.get_json() or {}
        
        # Update allowed fields
        if 'first_name' in data:
            user.first_name = data['first_name'].strip()
        
        if 'last_name' in data:
            user.last_name = data['last_name'].strip()
        
        if 'email' in data:
            new_email = data['email'].lower().strip()
            # Check if new email is already taken by another user
            existing = session.query(User).filter_by(email=new_email).first()
            if existing and existing.id != user.id:
                return jsonify({'error': 'Email already in use'}), 400
            
            if not validate_email(new_email):
                return jsonify({'error': 'Invalid email format'}), 400
            
            user.email = new_email
        
        if 'role' in data:
            role = data['role'].strip()
            ALLOWED_ROLES = ['Manager', 'HR', 'Sales', 'Production', 'Staff']
            if role not in ALLOWED_ROLES:
                return jsonify({'error': f'Role must be one of: {", ".join(ALLOWED_ROLES)}'}), 400
            user.role = role
        
        user.updated_at = datetime.utcnow()
        
        session.commit()  # 👈 Commit user updates
        
        current_app.logger.info(f"✅ User updated: {user.email}")
        
        return jsonify({
            'success': True,
            'message': 'User updated successfully',
            'user': user.to_dict()
        }), 200
        
    except Exception as e:
        session.rollback()  # 👈 Rollback on error
        current_app.logger.error(f"❌ Update user error: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()  # 👈 Close session


@auth_bp.route('/auth/users/<int:user_id>', methods=['DELETE'])
@admin_required
def delete_user(user_id):
    """Delete a user"""
    session = SessionLocal()  # 👈 Start session for transaction
    try:
        user = session.get(User, user_id)
        if not user:
            return jsonify({'error': 'User not found'}), 404
        
        # Prevent deleting yourself
        current_user = g.user
        if hasattr(current_user, 'id') and user.id == current_user.id:
            return jsonify({'error': 'You cannot delete your own account'}), 400
        
        email = user.email  # Save for logging
        
        session.delete(user)
        session.commit()  # 👈 Commit deletion
        
        current_app.logger.info(f"✅ User deleted: {email}")
        
        return jsonify({
            'success': True,
            'message': 'User deleted successfully'
        }), 200
        
    except Exception as e:
        session.rollback()  # 👈 Rollback on error
        current_app.logger.error(f"❌ Delete user error: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()  # 👈 Close session


@auth_bp.route('/settings/company', methods=['PUT'])
@admin_required
def update_company_settings():
    """Update company settings"""
    session = SessionLocal()  # 👈 Start session for transaction
    try:
        data = request.get_json() or {}
        
        # For now, just return success since you don't have a company settings table yet
        # TODO: Implement actual company settings storage in database
        
        current_app.logger.info(f"✅ Company settings update requested: {data}")
        
        return jsonify({
            'success': True,
            'message': 'Company settings updated successfully'
        }), 200
        
    except Exception as e:
        session.rollback()  # 👈 Rollback on error
        current_app.logger.error(f"❌ Company settings update error: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()  # 👈 Close session

@auth_bp.route('/auth/validate-invitation', methods=['POST'])
def validate_invitation():
    """Validate an invitation token and return user info"""
    session = SessionLocal()
    try:
        data = request.get_json() or {}
        
        invitation_token = data.get('invitation_token')
        if not invitation_token:
            return jsonify({'error': 'Invitation token is required'}), 400
        
        user = session.query(User).filter_by(
            invitation_token=invitation_token,
            is_invited=True
        ).first()
        
        if not user:
            return jsonify({'error': 'Invalid or expired invitation token'}), 400
        
        return jsonify({
            'success': True,
            'user': {
                'id': user.id,
                'email': user.email,
                'first_name': user.first_name,
                'last_name': user.last_name,
                'role': user.role,
            }
        }), 200
        
    except Exception as e:
        current_app.logger.error(f"❌ Validate invitation error: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()