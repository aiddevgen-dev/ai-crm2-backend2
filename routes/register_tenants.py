"""
Registered Tenants routes for admin tenant management
"""
from flask import Blueprint, request, jsonify, current_app
from models import RegisteredTenantModel
from utils.auth import token_required
from flask_mail import Message
from models import RegisteredTenantModel
# Create blueprint
register_tenants_bp = Blueprint('register_tenants', __name__, url_prefix='/api/register-tenants')

@register_tenants_bp.route('', methods=['POST'])
@token_required
def create_registered_tenant():
    """Create a new registered tenant and send email"""
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        email = data.get('email', '').strip()
        password = data.get('password', '')
        name = data.get('name', '').strip()
        
        if not email or not password:
            return jsonify({'error': 'Email and password are required'}), 400
        if not name:
            return jsonify({'error': 'Tenant name is required'}), 400
        
        # Validate email format
        import re
        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(email_pattern, email):
            return jsonify({'error': 'Invalid email format'}), 400
        
        # Validate password
        if len(password) < 6:
            return jsonify({'error': 'Password must be at least 6 characters long'}), 400
        
        # Get admin user ID from token
        admin_user_id = request.current_user['_id']
        
        # Create registered tenant
        result = RegisteredTenantModel.create_registered_tenant(email, password, name, admin_user_id)
        
        if not result:
            return jsonify({'error': 'Tenant with this email already exists'}), 409
        
        # Send email to the new tenant
        try:
            msg = Message(
                subject="Welcome to MultiTenants AI - Your Account Credentials",
                recipients=[email],
                html=f"""
                <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                    <h2 style="color: #333;">Welcome to MultiTenants AI, {name}!</h2>
                    <p>Hello {name},</p>
                    <p>Your account has been created successfully. Here are your credentials:</p>
                    
                    <div style="background-color: #f5f5f5; padding: 20px; border-radius: 5px; margin: 20px 0;">
                        <h3 style="margin-top: 0;">Your Account Details:</h3>
                        <p><strong>Email:</strong> {email}</p>
                        <p><strong>Password:</strong> {password}</p>
                        <p><strong>Tenant ID:</strong> {result['tenant_id']}</p>
                    </div>
                    
                    <p><strong>Important:</strong> Please keep these credentials safe and secure. You will need them to access your account.</p>
                    
                    <p>You can now log in to your account using these credentials.</p>
                    
                    <p>If you have any questions or need assistance, please don't hesitate to contact our support team.</p>
                    
                    <p>Best regards,<br>MultiTenants AI Team</p>
                </div>
                """
            )
            
            from app import mail
            mail.send(msg)
            
            # Log email for development
            current_app.logger.info(f"Welcome email sent to {email}")
            print(f"Welcome email sent to {email}")
            print(f"Credentials - Email: {email}, Password: {password}, Tenant ID: {result['tenant_id']}")
            
        except Exception as email_error:
            current_app.logger.error(f"Failed to send email: {str(email_error)}")
            # Don't fail the request if email fails, just log it
        
        return jsonify({
            'message': 'Tenant registered successfully and email sent',
            'tenant': {
                'id': result['id'],
                'email': email,
                'tenant_id': result['tenant_id']
            }
        }), 201
        
    except Exception as e:
        current_app.logger.error(f"Create registered tenant error: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

@register_tenants_bp.route('', methods=['GET'])
@token_required
def get_registered_tenants():
    """Get all registered tenants created by current admin"""
    try:
        # Get pagination parameters
        page = int(request.args.get('page', 1))
        limit = int(request.args.get('limit', 10))
        skip = (page - 1) * limit
        
        # Get admin user ID from token
        admin_user_id = request.current_user['_id']
        
        # Get registered tenants
        tenants = RegisteredTenantModel.get_tenants_by_admin(admin_user_id, skip, limit)
        
        # Remove password from response for security
        for tenant in tenants:
            tenant.pop('password', None)
        
        return jsonify({
            'tenants': tenants,
            'page': page,
            'limit': limit,
            'total': len(tenants)
        }), 200
        
    except Exception as e:
        current_app.logger.error(f"Get registered tenants error: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

@register_tenants_bp.route('/<tenant_id>', methods=['DELETE'])
@token_required
def delete_registered_tenant(tenant_id):
    """Delete a registered tenant"""
    try:
        admin_user_id = request.current_user['_id']
        
        # Check if tenant exists and belongs to this admin
        from models import mongo
        from bson import ObjectId
        
        tenant = mongo.db.registered_tenants.find_one({
            'tenant_id': tenant_id,
            'created_by': ObjectId(admin_user_id)
        })
        
        if not tenant:
            return jsonify({'error': 'Tenant not found or unauthorized'}), 404
        
        # Delete the tenant
        result = mongo.db.registered_tenants.delete_one({
            'tenant_id': tenant_id,
            'created_by': ObjectId(admin_user_id)
        })
        
        if result.deleted_count > 0:
            return jsonify({'message': 'Tenant deleted successfully'}), 200
        else:
            return jsonify({'error': 'Failed to delete tenant'}), 500
            
    except Exception as e:
        current_app.logger.error(f"Delete registered tenant error: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

@register_tenants_bp.route('/verify', methods=['POST'])
def verify_tenant_credentials():
    """Verify tenant credentials (public endpoint for tenant login)"""
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        tenant_id = data.get('tenant_id', '').strip()
        password = data.get('password', '')
        
        if not tenant_id or not password:
            return jsonify({'error': 'Tenant ID and password are required'}), 400
        
        # Verify credentials
        is_valid = RegisteredTenantModel.verify_tenant_credentials(tenant_id, password)
        
        if is_valid:
            tenant = RegisteredTenantModel.get_tenant_by_tenant_id(tenant_id)
            return jsonify({
                'valid': True,
                'tenant': {
                    'email': tenant['email'],
                    'tenant_id': tenant['tenant_id'],
                    'status': tenant['status']
                }
            }), 200
        else:
            return jsonify({'valid': False, 'error': 'Invalid credentials'}), 401
            
    except Exception as e:
        current_app.logger.error(f"Verify tenant credentials error: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500