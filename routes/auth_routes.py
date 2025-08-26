"""
Authentication routes for the multi-tenant application
"""
from flask import Blueprint, request, jsonify, current_app, session, redirect
from models import UserModel, TenantModel
from utils.auth import AuthUtils, token_required
import logging
from flask_mail import Message
from flask import  url_for
from google.oauth2 import id_token
from google.auth.transport import requests
from bson import ObjectId
import jwt  # Add this import for PyJWT

# from app import mongo  # Import mongo instance
from models import mongo
# from authlib.integrations.flask_client import OAuth
from requests_oauthlib import OAuth2Session
from datetime import datetime, timedelta
import secrets
# Create blueprint
auth_bp = Blueprint('auth', __name__, url_prefix='/auth')
# oauth = OAuth()
# Configure Google Calendar OAuth
# oauth.register(
#     name='google_calendar',
#     client_id=current_app.config.get('GOOGLE_CLIENT_ID'),
#     client_secret=current_app.config.get('GOOGLE_CLIENT_SECRET'),
#     access_token_url='https://oauth2.googleapis.com/token',
#     access_token_params=None,
#     authorize_url='https://accounts.google.com/o/oauth2/v2/auth',
#     authorize_params=None,
#     api_base_url='https://www.googleapis.com/calendar/v3/',
#     server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
#     client_kwargs={
#         'scope': 'https://www.googleapis.com/auth/calendar https://www.googleapis.com/auth/userinfo.email',
#         'access_type': 'offline',
#         'prompt': 'consent',
#         'include_granted_scopes': 'true'
#     }
# )
# google calendar integration:
@auth_bp.route('/google/calendar/integrate', methods=['GET'])
def google_calendar_integrate():
    """Initiate Google Calendar integration for current user"""
    try:
        # Get user info from JWT token
        auth_header = request.headers.get('Authorization')
        # if not auth_header or not auth_header.startswith('Bearer '):
        #     return jsonify({'error': 'Authorization token required'}), 401
        if not auth_header or not auth_header.startswith('Bearer '):
    # fallback: token in query
            q = request.args.get('token')
            if q:
                auth_header = f'Bearer {q}'

        if not auth_header or not auth_header.startswith('Bearer '):
            return jsonify({'error': 'Authorization token required'}), 401
        # hello
        token = auth_header.split(' ')[1]
        try:
            payload = jwt.decode(token, current_app.config['JWT_SECRET_KEY'], algorithms=['HS256'])
            user_id = payload.get('user_id')
        except jwt.InvalidTokenError:
            return jsonify({'error': 'Invalid token'}), 401
        
        if not user_id:
            return jsonify({'error': 'User ID not found in token'}), 401
        
        # Validate user exists
        user = UserModel.get_user_by_id(user_id)
        if not user:
            return jsonify({'error': 'User not found'}), 404
        
        # Store user info in session for callback
        session['integrating_user_id'] = user_id
        session['current_user_email'] = user.get('email')
        
        # Generate redirect URI
        base_url = request.url_root.rstrip('/')
        redirect_uri = f"{base_url}/auth/google/calendar/callback"
        
        return current_app.oauth.google_calendar.authorize_redirect(
            redirect_uri, 
            prompt='consent', 
            access_type='offline',
            login_hint=user.get('email')
        )
        
    except Exception as e:
        current_app.logger.error(f"Calendar integration error: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500


@auth_bp.route('/google/calendar/callback')
def google_calendar_callback():
    """Handle Google Calendar OAuth callback"""
    try:
        # Get user info from session
        user_id = session.pop('integrating_user_id', None)
        current_user_email = session.pop('current_user_email', None)
        
        if not user_id or not current_user_email:
            return jsonify({'error': 'User session not found'}), 400
        
        # Get OAuth token
        token = current_app.oauth.google_calendar.authorize_access_token()
        if not token:
            return jsonify({'error': 'Failed to get token from Google'}), 400
        
        access_token = token.get('access_token')
        refresh_token = token.get('refresh_token')
        expires_in = token.get('expires_in', 3600)
        
        # Get user info from Google
        userinfo = current_app.oauth.google_calendar.get('https://www.googleapis.com/oauth2/v2/userinfo')
        if userinfo.status_code != 200:
            return jsonify({'error': 'Failed to get user info from Google'}), 400
        
        google_account_info = userinfo.json()
        google_email = google_account_info.get('email')
        
        if not google_email:
            return jsonify({'error': 'Failed to get email from Google account'}), 400
        
        # Calculate expiration time
        expiration_time = datetime.utcnow() + timedelta(seconds=expires_in)
        
        # Update user with calendar integration data
        update_data = {
            'google_calendar_email': google_email,
            'google_calendar_token': access_token,
            'google_calendar_token_expiration': expiration_time
        }
        
        if refresh_token:
            update_data['google_calendar_refresh_token'] = refresh_token
        
        success = UserModel.update_user(user_id, update_data)
        
        if not success:
            return jsonify({'error': 'Failed to save calendar integration'}), 500
        
        # Redirect to frontend success page
        frontend_url = "http://localhost:3000" if current_app.config.get('ENV') == 'development' else "https://the-crm-ai.vercel.app"
        return redirect(f"{frontend_url}/dashboard?calendar_integrated=success")
        
    except Exception as e:
        current_app.logger.error(f"Calendar callback error: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500


@auth_bp.route('/google/calendar/status', methods=['GET'])
def check_google_calendar_status():
    """Check if user has Google Calendar integrated"""
    try:
        # Get user info from JWT token
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            return jsonify({'error': 'Authorization token required'}), 401
        
        token = auth_header.split(' ')[1]
        try:
            payload = jwt.decode(token, current_app.config['JWT_SECRET_KEY'], algorithms=['HS256'])
            user_id = payload.get('user_id')
        except jwt.InvalidTokenError:
            return jsonify({'error': 'Invalid token'}), 401
        
        user = UserModel.get_user_by_id(user_id)
        
        if not user:
            return jsonify({'error': 'User not found'}), 404
        
        # Check if calendar is integrated and token is valid
        if user.get('google_calendar_token'):
            expiration_time = user.get('google_calendar_token_expiration')
            if expiration_time and datetime.utcnow() < expiration_time:
                return jsonify({
                    'integrated': True,
                    'email': user.get('google_calendar_email')
                })
            else:
                # Token expired, try to refresh
                new_token = refresh_google_calendar_token(user_id)
                if new_token:
                    return jsonify({
                        'integrated': True,
                        'email': user.get('google_calendar_email')
                    })
        
        return jsonify({'integrated': False})
        
    except Exception as e:
        current_app.logger.error(f"Calendar status check error: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500


@auth_bp.route('/google/calendar/disconnect', methods=['POST'])
def disconnect_google_calendar():
    """Disconnect Google Calendar integration"""
    try:
        # Get user info from JWT token
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            return jsonify({'error': 'Authorization token required'}), 401
        
        token = auth_header.split(' ')[1]
        try:
            payload = jwt.decode(token, current_app.config['JWT_SECRET_KEY'], algorithms=['HS256'])
            user_id = payload.get('user_id')
        except jwt.InvalidTokenError:
            return jsonify({'error': 'Invalid token'}), 401
        
      
        user = UserModel.get_user_by_id(user_id)
        
        if not user:
            return jsonify({'error': 'User not found'}), 404
        
        # Remove Google Calendar integration fields
        success = UserModel.remove_fields(user_id, [
            'google_calendar_email',
            'google_calendar_token',
            'google_calendar_refresh_token',
            'google_calendar_token_expiration'
        ])
        
        if success:
            return jsonify({'success': True, 'message': 'Google Calendar disconnected successfully'})
        else:
            return jsonify({'error': 'Failed to disconnect calendar'}), 500
        
    except Exception as e:
        current_app.logger.error(f"Calendar disconnect error: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500


@auth_bp.route('/google/calendar/events', methods=['GET'])
def get_calendar_events():
    """Fetch user's Google Calendar events"""
    try:
        # Get user info from JWT token
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            return jsonify({'error': 'Authorization token required'}), 401
        
        token = auth_header.split(' ')[1]
        try:
            payload = jwt.decode(token, current_app.config['JWT_SECRET_KEY'], algorithms=['HS256'])
            user_id = payload.get('user_id')
        except jwt.InvalidTokenError:
            return jsonify({'error': 'Invalid token'}), 401
        
   
        user = UserModel.get_user_by_id(user_id)
        
        if not user or not user.get('google_calendar_token'):
            return jsonify({'error': 'Google Calendar not integrated'}), 400
        
        access_token = user.get('google_calendar_token')
        
        # Check if token is expired and refresh if needed
        token_expiration = user.get('google_calendar_token_expiration')
        if token_expiration and datetime.utcnow() >= token_expiration:
            new_token = refresh_google_calendar_token(user_id)
            if not new_token:
                return jsonify({'error': 'Failed to refresh Google token'}), 401
            access_token = new_token
        
        # Create OAuth session and fetch events
        token_dict = {
            "access_token": access_token,
            "token_type": "Bearer"
        }
        
        google_session = OAuth2Session(token=token_dict)
        response = google_session.get("https://www.googleapis.com/calendar/v3/calendars/primary/events")
        response.raise_for_status()
        
        response_data = response.json()
        if 'items' not in response_data:
            response_data['items'] = []
        
        return jsonify(response_data)
        
    except Exception as e:
        current_app.logger.error(f"Error fetching calendar events: {str(e)}")
        return jsonify({
            "error": f"Error fetching calendar events: {str(e)}",
            "items": []
        }), 500


# ==========================================
# UTILITY FUNCTION - ADD TO YOUR auth_routes.py
# ==========================================

def refresh_google_calendar_token(user_id):
    """Refresh Google Calendar access token using refresh token"""
    try:
        user = UserModel.get_user_by_id(user_id)
        
        if not user or not user.get('google_calendar_refresh_token'):
            return None
        
        refresh_token = user['google_calendar_refresh_token']
        
        # Use OAuth client to refresh token
        new_token = current_app.oauth.google_calendar.fetch_access_token(
            grant_type='refresh_token',
            refresh_token=refresh_token
        )
        
        # Update database with new token
        new_access_token = new_token['access_token']
        new_expires_in = new_token['expires_in']
        new_expiration_time = datetime.utcnow() + timedelta(seconds=new_expires_in)
        
        update_data = {
            'google_calendar_token': new_access_token,
            'google_calendar_token_expiration': new_expiration_time
        }
        
        UserModel.update_user(user_id, update_data)
        return new_access_token
        
    except Exception as e:
        current_app.logger.error(f"Failed to refresh token: {str(e)}")
        return None

# google sign on
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
        user_id = UserModel.create_user(email, password, tenant_id, 'admin')
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
                'tenant_id': str(user['tenant_id']),
                'role': user['role']
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