"""
Routes for authenticated tenants/users to view their assigned numbers and message history.
This is a complete and corrected conversion from the provided FastAPI file.
"""
import os
import logging
import re
from datetime import datetime
from flask import Blueprint, request, jsonify, current_app
from utils.auth import token_required  # Your existing decorator for user auth
from models import mongo
from bson import ObjectId
from pymongo.errors import PyMongoError
from utils.auth import tenant_token_required # Import our new decorator
import requests
# Create the Blueprint for tenant-facing number routes
# Using a distinct name to avoid conflicts
tenant_user_bp = Blueprint('tenant_user', __name__, url_prefix='/api/user')
def extract_transcript_from_call(call_doc):
    """Extract transcript from call events"""
    if not call_doc.get('events'):
        return ""
    
    transcript_parts = []
    for event in call_doc['events']:
        if (event.get('event_type') == 'telnyx_status' and 
            event.get('payload', {}).get('Transcript')):
            transcript_text = event['payload']['Transcript'].strip()
            if transcript_text:  # Only add non-empty transcripts
                transcript_parts.append(transcript_text)
    
    return ' '.join(transcript_parts)
def _normalize_phone_e164(raw: str) -> str:
    """Helper function to normalize phone number to E.164 format."""
    if not raw:
        return ""
    s = re.sub(r"[ \-()]", "", raw)
    if s.startswith("00"):
        s = "+" + s[2:]
    elif not s.startswith("+"):
        # Assume US number if no country code
        s = "+1" + s
    return s

# Add this route to your tenant_user_routes.py
@tenant_user_bp.route('/calls/by-number', methods=['GET'])
@tenant_token_required
def get_calls_by_phone_number():
    try:
        phone_number = request.args.get('phone_number')
        if not phone_number:
            return jsonify({"error": "phone_number query parameter is required"}), 400

        current_tenant_payload = request.current_tenant
        tenant_email = current_tenant_payload.get('tenant_email')

        # Find current user by email
        user_doc = mongo.db.registered_tenants.find_one({"email": tenant_email})
        # Add this debug logging in your /calls/by-number route after finding user_doc:
        current_app.logger.info(f"User doc: {user_doc}")
        current_app.logger.info(f"Looking for phone: {phone_number}")
        number_doc = mongo.db.telnyx_phone_numbers.find_one({
            "phone_number": phone_number,
            "assigned_to_user_id": user_doc["_id"]
        })
        current_app.logger.info(f"Number doc found: {number_doc}")
        if not user_doc:
            return jsonify({"error": "User not found"}), 404

        # Check if phone number is assigned to this user
        number_doc = mongo.db.telnyx_phone_numbers.find_one({
            "phone_number": phone_number,
            "assigned_to_user_id": user_doc["_id"]  # Direct assignment check
        })
        
        if not number_doc:
            return jsonify({"error": "You do not have permission to view calls for this number"}), 403

        # Build query and execute
        query = {"$or": [{"from": phone_number}, {"to": phone_number}]}
        limit = min(int(request.args.get('limit', 100)), 1000)
        skip = int(request.args.get('skip', 0))
        
        total_count = mongo.db.calls.count_documents(query)
        cursor = mongo.db.calls.find(query).sort("created_at", -1).skip(skip).limit(limit)
        result = [dict(call, id=str(call.pop("_id"))) for call in cursor]
        for call in cursor:
            call_dict = dict(call)
            call_dict["id"] = str(call.pop("_id"))
            
            # ADD: Extract and include transcript
            call_dict["transcript"] = extract_transcript_from_call(call)
            
            result.append(call_dict)
        return jsonify({
            "calls": result,
            "pagination": {
                "total_count": total_count,
                "returned_count": len(result),
                "skip": skip,
                "limit": limit,
                "has_more": skip + len(result) < total_count
            }
        }), 200
        
    except Exception as e:
        current_app.logger.error(f"Error in get_calls_by_phone_number: {e}", exc_info=True)
        return jsonify({"error": f"Internal server error: {str(e)}"}), 500

# @tenant_user_bp.route('/calls/by-number', methods=['GET'])
# @tenant_token_required
# def get_calls_by_phone_number():
#     """Get call records for a specific phone number with filters and pagination."""
#     try:
#         phone_number = request.args.get('phone_number')
#         if not phone_number:
#             return jsonify({"error": "phone_number query parameter is required"}), 400

#         current_user = request.current_user
        
#         # Security Check: Ensure the user has access to this number
#         if not mongo.db.telnyx_phone_numbers.find_one({
#             "phone_number": phone_number,
#             "tenant_id": ObjectId(current_user['tenant_id']),
#             "assigned_to_user_id": ObjectId(current_user['_id'])
#         }):
#             return jsonify({"error": "You do not have permission to view calls for this number"}), 403

#         # Create multiple search variations
#         search_numbers = [
#             phone_number.strip(),  # Original
#             phone_number.strip().replace(" ", "").replace("-", "").replace("(", "").replace(")", ""),  # Clean
#         ]
        
#         # Add +1 version if it looks like US number
#         clean_num = phone_number.strip().replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
#         if len(clean_num) == 10 and clean_num.isdigit():
#             search_numbers.append("+1" + clean_num)
#         elif len(clean_num) == 11 and clean_num.startswith("1"):
#             search_numbers.append("+" + clean_num)
        
#         # If it doesn't start with +, try adding +
#         if not clean_num.startswith("+") and clean_num.isdigit():
#             search_numbers.append("+" + clean_num)
        
#         # Remove duplicates
#         search_numbers = list(set(search_numbers))
        
#         # Build base query for phone number
#         query = {"$or": []}
        
#         # Add all variations to the query
#         for num in search_numbers:
#             query["$or"].extend([
#                 {"from": num},
#                 {"to": num}
#             ])
        
#         # Get filter parameters
#         direction = request.args.get('direction')
#         call_status = request.args.get('call_status')
#         hangup_source = request.args.get('hangup_source')
#         from_date = request.args.get('from_date')
#         to_date = request.args.get('to_date')
#         min_duration = request.args.get('min_duration', type=int)
#         max_duration = request.args.get('max_duration', type=int)
#         limit = min(int(request.args.get('limit', 100)), 1000)
#         skip = int(request.args.get('skip', 0))
        
#         # Add filters
#         if direction:
#             # Check in events array for direction
#             query["events"] = {
#                 "$elemMatch": {
#                     "payload.direction": direction
#                 }
#             }
        
#         if call_status:
#             query["last_status"] = call_status
        
#         if hangup_source:
#             query["hangup_source"] = hangup_source
        
#         # Add date range filter
#         if from_date or to_date:
#             date_filter = {}
#             try:
#                 if from_date:
#                     from_dt = datetime.fromisoformat(from_date.replace("Z", "+00:00"))
#                     date_filter["$gte"] = from_dt
#                 if to_date:
#                     to_dt = datetime.fromisoformat(to_date.replace("Z", "+00:00"))
#                     date_filter["$lte"] = to_dt
                
#                 if date_filter:
#                     query["created_at"] = date_filter
                    
#             except ValueError:
#                 return jsonify({"error": "Invalid date format. Use ISO-8601, e.g. 2025-08-26T00:00:00Z"}), 422
        
#         # Add duration filters
#         if min_duration is not None or max_duration is not None:
#             duration_conditions = [
#                 {"$ne": ["$duration", None]},
#                 {"$ne": ["$duration", ""]},
#             ]
            
#             if min_duration is not None:
#                 duration_conditions.append({
#                     "$gte": [{"$toInt": {"$ifNull": ["$duration", "0"]}}, min_duration]
#                 })
#             if max_duration is not None:
#                 duration_conditions.append({
#                     "$lte": [{"$toInt": {"$ifNull": ["$duration", "0"]}}, max_duration]
#                 })
            
#             query["$expr"] = {"$and": duration_conditions}
        
#         # Log what we're searching for
#         current_app.logger.info(f"Searching for phone numbers: {search_numbers}")
        
#         # Get total count for pagination
#         total_count = mongo.db.calls.count_documents(query)
        
#         # Execute query with pagination and sorting
#         cursor = mongo.db.calls.find(query).sort("created_at", -1).skip(skip).limit(limit)
#         calls = list(cursor)
        
#         # Transform results
#         result = []
#         for call in calls:
#             call_dict = dict(call)
#             call_dict["id"] = str(call["_id"])
#             call_dict.pop("_id", None)
#             result.append(call_dict)
        
#         return jsonify({
#             "calls": result,
#             "pagination": {
#                 "total_count": total_count,
#                 "returned_count": len(result),
#                 "skip": skip,
#                 "limit": limit,
#                 "has_more": skip + len(result) < total_count
#             },
#             "filters_applied": {
#                 "phone_number": phone_number,
#                 "searched_variations": search_numbers,
#                 "direction": direction,
#                 "call_status": call_status,
#                 "hangup_source": hangup_source,
#                 "from_date": from_date,
#                 "to_date": to_date,
#                 "min_duration": min_duration,
#                 "max_duration": max_duration
#             }
#         }), 200
        
#     except Exception as e:
#         current_app.logger.error(f"Error in get_calls_by_phone_number: {e}")
#         return jsonify({"error": f"Internal server error: {str(e)}"}), 500


# @tenant_user_bp.route('/recordings/<call_session_id>', methods=['GET'])
# @tenant_token_required  # CHANGE FROM @token_required
# def get_call_recording(call_session_id):
#     """Get call recording details from Telnyx API"""
#     try:
#         current_tenant_payload = request.current_tenant  # ADD THIS LINE
#         tenant_email = current_tenant_payload.get('tenant_email')  # ADD THIS LINE
        
#         # Find current user by email - ADD THESE LINES
#         user_doc = mongo.db.registered_tenants.find_one({"email": tenant_email})
#         if not user_doc:
#             return jsonify({"error": "User not found"}), 404
            
#         import requests
#         import os
        
#         # Get Telnyx API key from environment
#         telnyx_api_key = os.getenv('TELNYX_API_KEY')
#         if not telnyx_api_key:
#             return jsonify({"error": "Telnyx API key not configured"}), 500
        
#         # Call Telnyx API
#         url = f"https://api.telnyx.com/v2/recordings?filter[call_session_id]={call_session_id}"
#         headers = {
#             "Authorization": f"Bearer {telnyx_api_key}",
#             "Content-Type": "application/json"
#         }
        
#         response = requests.get(url, headers=headers)
        
#         if response.status_code == 200:
#             return jsonify(response.json())
#         else:
#             current_app.logger.error(f"Telnyx API error: {response.status_code} - {response.text}")
#             return jsonify({"error": "Failed to fetch recording from Telnyx"}), response.status_code
            
#     except Exception as e:
#         current_app.logger.error(f"Error fetching recording: {e}")
#         return jsonify({"error": f"Internal server error: {str(e)}"}), 500

@tenant_user_bp.route('/recordings/<call_session_id>', methods=['GET'])
@tenant_token_required
def get_call_recording(call_session_id):
    try:
        # Get call from database
        call_doc = mongo.db.calls.find_one({"call_key": call_session_id})
        if not call_doc:
            return jsonify({"error": "Call not found"}), 404
        
        # Get Telnyx API key
        telnyx_api_key = os.getenv('TELNYX_API_KEY')
        if not telnyx_api_key:
            return jsonify({"error": "Telnyx API key not configured"}), 500
        
        headers = {"Authorization": f"Bearer {telnyx_api_key}"}
        
        # Get all recent recordings
        response = requests.get("https://api.telnyx.com/v2/recordings", headers=headers)
        if response.status_code != 200:
            return jsonify({"error": "Failed to fetch recordings"}), 500
        
        recordings = response.json().get('data', [])
        
        # Match by phone numbers and time proximity
        call_time = datetime.fromisoformat(call_doc['created_at'].replace('Z', '+00:00'))
        call_from = call_doc['from']
        call_to = call_doc['to']
        
        for recording in recordings:
            rec_time = datetime.fromisoformat(recording['created_at'].replace('Z', '+00:00'))
            time_diff = abs((call_time - rec_time).total_seconds())
            
            # Match if same numbers and within 2 minutes
            if (recording['from'] == call_from and 
                recording['to'] == call_to and 
                time_diff <= 120):
                return jsonify({"data": [recording]})
        
        return jsonify({"data": []})
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500
# GET /api/user/my-numbers  helloABC
# @tenant_user_bp.route('/my-numbers', methods=['GET'])
# @token_required
# def get_my_assigned_numbers():
#     """Get all phone numbers assigned to the current logged-in user."""
#     try:
#         current_user = request.current_user
#         query = {
#             # In your schema, this is likely tenant_id, not company_id
#             "tenant_id": ObjectId(current_user['tenant_id']),
#             "assigned_to_user_id": ObjectId(current_user['_id'])
#         }

#         if request.args.get('status'):
#             query["status"] = request.args.get('status')

#         numbers_cursor = mongo.db.telnyx_phone_numbers.find(query).sort("phone_number", 1)
        
#         result = []
#         for number in numbers_cursor:
#             number['_id'] = str(number['_id'])
#             number['tenant_id'] = str(number['tenant_id'])
#             number['assigned_to_user_id'] = str(number['assigned_to_user_id'])
#             # Use the user's email from the token as the name
#             number['assigned_to_user_name'] = current_user.get('email', 'N/A')
#             result.append(number)
            
#         return jsonify(result), 200
#     except PyMongoError as e:
#         current_app.logger.error(f"Database error in /my-numbers: {e}")
#         return jsonify({"error": "Database error occurred"}), 500
#     except Exception as e:
#         current_app.logger.exception("Unexpected error in /my-numbers")
#         return jsonify({"error": "An unexpected server error occurred"}), 500

@tenant_user_bp.route('/my-numbers', methods=['GET'])
@tenant_token_required
def get_tenant_numbers():
    """
    Dynamically finds a user by the email in the token, then finds phone numbers
    assigned to that user's ID.
    """
    try:
        current_tenant_payload = request.current_tenant
        tenant_email = current_tenant_payload.get('tenant_email')

        if not tenant_email:
            return jsonify({"error": "Tenant email not found in token"}), 400

        # --- DYNAMIC 2-STEP LOOKUP ---
        # Step 1: Find the user/tenant in the 'users' collection by their email.
        # This assumes your main user/tenant records are in a 'users' collection.
        user_doc = mongo.db.registered_tenants.find_one({"email": tenant_email})

        if not user_doc:
            return jsonify({"error": f"No user found for email: {tenant_email}"}), 404
        
        # Step 2: Get the correct ID from the user document.
        correct_user_id = user_doc['_id']
        # --- END DYNAMIC LOGIC ---

        # Step 3: Use the user's ID to find phone numbers assigned to them.
        query = {
            "assigned_to_user_id": ObjectId(correct_user_id)
        }

        numbers_cursor = mongo.db.telnyx_phone_numbers.find(query).sort("phone_number", 1)
        
        result = []
        for number in numbers_cursor:
            number['_id'] = str(number['_id'])
            number['tenant_id'] = str(number.get('company_id'))
            if 'assigned_to_user_id' in number and number['assigned_to_user_id']:
                number['assigned_to_user_id'] = str(number['assigned_to_user_id'])
            result.append(number)
            
        return jsonify(result), 200

    except Exception as e:
        current_app.logger.error(f"Error in get_tenant_numbers: {e}", exc_info=True)
        return jsonify({"error": "An unexpected server error occurred"}), 500


# GET /api/user/my-numbers/<number_id>
@tenant_user_bp.route('/my-numbers/<number_id>', methods=['GET'])
@tenant_token_required
def get_my_assigned_number_details(number_id):
    """Get details of a specific phone number assigned to the current user."""
    try:
        current_user = request.current_user
        number = mongo.db.telnyx_phone_numbers.find_one({
            "_id": ObjectId(number_id),
            "tenant_id": ObjectId(current_user['tenant_id']),
            "assigned_to_user_id": ObjectId(current_user['_id'])
        })

        if not number:
            return jsonify({"error": "Phone number not found or not assigned to you"}), 404

        number['_id'] = str(number['_id'])
        number['tenant_id'] = str(number['tenant_id'])
        number['assigned_to_user_id'] = str(number['assigned_to_user_id'])
        number['assigned_to_user_name'] = current_user.get('email', 'N/A')

        return jsonify(number), 200
    except PyMongoError as e:
        current_app.logger.error(f"Database error in /my-numbers/{number_id}: {e}")
        return jsonify({"error": "Database error occurred"}), 500
    except Exception as e:
        current_app.logger.exception(f"Unexpected error in /my-numbers/{number_id}")
        return jsonify({"error": "An unexpected server error occurred"}), 500

# GET /api/user/by-number
@tenant_user_bp.route('/by-number', methods=['GET'])
@tenant_token_required
def get_messages_by_phone_number():
    try:
        phone_number = request.args.get('phone_number')
        if not phone_number:
            return jsonify({"error": "phone_number query parameter is required"}), 400

        # FIX: Use current_tenant, not current_user
        current_tenant_payload = request.current_tenant
        tenant_email = current_tenant_payload.get('tenant_email')

        # Find current user by email  
        user_doc = mongo.db.registered_tenants.find_one({"email": tenant_email})
        if not user_doc:
            return jsonify({"error": "User not found"}), 404

        # Debug logging
        current_app.logger.info(f"Looking for phone: {phone_number}, user_id: {user_doc['_id']}")
        
        # Check permission
        phone_check = mongo.db.telnyx_phone_numbers.find_one({
            "phone_number": phone_number,
            "assigned_to_user_id": user_doc["_id"]
        })
        
        current_app.logger.info(f"Phone check result: {phone_check}")
        
        if not phone_check:
            return jsonify({"error": "You do not have permission to view messages for this number"}), 403

        # Build query - normalize phone number
        normalized_phone = phone_number
        query = {"$or": [{"from": normalized_phone}, {"to": {"$in": [normalized_phone]}}]}
        
        # Add optional filters
        if request.args.get('direction'):
            query["direction"] = request.args.get('direction')
        if request.args.get('message_type'):
            query["type"] = request.args.get('message_type')
        
        limit = request.args.get('limit', 100, type=int)
        skip = request.args.get('skip', 0, type=int)

        total_count = mongo.db.telnyx_messages.count_documents(query)
        cursor = mongo.db.telnyx_messages.find(query).sort("created_at", -1).skip(skip).limit(limit)
        
        messages = [dict(msg, id=str(msg.pop("_id", None))) for msg in cursor]
        
        return jsonify({
            "messages": messages,
            "pagination": {
                "total_count": total_count,
                "returned_count": len(messages),
                "skip": skip,
                "limit": limit,
                "has_more": (skip + len(messages)) < total_count
            }
        }), 200

    except Exception as e:
        current_app.logger.error(f"Error in get_messages_by_phone_number: {e}", exc_info=True)
        return jsonify({"error": "An unexpected server error occurred"}), 500

# GET /api/user/by-number/<phone_number>/summary
@tenant_user_bp.route('/by-number/<phone_number>/summary', methods=['GET'])
@tenant_token_required
def get_message_summary_by_phone_number(phone_number):
    """Get message summary statistics for a specific phone number."""
    try:
        normalized_phone = _normalize_phone_e164(phone_number)

        # Security Check
        current_user = request.current_user
        if not mongo.db.telnyx_phone_numbers.find_one({
            "phone_number": normalized_phone,
            "tenant_id": ObjectId(current_user['tenant_id']),
            "assigned_to_user_id": ObjectId(current_user['_id'])
        }):
            return jsonify({"error": "Permission denied for this number's summary"}), 403

        match_query = {"$or": [{"from": normalized_phone}, {"to": {"$in": [normalized_phone]}}]}
        
        pipeline = [
            {"$match": match_query},
            {
                "$group": {
                    "_id": None,
                    "total_messages": {"$sum": 1},
                    "inbound_messages": {"$sum": {"$cond": [{"$eq": ["$direction", "inbound"]}, 1, 0]}},
                    "outbound_messages": {"$sum": {"$cond": [{"$eq": ["$direction", "outbound"]}, 1, 0]}},
                    "total_cost": {"$sum": {"$toDouble": "$cost.amount"}},
                }
            }
        ]
        
        result = list(mongo.db.telnyx_messages.aggregate(pipeline))
        
        summary = {
            "total_messages": result[0]["total_messages"] if result else 0,
            "inbound_messages": result[0]["inbound_messages"] if result else 0,
            "outbound_messages": result[0]["outbound_messages"] if result else 0,
            "total_cost_usd": round(result[0].get("total_cost", 0.0) or 0.0, 4) if result else 0.0,
        }
        
        return jsonify({
            "phone_number": phone_number,
            "normalized_phone": normalized_phone,
            "summary": summary
        }), 200

    except PyMongoError as e:
        current_app.logger.error(f"Database error in summary endpoint: {e}")
        return jsonify({"error": "Database error occurred"}), 500
    except Exception as e:
        current_app.logger.exception("Unexpected error in summary endpoint")
        return jsonify({"error": "An unexpected server error occurred"}), 500

# GET /api/user/<message_id>
@tenant_user_bp.route('/<message_id>', methods=['GET'])
@tenant_token_required
def get_message_details(message_id):
    """Get details of a specific message by its Telnyx message_id."""
    try:
        # A full security implementation would also check if the user
        # has access to either the 'from' or 'to' number in the message.
        message = mongo.db.telnyx_messages.find_one({"message_id": message_id})

        if not message:
            return jsonify({"error": "Message not found"}), 404

        message["id"] = str(message.pop("_id", None))
        return jsonify(message), 200

    except PyMongoError as e:
        current_app.logger.error(f"Database error for message_id {message_id}: {e}")
        return jsonify({"error": "Database error occurred"}), 500
    except Exception as e:
        current_app.logger.exception(f"Unexpected error for message_id {message_id}")
        return jsonify({"error": "An unexpected server error occurred"}), 500
