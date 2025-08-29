"""
Routes for managing Telnyx phone numbers, including searching, ordering, and assignment.
Complete conversion from the provided FastAPI file.
"""
from flask import Blueprint, request, jsonify, current_app
from utils.auth import token_required
from models import mongo # Your existing mongo instance from models.py
from models import RegisteredTenantModel
from services.telnyx_service import TelnyxService # Assuming you have this service file
from bson import ObjectId
from datetime import datetime
import logging
import uuid
import jwt
# Create the Blueprint for Telnyx routes
telnyx_bp = Blueprint('telnyx', __name__, url_prefix='/api/telnyx-numbers')

# 1. GET /search - Search available numbers
@telnyx_bp.route('/search', methods=['GET'])
@token_required
def search_available_numbers():
    """Search for available phone numbers on Telnyx."""
    try:
        area_code = request.args.get('area_code')
        city = request.args.get('city')
        state = request.args.get('state')
        country_code = request.args.get('country_code', 'US')
        number_type = request.args.get('number_type', 'local')
        limit = request.args.get('limit', 10, type=int)
        features = request.args.getlist('features') or ['voice', 'sms']

        result = TelnyxService.search_available_numbers(
            area_code=area_code, city=city, state=state, country_code=country_code,
            number_type=number_type, limit=limit, features=features
        )

        if not result.get("success"):
            return jsonify({"error": f"Failed to search numbers: {result.get('error', 'Unknown error')}"}), 400

        return jsonify({
            "available_numbers": result["numbers"],
            "search_criteria": {
                "area_code": area_code, "city": city, "state": state,
                "country_code": country_code, "number_type": number_type, "features": features
            },
            "count": len(result["numbers"])
        }), 200
    except Exception as e:
        current_app.logger.error(f"Error searching Telnyx numbers: {e}")
        return jsonify({"error": "An internal error occurred"}), 500

# 2. POST /order - Order numbers from Telnyx
@telnyx_bp.route('/order', methods=['POST'])
@token_required
def order_phone_numbers():
    """Order phone numbers from Telnyx and add to tenant inventory."""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No data provided"}), 400

        phone_numbers = data.get('phone_numbers')
        connection_id = data.get('connection_id')
        messaging_profile_id = data.get('messaging_profile_id')

        if not phone_numbers or not isinstance(phone_numbers, list):
            return jsonify({"error": "phone_numbers must be a list"}), 400

        current_user = request.current_user
        tenant_id = current_user.get('tenant_id')
        user_id = current_user['_id']

        existing_numbers = list(mongo.db.telnyx_phone_numbers.find({
            "phone_number": {"$in": phone_numbers},
            "tenant_id": ObjectId(tenant_id)
        }))

        if existing_numbers:
            existing_list = [num["phone_number"] for num in existing_numbers]
            return jsonify({"error": f"Numbers already exist in system: {existing_list}"}), 409

        result = TelnyxService.order_phone_numbers(
            phone_numbers=phone_numbers,
            company_id=str(tenant_id), # Pass tenant_id as company_id
            ordered_by_user_id=str(user_id), # Pass user_id as ordered_by_user_id
            connection_id=data.get('connection_id'),
            messaging_profile_id=data.get('messaging_profile_id')
        )

        if not result.get("success"):
            return jsonify({"error": f"Failed to order numbers: {result.get('error', 'Unknown error')}"}), 400

        return jsonify(result), 200
    except Exception as e:
        current_app.logger.error(f"Error ordering Telnyx numbers: {e}")
        return jsonify({"error": "An internal error occurred"}), 500

# 3. GET / - List tenant's Telnyx numbers
# @telnyx_bp.route('', methods=['GET'])
# @token_required
# def list_telnyx_numbers():
#     """List all Telnyx phone numbers owned by the tenant."""
#     try:
#         current_user = request.current_user
#         current_app.logger.info(f"DEBUG: current_user object in list_telnyx_numbers: {request.current_user}")
#         tenant_id = current_user.get('tenant_id')
#         query = {"company_id": str(tenant_id)}
#         if request.args.get('status'):
#             query["status"] = request.args.get('status')
#         if request.args.get('assigned') is not None:
#             is_assigned = request.args.get('assigned').lower() in ['true', '1']
#             query["assigned_to_user_id"] = {"$ne": None} if is_assigned else None
#         if request.args.get('number_type'):
#             query["number_type"] = request.args.get('number_type')

#         numbers_cursor = mongo.db.telnyx_phone_numbers.find(query).sort("phone_number", 1)
        
#         result = []
#         for number in numbers_cursor:
#             number['_id'] = str(number['_id'])
#             number['tenant_id'] = str(number['tenant_id'])
#             if number.get('assigned_to_user_id'):
#                 user = mongo.db.users.find_one({"_id": ObjectId(number['assigned_to_user_id'])})
#                 number['assigned_to_user_name'] = user.get('email') if user else "Unknown User"
#             result.append(number)

#         return jsonify(result), 200
#     except Exception as e:
#         current_app.logger.error(f"Error listing Telnyx numbers: {e}")
#         return jsonify({"error": "An internal error occurred"}), 500

@telnyx_bp.route('', methods=['GET'])
@token_required
def list_telnyx_numbers():
    """List all Telnyx phone numbers owned by the tenant."""
    try:
        # Manually decode the token to reliably get the tenant_id
        token = request.headers.get('Authorization').split(" ")[1]
        payload = jwt.decode(token, current_app.config['JWT_SECRET_KEY'], algorithms=["HS256"])
        tenant_id_from_token = payload['tenant_id']

        # Use the string ID from the token to query the string field in the DB
        query = {"company_id": tenant_id_from_token}

        numbers_cursor = mongo.db.telnyx_phone_numbers.find(query).sort("phone_number", 1)

        numbers_list = []
        # for number in numbers_cursor:
        #     number['_id'] = str(number['_id'])
        #     numbers_list.append(number)

        for number in numbers_cursor:
            number['_id'] = str(number['_id'])
            # Add this 'if' block to safely convert the user ID to a string
            if number.get('assigned_to_user_id'):
                number['assigned_to_user_id'] = str(number['assigned_to_user_id'])

            # NEW: Add agent information if assigned
            if number.get('assigned_agent_id'):
                agent = mongo.db.agents.find_one({"agent_id": number['assigned_agent_id']})
                if agent:
                    number['assigned_agent_name'] = agent['name']
                    number['assigned_agent_type'] = agent['agent_type']
            numbers_list.append(number)
        return jsonify(numbers_list), 200
    except Exception as e:
        current_app.logger.error(f"Error listing Telnyx numbers: {e}")
        return jsonify({"error": "An internal error occurred"}), 500

# 4. GET /{number_id} - Get specific number details
@telnyx_bp.route('/<number_id>', methods=['GET'])
@token_required
def get_telnyx_number(number_id):
    """Get details of a specific Telnyx phone number."""
    try:
        current_user = request.current_user
        number = mongo.db.telnyx_phone_numbers.find_one({
            "_id": ObjectId(number_id),
            "tenant_id": ObjectId(current_user['tenant_id'])
        })
        if not number:
            return jsonify({"error": "Phone number not found"}), 404
        
        number['_id'] = str(number['_id'])
        number['tenant_id'] = str(number['tenant_id'])
        if number.get('assigned_to_user_id'):
            user = mongo.db.users.find_one({"_id": ObjectId(number['assigned_to_user_id'])})
            number['assigned_to_user_name'] = user.get('email') if user else "Unknown User"

        return jsonify(number), 200
    except Exception as e:
        current_app.logger.error(f"Error getting Telnyx number: {e}")
        return jsonify({"error": "An internal error occurred"}), 500

# 5. POST /{number_id}/assign - Assign to a user
# @telnyx_bp.route('/<number_id>/assign', methods=['POST'])
# @token_required
# def assign_telnyx_number(number_id):
#     """Assign a Telnyx phone number to a user."""
#     try:
#         data = request.get_json()
#         user_id_to_assign = data.get('user_id')
#         if not user_id_to_assign:
#             return jsonify({"error": "user_id must be provided"}), 400

#         current_user = request.current_user
#         tenant_id = current_user.get('tenant_id')

#         number = mongo.db.telnyx_phone_numbers.find_one({
#             "_id": number_id, # The _id in this collection is a string
#             "company_id": str(tenant_id) # Use the correct field name and data type
#         })
#         if not number:
#             return jsonify({"error": "Phone number not found"}), 404

#         admin_id = current_user.get('_id') # Get the logged-in admin's ID
#         current_app.logger.info(f"DEBUG: Attempting to assign to user_id: {user_id_to_assign}")
#         current_app.logger.info(f"DEBUG: Verifying against admin_id (created_by): {admin_id}")

#         target_user = mongo.db.registered_tenants.find_one({
#             "_id": ObjectId(user_id_to_assign),
#             "created_by": ObjectId(admin_id) 
#         })

#         if not target_user:
#             return jsonify({"error": "Target user not found in this tenant"}), 404

#         update_data = {
#             "assigned_to_user_id": ObjectId(user_id_to_assign),
#             "status": "assigned",
#             "updated_at": datetime.utcnow()
#         }
#         mongo.db.telnyx_phone_numbers.update_one({"_id": number_id}, {"$set": update_data})

#         return jsonify({"message": "Phone number assigned successfully"}), 200
#     except Exception as e:
#         current_app.logger.error(f"Error assigning Telnyx number: {e}")
#         return jsonify({"error": "An internal error occurred"}), 500

@telnyx_bp.route('/<number_id>/assign', methods=['POST'])
@token_required
def assign_telnyx_number(number_id):
    """Assign a Telnyx phone number to a user and optionally to an agent."""
    try:
        data = request.get_json()
        user_id_to_assign = data.get('user_id')
        agent_id_to_assign = data.get('agent_id')  # NEW: Optional agent assignment
        
        if not user_id_to_assign:
            return jsonify({"error": "user_id must be provided"}), 400

        current_user = request.current_user
        tenant_id = current_user.get('tenant_id')

        number = mongo.db.telnyx_phone_numbers.find_one({
            "_id": number_id,
            "company_id": str(tenant_id)
        })
        if not number:
            return jsonify({"error": "Phone number not found"}), 404

        admin_id = current_user.get('_id')
        target_user = mongo.db.registered_tenants.find_one({
            "_id": ObjectId(user_id_to_assign),
            "created_by": ObjectId(admin_id) 
        })

        if not target_user:
            return jsonify({"error": "Target user not found in this tenant"}), 404

        # Prepare update data
        update_data = {
            "assigned_to_user_id": ObjectId(user_id_to_assign),
            "status": "assigned",
            "updated_at": datetime.utcnow()
        }

        # NEW: Handle agent assignment if provided
        if agent_id_to_assign:
            # Verify agent exists and belongs to this admin
            agent = mongo.db.agents.find_one({
                "agent_id": agent_id_to_assign,
                "created_by": ObjectId(admin_id)
            })
            
            if agent:
                # Check if agent is already assigned to another phone
                if agent.get('assigned_to_phone_number'):
                    return jsonify({"error": "Agent is already assigned to another phone number"}), 400
                
                # Add agent assignment to phone number
                update_data["assigned_agent_id"] = agent_id_to_assign
                
                # Update agent document to show it's assigned to this phone
                mongo.db.agents.update_one(
                    {"agent_id": agent_id_to_assign},
                    {"$set": {
                        "assigned_to_phone_number": number["phone_number"],
                        "updated_at": datetime.utcnow()
                    }}
                )
            else:
                return jsonify({"error": "Agent not found or unauthorized"}), 404

        # Update phone number with user and optionally agent
        mongo.db.telnyx_phone_numbers.update_one({"_id": number_id}, {"$set": update_data})

        response_message = "Phone number assigned successfully"
        if agent_id_to_assign:
            response_message += " with agent"

        return jsonify({"message": response_message}), 200
        
    except Exception as e:
        current_app.logger.error(f"Error assigning Telnyx number: {e}")
        return jsonify({"error": "An internal error occurred"}), 500

# 6. POST /{number_id}/unassign - Unassign number
@telnyx_bp.route('/<number_id>/unassign', methods=['POST'])
@token_required
def unassign_telnyx_number(number_id):
    """Unassign a Telnyx phone number."""
    try:
        current_user = request.current_user
        number = mongo.db.telnyx_phone_numbers.find_one({
            "_id": ObjectId(number_id),
            "tenant_id": ObjectId(current_user['tenant_id'])
        })
        if not number:
            return jsonify({"error": "Phone number not found"}), 404
        if not number.get("assigned_to_user_id"):
            return jsonify({"error": "Phone number is not currently assigned"}), 400

        update_data = {
            "assigned_to_user_id": None,
            "status": "available",
            "updated_at": datetime.utcnow()
        }
        mongo.db.telnyx_phone_numbers.update_one({"_id": ObjectId(number_id)}, {"$set": update_data})

        return jsonify({"message": "Phone number unassigned successfully"}), 200
    except Exception as e:
        current_app.logger.error(f"Error unassigning Telnyx number: {e}")
        return jsonify({"error": "An internal error occurred"}), 500

# 7. DELETE /{number_id}/release - Release number back to Telnyx
@telnyx_bp.route('/<number_id>/release', methods=['DELETE'])
@token_required
def release_telnyx_number(number_id):
    """Release a Telnyx phone number back to Telnyx."""
    try:
        current_user = request.current_user
        number = mongo.db.telnyx_phone_numbers.find_one({
            "_id": ObjectId(number_id),
            "tenant_id": ObjectId(current_user['tenant_id'])
        })
        if not number:
            return jsonify({"error": "Phone number not found"}), 404
        if number.get("assigned_to_user_id"):
            return jsonify({"error": "Cannot release an assigned number. Please unassign first."}), 400

        result = TelnyxService.release_phone_number(number["telnyx_number_id"])
        if not result.get("success"):
            current_app.logger.warning(f"Failed to release {number['phone_number']} from Telnyx API, but removing from our DB anyway.")

        mongo.db.telnyx_phone_numbers.delete_one({"_id": ObjectId(number_id)})
        
        return jsonify({
            "message": "Phone number released successfully",
            "telnyx_release_success": result.get("success", False)
        }), 200
    except Exception as e:
        current_app.logger.error(f"Error releasing Telnyx number: {e}")
        return jsonify({"error": "An internal error occurred"}), 500

# 8. GET /orders - List order history
# @telnyx_bp.route('/orders', methods=['GET'])
# @token_required
# def list_telnyx_orders():
#     """List all Telnyx number orders for the tenant."""
#     try:
#         current_user = request.current_user
#         current_app.logger.info(f"DEBUG: current_user object in list_telnyx_orders: {request.current_user}")
#         orders_cursor = mongo.db.telnyx_orders.find({
#     "company_id": str(current_user.get('tenant_id'))
# }).sort("ordered_at", -1)
        
#         result = []
#         for order in orders_cursor:
#             order['_id'] = str(order['_id'])
#             order['tenant_id'] = str(order['tenant_id'])
#             if order.get('ordered_by_user_id'):
#                 user = mongo.db.users.find_one({"_id": ObjectId(order['ordered_by_user_id'])})
#                 order['ordered_by_name'] = user.get('email') if user else "Unknown"
#             result.append(order)
        
#         return jsonify(result), 200
#     except Exception as e:
#         current_app.logger.error(f"Error listing Telnyx orders: {e}")
#         return jsonify({"error": "An internal error occurred"}), 500
# routes/telnyx_routes.py

@telnyx_bp.route('/orders', methods=['GET'])
@token_required
def list_telnyx_orders():
    """List all Telnyx number orders for the tenant."""
    try:
        # Manually decode the token to reliably get the tenant_id
        token = request.headers.get('Authorization').split(" ")[1]
        payload = jwt.decode(token, current_app.config['JWT_SECRET_KEY'], algorithms=["HS256"])
        tenant_id_from_token = payload['tenant_id']

        # Use the string ID from the token to query the string field in the DB
        orders_cursor = mongo.db.telnyx_orders.find({
            "company_id": tenant_id_from_token
        }).sort("ordered_at", -1)

        result = []
        for order in orders_cursor:
            order['_id'] = str(order['_id'])
            if order.get('ordered_by_user_id'):
                user = mongo.db.users.find_one({"_id": ObjectId(order['ordered_by_user_id'])})
                order['ordered_by_name'] = user.get('email') if user else "Unknown"
            result.append(order)

        return jsonify(result), 200
    except Exception as e:
        current_app.logger.error(f"Error listing Telnyx orders: {e}")
        return jsonify({"error": "An internal error occurred"}), 500

# 9. GET /{number_id}/telnyx-sync - Sync with Telnyx data
@telnyx_bp.route('/<number_id>/telnyx-sync', methods=['GET'])
@token_required
def sync_with_telnyx(number_id):
    """Sync phone number data with Telnyx."""
    try:
        current_user = request.current_user
        number = mongo.db.telnyx_phone_numbers.find_one({
            "_id": ObjectId(number_id),
            "tenant_id": ObjectId(current_user['tenant_id'])
        })
        if not number:
            return jsonify({"error": "Phone number not found"}), 404

        result = TelnyxService.get_number_details(number["telnyx_number_id"])
        if not result.get("success"):
            return jsonify({"error": f"Failed to sync with Telnyx: {result.get('error')}"}), 400

        telnyx_data = result["number_data"]
        update_data = {
            "telnyx_metadata": telnyx_data,
            "updated_at": datetime.utcnow()
        }
        if "monthly_cost" in telnyx_data:
            update_data["monthly_cost"] = float(telnyx_data["monthly_cost"])

        mongo.db.telnyx_phone_numbers.update_one({"_id": ObjectId(number_id)}, {"$set": update_data})

        return jsonify({
            "message": "Successfully synced with Telnyx",
            "last_synced": datetime.utcnow().isoformat()
        }), 200
    except Exception as e:
        current_app.logger.error(f"Error syncing with Telnyx: {e}")
        return jsonify({"error": "An internal error occurred"}), 500
