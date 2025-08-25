"""
Tenant Authentication routes for registered tenants
"""
from flask import Blueprint, request, jsonify, current_app
from models import RegisteredTenantModel
from utils.auth import AuthUtils
from bson import ObjectId
from datetime import datetime, timedelta   # ✅ also fixes step 3
import jwt
import logging
from models import mongo

# now = datetime.utcnow()
# Create blueprint
tenant_auth_bp = Blueprint('tenant_auth', __name__, url_prefix='/api/tenant-auth')

def generate_tenant_token(tenant_id, tenant_email):
    """Generate JWT token for tenant authentication"""
    try:
        import jwt
        from datetime import datetime, timedelta
        
        payload = {
    'user_id': tenant_id,
    'tenant_id': tenant_id,
    'tenant_email': tenant_email,
    'role': 'tenant',  # ADD THIS LINE
    'exp': datetime.utcnow() + timedelta(hours=current_app.config.get('JWT_EXPIRATION_HOURS', 24)),
    'iat': datetime.utcnow(),
    'type': 'tenant_access'
}
        
        token = jwt.encode(
            payload,
            current_app.config['JWT_SECRET_KEY'],
            algorithm=current_app.config.get('JWT_ALGORITHM', 'HS256')
        )
        
        return token
        
    except Exception as e:
        current_app.logger.error(f"Token generation error: {str(e)}")
        print(f"DEBUG - Token generation error: {str(e)}")
        return None
    

@tenant_auth_bp.route('/login', methods=['POST'])
def tenant_login():
    """Login for registered tenants"""
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({'error': 'No data provided', 'success': False}), 400
        
        tenant_id = data.get('tenant_id', '').strip()
        password = data.get('password', '')
        
        if not tenant_id or not password:
            return jsonify({'error': 'Tenant ID and password are required', 'success': False}), 400
        
        # Verify tenant credentials
        is_valid = RegisteredTenantModel.verify_tenant_credentials(tenant_id, password)
        
        if not is_valid:
            return jsonify({'error': 'Invalid Tenant ID or password', 'success': False}), 401
        
        # Get tenant details
        tenant = RegisteredTenantModel.get_tenant_by_tenant_id(tenant_id)
        
        if not tenant:
            return jsonify({'error': 'Tenant not found', 'success': False}), 404
        
        # Check if tenant is active
        # if tenant.get('status') != 'active':
        #     return jsonify({'error': 'Tenant account is not active', 'success': False}), 403
        now = datetime.utcnow()

        now = datetime.utcnow()

# ✅ If suspended/blocked, deny BEFORE touching last_login
        if tenant.get('status') in ('suspended', 'blocked'):
            return jsonify({'error': 'Tenant account is not permitted to login', 'success': False}), 403

        # ✅ First login (inactive/pending/etc.): auto-activate and set last_login
        if tenant.get('status') != 'active':
            mongo.db.registered_tenants.update_one(
                {'tenant_id': tenant_id},
                {
                    '$set': {
                        'status': 'active',
                        'activated_at': tenant.get('activated_at') or now,
                        'last_login': now,
                        'updated_at': now,
                    },
                    '$inc': {'login_count': 1}
                }
            )
            tenant['status'] = 'active'
        else:
            # ✅ Already active: just bump last_login / updated_at, increment login_count
            mongo.db.registered_tenants.update_one(
                {'tenant_id': tenant_id},
                {
                    '$set': {
                        'last_login': now,
                        'updated_at': now,
                    },
                    '$inc': {'login_count': 1}
                }
            )

        # Generate JWT token for tenant
        token = generate_tenant_token(tenant_id, tenant['email'])
        
        if not token:
            return jsonify({'error': 'Failed to generate authentication token', 'success': False}), 500
        
        # Update last login time
        now = datetime.utcnow()
        # mongo.db.registered_tenants.update_one(
        #     {'tenant_id': tenant_id},
        #     {
        #         '$set': {
        #             'last_login': datetime.utcnow(),
        #             'updated_at': datetime.utcnow()
        #         }
        #     }
        # )
        
        return jsonify({
            'success': True,
            'message': 'Login successful',
            'token': token,
            'user': {
                'tenant_id': tenant['tenant_id'],
                'email': tenant['email'],
                'name': tenant['name'],
                'status': tenant['status'],
                'role': tenant.get('role', 'tenant'),
            }
        }), 200
        
    except Exception as e:
        current_app.logger.error(f"Tenant login error: {str(e)}")
        return jsonify({'error': 'Internal server error', 'success': False}), 500

@tenant_auth_bp.route('/verify-token', methods=['POST'])
def verify_tenant_token():
    """Verify tenant JWT token"""
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({'error': 'No data provided', 'valid': False}), 400
        
        token = data.get('token', '')
        
        if not token:
            return jsonify({'error': 'Token is required', 'valid': False}), 400
        
        try:
            # Decode token
            payload = jwt.decode(
                token,
                current_app.config['JWT_SECRET_KEY'],
                algorithms=['HS256']
            )
            
            # Check if it's a tenant token
            if payload.get('type') != 'tenant_access':
                return jsonify({'error': 'Invalid token type', 'valid': False}), 400
            
            tenant_id = payload.get('tenant_id')
            tenant_email = payload.get('tenant_email')
            
            if not tenant_id or not tenant_email:
                return jsonify({'error': 'Invalid token payload', 'valid': False}), 400
            
            # Verify tenant still exists and is active
            tenant = RegisteredTenantModel.get_tenant_by_tenant_id(tenant_id)
            
            if not tenant or tenant.get('status') != 'active':
                return jsonify({'error': 'Tenant not found or inactive', 'valid': False}), 401
            
            return jsonify({
                'valid': True,
                'tenant': {
                    'tenant_id': tenant['tenant_id'],
                    'email': tenant['email'],
                    'name': tenant['name'],
                    'status': tenant['status']
                }
            }), 200
            
        except jwt.ExpiredSignatureError:
            return jsonify({'error': 'Token has expired', 'valid': False}), 401
        except jwt.InvalidTokenError:
            return jsonify({'error': 'Invalid token', 'valid': False}), 401
            
    except Exception as e:
        current_app.logger.error(f"Token verification error: {str(e)}")
        return jsonify({'error': 'Internal server error', 'valid': False}), 500

@tenant_auth_bp.route('/profile', methods=['GET'])
def get_tenant_profile():
    """Get tenant profile information (protected route)"""
    try:
        # Get token from Authorization header
        auth_header = request.headers.get('Authorization')
        
        if not auth_header or not auth_header.startswith('Bearer '):
            return jsonify({'error': 'Authorization token required'}), 401
        
        token = auth_header.split(' ')[1]
        
        try:
            # Decode token
            payload = jwt.decode(
                token,
                current_app.config['JWT_SECRET_KEY'],
                algorithms=['HS256']
            )
            
            # Check if it's a tenant token
            if payload.get('type') != 'tenant_access':
                return jsonify({'error': 'Invalid token type'}), 401
            
            tenant_id = payload.get('tenant_id')
            
            # Get tenant details
            tenant = RegisteredTenantModel.get_tenant_by_tenant_id(tenant_id)
            
            if not tenant:
                return jsonify({'error': 'Tenant not found'}), 404
            
            if tenant.get('status') != 'active':
                return jsonify({'error': 'Tenant account is not active'}), 403
            
            return jsonify({
                'tenant': {
                    'tenant_id': tenant['tenant_id'],
                    'email': tenant['email'],   
                    'name': tenant['name'],
                    'role': tenant['role'],
                    'status': tenant['status'],
                    'created_at': tenant['created_at'].isoformat(),
                    'last_login': tenant.get('last_login').isoformat() if tenant.get('last_login') else None
                }
            }), 200
            
        except jwt.ExpiredSignatureError:
            return jsonify({'error': 'Token has expired'}), 401
        except jwt.InvalidTokenError:
            return jsonify({'error': 'Invalid token'}), 401
            
    except Exception as e:
        current_app.logger.error(f"Get tenant profile error: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

@tenant_auth_bp.route('/forgot-password', methods=['POST'])
def tenant_forgot_password():
    """Forgot password for tenants"""
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        tenant_id = data.get('tenant_id', '').strip()
        
        if not tenant_id:
            return jsonify({'error': 'Tenant ID is required'}), 400
        
        # Get tenant details
        tenant = RegisteredTenantModel.get_tenant_by_tenant_id(tenant_id)
        
        if tenant:
            # Generate a simple reset token (you might want to make this more secure)
            reset_token = AuthUtils.generate_random_string(32)
            
            # Store reset token in database with expiration
            now = datetime.utcnow()
            mongo.db.registered_tenants.update_one(
                {'tenant_id': tenant_id},
                {
                    '$set': {
                        'reset_token': reset_token,
                        'reset_token_expires': datetime.utcnow() + timedelta(hours=1),
                        'updated_at': datetime.utcnow()
                    }
                }
            )
            
            # Send email with reset instructions
            try:
                from flask_mail import Message
                from app import mail
                
                reset_url_local = f"http://localhost:3000/tenant-auth/reset-password?token={reset_token}"
                reset_url_prod = f"https://the-crm-ai.vercel.app/tenant-auth/reset-password?token={reset_token}"
                
                msg = Message(
                    subject="Password Reset Request - MultiTenants AI",
                    recipients=[tenant['email']],
                    html=f"""
                    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                        <h2 style="color: #333;">Password Reset Request</h2>
                        <p>Hello {tenant['name']},</p>
                        <p>You requested a password reset for your tenant account.</p>
                        
                        <p><strong>Tenant ID:</strong> {tenant_id}</p>
                        
                        <p>Click one of the links below to reset your password:</p>
                        
                        <div style="margin: 20px 0;">
                            <p><strong>Production:</strong> <a href="{reset_url_prod}" style="color: #007bff;">{reset_url_prod}</a></p>
                            <p><strong>Local Development:</strong> <a href="{reset_url_local}" style="color: #007bff;">{reset_url_local}</a></p>
                        </div>
                        
                        <p><strong>Important:</strong> This link will expire in 1 hour.</p>
                        <p>If you didn't request this, please ignore this email.</p>
                        
                        <p>Best regards,<br>MultiTenants AI Team</p>
                    </div>
                    """
                )
                
                mail.send(msg)
                current_app.logger.info(f"Password reset email sent to {tenant['email']}")
                
            except Exception as email_error:
                current_app.logger.error(f"Failed to send reset email: {str(email_error)}")
        
        # Always return success message for security (don't reveal if tenant exists)
        return jsonify({
            'message': 'If the Tenant ID exists, reset instructions have been sent to the associated email'
        }), 200
        
    except Exception as e:
        current_app.logger.error(f"Tenant forgot password error: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

@tenant_auth_bp.route('/logout', methods=['POST'])
def tenant_logout():
    """Logout tenant (mainly for frontend to clear local storage)"""
    try:
        # In a stateless JWT system, logout is mainly handled on the frontend
        # by removing the token from local storage
        return jsonify({'message': 'Logged out successfully'}), 200
        
    except Exception as e:
        current_app.logger.error(f"Tenant logout error: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500