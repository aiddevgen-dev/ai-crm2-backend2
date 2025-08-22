"""
Recording routes for the multi-tenant CRM application
"""
from flask import Blueprint, request, jsonify, current_app
from models import RecordingModel
from utils.auth import token_required

# Create blueprint
recording_bp = Blueprint('recordings', __name__, url_prefix='/api/recordings')

@recording_bp.route('', methods=['GET'])
@token_required
def get_recordings():
    """Get recordings for current tenant"""
    try:
        page = int(request.args.get('page', 1))
        limit = int(request.args.get('limit', 10))
        skip = (page - 1) * limit
        
        tenant_id = request.current_tenant_id
        recordings = RecordingModel.get_recordings_by_tenant(tenant_id, skip, limit)
        
        return jsonify({
            'recordings': recordings,
            'page': page,
            'limit': limit,
            'total': len(recordings)
        }), 200
        
    except Exception as e:
        current_app.logger.error(f"Get recordings error: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

@recording_bp.route('', methods=['POST'])
@token_required
def create_recording():
    """Create a new recording"""
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        title = data.get('title', '').strip()
        file_path = data.get('file_path', '').strip()
        duration = data.get('duration', 0)
        appointment_id = data.get('appointment_id')
        
        if not title:
            return jsonify({'error': 'Recording title is required'}), 400
        
        if not file_path:
            return jsonify({'error': 'File path is required'}), 400
        
        user_id = request.current_user['_id']
        tenant_id = request.current_tenant_id
        
        recording_id = RecordingModel.create_recording(
            title, file_path, duration, appointment_id, tenant_id, user_id
        )
        
        if recording_id:
            return jsonify({
                'message': 'Recording created successfully',
                'recording_id': recording_id
            }), 201
        else:
            return jsonify({'error': 'Failed to create recording'}), 500
            
    except Exception as e:
        current_app.logger.error(f"Create recording error: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500