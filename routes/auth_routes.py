"""
Authentication routes for the multi-tenant application
"""
from flask import Blueprint, request, jsonify, current_app
from models import UserModel, TenantModel
from utils.auth import AuthUtils, token_required
import logging
from flask_mail import Message
from flask import current_app, url_for
from google.oauth2 import id_token
from google.auth.transport import requests
from bson import ObjectId
from datetime import datetime
# from app import mongo  # Import mongo instance
from models import mongo
# Create blueprint
auth_bp = Blueprint('auth', __name__, url_prefix='/auth')

@auth_bp.route('/google-auth', methods=['POST'])
def google_auth():
    """Handle Google OAuth authentication"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        google_token = data.get('credential')
        if not google_token:
            return jsonify({'error': 'Google token required'}), 400
        
        # Verify Google token
        try:
            idinfo = id_token.verify_oauth2_token(
                google_token, 
                requests.Request(), 
                current_app.config['GOOGLE_CLIENT_ID']
            )
            
            if idinfo['iss'] not in ['accounts.google.com', 'https://accounts.google.com']:
                return jsonify({'error': 'Invalid token issuer'}), 400
                
        except ValueError:
            return jsonify({'error': 'Invalid Google token'}), 400
        
        email = idinfo.get('email')
        name = idinfo.get('name', '')
        
        if not email:
            return jsonify({'error': 'Email not provided by Google'}), 400
        
        # Check if user exists
        existing_user = UserModel.get_user_by_email(email)
        
        if existing_user:
            # Login existing user
            if existing_user.get('status') != 'active':
                return jsonify({'error': 'Account is inactive'}), 403
            
            # Generate JWT token
            token = AuthUtils.generate_token(existing_user['_id'], existing_user['tenant_id'])
            
            return jsonify({
                'token': token,
                'user': {
                    'id': str(existing_user['_id']),
                    'email': existing_user['email'],
                    'tenant_id': str(existing_user['tenant_id'])
                }
            }), 200
        else:
            # Register new user
            tenant_id = TenantModel.create_tenant(name or f"Google User - {email.split('@')[0]}")
            if not tenant_id:
                return jsonify({'error': 'Failed to create tenant'}), 500
            
            # Create user with Google flag (no password needed)
            user_data = {
                'email': email.lower(),
                'password': None,  # No password for Google users
                'tenant_id': ObjectId(tenant_id),
                'created_at': datetime.utcnow(),
                'updated_at': datetime.utcnow(),
                'status': 'active',
                'auth_provider': 'google',
                'google_id': idinfo.get('sub')
            }
            
            result = mongo.db.users.insert_one(user_data)
            user_id = str(result.inserted_id)
            
            # Generate JWT token
            token = AuthUtils.generate_token(user_id, tenant_id)
            
            return jsonify({
                'token': token,
                'user': {
                    'id': user_id,
                    'email': email,
                    'tenant_id': tenant_id
                }
            }), 201
            
    except Exception as e:
        current_app.logger.error(f"Google auth error: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

@auth_bp.route('/forgot-password', methods=['POST'])
def forgot_password():
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        email = data.get('email', '').strip()
        if not email:
            return jsonify({'error': 'Email is required'}), 400
        
        if not AuthUtils.validate_email(email):
            return jsonify({'error': 'Invalid email format'}), 400
        
        reset_token = UserModel.generate_reset_token(email)
        
        if reset_token:
            # Send email with reset link
            reset_url = f"http://localhost:3000/reset-password?token={reset_token}"
            
            msg = Message(
                subject="Password Reset Request",
                recipients=[email],
                html=f"""
                <h2>Password Reset Request</h2>
                <p>You requested a password reset. Click the link below to reset your password:</p>
                <p><a href="{reset_url}">Reset Password</a></p>
                <p>This link will expire in 1 hour.</p>
                <p>If you didn't request this, please ignore this email.</p>
                """
            )
            
            from app import mail
            mail.send(msg)
            
            # Also log to console for development
            print(f"Password reset email sent to {email}")
            print(f"Reset URL: {reset_url}")
            
            return jsonify({
                'message': 'Password reset instructions have been sent to your email'
            }), 200
        else:
            return jsonify({
                'message': 'If the email exists, reset instructions have been sent'
            }), 200
        
    except Exception as e:
        current_app.logger.error(f"Forgot password error: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

@auth_bp.route('/register', methods=['POST'])
def register():
    """Register a new user and create a new tenant"""
    try:
        # Get request data
        data = request.get_json()
        
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        email = data.get('email', '').strip()
        password = data.get('password', '')
        tenant_name = data.get('tenant_name', '')
        
        # Validate required fields
        if not email or not password:
            return jsonify({'error': 'Email and password are required'}), 400
        
        # Validate email format
        if not AuthUtils.validate_email(email):
            return jsonify({'error': 'Invalid email format'}), 400
        
        # Validate password
        is_valid, message = AuthUtils.validate_password(password)
        if not is_valid:
            return jsonify({'error': message}), 400
        
        # Check if user already exists
        existing_user = UserModel.get_user_by_email(email)
        if existing_user:
            return jsonify({'error': 'User with this email already exists'}), 409
        
        # Create new tenant
        tenant_id = TenantModel.create_tenant(tenant_name)
        if not tenant_id:
            return jsonify({'error': 'Failed to create tenant'}), 500
        
        # Create new user
        user_id = UserModel.create_user(email, password, tenant_id)
        if not user_id:
            return jsonify({'error': 'Failed to create user'}), 500
        
        return jsonify({
            'message': 'User registered successfully',
            'user_id': user_id,
            'tenant_id': tenant_id
        }), 201
        
    except Exception as e:
        current_app.logger.error(f"Registration error: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

@auth_bp.route('/login', methods=['POST'])
def login():
    """Login user and return JWT token"""
    try:
        # Get request data
        data = request.get_json()
        
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        email = data.get('email', '').strip()
        password = data.get('password', '')
        
        # Validate required fields
        if not email or not password:
            return jsonify({'error': 'Email and password are required'}), 400
        
        # Get user by email
        user = UserModel.get_user_by_email(email)
        if not user:
            return jsonify({'error': 'Invalid credentials'}), 401
        
        # Verify password
        if not UserModel.verify_password(user['password'], password):
            return jsonify({'error': 'Invalid credentials'}), 401
        
        # Check user status
        if user.get('status') != 'active':
            return jsonify({'error': 'Account is inactive'}), 403
        
        # Generate JWT token
        token = AuthUtils.generate_token(user['_id'], user['tenant_id'])
        
        return jsonify({
            'token': token,
            'user': {
                'id': str(user['_id']),
                'email': user['email'],
                'tenant_id': str(user['tenant_id'])
            }
        }), 200
        
    except Exception as e:
        current_app.logger.error(f"Login error: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

@auth_bp.route('/reset-password', methods=['POST'])
def reset_password():
    """Reset password using token"""
    try:
        # Get request data
        data = request.get_json()
        
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        token = data.get('token', '').strip()
        new_password = data.get('new_password', '')
        
        # Validate required fields
        if not token or not new_password:
            return jsonify({'error': 'Token and new password are required'}), 400
        
        # Validate new password
        is_valid, message = AuthUtils.validate_password(new_password)
        if not is_valid:
            return jsonify({'error': message}), 400
        
        # Reset password
        success = UserModel.reset_password(token, new_password)
        
        if success:
            return jsonify({'message': 'Password reset successfully'}), 200
        else:
            return jsonify({'error': 'Invalid or expired token'}), 400
        
    except Exception as e:
        current_app.logger.error(f"Reset password error: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

@auth_bp.route('/me', methods=['GET'])
@token_required
def get_current_user():
    """Get current user information (protected route example)"""
    try:
        user = request.current_user
        
        return jsonify({
            'user': {
                'id': str(user['_id']),
                'email': user['email'],
                'tenant_id': str(user['tenant_id']),
                'created_at': user['created_at'].isoformat(),
                'status': user['status']
            }
        }), 200
        
    except Exception as e:
        current_app.logger.error(f"Get current user error: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

@auth_bp.route('/validate-token', methods=['POST'])
def validate_token():
    """Validate JWT token"""
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        token = data.get('token', '')
        
        if not token:
            return jsonify({'error': 'Token is required'}), 400
        
        # Decode token
        payload = AuthUtils.decode_token(token)
        
        if payload:
            return jsonify({
                'valid': True,
                'user_id': payload['user_id'],
                'tenant_id': payload['tenant_id']
            }), 200
        else:
            return jsonify({'valid': False}), 200
            
    except Exception as e:
        current_app.logger.error(f"Token validation error: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500