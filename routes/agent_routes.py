# Backend Route - agents_routes.py
"""
Routes for managing AI Agents - creation, assignment to phone numbers, and tool management
"""
from flask import Blueprint, request, jsonify, current_app
from utils.auth import token_required
from models import mongo
from bson import ObjectId
from datetime import datetime
import uuid

# Create the Blueprint for Agent routes
agents_bp = Blueprint('agents', __name__, url_prefix='/api/agents')

# Available tools that can be assigned to agents
AVAILABLE_TOOLS = [
    {"id": "calendar_scheduling", "name": "Calendar Scheduling", "description": "Schedule appointments and manage calendar"},
    {"id": "crm_integration", "name": "CRM Integration", "description": "Create and update customer records"},
    {"id": "payment_processing", "name": "Payment Processing", "description": "Handle payment collection and invoicing"},
    {"id": "document_generation", "name": "Document Generation", "description": "Generate quotes, contracts, and reports"},
    {"id": "email_notifications", "name": "Email Notifications", "description": "Send automated email notifications"},
    {"id": "sms_messaging", "name": "SMS Messaging", "description": "Send SMS updates and reminders"},
    {"id": "inventory_management", "name": "Inventory Management", "description": "Track and manage inventory items"},
    {"id": "lead_qualification", "name": "Lead Qualification", "description": "Qualify and score incoming leads"},
    {"id": "call_recording", "name": "Call Recording", "description": "Record and transcribe phone conversations"},
    {"id": "data_analytics", "name": "Data Analytics", "description": "Generate reports and analytics"},
]

@agents_bp.route('/tools', methods=['GET'])
@token_required
def get_available_tools():
    """Get list of available tools that can be assigned to agents"""
    return jsonify({"tools": AVAILABLE_TOOLS}), 200

@agents_bp.route('', methods=['POST'])
@token_required
def create_agent():
    """Create a new AI agent"""
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        name = data.get('name', '').strip()
        description = data.get('description', '').strip()
        system_prompt = data.get('system_prompt', '').strip()
        assigned_tools = data.get('assigned_tools', [])
        agent_type = data.get('agent_type', 'general')  # general, sales, support, etc.
        
        # Validation
        if not name:
            return jsonify({'error': 'Agent name is required'}), 400
        if not system_prompt:
            return jsonify({'error': 'System prompt is required'}), 400
        if not assigned_tools or not isinstance(assigned_tools, list):
            return jsonify({'error': 'At least one tool must be assigned'}), 400
        
        # Validate tools exist
        tool_ids = [tool['id'] for tool in AVAILABLE_TOOLS]
        invalid_tools = [tool for tool in assigned_tools if tool not in tool_ids]
        if invalid_tools:
            return jsonify({'error': f'Invalid tools: {invalid_tools}'}), 400
        
        # Get admin user info
        current_user = request.current_user
        admin_user_id = current_user['_id']
        tenant_id = current_user.get('tenant_id')
        
        # Generate agent ID
        agent_id = str(uuid.uuid4())
        
        # Create agent document
        agent_doc = {
            "agent_id": agent_id,
            "name": name,
            "description": description,
            "system_prompt": system_prompt,
            "assigned_tools": assigned_tools,
            "agent_type": agent_type,
            "status": "active",
            "created_by": ObjectId(admin_user_id),
            "tenant_id": tenant_id,
            "assigned_to_phone_number": None,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        }
        
        # Insert into database
        result = mongo.db.agents.insert_one(agent_doc)
        
        # Return response
        return jsonify({
            'message': 'Agent created successfully',
            'agent': {
                'id': str(result.inserted_id),
                'agent_id': agent_id,
                'name': name,
                'description': description,
                'agent_type': agent_type,
                'status': 'active',
                'assigned_tools': assigned_tools,
                'created_at': agent_doc['created_at'].isoformat()
            }
        }), 201
        
    except Exception as e:
        current_app.logger.error(f"Create agent error: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

@agents_bp.route('', methods=['GET'])
@token_required
def get_agents():
    """Get all agents created by current admin"""
    try:
        # Get admin user ID from token
        admin_user_id = request.current_user['_id']
        
        # Get pagination parameters
        page = int(request.args.get('page', 1))
        limit = int(request.args.get('limit', 20))
        skip = (page - 1) * limit
        
        # Query agents created by this admin
        agents_cursor = mongo.db.agents.find({
            "created_by": ObjectId(admin_user_id)
        }).sort("created_at", -1).skip(skip).limit(limit)
        
        agents = []
        for agent in agents_cursor:
            agent_data = {
                'id': str(agent['_id']),
                'agent_id': agent['agent_id'],
                'name': agent['name'],
                'description': agent['description'],
                'system_prompt': agent['system_prompt'],
                'assigned_tools': agent['assigned_tools'],
                'agent_type': agent['agent_type'],
                'status': agent['status'],
                'assigned_to_phone_number': agent.get('assigned_to_phone_number'),
                'created_at': agent['created_at'].isoformat(),
                'updated_at': agent['updated_at'].isoformat()
            }
            
            # Get phone number details if assigned
            if agent.get('assigned_to_phone_number'):
                phone_doc = mongo.db.telnyx_phone_numbers.find_one({
                    "phone_number": agent['assigned_to_phone_number']
                })
                if phone_doc:
                    agent_data['phone_number_details'] = {
                        'phone_number': phone_doc['phone_number'],
                        'status': phone_doc['status']
                    }
            
            agents.append(agent_data)
        
        # Get total count
        total = mongo.db.agents.count_documents({"created_by": ObjectId(admin_user_id)})
        
        return jsonify({
            'agents': agents,
            'pagination': {
                'page': page,
                'limit': limit,
                'total': total,
                'has_more': skip + len(agents) < total
            }
        }), 200
        
    except Exception as e:
        current_app.logger.error(f"Get agents error: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

@agents_bp.route('/<agent_id>', methods=['PUT'])
@token_required
def update_agent(agent_id):
    """Update an existing agent"""
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        admin_user_id = request.current_user['_id']
        
        # Check if agent exists and belongs to this admin
        agent = mongo.db.agents.find_one({
            "agent_id": agent_id,
            "created_by": ObjectId(admin_user_id)
        })
        
        if not agent:
            return jsonify({'error': 'Agent not found or unauthorized'}), 404
        
        # Prepare update data
        update_data = {"updated_at": datetime.utcnow()}
        
        if 'name' in data:
            update_data['name'] = data['name'].strip()
        if 'description' in data:
            update_data['description'] = data['description'].strip()
        if 'system_prompt' in data:
            update_data['system_prompt'] = data['system_prompt'].strip()
        if 'assigned_tools' in data:
            # Validate tools
            tool_ids = [tool['id'] for tool in AVAILABLE_TOOLS]
            invalid_tools = [tool for tool in data['assigned_tools'] if tool not in tool_ids]
            if invalid_tools:
                return jsonify({'error': f'Invalid tools: {invalid_tools}'}), 400
            update_data['assigned_tools'] = data['assigned_tools']
        if 'agent_type' in data:
            update_data['agent_type'] = data['agent_type']
        if 'status' in data:
            update_data['status'] = data['status']
        
        # Update agent
        result = mongo.db.agents.update_one(
            {"agent_id": agent_id, "created_by": ObjectId(admin_user_id)},
            {"$set": update_data}
        )
        
        if result.modified_count > 0:
            return jsonify({'message': 'Agent updated successfully'}), 200
        else:
            return jsonify({'message': 'No changes made'}), 200
            
    except Exception as e:
        current_app.logger.error(f"Update agent error: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

@agents_bp.route('/<agent_id>', methods=['DELETE'])
@token_required
def delete_agent(agent_id):
    """Delete an agent"""
    try:
        admin_user_id = request.current_user['_id']
        
        # Check if agent exists and belongs to this admin
        agent = mongo.db.agents.find_one({
            "agent_id": agent_id,
            "created_by": ObjectId(admin_user_id)
        })
        
        if not agent:
            return jsonify({'error': 'Agent not found or unauthorized'}), 404
        
        # Check if agent is assigned to a phone number
        if agent.get('assigned_to_phone_number'):
            # Unassign from phone number first
            mongo.db.telnyx_phone_numbers.update_one(
                {"phone_number": agent['assigned_to_phone_number']},
                {"$unset": {"assigned_agent_id": ""}}
            )
        
        # Delete the agent
        result = mongo.db.agents.delete_one({
            "agent_id": agent_id,
            "created_by": ObjectId(admin_user_id)
        })
        
        if result.deleted_count > 0:
            return jsonify({'message': 'Agent deleted successfully'}), 200
        else:
            return jsonify({'error': 'Failed to delete agent'}), 500
            
    except Exception as e:
        current_app.logger.error(f"Delete agent error: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

@agents_bp.route('/<agent_id>/assign-phone', methods=['POST'])
@token_required
def assign_agent_to_phone(agent_id):
    """Assign an agent to a phone number"""
    try:
        data = request.get_json()
        phone_number = data.get('phone_number')
        
        if not phone_number:
            return jsonify({'error': 'phone_number is required'}), 400
        
        admin_user_id = request.current_user['_id']
        tenant_id = request.current_user.get('tenant_id')
        
        # Check if agent exists and belongs to this admin
        agent = mongo.db.agents.find_one({
            "agent_id": agent_id,
            "created_by": ObjectId(admin_user_id)
        })
        
        if not agent:
            return jsonify({'error': 'Agent not found or unauthorized'}), 404
        
        # Check if phone number exists and belongs to this tenant
        phone_doc = mongo.db.telnyx_phone_numbers.find_one({
            "phone_number": phone_number,
            "company_id": str(tenant_id)
        })
        
        if not phone_doc:
            return jsonify({'error': 'Phone number not found or unauthorized'}), 404
        
        # Check if phone number already has an agent assigned
        if phone_doc.get('assigned_agent_id'):
            return jsonify({'error': 'Phone number already has an agent assigned'}), 400
        
        # Update phone number with agent assignment
        mongo.db.telnyx_phone_numbers.update_one(
            {"phone_number": phone_number},
            {"$set": {
                "assigned_agent_id": agent_id,
                "updated_at": datetime.utcnow()
            }}
        )
        
        # Update agent with phone number assignment
        mongo.db.agents.update_one(
            {"agent_id": agent_id},
            {"$set": {
                "assigned_to_phone_number": phone_number,
                "updated_at": datetime.utcnow()
            }}
        )
        
        return jsonify({'message': 'Agent assigned to phone number successfully'}), 200
        
    except Exception as e:
        current_app.logger.error(f"Assign agent to phone error: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

@agents_bp.route('/<agent_id>/unassign-phone', methods=['POST'])
@token_required
def unassign_agent_from_phone(agent_id):
    """Unassign an agent from a phone number"""
    try:
        admin_user_id = request.current_user['_id']
        
        # Check if agent exists and belongs to this admin
        agent = mongo.db.agents.find_one({
            "agent_id": agent_id,
            "created_by": ObjectId(admin_user_id)
        })
        
        if not agent:
            return jsonify({'error': 'Agent not found or unauthorized'}), 404
        
        phone_number = agent.get('assigned_to_phone_number')
        if not phone_number:
            return jsonify({'error': 'Agent is not assigned to any phone number'}), 400
        
        # Remove agent assignment from phone number
        mongo.db.telnyx_phone_numbers.update_one(
            {"phone_number": phone_number},
            {
                "$unset": {"assigned_agent_id": ""},
                "$set": {"updated_at": datetime.utcnow()}
            }
        )
        
        # Remove phone number assignment from agent
        mongo.db.agents.update_one(
            {"agent_id": agent_id},
            {
                "$unset": {"assigned_to_phone_number": ""},
                "$set": {"updated_at": datetime.utcnow()}
            }
        )
        
        return jsonify({'message': 'Agent unassigned from phone number successfully'}), 200
        
    except Exception as e:
        current_app.logger.error(f"Unassign agent from phone error: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

# Route to get available phone numbers for assignment
@agents_bp.route('/available-phones', methods=['GET'])
@token_required
def get_available_phones():
    """Get phone numbers that can have agents assigned"""
    try:
        tenant_id = request.current_user.get('tenant_id')
        
        # Get phone numbers belonging to this tenant that don't have agents assigned
        phones_cursor = mongo.db.telnyx_phone_numbers.find({
            "company_id": str(tenant_id),
            "assigned_agent_id": {"$exists": False}
        })
        
        available_phones = []
        for phone in phones_cursor:
            available_phones.append({
                'phone_number': phone['phone_number'],
                'status': phone['status'],
                'assigned_to_user_id': str(phone.get('assigned_to_user_id', ''))
            })
        
        return jsonify({'available_phones': available_phones}), 200
        
    except Exception as e:
        current_app.logger.error(f"Get available phones error: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500