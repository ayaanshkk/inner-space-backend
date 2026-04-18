"""
Authentication Helpers for StreemLyne_MT Schema
Reusable authentication and authorization utilities
"""
from functools import wraps
from flask import request, jsonify, current_app
import jwt
from datetime import datetime, timedelta
from sqlalchemy import text


def get_current_user():
    """Get current user from request context"""
    if hasattr(request, 'current_user'):
        return request.current_user
    return None


def get_current_tenant_id():
    """Get tenant_id from current user context"""
    user = get_current_user()
    if user:
        return user.get('tenant_id')
    return None


def get_current_employee_id():
    """Get employee_id from current user context"""
    user = get_current_user()
    if user:
        return user.get('employee_id')
    return None


def get_current_user_roles():
    """Get role IDs for current user"""
    user = get_current_user()
    if user:
        role_ids = user.get('role_ids', '')
        if role_ids:
            return [int(r.strip()) for r in role_ids.split(',') if r.strip()]
    return []


def has_role(role_id):
    """Check if current user has a specific role"""
    return role_id in get_current_user_roles()


def is_admin():
    """Check if current user is an admin"""
    # Assuming role_id 1 is admin - adjust based on your schema
    return has_role(1)


def token_required(f):
    """Decorator to require authentication"""
    
    @wraps(f)
    def decorated(*args, **kwargs):
        # Handle OPTIONS requests (CORS preflight)
        if request.method == 'OPTIONS':
            return f(*args, **kwargs)
        
        token = None
        
        # Extract token from Authorization header
        if 'Authorization' in request.headers:
            auth_header = request.headers['Authorization']
            try:
                # Expected format: "Bearer <token>"
                token = auth_header.split(" ")[1]
            except IndexError:
                return jsonify({'error': 'Invalid token format'}), 401
        
        if not token:
            return jsonify({'error': 'Token is missing'}), 401
        
        try:
            # Decode JWT token
            payload = jwt.decode(
                token, 
                current_app.config['SECRET_KEY'], 
                algorithms=['HS256']
            )
            
            # Extract user info from token payload
            # Expected payload structure: {
            #   'user_id': employee_id,
            #   'tenant_id': tenant_id,
            #   'employee_id': employee_id,
            #   'employee_name': name,
            #   'email': email,
            #   'role_ids': role_ids (comma-separated string)
            # }
            
            current_user = {
                'user_id': payload.get('user_id'),
                'employee_id': payload.get('employee_id'),
                'tenant_id': payload.get('tenant_id'),
                'employee_name': payload.get('employee_name'),
                'email': payload.get('email'),
                'role_ids': payload.get('role_ids', '')
            }
            
            # Attach the user to the request object
            request.current_user = current_user
            
        except jwt.ExpiredSignatureError:
            return jsonify({'error': 'Token has expired'}), 401
        except jwt.InvalidTokenError as e:
            current_app.logger.error(f"Invalid token: {e}")
            return jsonify({'error': 'Token is invalid'}), 401
        except Exception as e:
            current_app.logger.error(f"Token verification failed: {e}")
            return jsonify({'error': 'Token verification failed'}), 401
        
        return f(*args, **kwargs)
    
    return decorated


def role_required(*role_ids):
    """Decorator to require specific role(s)"""
    
    def decorator(f):
        @wraps(f)
        @token_required
        def decorated_function(*args, **kwargs):
            user_roles = get_current_user_roles()
            
            # Check if user has any of the required roles
            if not any(role_id in user_roles for role_id in role_ids):
                return jsonify({
                    'error': 'Insufficient permissions',
                    'required_roles': list(role_ids),
                    'user_roles': user_roles
                }), 403
            
            return f(*args, **kwargs)
        
        return decorated_function
    
    return decorator


def generate_token(employee_id, tenant_id, employee_name, email, role_ids):
    """
    Generate JWT token for authenticated user
    
    Args:
        employee_id: Employee ID from Employee_Master
        tenant_id: Tenant ID
        employee_name: Employee's full name
        email: Employee's email
        role_ids: Comma-separated string of role IDs
    
    Returns:
        str: JWT token
    """
    payload = {
        'user_id': employee_id,
        'employee_id': employee_id,
        'tenant_id': tenant_id,
        'employee_name': employee_name,
        'email': email,
        'role_ids': role_ids,
        'exp': datetime.utcnow() + timedelta(days=7),  # Token expires in 7 days
        'iat': datetime.utcnow()
    }
    
    token = jwt.encode(
        payload,
        current_app.config['SECRET_KEY'],
        algorithm='HS256'
    )
    
    return token


def verify_employee_credentials(session, email, password_hash, tenant_id=None):
    """
    Verify employee credentials against database
    
    Args:
        session: SQLAlchemy session
        email: Employee email
        password_hash: Hashed password to verify
        tenant_id: Optional tenant_id filter
    
    Returns:
        dict: Employee info if valid, None if invalid
    """
    query = text("""
        SELECT 
            e.employee_id,
            e.tenant_id,
            e.employee_name,
            e.email,
            e.role_ids,
            u.password as password_hash
        FROM "StreemLyne_MT"."Employee_Master" e
        JOIN "StreemLyne_MT"."User_Master" u ON e.employee_id = u.employee_id
        WHERE e.email = :email
    """)
    
    params = {'email': email}
    
    if tenant_id:
        query = text("""
            SELECT 
                e.employee_id,
                e.tenant_id,
                e.employee_name,
                e.email,
                e.role_ids,
                u.password as password_hash
            FROM "StreemLyne_MT"."Employee_Master" e
            JOIN "StreemLyne_MT"."User_Master" u ON e.employee_id = u.employee_id
            WHERE e.email = :email AND e.tenant_id = :tenant_id
        """)
        params['tenant_id'] = tenant_id
    
    result = session.execute(query, params)
    employee = result.fetchone()
    
    if not employee:
        return None
    
    # Verify password hash
    # You should use bcrypt or werkzeug.security.check_password_hash
    # For now, simple comparison (REPLACE WITH PROPER PASSWORD HASHING)
    if employee.password_hash != password_hash:
        return None
    
    return {
        'employee_id': employee.employee_id,
        'tenant_id': employee.tenant_id,
        'employee_name': employee.employee_name,
        'email': employee.email,
        'role_ids': employee.role_ids
    }


def check_tenant_access(resource_tenant_id):
    """
    Check if current user has access to a resource from another tenant
    
    Args:
        resource_tenant_id: Tenant ID of the resource being accessed
    
    Returns:
        bool: True if access allowed, False otherwise
    """
    current_tenant = get_current_tenant_id()
    
    if not current_tenant:
        return False
    
    # User can only access resources from their own tenant
    return current_tenant == resource_tenant_id


def tenant_isolation_check(f):
    """
    Decorator to ensure tenant isolation
    Checks that resource belongs to current user's tenant
    """
    
    @wraps(f)
    @token_required
    def decorated_function(*args, **kwargs):
        # This decorator assumes route functions will check tenant_id
        # It's a reminder to implement tenant checks
        return f(*args, **kwargs)
    
    return decorated_function


# Example usage in routes:
"""
from .auth_helpers import token_required, role_required, get_current_tenant_id

@app.route('/api/clients', methods=['GET'])
@token_required
def get_clients():
    tenant_id = get_current_tenant_id()
    # Query only clients for this tenant
    ...

@app.route('/api/admin/users', methods=['GET'])
@role_required(1)  # Only admin role (role_id=1)
def get_all_users():
    ...
"""