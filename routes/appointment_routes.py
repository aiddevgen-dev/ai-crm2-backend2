"""
Appointment routes for the multi-tenant CRM application
"""
from flask import Blueprint, request, jsonify, current_app
from models import AppointmentModel
from utils.auth import token_required
from datetime import datetime

# Create blueprint
appointment_bp = Blueprint('appointments', __name__, url_prefix='/api/appointments')

@appointment_bp.route('', methods=['GET'])
@token_required
def get_appointments():
    """Get appointments for current tenant"""
    try:
        # Get pagination parameters
        page = int(request.args.get('page', 1))
        limit = int(request.args.get('limit', 10))
        skip = (page - 1) * limit
        
        # Get tenant_id from token
        tenant_id = request.current_tenant_id
        
        # Get appointments
        appointments = AppointmentModel.get_appointments_by_tenant(tenant_id, skip, limit)
        
        return jsonify({
            'appointments': appointments,
            'page': page,
            'limit': limit,
            'total': len(appointments)
        }), 200
        
    except Exception as e:
        current_app.logger.error(f"Get appointments error: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

@appointment_bp.route('', methods=['POST'])
@token_required
def create_appointment():
    """Create a new appointment"""
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        title = data.get('title', '').strip()
        description = data.get('description', '').strip()
        lead_id = data.get('lead_id')
        scheduled_at_str = data.get('scheduled_at')
        
        if not title:
            return jsonify({'error': 'Appointment title is required'}), 400
        
        if not scheduled_at_str:
            return jsonify({'error': 'Scheduled time is required'}), 400
        
        # Parse scheduled_at
        try:
            scheduled_at = datetime.fromisoformat(scheduled_at_str.replace('Z', '+00:00'))
        except ValueError:
            return jsonify({'error': 'Invalid date format'}), 400
        
        # Get user and tenant info from token
        user_id = request.current_user['_id']
        tenant_id = request.current_tenant_id
        
        # Create appointment
        appointment_id = AppointmentModel.create_appointment(
            title, description, lead_id, scheduled_at, tenant_id, user_id
        )
        
        if appointment_id:
            return jsonify({
                'message': 'Appointment created successfully',
                'appointment_id': appointment_id
            }), 201
        else:
            return jsonify({'error': 'Failed to create appointment'}), 500
            
    except Exception as e:
        current_app.logger.error(f"Create appointment error: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500