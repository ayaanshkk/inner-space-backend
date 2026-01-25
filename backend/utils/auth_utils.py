"""
JWT Authentication Utilities
"""
import jwt
import os
from datetime import datetime, timedelta
from functools import wraps
from flask import request, jsonify, g
from backend.db import SessionLocal
from backend.models import User

# Get configuration from environment
JWT_SECRET_KEY = os.getenv('JWT_SECRET_KEY', 'dev-jwt-secret-change-in-production')
JWT_ALGORITHM = 'HS256'
JWT_ACCESS_TOKEN_EXPIRES = int(os.getenv('JWT_ACCESS_TOKEN_EXPIRES', 3600))  # 1 hour


def generate_token(user_id: int, email: str) -> str:
    """
    Generate JWT access token
    
    Args:
        user_id: User ID
        email: User email
        
    Returns:
        JWT token string
    """
    payload = {
        'user_id': user_id,
        'email': email,
        'exp': datetime.utcnow() + timedelta(seconds=JWT_ACCESS_TOKEN_EXPIRES),
        'iat': datetime.utcnow()
    }
    
    token = jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
    return token


def decode_token(token: str) -> dict:
    """
    Decode and validate JWT token
    
    Args:
        token: JWT token string
        
    Returns:
        Decoded payload
        
    Raises:
        jwt.ExpiredSignatureError: Token has expired
        jwt.InvalidTokenError: Token is invalid
    """
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise ValueError('Token has expired')
    except jwt.InvalidTokenError:
        raise ValueError('Invalid token')


def get_token_from_header() -> str:
    """
    Extract token from Authorization header
    
    Returns:
        Token string
        
    Raises:
        ValueError: If token is missing or invalid format
    """
    auth_header = request.headers.get('Authorization')
    
    if not auth_header:
        raise ValueError('Authorization header missing')
    
    # Expected format: "Bearer <token>"
    parts = auth_header.split()
    
    if len(parts) != 2 or parts[0].lower() != 'bearer':
        raise ValueError('Invalid authorization header format. Expected: Bearer <token>')
    
    return parts[1]


def require_auth(f):
    """
    Decorator to require authentication for routes
    
    Usage:
        @app.route('/protected')
        @require_auth
        def protected_route():
            user = g.user  # Authenticated user is available
            return jsonify({'message': f'Hello {user.email}'})
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        try:
            # Extract token
            token = get_token_from_header()
            
            # Decode token
            payload = decode_token(token)
            
            # Get user from database
            session = SessionLocal()
            user = session.query(User).filter_by(id=payload['user_id']).first()
            
            if not user:
                session.close()
                return jsonify({'error': 'User not found'}), 401
            
            if not user.is_active:
                session.close()
                return jsonify({'error': 'User account is inactive'}), 401
            
            # Store user in g for access in route
            g.user = user
            g.db_session = session
            
            # Call the actual route function
            response = f(*args, **kwargs)
            
            # Close session after request
            session.close()
            
            return response
            
        except ValueError as e:
            return jsonify({'error': str(e)}), 401
        except Exception as e:
            return jsonify({'error': 'Authentication failed'}), 401
    
    return decorated_function


def optional_auth(f):
    """
    Decorator for routes that work with or without authentication
    
    If token is provided and valid, g.user will be set
    If no token or invalid token, g.user will be None
    
    Usage:
        @app.route('/optional')
        @optional_auth
        def optional_route():
            if g.user:
                return jsonify({'message': f'Hello {g.user.email}'})
            else:
                return jsonify({'message': 'Hello guest'})
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        try:
            token = get_token_from_header()
            payload = decode_token(token)
            
            session = SessionLocal()
            user = session.query(User).filter_by(id=payload['user_id']).first()
            
            if user and user.is_active:
                g.user = user
                g.db_session = session
            else:
                g.user = None
                g.db_session = None
                session.close()
                
        except (ValueError, Exception):
            g.user = None
            g.db_session = None
        
        response = f(*args, **kwargs)
        
        if hasattr(g, 'db_session') and g.db_session:
            g.db_session.close()
        
        return response
    
    return decorated_function


def get_current_user() -> User:
    """
    Get current authenticated user from g context
    
    Returns:
        User object
        
    Raises:
        ValueError: If no user in context (not authenticated)
    """
    if not hasattr(g, 'user') or g.user is None:
        raise ValueError('No authenticated user')
    
    return g.user