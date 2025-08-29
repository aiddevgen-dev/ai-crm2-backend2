# pipecat.py - Flask Backend for Pipecat Voice Webhooks
import logging
import json
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from dataclasses import dataclass

from flask import Flask, request, jsonify, Blueprint
from werkzeug.exceptions import BadRequest, InternalServerError, NotFound, ServiceUnavailable
from pymongo import MongoClient, ReturnDocument
from pymongo.errors import DuplicateKeyError
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Database configuration
# Database configuration
MONGODB_URL = "mongodb+srv://absar:absar12345@cluster0.f18xqed.mongodb.net/"
DATABASE_NAME = "multitenant_auth_db"

# Global variables
_db_client = None
_database = None
_INDEX_READY = False

# Data classes for validation
@dataclass
class ContactInfo:
    name: Optional[str] = None
    phone_e164: Optional[str] = None
    email: Optional[str] = None

@dataclass
class ServiceAddress:
    street: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip: Optional[str] = None
    in_service_area: Optional[bool] = None

@dataclass
class ProblemInfo:
    summary: Optional[str] = None
    category: Optional[str] = None
    urgency: Optional[str] = None  # EMERGENCY|TODAY|48_HOURS|THIS_WEEK
    property_type: Optional[str] = None  # residential|commercial
    photos_ok: Optional[bool] = None

@dataclass
class CallData:
    tenant_id: Optional[str] = None
    call_key: Optional[str] = None
    call_session_id: Optional[str] = None
    vertical: Optional[str] = None
    lead_status: Optional[str] = None
    qualified: Optional[bool] = None
    reason_codes: Optional[List[str]] = None
    contact: Optional[ContactInfo] = None
    service_address: Optional[ServiceAddress] = None
    problem: Optional[ProblemInfo] = None
    availability: Optional[List[str]] = None
    consent_sms: Optional[bool] = None
    opt_out: Optional[bool] = None
    approval_deadline_minutes: Optional[int] = None
    call_completed: Optional[bool] = None
    data_collection_status: Optional[str] = None  # in_progress|complete|partial
    notes: Optional[str] = None
    call_status: Optional[str] = None  # completed|disconnected
    timestamp: Optional[float] = None

# Database utilities
def get_database():
    """Get database connection"""
    global _db_client, _database
    
    if _database is None:
        try:
            _db_client = MongoClient(MONGODB_URL)
            _database = _db_client[DATABASE_NAME]
            
            # Test connection
            _database.command("ping")
            logger.info(f"Connected to MongoDB: {DATABASE_NAME}")
            
        except Exception as e:
            logger.error(f"Failed to connect to MongoDB: {e}")
            return None
    
    return _database

def ensure_index_once(db):
    """Ensure the unique index on 'call_key' is created once."""
    global _INDEX_READY
    if _INDEX_READY:
        return
    
    try:
        db["calls"].create_index("call_key", unique=True)
        _INDEX_READY = True
        logger.info("Successfully created unique index on 'call_key' in 'calls' collection.")
    except Exception as e:
        logger.error(f"Failed to create index on 'call_key': {e}")

def clean_none_values(data):
    """
    Recursively remove None values and empty strings from nested dictionaries and lists.
    Preserves False and 0 values as they are meaningful.
    """
    if isinstance(data, dict):
        cleaned = {}
        for key, value in data.items():
            if value is None or value == "":
                continue
            elif isinstance(value, (dict, list)):
                cleaned_value = clean_none_values(value)
                if cleaned_value:  # Only include non-empty dicts/lists
                    cleaned[key] = cleaned_value
            else:
                cleaned[key] = value
        return cleaned
    elif isinstance(data, list):
        cleaned = []
        for item in data:
            if item is None or item == "":
                continue
            elif isinstance(item, (dict, list)):
                cleaned_item = clean_none_values(item)
                if cleaned_item:  # Only include non-empty dicts/lists
                    cleaned.append(cleaned_item)
            else:
                cleaned.append(item)
        return cleaned
    else:
        return data

def handle_call_completion(call_identifier: str, call_data: dict):
    """
    Handle post-processing when a call is completed.
    This can include notifications, CRM sync, etc.
    """
    try:
        logger.info(f"Processing call completion for: {call_identifier}")
        
        # Example: Send notification if qualified lead
        if call_data.get("qualified", False):
            logger.info(f"Qualified lead completed: {call_identifier}")
            # Add notification logic here
            
        # Example: Log final call statistics
        contact = call_data.get("contact", {})
        problem = call_data.get("problem", {})
        
        stats = {
            "call_id": call_identifier,
            "customer_name": contact.get("name", "Unknown"),
            "problem_type": problem.get("category", "Unknown"),
            "urgency": problem.get("urgency", "Unknown"),
            "qualified": call_data.get("qualified", False),
            "data_complete": call_data.get("data_collection_status") == "complete",
            "conversation_length": len(call_data.get("conversation_log", [])),
        }
        
        logger.info(f"Call completion stats: {json.dumps(stats, indent=2)}")
        
    except Exception as e:
        logger.error(f"Error in call completion handling: {e}")
        # Don't raise - this is non-critical post-processing

# Create Blueprint for webhook routes
webhook_bp = Blueprint('webhook', __name__, url_prefix='/webhooks/pipecat')
@webhook_bp.route('/voice', methods=['POST'])
def handle_voice_webhook():
    """
    Handle voice webhook with event-based structure
    """
    try:
        if not request.is_json:
            raise BadRequest("Content-Type must be application/json")
        
        payload = request.get_json()
        if not payload:
            raise BadRequest("Empty JSON payload")
        
        db = get_database()
        if db is None:
            logger.error("Database connection failed")
            raise ServiceUnavailable("Database unavailable")
            
        calls = db["calls"]
        ensure_index_once(db)

        now = datetime.utcnow()
        now_iso = now.isoformat()
        
        event_type = payload.get("event_type", "unknown_event")
        call_status = payload.get("call_status", "unknown_status")

        # --- Identify the call ---
        telnyx_data = payload.get("telnyx", {})
        raw_start_frame = payload.get("raw_start_frame", {})
        start_obj = raw_start_frame.get("start", {})
        
        call_session_id = telnyx_data.get("call_session_id") or start_obj.get("call_session_id")
        stream_id = telnyx_data.get("stream_id") or start_obj.get("stream_id")

        # Use call_session_id as the primary, durable key. Stream_id is secondary.
        call_key = call_session_id or stream_id
        if not call_key:
            raise BadRequest("Payload must contain 'telnyx.call_session_id' or 'stream_id' to identify the call.")

        # --- Prepare the database update ---
        event_doc = {
            "ts": now_iso,
            "event_type": event_type,
            "call_status": call_status,
            "payload": payload,  # Store the exact payload for auditing
        }

        update_doc = {
            "$push": {"events": event_doc},
            "$set": {
                "last_status": call_status,
                "last_event_type": event_type,
                "updated_at": now_iso,
            },
            "$setOnInsert": {
                "call_key": call_key,
                "created_at": now_iso,
            },
        }

        # --- Handle different payload types ---
        if call_status == "initiated":
            # This is the FIRST webhook call from server.py
            from_number = payload.get("from")
            to_number = payload.get("to")
            
            update_doc["$set"].update({
                "from": from_number,
                "to": to_number,
                "telnyx_metadata": telnyx_data,
                "initial_payload": payload.get("raw_start_frame"),
            })
            logger.info(f"Initiating call record for key: {call_key}")

        else:
            # This is the SECOND webhook call from bot.py
            fields_to_merge = {
                k: v for k, v in payload.items() 
                if k not in ["call_status", "event_type", "timestamp", "telnyx"]
            }
            update_doc["$set"].update(fields_to_merge)
            logger.info(f"Updating call record for key: {call_key} with final data.")

        # --- Execute the database operation ---
        try:
            updated_call = calls.find_one_and_update(
                {"call_key": call_key},
                update_doc,
                upsert=True,
                return_document=ReturnDocument.AFTER,
            )
        except Exception as e:
            logger.error(f"Database upsert failed for call_key '{call_key}': {e}")
            raise InternalServerError("Database operation failed.")

        return jsonify({
            "ok": True,
            "call_id": str(updated_call["_id"]),
            "call_key": updated_call["call_key"],
            "last_status": updated_call["last_status"],
        })

    except (BadRequest, ServiceUnavailable, InternalServerError):
        raise
    except Exception as e:
        logger.error(f"Unexpected error in voice webhook: {e}")
        raise InternalServerError("Something went wrong.")

@webhook_bp.route('/call', methods=['POST'])
def handle_call_webhook():
    """
    Handle incoming webhook data from Pipecat voice bot.
    Updates existing call records or creates new ones based on call_key/call_session_id.
    Handles real-time updates and conversation logging.
    """
    try:
        if not request.is_json:
            raise BadRequest("Content-Type must be application/json")
        
        request_data = request.get_json()
        if not request_data:
            raise BadRequest("Empty JSON payload")
        
        # Log incoming request for debugging (truncate large conversation logs)
        log_data = request_data.copy()
        if "conversation_log" in log_data and len(log_data["conversation_log"]) > 5:
            log_data["conversation_log"] = log_data["conversation_log"][-5:]  # Last 5 entries only
        logger.info(f"Received webhook data: {json.dumps(log_data, indent=2)}")
        
        # Get database connection
        db = get_database()
        if db is None:
            raise ServiceUnavailable("Database connection failed")
        
        calls_collection = db.calls
        
        # Determine the call identifier (prefer call_key over call_session_id)
        call_identifier = None
        if "call_key" in request_data:
            call_identifier = request_data["call_key"]
        elif "call_session_id" in request_data:
            call_identifier = request_data["call_session_id"]
        
        if not call_identifier:
            logger.error("No call_key or call_session_id found in request")
            raise BadRequest("call_key or call_session_id is required")
        
        # Clean the data of None values and empty strings
        cleaned_data = clean_none_values(request_data)
        
        # Add metadata
        cleaned_data["updated_at"] = datetime.now(timezone.utc)
        
        # Ensure call_key is set for consistency
        if "call_key" not in cleaned_data:
            cleaned_data["call_key"] = call_identifier
        
        # Handle call_status specific logic
        call_status = cleaned_data.get("call_status", "in_progress")
        data_collection_status = cleaned_data.get("data_collection_status", "in_progress")
        
        # Check if this is a real-time update or final call
        is_final_update = (
            call_status in ["completed", "disconnected"] or 
            data_collection_status == "complete" or
            cleaned_data.get("call_completed", False)
        )
        
        # Find existing call record
        existing_call = calls_collection.find_one({
            "$or": [
                {"call_key": call_identifier},
                {"call_session_id": call_identifier}
            ]
        })
        
        if existing_call:
            # Update existing record
            logger.info(f"Updating existing call record for: {call_identifier} (status: {call_status})")
            
            # Build sophisticated update operations
            set_operations = {}
            push_operations = {}
            
            # Handle top-level fields
            for key, value in cleaned_data.items():
                if key in ["contact", "service_address", "problem"]:
                    # Handle nested objects - merge intelligently
                    if isinstance(value, dict) and value:
                        existing_nested = existing_call.get(key, {})
                        for nested_key, nested_value in value.items():
                            # Only update if value is meaningful (not empty string or None)
                            if nested_value not in [None, "", []]:
                                set_operations[f"{key}.{nested_key}"] = nested_value
                elif key == "conversation_log":
                    # Handle conversation log - append new entries
                    if isinstance(value, list) and value:
                        existing_log = existing_call.get("conversation_log", [])
                        existing_timestamps = {entry.get("timestamp") for entry in existing_log}
                        
                        # Only add new conversation entries
                        new_entries = [
                            entry for entry in value 
                            if entry.get("timestamp") not in existing_timestamps
                        ]
                        
                        if new_entries:
                            push_operations["conversation_log"] = {"$each": new_entries}
                elif key == "availability":
                    # Replace availability array entirely if provided and non-empty
                    if isinstance(value, list) and value:
                        set_operations[key] = value
                elif key == "reason_codes":
                    # Merge reason codes
                    if isinstance(value, list) and value:
                        existing_codes = set(existing_call.get("reason_codes", []))
                        new_codes = set(value)
                        combined_codes = list(existing_codes.union(new_codes))
                        set_operations[key] = combined_codes
                else:
                    # For other fields, update if value is meaningful
                    if value not in [None, "", []]:
                        set_operations[key] = value
            
            # Special handling for qualification and status updates
            if is_final_update:
                set_operations["call_completed"] = True
                set_operations["final_updated_at"] = datetime.now(timezone.utc)
                
                # Mark as qualified if we have minimum required data
                contact = {**existing_call.get("contact", {}), **cleaned_data.get("contact", {})}
                address = {**existing_call.get("service_address", {}), **cleaned_data.get("service_address", {})}
                problem = {**existing_call.get("problem", {}), **cleaned_data.get("problem", {})}
                
                has_minimum_data = (
                    contact.get("name") and 
                    contact.get("phone_e164") and
                    address.get("street") and 
                    problem.get("summary")
                )
                
                if has_minimum_data:
                    set_operations["qualified"] = True
                    set_operations["lead_status"] = "pending_approval"
            
            # Build the update query
            update_query = {}
            if set_operations:
                update_query["$set"] = set_operations
            if push_operations:
                update_query.update(push_operations)
            
            # Execute update
            if update_query:
                result = calls_collection.update_one(
                    {"$or": [{"call_key": call_identifier}, {"call_session_id": call_identifier}]},
                    update_query
                )
                
                if result.modified_count > 0:
                    logger.info(f"Successfully updated call record: {call_identifier}")
                    operation = "updated"
                else:
                    logger.info(f"No changes made to call record: {call_identifier}")
                    operation = "no_change"
            else:
                operation = "no_change"
                
        else:
            # Create new record
            logger.info(f"Creating new call record for: {call_identifier}")
            
            # Ensure required fields are present
            new_record = {
                "call_key": call_identifier,
                "created_at": datetime.now(timezone.utc),
                "tenant_id": cleaned_data.get("tenant_id", "unknown"),
                "vertical": cleaned_data.get("vertical", "unknown"),
                "lead_status": cleaned_data.get("lead_status", "new"),
                "qualified": cleaned_data.get("qualified", False),
                "reason_codes": cleaned_data.get("reason_codes", []),
                "contact": cleaned_data.get("contact", {}),
                "service_address": cleaned_data.get("service_address", {}),
                "problem": cleaned_data.get("problem", {}),
                "availability": cleaned_data.get("availability", []),
                "consent_sms": cleaned_data.get("consent_sms", False),
                "opt_out": cleaned_data.get("opt_out", False),
                "call_completed": cleaned_data.get("call_completed", False),
                "data_collection_status": cleaned_data.get("data_collection_status", "in_progress"),
                "conversation_log": cleaned_data.get("conversation_log", []),
                "notes": cleaned_data.get("notes", ""),
                **cleaned_data  # Include any additional fields
            }
            
            result = calls_collection.insert_one(new_record)
            logger.info(f"Successfully created call record: {call_identifier} with ID: {result.inserted_id}")
            operation = "created"
        
        # For final updates, trigger any post-processing (notifications, etc.)
        if is_final_update:
            handle_call_completion(call_identifier, cleaned_data)
        
        # Return success response
        response_data = {
            "status": "success",
            "operation": operation,
            "call_identifier": call_identifier,
            "is_final": is_final_update,
            "data_collection_status": data_collection_status,
            "message": f"Call data {operation} successfully"
        }
        
        logger.info(f"Webhook processed successfully: {response_data}")
        return jsonify(response_data)
        
    except (BadRequest, ServiceUnavailable):
        raise
    except Exception as e:
        logger.error(f"Unexpected error processing webhook: {str(e)}", exc_info=True)
        raise InternalServerError(f"Internal server error: {str(e)}")

@webhook_bp.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    try:
        # Test database connection
        db = get_database()
        if db is None:
            raise ServiceUnavailable("Database connection failed")
        
        db.command("ping")
        
        return jsonify({
            "status": "healthy",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "database": "connected"
        })
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise ServiceUnavailable(f"Service unhealthy: {str(e)}")

@webhook_bp.route('/status', methods=['POST'])
def handle_status_webhook():
    """
    Handle Telnyx status webhooks. These are typically sent as form data.
    """
    try:
        # Telnyx status webhooks often send 'application/x-www-form-urlencoded'
        if not request.form:
            raise BadRequest("Request is not form data or is empty")

        payload = request.form.to_dict()
        logger.info(f"Received Telnyx status webhook: {payload}")

        db = get_database()
        if db is None:
            raise ServiceUnavailable("Database unavailable")
        
        calls_collection = db.calls

        # Detect Telnyx event type
        event_type = payload.get("event_type") or "telnyx_status"

        # Normalize IDs from the payload
        call_sid = payload.get("CallSid") or payload.get("call_control_id")
        if not call_sid:
            raise BadRequest("Missing 'CallSid' or 'call_control_id' in Telnyx status payload")
            
        call_status = payload.get("CallStatus") or payload.get("status")

        # Build the event entry to be pushed into the events array
        event_entry = {
            "ts": payload.get("Timestamp", datetime.now(timezone.utc).isoformat()),
            "event_type": event_type,
            "call_status": call_status,
            "payload": payload,
        }

        # Base update fields
        update_data = {
            "call_sid": call_sid,
            "last_event_type": event_type,
            "updated_at": payload.get("Timestamp", datetime.now(timezone.utc).isoformat()),
        }

        # If this is a normal status update
        if event_type != "call.transcription":
            update_data.update({
                "last_status": call_status,
                "duration": payload.get("CallDuration"),
                "hangup_source": payload.get("HangupSource"),
                "from": payload.get("From"),
                "to": payload.get("To"),
                "account_sid": payload.get("AccountSid"),
            })

        # Remove any keys that have None values to avoid overwriting good data
        update_data = {k: v for k, v in update_data.items() if v is not None}

        # Build a query to find the matching call document
        query = {
            "$or": [
                {"telnyx_metadata.call_control_id": call_sid},
                {"call_sid": call_sid},
                {"call_key": call_sid},  # Fallback for matching Pipecat's key
            ]
        }

        # Start building the update document
        update_doc = {
            "$set": update_data,
            "$push": {"events": event_entry}
        }

        # If this is a transcription event
        if event_type == "call.transcription":
            transcript = payload.get("transcript")
            confidence = payload.get("confidence")
            is_final = payload.get("is_final")

            transcription_entry = {
                "ts": payload.get("Timestamp", datetime.now(timezone.utc).isoformat()),
                "transcript": transcript,
                "confidence": confidence,
                "is_final": is_final,
            }

            # Merge transcription into $push
            update_doc["$push"]["transcriptions"] = transcription_entry

        # Perform an upsert operation
        result = calls_collection.update_one(
            query,
            update_doc,
            upsert=True
        )

        if result.matched_count:
            logger.info(f"Updated call {call_sid} with event {event_type}")
        elif result.upserted_id:
            logger.info(f"Inserted new call record for {call_sid} via status webhook")

        return jsonify({
            "success": True, 
            "call_sid": call_sid,
            "event_type": event_type,
            "operation": "updated" if result.matched_count else "created"
        })

    except (BadRequest, ServiceUnavailable):
        raise
    except Exception as e:
        logger.error(f"Failed to process Telnyx status webhook: {e}", exc_info=True)
        raise InternalServerError("Failed to process status webhook")
# API routes for call management
api_bp = Blueprint('api', __name__, url_prefix='/api')

@api_bp.route('/calls/<call_session_id>', methods=['GET'])
def get_call_data(call_session_id):
    """Retrieve call data by session ID (for debugging/testing)"""
    try:
        db = get_database()
        if db is None:
            raise ServiceUnavailable("Database connection failed")
        
        calls_collection = db.calls
        
        call_data = calls_collection.find_one(
            {"$or": [{"call_session_id": call_session_id}, {"call_key": call_session_id}]},
            {"_id": 0}  # Exclude MongoDB ObjectId
        )
        
        if not call_data:
            raise NotFound("Call session not found")
        
        return jsonify(call_data)
        
    except (NotFound, ServiceUnavailable):
        raise
    except Exception as e:
        logger.error(f"Error retrieving call data: {e}")
        raise InternalServerError(str(e))

@api_bp.route('/calls', methods=['GET'])
def list_recent_calls():
    """List recent calls (for debugging/testing)"""
    try:
        limit = int(request.args.get('limit', 10))
        skip = int(request.args.get('skip', 0))
        
        db = get_database()
        if db is None:
            raise ServiceUnavailable("Database connection failed")
        
        calls_collection = db.calls
        
        calls = list(calls_collection.find(
            {},
            {"_id": 0}  # Exclude MongoDB ObjectId
        ).sort("created_at", -1).skip(skip).limit(limit))
        
        total = calls_collection.count_documents({})
        
        return jsonify({
            "calls": calls,
            "total": total,
            "limit": limit,
            "skip": skip
        })
        
    except ServiceUnavailable:
        raise
    except Exception as e:
        logger.error(f"Error listing calls: {e}")
        raise InternalServerError(str(e))

@api_bp.route('/calls/<call_session_id>', methods=['DELETE'])
def delete_call(call_session_id):
    """Delete a call record"""
    try:
        db = get_database()
        if db is None:
            raise ServiceUnavailable("Database connection failed")
        
        calls_collection = db.calls
        
        result = calls_collection.delete_one(
            {"$or": [{"call_session_id": call_session_id}, {"call_key": call_session_id}]}
        )
        
        if result.deleted_count == 0:
            raise NotFound("Call session not found")
        
        return jsonify({
            "message": f"Call {call_session_id} deleted successfully",
            "deleted_count": result.deleted_count
        })
        
    except (NotFound, ServiceUnavailable):
        raise
    except Exception as e:
        logger.error(f"Error deleting call: {e}")
        raise InternalServerError(str(e))

# Error handlers
def bad_request(error):
    return jsonify({"error": "Bad request", "message": str(error.description)}), 400

def not_found(error):
    return jsonify({"error": "Not found", "message": str(error.description)}), 404

def internal_error(error):
    return jsonify({"error": "Internal server error", "message": "Something went wrong"}), 500

def service_unavailable(error):
    return jsonify({"error": "Service unavailable", "message": str(error.description)}), 503

# Function to create app (for integration with main Flask app)
def create_pipecat_webhook_bp():
    """Create and return the pipecat webhook blueprint"""
    return webhook_bp, api_bp

# Standalone app for testing
if __name__ == '__main__':
    # Create Flask app for standalone testing
    app = Flask(__name__)
    app.config['JSON_SORT_KEYS'] = False
    
    # Register error handlers
    app.register_error_handler(400, bad_request)
    app.register_error_handler(404, not_found)
    app.register_error_handler(500, internal_error)
    app.register_error_handler(503, service_unavailable)
    
    # Register blueprints
    app.register_blueprint(webhook_bp)
    app.register_blueprint(api_bp)
    
    # Root route
    @app.route('/')
    def index():
        """Root endpoint with API information"""
        return jsonify({
            "service": "Pipecat Voice Webhook Backend",
            "version": "1.0.0",
            "status": "running",
            "endpoints": {
                "webhooks": {
                    "voice": "/webhooks/pipecat/voice",
                    "call": "/webhooks/pipecat/call",
                    "health": "/webhooks/pipecat/health"
                },
                "api": {
                    "list_calls": "/api/calls",
                    "get_call": "/api/calls/{call_session_id}",
                    "delete_call": "/api/calls/{call_session_id}"
                }
            }
        })
    
    # Initialize database on startup
    with app.app_context():
        try:
            db = get_database()
            if db is not None:
                ensure_index_once(db)
                logger.info("Database initialized successfully")
            else:
                logger.error("Failed to initialize database")
        except Exception as e:
            logger.error(f"Error initializing database: {e}")
    
    # For development only
    app.run(
        host='0.0.0.0',
        port=int(os.getenv('PORT', 5000)),
        debug=os.getenv('FLASK_ENV') == 'development'
    )