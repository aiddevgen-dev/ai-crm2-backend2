"""
Lead routes for the multi-tenant CRM application
"""
from flask import Blueprint, request, jsonify, current_app
from models import LeadModel
from utils.auth import token_required

# Create blueprint
lead_bp = Blueprint('leads', __name__, url_prefix='/api/leads')

@lead_bp.route('', methods=['GET'])
@token_required
def get_leads():
    """Get leads for current tenant"""
    try:
        # Get pagination parameters
        page = int(request.args.get('page', 1))
        limit = int(request.args.get('limit', 10))
        skip = (page - 1) * limit
        
        # Get tenant_id from token
        tenant_id = request.current_tenant_id
        
        # Get leads
        leads = LeadModel.get_leads_by_tenant(tenant_id, skip, limit)
        
        return jsonify({
            'leads': leads,
            'page': page,
            'limit': limit,
            'total': len(leads)
        }), 200
        
    except Exception as e:
        current_app.logger.error(f"Get leads error: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

@lead_bp.route('', methods=['POST'])
@token_required
def create_lead():
    """Create a new lead"""
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        name = data.get('name', '').strip()
        email = data.get('email', '').strip()
        phone = data.get('phone', '').strip()
        campaign_id = data.get('campaign_id')
        
        if not name:
            return jsonify({'error': 'Lead name is required'}), 400
        
        # Basic email validation
        if email and '@' not in email:
            return jsonify({'error': 'Invalid email format'}), 400
        
        # Get user and tenant info from token
        user_id = request.current_user['_id']
        tenant_id = request.current_tenant_id
        
        # Create lead
        lead_id = LeadModel.create_lead(name, email, phone, campaign_id, tenant_id, user_id)
        
        if lead_id:
            return jsonify({
                'message': 'Lead created successfully',
                'lead_id': lead_id
            }), 201
        else:
            return jsonify({'error': 'Failed to create lead'}), 500
            
    except Exception as e:
        current_app.logger.error(f"Create lead error: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500