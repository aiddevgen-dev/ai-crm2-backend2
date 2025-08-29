# tools_webhook.py - Flask Backend for Tool Calling Webhooks
import logging
import json
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional
from dataclasses import dataclass

from flask import Flask, request, jsonify, Blueprint
from werkzeug.exceptions import BadRequest, InternalServerError, NotFound, ServiceUnavailable
from pymongo import MongoClient, ReturnDocument
from pymongo.errors import DuplicateKeyError
import os
from dotenv import load_dotenv
from models import mongo
# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Database configuration
MONGODB_URL = "mongodb+srv://absar:absar12345@cluster0.f18xqed.mongodb.net/"
DATABASE_NAME = "multitenant_auth_db"

# Global variables
_db_client = None
_database = None

# def get_database():
#     """Get database connection"""
#     global _db_client, _database
    
#     if _database is None:
#         try:
#             _db_client = MongoClient(MONGODB_URL)
#             _database = _db_client[DATABASE_NAME]
            
#             # Test connection
#             _database.command("ping")
#             logger.info(f"Connected to MongoDB: {DATABASE_NAME}")
            
#         except Exception as e:
#             logger.error(f"Failed to connect to MongoDB: {e}")
#             return None
    
#     return _database


def get_database():
    """Use existing database connection from main app"""
    return mongo.db


def clean_none_values(data):
    """Remove None values and empty strings from nested dictionaries"""
    if isinstance(data, dict):
        cleaned = {}
        for key, value in data.items():
            if value is None or value == "":
                continue
            elif isinstance(value, (dict, list)):
                cleaned_value = clean_none_values(value)
                if cleaned_value:
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
                if cleaned_item:
                    cleaned.append(cleaned_item)
            else:
                cleaned.append(item)
        return cleaned
    else:
        return data

# Create Blueprint for tool webhook routes
tools_bp = Blueprint('tools', __name__, url_prefix='/webhooks/tools')

@tools_bp.route('/appointments', methods=['POST'])
def handle_appointment_tool():
    """Handle set_appointment tool calls"""
    try:
        if not request.is_json:
            raise BadRequest("Content-Type must be application/json")
        
        payload = request.get_json()
        if not payload:
            raise BadRequest("Empty JSON payload")
        
        logger.info(f"Received appointment tool request: {json.dumps(payload, indent=2)}")
        
        # Extract appointment data
        tenant_id = payload.get("tenant_id")
        call_session_id = payload.get("call_session_id")
        customer_info = payload.get("customer_info", {})
        appointment_data = payload.get("appointment", {})
        
        if not all([tenant_id, call_session_id, customer_info, appointment_data]):
            raise BadRequest("Missing required fields: tenant_id, call_session_id, customer_info, appointment")
        
        db = get_database()
        if db is None:
            raise ServiceUnavailable("Database connection failed")
        
        appointments_collection = db.appointments
        
        # Create appointment record
        appointment_record = {
            "appointment_id": f"apt_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{tenant_id[:8]}",
            "tenant_id": tenant_id,
            "call_session_id": call_session_id,
            "customer_name": customer_info.get("name"),
            "customer_phone": customer_info.get("phone"),
            "service_address": customer_info.get("service_address"),
            "appointment_date": appointment_data.get("date"),
            "appointment_time": appointment_data.get("time"),
            "problem_description": appointment_data.get("problem"),
            "urgency": appointment_data.get("urgency", "normal"),
            "status": "confirmed",
            "source": "ai_voice_call",
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc)
        }
        
        # Insert appointment
        result = appointments_collection.insert_one(appointment_record)
        appointment_id = appointment_record["appointment_id"]
        
        logger.info(f"Created appointment: {appointment_id}")
        
        # Update the original call record to link appointment
        calls_collection = db.calls
        calls_collection.update_one(
            {"call_key": call_session_id},
            {"$set": {"appointment_id": appointment_id, "appointment_scheduled": True}}
        )
        
        return jsonify({
            "success": True,
            "appointment_id": appointment_id,
            "status": "confirmed",
            "message": f"Appointment scheduled for {customer_info.get('name')} on {appointment_data.get('date')} at {appointment_data.get('time')}"
        })
        
    except (BadRequest, ServiceUnavailable):
        raise
    except Exception as e:
        logger.error(f"Error in appointment tool: {e}")
        raise InternalServerError(str(e))

@tools_bp.route('/notifications', methods=['POST'])
def handle_notification_tool():
    """Handle send_notification tool calls"""
    try:
        if not request.is_json:
            raise BadRequest("Content-Type must be application/json")
        
        payload = request.get_json()
        if not payload:
            raise BadRequest("Empty JSON payload")
        
        logger.info(f"Received notification tool request: {json.dumps(payload, indent=2)}")
        
        phone_number = payload.get("phone_number")
        message_type = payload.get("message_type")
        custom_message = payload.get("custom_message")
        appointment_details = payload.get("appointment_details", {})
        tenant_id = payload.get("tenant_id")
        call_session_id = payload.get("call_session_id")
        
        if not all([phone_number, message_type, tenant_id]):
            raise BadRequest("Missing required fields: phone_number, message_type, tenant_id")
        
        db = get_database()
        if db is None:
            raise ServiceUnavailable("Database connection failed")
        
        notifications_collection = db.notifications
        
        # Generate message content based on type
        message_content = ""
        if message_type == "confirmation":
            if appointment_details:
                message_content = f"Appointment confirmed for {appointment_details.get('date')} at {appointment_details.get('time')}. We'll call 30min before arrival. Reply STOP to opt out."
            else:
                message_content = "Thank you for calling! We've received your service request and will contact you shortly with scheduling options. Reply STOP to opt out."
        
        elif message_type == "reminder":
            message_content = f"Reminder: You have an electrical service appointment tomorrow. Our technician will call 30min before arrival. Reply STOP to opt out."
        
        elif message_type == "emergency":
            message_content = "EMERGENCY: Your electrical service request has been escalated. Our emergency technician will contact you within 1 hour. If immediate danger, call 911."
        
        elif message_type == "custom" and custom_message:
            message_content = custom_message
        
        else:
            raise BadRequest("Invalid message_type or missing custom_message")
        
        # Create notification record
        notification_record = {
            "notification_id": f"sms_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{tenant_id[:8]}",
            "tenant_id": tenant_id,
            "call_session_id": call_session_id,
            "phone_number": phone_number,
            "message_type": message_type,
            "message_content": message_content,
            "status": "queued",
            "created_at": datetime.now(timezone.utc),
            "scheduled_for": datetime.now(timezone.utc)
        }
        
        # Insert notification
        result = notifications_collection.insert_one(notification_record)
        notification_id = notification_record["notification_id"]
        
        logger.info(f"Queued notification: {notification_id} to {phone_number}")
        
        # Here you would integrate with your SMS provider (Telnyx, Twilio, etc.)
        # For now, we'll mark it as sent
        notifications_collection.update_one(
            {"notification_id": notification_id},
            {"$set": {"status": "sent", "sent_at": datetime.now(timezone.utc)}}
        )
        
        return jsonify({
            "success": True,
            "notification_id": notification_id,
            "status": "sent",
            "message": f"Notification sent to {phone_number}"
        })
        
    except (BadRequest, ServiceUnavailable):
        raise
    except Exception as e:
        logger.error(f"Error in notification tool: {e}")
        raise InternalServerError(str(e))

@tools_bp.route('/qualification', methods=['POST'])
def handle_qualification_tool():
    """Handle qualify_lead tool calls"""
    try:
        if not request.is_json:
            raise BadRequest("Content-Type must be application/json")
        
        payload = request.get_json()
        if not payload:
            raise BadRequest("Empty JSON payload")
        
        logger.info(f"Received qualification tool request: {json.dumps(payload, indent=2)}")
        
        customer_data = payload.get("customer_data", {})
        qualification_criteria = payload.get("qualification_criteria", {})
        tenant_id = payload.get("tenant_id")
        call_session_id = payload.get("call_session_id")
        
        if not all([customer_data, tenant_id, call_session_id]):
            raise BadRequest("Missing required fields: customer_data, tenant_id, call_session_id")
        
        # Calculate qualification score
        score = 0
        status = "disqualified"
        reasons = []
        
        # Check contact information (30 points)
        contact = customer_data.get("contact", {})
        if contact.get("name"):
            score += 10
        if contact.get("phone_e164"):
            score += 20
        else:
            reasons.append("missing_phone")
        
        # Check service address (25 points)
        address = customer_data.get("service_address", {})
        if address.get("street") and address.get("zip"):
            score += 15
        if address.get("in_service_area"):
            score += 10
        else:
            reasons.append("out_of_service_area")
        
        # Check problem details (25 points)
        problem = customer_data.get("problem", {})
        if problem.get("summary"):
            score += 15
        if problem.get("category"):
            score += 10
        
        # Check urgency and availability (20 points)
        if problem.get("urgency") in ["emergency", "urgent"]:
            score += 10
        if customer_data.get("availability"):
            score += 10
        
        # Determine qualification status
        if score >= 70:
            status = "qualified"
        elif score >= 50:
            status = "needs_review"
            reasons.append("low_score")
        else:
            status = "disqualified"
            reasons.append("insufficient_information")
        
        db = get_database()
        if db is None:
            raise ServiceUnavailable("Database connection failed")
        
        qualifications_collection = db.lead_qualifications
        
        # Create qualification record
        qualification_record = {
            "qualification_id": f"qual_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{tenant_id[:8]}",
            "tenant_id": tenant_id,
            "call_session_id": call_session_id,
            "customer_data": customer_data,
            "qualification_criteria": qualification_criteria,
            "score": score,
            "status": status,
            "reasons": reasons,
            "qualified_at": datetime.now(timezone.utc)
        }
        
        # Insert qualification
        result = qualifications_collection.insert_one(qualification_record)
        qualification_id = qualification_record["qualification_id"]
        
        # Update the original call record
        calls_collection = db.calls
        calls_collection.update_one(
            {"call_key": call_session_id},
            {
                "$set": {
                    "qualification_id": qualification_id,
                    "qualification_score": score,
                    "qualification_status": status,
                    "qualified": status == "qualified"
                }
            }
        )
        
        logger.info(f"Lead qualification completed: {qualification_id} - {status} (score: {score})")
        
        return jsonify({
            "success": True,
            "qualification_id": qualification_id,
            "score": score,
            "status": status,
            "reasons": reasons
        })
        
    except (BadRequest, ServiceUnavailable):
        raise
    except Exception as e:
        logger.error(f"Error in qualification tool: {e}")
        raise InternalServerError(str(e))

@tools_bp.route('/availability', methods=['POST'])
def handle_availability_tool():
    """Handle check_availability tool calls"""
    try:
        if not request.is_json:
            raise BadRequest("Content-Type must be application/json")
        
        payload = request.get_json()
        if not payload:
            raise BadRequest("Empty JSON payload")
        
        logger.info(f"Received availability tool request: {json.dumps(payload, indent=2)}")
        
        service_address = payload.get("service_address")
        preferred_dates = payload.get("preferred_dates", [])
        urgency = payload.get("urgency", "normal")
        tenant_id = payload.get("tenant_id")
        
        if not all([service_address, tenant_id]):
            raise BadRequest("Missing required fields: service_address, tenant_id")
        
        # Mock availability checking - in production, integrate with scheduling system
        available_slots = []
        
        if urgency == "emergency":
            # Emergency slots - within 2 hours
            now = datetime.now()
            available_slots = [
                {
                    "date": now.strftime("%Y-%m-%d"),
                    "time": (now + timedelta(hours=1)).strftime("%I:%M %p"),
                    "technician": "Emergency Team",
                    "slot_type": "emergency"
                },
                {
                    "date": now.strftime("%Y-%m-%d"), 
                    "time": (now + timedelta(hours=2)).strftime("%I:%M %p"),
                    "technician": "Emergency Team",
                    "slot_type": "emergency"
                }
            ]
        else:
            # Regular availability
            base_date = datetime.now() + timedelta(days=1)
            for i in range(3):
                date = base_date + timedelta(days=i)
                available_slots.extend([
                    {
                        "date": date.strftime("%Y-%m-%d"),
                        "time": "10:00 AM",
                        "technician": f"Tech Team {i+1}",
                        "slot_type": "regular"
                    },
                    {
                        "date": date.strftime("%Y-%m-%d"),
                        "time": "2:00 PM", 
                        "technician": f"Tech Team {i+1}",
                        "slot_type": "regular"
                    }
                ])
        
        db = get_database()
        if db is None:
            raise ServiceUnavailable("Database connection failed")
        
        # Log availability check
        availability_checks = db.availability_checks
        check_record = {
            "check_id": f"avail_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{tenant_id[:8]}",
            "tenant_id": tenant_id,
            "call_session_id": payload.get("call_session_id"),
            "service_address": service_address,
            "preferred_dates": preferred_dates,
            "urgency": urgency,
            "available_slots": available_slots,
            "checked_at": datetime.now(timezone.utc)
        }
        
        availability_checks.insert_one(check_record)
        
        logger.info(f"Availability check completed: {len(available_slots)} slots found")
        
        return jsonify({
            "success": True,
            "available_slots": available_slots,
            "total_slots": len(available_slots),
            "urgency_level": urgency
        })
        
    except (BadRequest, ServiceUnavailable):
        raise
    except Exception as e:
        logger.error(f"Error in availability tool: {e}")
        raise InternalServerError(str(e))

@tools_bp.route('/tickets', methods=['POST'])
def handle_service_ticket_tool():
    """Handle create_service_ticket tool calls"""
    try:
        if not request.is_json:
            raise BadRequest("Content-Type must be application/json")
        
        payload = request.get_json()
        if not payload:
            raise BadRequest("Empty JSON payload")
        
        logger.info(f"Received service ticket tool request: {json.dumps(payload, indent=2)}")
        
        customer_data = payload.get("customer_data", {})
        problem_details = payload.get("problem_details", {})
        tenant_id = payload.get("tenant_id")
        call_session_id = payload.get("call_session_id")
        
        if not all([customer_data, problem_details, tenant_id, call_session_id]):
            raise BadRequest("Missing required fields: customer_data, problem_details, tenant_id, call_session_id")
        
        db = get_database()
        if db is None:
            raise ServiceUnavailable("Database connection failed")
        
        service_tickets = db.service_tickets
        
        # Generate ticket ID
        ticket_id = f"TKT-{datetime.now().strftime('%Y%m%d')}-{tenant_id[:4].upper()}-{datetime.now().strftime('%H%M%S')}"
        
        # Create service ticket
        ticket_record = {
            "ticket_id": ticket_id,
            "tenant_id": tenant_id,
            "call_session_id": call_session_id,
            "customer_info": customer_data.get("contact", {}),
            "service_address": customer_data.get("service_address", {}),
            "problem_description": problem_details.get("summary", ""),
            "problem_category": problem_details.get("category", "other electrical"),
            "urgency": problem_details.get("urgency", "normal"),
            "property_type": problem_details.get("property_type", "residential"),
            "source": "ai_voice_call",
            "status": "open",
            "priority": "high" if problem_details.get("urgency") == "emergency" else "normal",
            "assigned_to": None,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc)
        }
        
        # Insert ticket
        result = service_tickets.insert_one(ticket_record)
        
        # Update the original call record
        calls_collection = db.calls
        calls_collection.update_one(
            {"call_key": call_session_id},
            {"$set": {"service_ticket_id": ticket_id, "ticket_created": True}}
        )
        
        logger.info(f"Service ticket created: {ticket_id}")
        
        return jsonify({
            "success": True,
            "ticket_id": ticket_id,
            "status": "created",
            "priority": ticket_record["priority"]
        })
        
    except (BadRequest, ServiceUnavailable):
        raise
    except Exception as e:
        logger.error(f"Error in service ticket tool: {e}")
        raise InternalServerError(str(e))

@tools_bp.route('/pricing', methods=['POST'])
def handle_pricing_tool():
    """Handle get_pricing_estimate tool calls"""
    try:
        if not request.is_json:
            raise BadRequest("Content-Type must be application/json")
        
        payload = request.get_json()
        if not payload:
            raise BadRequest("Empty JSON payload")
        
        logger.info(f"Received pricing tool request: {json.dumps(payload, indent=2)}")
        
        service_type = payload.get("service_type")
        problem_description = payload.get("problem_description", "").lower()
        property_type = payload.get("property_type", "residential")
        tenant_id = payload.get("tenant_id")
        
        if not all([service_type, tenant_id]):
            raise BadRequest("Missing required fields: service_type, tenant_id")
        
        # Mock pricing logic - in production, integrate with pricing system
        price_estimates = {
            "lighting": {
                "residential": "$150-300",
                "commercial": "$200-500"
            },
            "outlet": {
                "residential": "$120-250", 
                "commercial": "$180-400"
            },
            "panel": {
                "residential": "$800-1500",
                "commercial": "$1200-3000"
            },
            "emergency": {
                "residential": "$300-600",
                "commercial": "$400-800"
            },
            "default": {
                "residential": "$200-400",
                "commercial": "$250-600"
            }
        }
        
        # Determine service category
        category = "default"
        if any(word in problem_description for word in ["light", "fixture", "bulb", "flicker"]):
            category = "lighting"
        elif any(word in problem_description for word in ["outlet", "switch", "plug"]):
            category = "outlet"  
        elif any(word in problem_description for word in ["panel", "breaker", "fuse"]):
            category = "panel"
        elif any(word in problem_description for word in ["emergency", "urgent", "burning", "spark"]):
            category = "emergency"
        
        price_range = price_estimates.get(category, price_estimates["default"]).get(property_type, "$200-400")
        
        db = get_database()
        if db is None:
            raise ServiceUnavailable("Database connection failed")
        
        # Log pricing request
        pricing_requests = db.pricing_requests
        pricing_record = {
            "pricing_id": f"price_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{tenant_id[:8]}",
            "tenant_id": tenant_id,
            "call_session_id": payload.get("call_session_id"),
            "service_type": service_type,
            "problem_description": problem_description,
            "property_type": property_type,
            "category": category,
            "price_range": price_range,
            "requested_at": datetime.now(timezone.utc)
        }
        
        pricing_requests.insert_one(pricing_record)
        
        logger.info(f"Pricing estimate provided: {category} - {price_range}")
        
        return jsonify({
            "success": True,
            "price_range": price_range,
            "category": category,
            "property_type": property_type,
            "disclaimer": "Final pricing subject to technician inspection"
        })
        
    except (BadRequest, ServiceUnavailable):
        raise
    except Exception as e:
        logger.error(f"Error in pricing tool: {e}")
        raise InternalServerError(str(e))

@tools_bp.route('/emergency', methods=['POST'])
def handle_emergency_tool():
    """Handle handle_emergency tool calls"""
    try:
        if not request.is_json:
            raise BadRequest("Content-Type must be application/json")
        
        payload = request.get_json()
        if not payload:
            raise BadRequest("Empty JSON payload")
        
        logger.info(f"Received emergency tool request: {json.dumps(payload, indent=2)}")
        
        customer_data = payload.get("customer_data", {})
        emergency_details = payload.get("emergency_details", {})
        tenant_id = payload.get("tenant_id")
        call_session_id = payload.get("call_session_id")
        
        if not all([customer_data, emergency_details, tenant_id, call_session_id]):
            raise BadRequest("Missing required fields: customer_data, emergency_details, tenant_id, call_session_id")
        
        db = get_database()
        if db is None:
            raise ServiceUnavailable("Database connection failed")
        
        emergency_requests = db.emergency_requests
        
        # Generate emergency ID
        emergency_id = f"EMG-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{tenant_id[:4].upper()}"
        
        # Create emergency record
        emergency_record = {
            "emergency_id": emergency_id,
            "tenant_id": tenant_id,
            "call_session_id": call_session_id,
            "customer_data": customer_data,
            "emergency_details": emergency_details,
            "priority": "CRITICAL",
            "status": "dispatched",
            "estimated_response": "30 minutes",
            "created_at": datetime.now(timezone.utc),
            "escalated_at": datetime.now(timezone.utc)
        }
        
        # Insert emergency record
        result = emergency_requests.insert_one(emergency_record)
        
        # Update the original call record
        calls_collection = db.calls
        calls_collection.update_one(
            {"call_key": call_session_id},
            {
                "$set": {
                    "emergency_id": emergency_id,
                    "emergency_escalated": True,
                    "priority": "CRITICAL"
                }
            }
        )
        
        # Here you would integrate with emergency dispatch system
        # Send alerts, notifications, etc.
        
        logger.info(f"Emergency escalated: {emergency_id}")
        
        return jsonify({
            "success": True,
            "emergency_id": emergency_id,
            "status": "escalated",
            "estimated_response": "30 minutes",
            "priority": "CRITICAL"
        })
        
    except (BadRequest, ServiceUnavailable):
        raise
    except Exception as e:
        logger.error(f"Error in emergency tool: {e}")
        raise InternalServerError(str(e))

@tools_bp.route('/health', methods=['GET'])
def tools_health_check():
    """Health check for tools endpoints"""
    try:
        db = get_database()
        if db is None:
            raise ServiceUnavailable("Database connection failed")
        
        db.command("ping")
        
        return jsonify({
            "status": "healthy",
            "service": "tools_webhook",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "database": "connected",
            "available_tools": [
                "appointments", "notifications", "qualification", 
                "availability", "tickets", "pricing", "emergency"
            ]
        })
    except Exception as e:
        logger.error(f"Tools health check failed: {e}")
        raise ServiceUnavailable(f"Service unhealthy: {str(e)}")

# Error handlers
def bad_request(error):
    return jsonify({"error": "Bad request", "message": str(error.description)}), 400

def not_found(error):
    return jsonify({"error": "Not found", "message": str(error.description)}), 404

def internal_error(error):
    return jsonify({"error": "Internal server error", "message": "Something went wrong"}), 500

def service_unavailable(error):
    return jsonify({"error": "Service unavailable", "message": str(error.description)}), 503

# Function to create blueprint (for integration with main Flask app)
def create_tools_webhook_bp():
    """Create and return the tools webhook blueprint"""
    return tools_bp

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
    
    # Register blueprint
    app.register_blueprint(tools_bp)
    
    # Root route
    @app.route('/')
    def index():
        return jsonify({
            "service": "Tools Webhook Backend",
            "version": "1.0.0",
            "status": "running",
            "endpoints": {
                "appointments": "/webhooks/tools/appointments",
                "notifications": "/webhooks/tools/notifications", 
                "qualification": "/webhooks/tools/qualification",
                "availability": "/webhooks/tools/availability",
                "tickets": "/webhooks/tools/tickets",
                "pricing": "/webhooks/tools/pricing",
                "emergency": "/webhooks/tools/emergency",
                "health": "/webhooks/tools/health"
            }
        })
    
    # Initialize database on startup
    with app.app_context():
        try:
            db = get_database()
            if db is not None:
                logger.info("Database initialized successfully for tools webhook")
            else:
                logger.error("Failed to initialize database")
        except Exception as e:
            logger.error(f"Error initializing database: {e}")
    
    # For development only
    app.run(
        host='0.0.0.0',
        port=int(os.getenv('PORT', 5001)),
        debug=os.getenv('FLASK_ENV') == 'development'
    )