"""
Synchronous authentication and utility functions converted for a Flask application.
"""
import logging
import hashlib
import secrets
import bcrypt
import jwt
from bson import ObjectId
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

# Import the mongo instance from your models file, which is the Flask standard
from models import mongo
from flask import current_app, request
from flask_mail import Message

# In-memory stores for rate limiting (can be replaced with Redis in production)
rate_limit_store = {}
failed_attempts_store = {}


def get_database():
    """
    Returns the current Flask-PyMongo database instance.
    This is a synchronous wrapper to provide the requested function,
    accessing the globally managed mongo connection.
    """
    return mongo.db


class AuthUtils:
    """A class to encapsulate authentication-related utility functions."""

    @staticmethod
    def hash_password(password: str) -> str:
        """Hash password using bcrypt."""
        salt = bcrypt.gensalt(rounds=current_app.config.get("BCRYPT_ROUNDS", 12))
        return bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')

    @staticmethod
    def verify_password(password: str, hashed: str) -> bool:
        """Verify password against a bcrypt hash."""
        return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))

    @staticmethod
    def generate_token(user_id: ObjectId, tenant_id: ObjectId, role: str = "admin") -> str:
        """
        Create JWT access token. This matches the existing token structure in your app.
        """
        try:
            payload = {
                'user_id': str(user_id),
                'tenant_id': str(tenant_id),
                'role': role,
                'exp': datetime.utcnow() + timedelta(hours=current_app.config.get('JWT_EXPIRATION_HOURS', 24)),
                'iat': datetime.utcnow()
            }
            return jwt.encode(payload, current_app.config['JWT_SECRET_KEY'], algorithm="HS256")
        except Exception as e:
            logging.error(f"Token creation failed: {e}")
            raise ValueError(f"Token creation failed: {e}")

    @staticmethod
    def decode_token(token: str) -> Optional[Dict[str, Any]]:
        """Decodes a JWT token and returns its payload."""
        try:
            payload = jwt.decode(token, current_app.config['JWT_SECRET_KEY'], algorithms=["HS256"])
            return payload
        except jwt.ExpiredSignatureError:
            logging.warning("Token has expired.")
            return None
        except jwt.InvalidTokenError as e:
            logging.error(f"Invalid token: {e}")
            return None

    @staticmethod
    def create_email_token(user_id: str, purpose: str = "verify") -> str:
        """Create JWT token for email verification or password reset."""
        try:
            payload = {
                "sub": user_id,
                "purpose": purpose,
                "exp": datetime.utcnow() + timedelta(hours=1), # Typically 1 hour expiry
                "iat": datetime.utcnow()
            }
            return jwt.encode(payload, current_app.config['JWT_SECRET_KEY'], algorithm="HS256")
        except Exception as e:
            logging.error(f"Email token creation failed: {e}")
            raise ValueError(f"Email token creation failed: {e}")

    @staticmethod
    def send_email(to_email: str, subject: str, html_content: str):
        """Send email using the Flask-Mail extension."""
        try:
            # Import the mail instance from your app factory
            from app import mail
            msg = Message(
                subject=subject,
                recipients=[to_email],
                html=html_content,
                sender=current_app.config.get('MAIL_DEFAULT_SENDER')
            )
            mail.send(msg)
        except Exception as e:
            logging.error(f"Email sending failed: {e}")
            raise ConnectionError(f"Email sending failed: {e}")

    @staticmethod
    def get_device_fingerprint() -> str:
        """Create a device fingerprint from the current Flask request."""
        user_agent = request.headers.get("user-agent", "")
        # Use request.remote_addr for the client's IP in Flask
        ip = request.remote_addr or "unknown"
        return f"{user_agent}|{ip}"

    @staticmethod
    def check_rate_limit(key: str, limit: int = 10) -> bool:
        """Check if a rate limit has been exceeded for a given key."""
        now = datetime.utcnow()
        one_minute_ago = now - timedelta(minutes=1)
        
        if key not in rate_limit_store:
            rate_limit_store[key] = []
        
        # Filter out timestamps older than one minute
        rate_limit_store[key] = [ts for ts in rate_limit_store[key] if ts > one_minute_ago]
        
        if len(rate_limit_store[key]) >= limit:
            return False # Limit exceeded
        
        rate_limit_store[key].append(now)
        return True # OK

    @staticmethod
    def to_object_id(id_str: str) -> Optional[ObjectId]:
        """Safely convert a string to a BSON ObjectId."""
        try:
            return ObjectId(id_str)
        except Exception:
            return None
