# telnyx.py - Flask Backend for Telnyx SMS/MMS Webhooks
import logging
import json
import base64
import hashlib
import hmac
import os
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Optional, List

from flask import Flask, request, jsonify, Blueprint
from werkzeug.exceptions import BadRequest, InternalServerError, NotFound, ServiceUnavailable, Unauthorized
from pymongo import MongoClient, ReturnDocument
from pymongo.errors import DuplicateKeyError
from dotenv import load_dotenv

# Import for Ed25519 signature verification
try:
    from nacl.signing import VerifyKey
    from nacl.exceptions import BadSignatureError
    NACL_AVAILABLE = True
except ImportError:
    NACL_AVAILABLE = False
    print("Warning: PyNaCl not installed. Ed25519 signature verification will be disabled.")
    print("Install with: pip install PyNaCl")

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("telnyx.webhooks")

# Configuration
# MONGODB_URL = os.getenv('MONGODB_URL', 'mongodb://localhost:27017')
# DATABASE_NAME = os.getenv('MONGODB_DATABASE', 'multitenant_auth_db')
MONGODB_URL = "mongodb+srv://absar:absar12345@cluster0.f18xqed.mongodb.net/"
DATABASE_NAME = "multitenant_auth_db"
TELNYX_PUBLIC_KEY = os.getenv("TELNYX_PUBLIC_KEY", "").strip()  # Base64 string
TELNYX_WEBHOOK_SECRET = os.getenv("TELNYX_WEBHOOK_SECRET", "").strip()  # For v1 HMAC

# Global variables
_db_client = None
_database = None
_INDEX_READY = False

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

def ensure_indices_once(db):
    """Ensure required indices are created once."""
    global _INDEX_READY
    if _INDEX_READY:
        return
    
    try:
        # Create indices for telnyx_webhook_events collection
        db["telnyx_webhook_events"].create_index("event_id", unique=True)
        db["telnyx_webhook_events"].create_index([("event_type", 1), ("occurred_at", -1)])
        db["telnyx_webhook_events"].create_index("first_seen_at")
        
        # Create indices for telnyx_messages collection
        db["telnyx_messages"].create_index("message_id", unique=True)
        db["telnyx_messages"].create_index([("direction", 1), ("created_at", -1)])
        db["telnyx_messages"].create_index([("from", 1), ("created_at", -1)])
        db["telnyx_messages"].create_index([("status", 1), ("created_at", -1)])
        db["telnyx_messages"].create_index("messaging_profile_id")
        
        _INDEX_READY = True
        logger.info("Successfully created indices for Telnyx webhook collections.")
    except Exception as e:
        logger.error(f"Failed to create indices: {e}")

# Signature verification helpers
def _verify_v2_signature(timestamp: str, raw_body: bytes, signature_b64: str, public_key_b64: str) -> bool:
    """
    Verify Telnyx API v2 webhook (Ed25519) using public key.
    Signed message = f"{timestamp}|{raw_json}"
    """
    if not NACL_AVAILABLE:
        logger.warning("PyNaCl not available; skipping v2 signature verification.")
        return False
        
    if not public_key_b64:
        logger.warning("TELNYX_PUBLIC_KEY not set; skipping v2 verification.")
        return False

    try:
        signed = f"{timestamp}|{raw_body.decode('utf-8')}".encode("utf-8")
        sig = base64.b64decode(signature_b64)
        verify_key = VerifyKey(base64.b64decode(public_key_b64))
        verify_key.verify(signed, sig)
        return True
    except BadSignatureError:
        logger.exception("Telnyx v2 webhook signature verification failed (BadSignature).")
        return False
    except Exception:
        logger.exception("Telnyx v2 webhook signature verification failed (Exception).")
        return False

def _verify_v1_signature(signature_header: str, raw_body: bytes, secret: str = None) -> bool:
    """
    Verify Telnyx API v1 webhook using HMAC-SHA256.
    Format: t=<timestamp>,v1=<signature>
    """
    if not secret:
        secret = TELNYX_WEBHOOK_SECRET
        
    if not secret:
        logger.warning("TELNYX_WEBHOOK_SECRET not set; skipping v1 verification.")
        return False

    try:
        # Parse signature header
        sig_parts = {}
        for part in signature_header.split(','):
            if '=' in part:
                key, value = part.split('=', 1)
                sig_parts[key] = value
        
        timestamp = sig_parts.get('t')
        signature = sig_parts.get('v1')
        
        if not timestamp or not signature:
            logger.error("Invalid signature header format")
            return False
        
        # Create signed payload
        signed_payload = f"{timestamp}.{raw_body.decode('utf-8')}"
        
        # Compute expected signature
        expected_sig = hmac.new(
            secret.encode('utf-8'),
            signed_payload.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        # Compare signatures
        return hmac.compare_digest(signature, expected_sig)
        
    except Exception:
        logger.exception("Telnyx v1 webhook signature verification failed.")
        return False

# Event normalizer
def _normalize_event(evt: Dict[str, Any]) -> Dict[str, Any]:
    """
    Produce a convenient, flattened record for quick querying,
    while preserving the full original payload too.
    Works for `message.received`, `message.sent`, `message.finalized`, etc.
    """
    data = evt.get("data", {})
    event_type = data.get("event_type")
    event_id = data.get("id")
    occurred_at = data.get("occurred_at")

    payload = data.get("payload", {}) or {}
    # Common payload fields across inbound/outbound:
    message_id = payload.get("id")
    direction = payload.get("direction")
    msg_type = payload.get("type")  # 'SMS' or 'MMS'
    text = payload.get("text")
    encoding = payload.get("encoding")
    errors = payload.get("errors") or []
    cost = payload.get("cost") or {}
    media = payload.get("media") or []  # MMS list
    profile_id = payload.get("messaging_profile_id")

    # 'from' and 'to' shapes differ in v2 (objects/arrays); normalize to simple strings.
    from_addr = None
    if isinstance(payload.get("from"), dict):
        from_addr = payload["from"].get("phone_number") or payload["from"].get("address")
    elif isinstance(payload.get("from"), str):
        from_addr = payload["from"]

    to_list = []
    raw_to = payload.get("to", [])
    if isinstance(raw_to, list):
        for entry in raw_to:
            if isinstance(entry, dict):
                to_list.append(entry.get("phone_number") or entry.get("address"))
            elif isinstance(entry, str):
                to_list.append(entry)
    elif isinstance(raw_to, str):
        to_list = [raw_to]

    status = payload.get("status")  # often present in outbound lifecycle
    timestamps = {
        "received_at": payload.get("received_at"),
        "sent_at": payload.get("sent_at"),
        "completed_at": payload.get("completed_at"),
    }

    normalized = {
        "event_id": event_id,
        "event_type": event_type,
        "occurred_at": occurred_at,
        "message_id": message_id,
        "direction": direction,
        "type": msg_type,
        "from": from_addr,
        "to": to_list,
        "text": text,
        "encoding": encoding,
        "media": media,
        "errors": errors,
        "cost": cost,
        "status": status,
        "messaging_profile_id": profile_id,
        "timestamps": timestamps,
        # Keep the whole thing, too:
        "raw_event": evt,
        "ingested_at": datetime.now(timezone.utc).isoformat(),
    }
    return normalized

# Create Blueprint for Telnyx webhook routes
telnyx_bp = Blueprint('telnyx_webhooks', __name__, url_prefix='/webhooks/telnyx')

@telnyx_bp.route('/sms/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({
        "ok": True, 
        "ts": datetime.now(timezone.utc).isoformat(),
        "service": "Telnyx SMS/MMS Webhook",
        "nacl_available": NACL_AVAILABLE
    })

@telnyx_bp.route('/sms', methods=['POST'])
def telnyx_sms_webhook():
    """
    Receives Telnyx messaging webhooks (SMS/MMS API v2).
    - Verifies signature (v2 Ed25519; optional v1 fallback)
    - Upserts event into `telnyx_webhook_events`
    - Upserts normalized message row into `telnyx_messages`
    """
    try:
        # 1) Read raw body for signature verification
        raw_body = request.get_data()
        
        # Quick parse (after we have the raw bytes)
        try:
            event = json.loads(raw_body.decode("utf-8"))
        except Exception:
            logger.exception("Invalid JSON in webhook body.")
            raise BadRequest("Invalid JSON")

        # 2) Verify signature (prefer v2; fallback to v1 only if needed)
        headers = request.headers
        v2_sig = headers.get("telnyx-signature-ed25519") or headers.get("Telnyx-Signature-Ed25519")
        v2_ts = headers.get("telnyx-timestamp") or headers.get("Telnyx-Timestamp")

        verified = False
        verification_method = "none"
        
        # Try v2 signature first (Ed25519)
        if v2_sig and v2_ts:
            verified = _verify_v2_signature(v2_ts, raw_body, v2_sig, TELNYX_PUBLIC_KEY)
            if verified:
                verification_method = "ed25519"

        # Fallback to v1 signature (HMAC-SHA256)
        if not verified:
            v1_sig = headers.get("x-telnyx-signature") or headers.get("X-Telnyx-Signature")
            if v1_sig:
                verified = _verify_v1_signature(v1_sig, raw_body)
                if verified:
                    verification_method = "hmac-sha256"

        # In development, you might want to allow unverified webhooks
        # Uncomment the next line for development only:
        # verified = True if os.getenv('FLASK_ENV') == 'development' else verified

        if not verified:
            logger.error(f"Webhook signature verification failed. Headers: {dict(headers)}")
            raise Unauthorized("Invalid Telnyx signature")

        logger.info(f"Webhook verified using {verification_method}")

        # 3) Normalize + store
        db = get_database()
        if db is None:
            raise ServiceUnavailable("Database connection failed")
        
        ensure_indices_once(db)

        normalized = _normalize_event(event)
        event_id = normalized.get("event_id")
        message_id = normalized.get("message_id")

        now_utc = datetime.now(timezone.utc)

        if not event_id:
            logger.warning("Missing event id in webhook.")
        if not message_id:
            logger.warning("Missing message id in payload.")

        # Log normalized event for debugging (truncate text for privacy)
        log_normalized = normalized.copy()
        if log_normalized.get("text") and len(log_normalized["text"]) > 50:
            log_normalized["text"] = log_normalized["text"][:50] + "..."
        logger.info(f"Processing event: {log_normalized.get('event_type')} for message: {message_id}")

        # (a) Store raw event (idempotent)
        if event_id:
            db.telnyx_webhook_events.update_one(
                {"event_id": event_id},
                {
                    "$setOnInsert": {
                        "event_id": event_id,
                        "first_seen_at": now_utc,
                    },
                    "$set": {
                        "event_type": normalized.get("event_type"),
                        "occurred_at": normalized.get("occurred_at"),
                        "raw_event": normalized.get("raw_event"),
                        "last_seen_at": now_utc,
                        "verification_method": verification_method,
                    },
                },
                upsert=True,
            )

        # (b) Upsert message record with latest info
        if message_id:
            set_doc = {
                # IMPORTANT: do NOT include "message_id" here (it's in the filter)
                "direction": normalized.get("direction"),
                "type": normalized.get("type"),
                "from": normalized.get("from"),
                "to": normalized.get("to"),
                "text": normalized.get("text"),
                "encoding": normalized.get("encoding"),
                "media": normalized.get("media"),
                "errors": normalized.get("errors"),
                "cost": normalized.get("cost"),
                "status": normalized.get("status"),
                "messaging_profile_id": normalized.get("messaging_profile_id"),
                "timestamps": normalized.get("timestamps"),
                "last_event_type": normalized.get("event_type"),
                "last_event_id": event_id,
                "last_occurred_at": normalized.get("occurred_at"),
                "updated_at": now_utc,
                "verification_method": verification_method,
            }

            update_ops = {
                "$setOnInsert": {
                    "message_id": message_id,
                    "created_at": now_utc,
                },
                "$set": set_doc,
            }

            # Only add this operator if we have an event_id
            if event_id:
                update_ops["$addToSet"] = {"event_ids": event_id}

            result = db.telnyx_messages.update_one(
                {"message_id": message_id},
                update_ops,
                upsert=True,
            )
            
            logger.info(f"Message {'updated' if result.matched_count > 0 else 'created'}: {message_id}")

        # 4) Return quickly—Telnyx retries if not 2xx
        return jsonify({
            "ok": True,

            "event_id": event_id,
            "message_id": message_id,
            "verification_method": verification_method,
            "processed_at": now_utc.isoformat()
        })

    except (BadRequest, Unauthorized, ServiceUnavailable):
        raise
    except Exception as e:
        logger.exception("Failed to process Telnyx webhook.")
        # Return 2xx to avoid repeated retries if you prefer; here we return 500 to surface issues.
        raise InternalServerError(f"Processing error: {str(e)}")

# API routes for message management
api_bp = Blueprint('telnyx_webhooks_api', __name__, url_prefix='/api/telnyx')

@api_bp.route('/messages', methods=['GET'])
def list_messages():
    """List recent messages with filtering options"""
    try:
        # Query parameters
        limit = min(int(request.args.get('limit', 50)), 1000)  # Max 1000
        skip = int(request.args.get('skip', 0))
        direction = request.args.get('direction')  # 'inbound' or 'outbound'
        status = request.args.get('status')
        from_number = request.args.get('from')
        to_number = request.args.get('to')
        message_type = request.args.get('type')  # 'SMS' or 'MMS'
        
        db = get_database()
        if db is None:
            raise ServiceUnavailable("Database connection failed")
        
        # Build query filter
        query_filter = {}
        if direction:
            query_filter["direction"] = direction
        if status:
            query_filter["status"] = status
        if from_number:
            query_filter["from"] = from_number
        if to_number:
            query_filter["to"] = {"$in": [to_number]}
        if message_type:
            query_filter["type"] = message_type
        
        messages_collection = db.telnyx_messages
        
        # Get messages with pagination
        messages = list(messages_collection.find(
            query_filter,
            {"_id": 0}  # Exclude MongoDB ObjectId
        ).sort("created_at", -1).skip(skip).limit(limit))
        
        # Get total count for pagination info
        total = messages_collection.count_documents(query_filter)
        
        return jsonify({
            "messages": messages,
            "pagination": {
                "total": total,
                "limit": limit,
                "skip": skip,
                "has_more": skip + limit < total
            },
            "filters": {
                "direction": direction,
                "status": status,
                "from": from_number,
                "to": to_number,
                "type": message_type
            }
        })
        
    except ServiceUnavailable:
        raise
    except Exception as e:
        logger.error(f"Error listing messages: {e}")
        raise InternalServerError(str(e))

@api_bp.route('/messages/<message_id>', methods=['GET'])
def get_message(message_id):
    """Get a specific message by ID"""
    try:
        db = get_database()
        if db is None:
            raise ServiceUnavailable("Database connection failed")
        
        message = db.telnyx_messages.find_one(
            {"message_id": message_id},
            {"_id": 0}
        )
        
        if not message:
            raise NotFound(f"Message {message_id} not found")
        
        return jsonify(message)
        
    except (NotFound, ServiceUnavailable):
        raise
    except Exception as e:
        logger.error(f"Error retrieving message: {e}")
        raise InternalServerError(str(e))

@api_bp.route('/events', methods=['GET'])
def list_events():
    """List recent webhook events"""
    try:
        limit = min(int(request.args.get('limit', 50)), 1000)
        skip = int(request.args.get('skip', 0))
        event_type = request.args.get('event_type')
        
        db = get_database()
        if db is None:
            raise ServiceUnavailable("Database connection failed")
        
        query_filter = {}
        if event_type:
            query_filter["event_type"] = event_type
        
        events_collection = db.telnyx_webhook_events
        
        events = list(events_collection.find(
            query_filter,
            {"_id": 0, "raw_event": 0}  # Exclude ObjectId and raw_event for performance
        ).sort("first_seen_at", -1).skip(skip).limit(limit))
        
        total = events_collection.count_documents(query_filter)
        
        return jsonify({
            "events": events,
            "pagination": {
                "total": total,
                "limit": limit,
                "skip": skip,
                "has_more": skip + limit < total
            }
        })
        
    except ServiceUnavailable:
        raise
    except Exception as e:
        logger.error(f"Error listing events: {e}")
        raise InternalServerError(str(e))

@api_bp.route('/events/<event_id>', methods=['GET'])
def get_event(event_id):
    """Get a specific event by ID (including raw event data)"""
    try:
        db = get_database()
        if db is None:
            raise ServiceUnavailable("Database connection failed")
        
        event = db.telnyx_webhook_events.find_one(
            {"event_id": event_id},
            {"_id": 0}
        )
        
        if not event:
            raise NotFound(f"Event {event_id} not found")
        
        return jsonify(event)
        
    except (NotFound, ServiceUnavailable):
        raise
    except Exception as e:
        logger.error(f"Error retrieving event: {e}")
        raise InternalServerError(str(e))

@api_bp.route('/stats', methods=['GET'])
def get_stats():
    """Get webhook processing statistics"""
    try:
        db = get_database()
        if db is None:
            raise ServiceUnavailable("Database connection failed")
        
        # Get message statistics
        message_stats = list(db.telnyx_messages.aggregate([
            {
                "$group": {
                    "_id": None,
                    "total_messages": {"$sum": 1},
                    "inbound_count": {
                        "$sum": {"$cond": [{"$eq": ["$direction", "inbound"]}, 1, 0]}
                    },
                    "outbound_count": {
                        "$sum": {"$cond": [{"$eq": ["$direction", "outbound"]}, 1, 0]}
                    },
                    "sms_count": {
                        "$sum": {"$cond": [{"$eq": ["$type", "SMS"]}, 1, 0]}
                    },
                    "mms_count": {
                        "$sum": {"$cond": [{"$eq": ["$type", "MMS"]}, 1, 0]}
                    }
                }
            }
        ]))
        
        # Get event statistics
        event_stats = list(db.telnyx_webhook_events.aggregate([
            {
                "$group": {
                    "_id": "$event_type",
                    "count": {"$sum": 1},
                    "last_seen": {"$max": "$last_seen_at"}
                }
            },
            {"$sort": {"count": -1}}
        ]))
        
        # Get recent activity (last 24 hours)
        last_24h = datetime.now(timezone.utc) - timedelta(hours=24)
        recent_count = db.telnyx_messages.count_documents({
            "created_at": {"$gte": last_24h}
        })
        
        return jsonify({
            "message_stats": message_stats[0] if message_stats else {},
            "event_types": event_stats,
            "recent_activity": {
                "last_24h_messages": recent_count,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        })
        
    except ServiceUnavailable:
        raise
    except Exception as e:
        logger.error(f"Error getting stats: {e}")
        raise InternalServerError(str(e))

# Error handlers
def bad_request(error):
    return jsonify({"error": "Bad request", "message": str(error.description)}), 400

def unauthorized(error):
    return jsonify({"error": "Unauthorized", "message": str(error.description)}), 401

def not_found(error):
    return jsonify({"error": "Not found", "message": str(error.description)}), 404

def internal_error(error):
    return jsonify({"error": "Internal server error", "message": "Something went wrong"}), 500

def service_unavailable(error):
    return jsonify({"error": "Service unavailable", "message": str(error.description)}), 503

# Function to create app (for integration with main Flask app)
def create_telnyx_webhook_bp():
    """Create and return the telnyx webhook blueprint"""
    return telnyx_bp, api_bp

# Standalone app for testing
if __name__ == '__main__':
    # Create Flask app for standalone testing
    app = Flask(__name__)
    app.config['JSON_SORT_KEYS'] = False
    
    # Register error handlers
    app.register_error_handler(400, bad_request)
    app.register_error_handler(401, unauthorized)
    app.register_error_handler(404, not_found)
    app.register_error_handler(500, internal_error)
    app.register_error_handler(503, service_unavailable)
    
    # Register blueprints
    app.register_blueprint(telnyx_bp)
    app.register_blueprint(api_bp)
    
    # Root route
    @app.route('/')
    def index():
        """Root endpoint with API information"""
        return jsonify({
            "service": "Telnyx SMS/MMS Webhook Backend",
            "version": "1.0.0",
            "status": "running",
            "nacl_available": NACL_AVAILABLE,
            "endpoints": {
                "webhooks": {
                    "sms": "/webhooks/telnyx/sms",
                    "health": "/webhooks/telnyx/sms/health"
                },
                "api": {
                    "messages": "/api/telnyx/messages",
                    "message_detail": "/api/telnyx/messages/{message_id}",
                    "events": "/api/telnyx/events",
                    "event_detail": "/api/telnyx/events/{event_id}",
                    "stats": "/api/telnyx/stats"
                }
            }
        })
    
    # Initialize database on startup
    with app.app_context():
        try:
            db = get_database()
            if db is not None:
                ensure_indices_once(db)
                logger.info("Database initialized successfully")
            else:
                logger.error("Failed to initialize database")
        except Exception as e:
            logger.error(f"Error initializing database: {e}")
    
    # Validate required environment variables
    if not TELNYX_PUBLIC_KEY and not TELNYX_WEBHOOK_SECRET:
        logger.warning("Neither TELNYX_PUBLIC_KEY nor TELNYX_WEBHOOK_SECRET is set. Webhook signature verification will be disabled.")
    
    # For development only
    app.run(
        host='0.0.0.0',
        port=int(os.getenv('PORT', 5001)),
        debug=os.getenv('FLASK_ENV') == 'development'
    )