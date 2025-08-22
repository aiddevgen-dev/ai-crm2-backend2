"""
Campaign routes for the multi-tenant CRM application
"""
from flask import Blueprint, request, jsonify, current_app
from models import CampaignModel
from utils.auth import token_required

# Create blueprint
campaign_bp = Blueprint('campaigns', __name__, url_prefix='/api/campaigns')

@campaign_bp.route('', methods=['GET'])
@token_required
def get_campaigns():
    """Get campaigns for current tenant"""
    try:
        # Get pagination parameters
        page = int(request.args.get('page', 1))
        limit = int(request.args.get('limit', 10))
        skip = (page - 1) * limit
        
        # Get tenant_id from token
        tenant_id = request.current_tenant_id
        
        # Get campaigns
        campaigns = CampaignModel.get_campaigns_by_tenant(tenant_id, skip, limit)
        
        return jsonify({
            'campaigns': campaigns,
            'page': page,
            'limit': limit,
            'total': len(campaigns)
        }), 200
        
    except Exception as e:
        current_app.logger.error(f"Get campaigns error: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

@campaign_bp.route('', methods=['POST'])
@token_required
def create_campaign():
    """Create a new campaign"""
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        name = data.get('name', '').strip()
        description = data.get('description', '').strip()
        
        if not name:
            return jsonify({'error': 'Campaign name is required'}), 400
        
        # Get user and tenant info from token
        user_id = request.current_user['_id']
        tenant_id = request.current_tenant_id
        
        # Create campaign
        campaign_id = CampaignModel.create_campaign(name, description, tenant_id, user_id)
        
        if campaign_id:
            return jsonify({
                'message': 'Campaign created successfully',
                'campaign_id': campaign_id
            }), 201
        else:
            return jsonify({'error': 'Failed to create campaign'}), 500
            
    except Exception as e:
        current_app.logger.error(f"Create campaign error: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

@campaign_bp.route('/<campaign_id>', methods=['GET'])
@token_required
def get_campaign(campaign_id):
    """Get specific campaign by ID"""
    try:
        tenant_id = request.current_tenant_id
        
        campaign = CampaignModel.get_campaign_by_id(campaign_id, tenant_id)
        
        if campaign:
            return jsonify({'campaign': campaign}), 200
        else:
            return jsonify({'error': 'Campaign not found'}), 404
            
    except Exception as e:
        current_app.logger.error(f"Get campaign error: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500