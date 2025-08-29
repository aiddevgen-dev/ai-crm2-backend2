"""
Authentication utilities and decorators
"""
import jwt
from datetime import datetime, timedelta
from functools import wraps
from flask import current_app, request, jsonify
from models import UserModel
from utils.utils import AuthUtils 
class AuthUtils:
    """Utility class for authentication operations"""
    
    @staticmethod
    def generate_token(user_id, tenant_id):
        """Generate JWT token"""
        payload = {
            'user_id': str(user_id),
            'tenant_id': str(tenant_id),
            'role': 'admin',  # ADD THIS LINE
            'exp': datetime.utcnow() + timedelta(hours=current_app.config['JWT_EXPIRATION_HOURS']),
            'iat': datetime.utcnow()
        }
        
        return jwt.encode(
            payload,
            current_app.config['JWT_SECRET_KEY'],
            algorithm=current_app.config['JWT_ALGORITHM']
        )
    

    @staticmethod
    def decode_token(token):
        """Decode JWT token"""
        try:
            payload = jwt.decode(
                token,
                current_app.config['JWT_SECRET_KEY'],
                algorithms=[current_app.config['JWT_ALGORITHM']]
            )
            return payload
        except jwt.ExpiredSignatureError:
            return None
        except jwt.InvalidTokenError:
            return None
    @staticmethod
    def generate_random_string(length):
        import secrets
        import string
        alphabet = string.ascii_letters + string.digits
        return ''.join(secrets.choice(alphabet) for _ in range(length))
    @staticmethod
    def validate_email(email):
        """Basic email validation"""
        import re
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        return re.match(pattern, email) is not None
    
    @staticmethod
    def validate_password(password):
        """Basic password validation"""
        if len(password) < 6:
            return False, "Password must be at least 6 characters long"
        return True, "Valid password"

def token_required(f):
    """Decorator to require JWT token"""
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        
        # Check for token in headers
        if 'Authorization' in request.headers:
            auth_header = request.headers['Authorization']
            try:
                token = auth_header.split(" ")[1]  # Bearer <token>
            except IndexError:
                return jsonify({'message': 'Invalid token format'}), 401
        
        if not token:
            return jsonify({'message': 'Token is missing'}), 401
        
        # Decode token
        payload = AuthUtils.decode_token(token)
        if not payload:
            return jsonify({'message': 'Token is invalid or expired'}), 401
        
        # Get current user
        current_user = UserModel.get_user_by_id(payload['user_id'])
        if not current_user:
            return jsonify({'message': 'User not found'}), 401
        
        # Add user info to request context
        request.current_user = current_user
        request.current_tenant_id = payload['tenant_id']
        
        return f(*args, **kwargs)
    
    return decorated

# In utils/auth.py, ADD this new decorator function



# ... your existing token_required function remains untouched ...

def tenant_token_required(f):
    """Decorator to require a JWT token with a 'tenant' role"""
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        
        if 'Authorization' in request.headers:
            auth_header = request.headers['Authorization']
            try:
                token = auth_header.split(" ")[1]
            except IndexError:
                return jsonify({'message': 'Invalid token format'}), 401
        
        if not token:
            return jsonify({'message': 'Token is missing'}), 401
        
        payload = AuthUtils.decode_token(token)
        if not payload:
            return jsonify({'message': 'Token is invalid or expired'}), 401

        # SECURITY CHECK: Ensure the token is for a tenant
        if payload.get('role') != 'tenant':
            return jsonify({'message': 'Access denied: Tenant role required'}), 401
        
        # Attach the entire tenant payload to the request for use in the route
        request.current_tenant = payload
        
        return f(*args, **kwargs)
    
    return decorated
