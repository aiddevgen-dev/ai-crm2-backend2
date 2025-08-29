"""
Main Flask application file for multi-tenant authentication system
samad.aidevgen@gmail.com
test123-45
"""
import os
import logging
from flask import Flask, jsonify, request
from flask_cors import CORS
from config import config
from models import mongo, bcrypt
from routes.auth_routes import auth_bp
from routes.campaign_routes import campaign_bp
from routes.lead_routes import lead_bp
from routes.appointment_routes import appointment_bp
from routes.recording_routes import recording_bp
from routes.knowledge_routes import knowledge_bp
from routes.register_tenants import register_tenants_bp
from routes.tenants_auth_routes import tenant_auth_bp
from routes.telnyx_routes import telnyx_bp
from routes.tenant_user_routes import tenant_user_bp
from routes.agent_routes import agents_bp
# Add these imports after your existing route imports
from webhook.pipecat import create_pipecat_webhook_bp
from webhook.telnyx import create_telnyx_webhook_bp
from webhook.tools_webhook import create_tools_webhook_bp
from flask_mail import Mail 
from authlib.integrations.flask_client import OAuth

mail = Mail()

def create_app(config_name=None):
    """Application factory pattern"""
    if config_name is None:
        config_name = os.getenv('FLASK_ENV', 'default')
    
    app = Flask(__name__)
    
    # Load configuration
    app.config.from_object(config[config_name])
    # Add Google OAuth configuration
    app.config['GOOGLE_CLIENT_ID'] = os.getenv('GOOGLE_CLIENT_ID')
    app.config['GOOGLE_CLIENT_SECRET'] = os.getenv('GOOGLE_CLIENT_SECRET')
    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'your-secret-key')
    
    # Initialize extensions
    mongo.init_app(app)
    bcrypt.init_app(app)

    
    # Initialize CORS
    # Initialize CORS (echoes the exact Origin, required for credentials)
    ALLOWED_ORIGINS = [
        "https://the-crm-ai.vercel.app",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]

    CORS(
        app,
        resources={r"/*": {"origins": ALLOWED_ORIGINS}},
        supports_credentials=True
    )

    pipecat_webhook_bp, pipecat_api_bp = create_pipecat_webhook_bp()
    telnyx_webhook_bp, telnyx_api_bp = create_telnyx_webhook_bp()
    tools_bp = create_tools_webhook_bp()  # Add this line
    # Register blueprints
    app.register_blueprint(auth_bp)
    app.register_blueprint(campaign_bp)
    app.register_blueprint(lead_bp)
    app.register_blueprint(appointment_bp)
    app.register_blueprint(recording_bp)
    app.register_blueprint(knowledge_bp)
    app.register_blueprint(register_tenants_bp)
    app.register_blueprint(tenant_auth_bp)
    app.register_blueprint(telnyx_bp)
    app.register_blueprint(tenant_user_bp)
    app.register_blueprint(pipecat_webhook_bp)
    app.register_blueprint(pipecat_api_bp)
    app.register_blueprint(telnyx_webhook_bp) 
    app.register_blueprint(telnyx_api_bp)
    app.register_blueprint(tools_bp) 
    app.register_blueprint(agents_bp)
    # Setup logging
    setup_logging(app)
        # --- Force CORS headers for all responses ---
    @app.after_request
    def add_cors_headers(resp):
        origin = request.headers.get("Origin")
        if origin in ALLOWED_ORIGINS:
            resp.headers["Access-Control-Allow-Origin"] = origin
            resp.headers["Vary"] = "Origin"
            resp.headers["Access-Control-Allow-Credentials"] = "true"
            resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
            resp.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
        return resp

    @app.before_request
    def handle_preflight():
        if request.method == "OPTIONS":
            return ("", 204)

    
    # Create database indexes
    create_indexes(app)
    
    # Error handlers
    setup_error_handlers(app)
    mail.init_app(app)
    # Initialize OAuth
    oauth = create_oauth(app)
    # Health check route
    @app.route('/health', methods=['GET'])
    def health_check():
        """Health check endpoint"""
        return jsonify({
            'status': 'healthy',
            'message': 'Multi-tenant auth service is running',
            'version': '1.0.0'
        }), 200
    
    # Root route
    @app.route('/', methods=['GET'])
    def root():
        """Root endpoint with API information"""
        return jsonify({
            'message': 'Multi-tenant Authentication API',
            'version': '1.0.0',
            'endpoints': {
                'auth': {
                    'register': 'POST /auth/register',
                    'login': 'POST /auth/login',
                    'forgot_password': 'POST /auth/forgot-password',
                    'reset_password': 'POST /auth/reset-password',
                    'validate_token': 'POST /auth/validate-token',
                    'me': 'GET /auth/me (requires token)'
                },
                'health': 'GET /health'
            }
        }), 200
    
    return app

def setup_logging(app):
    """Setup application logging"""
    # Disable MongoDB debug logs
    logging.getLogger('pymongo').setLevel(logging.WARNING)
    
    if not app.debug:
        # Production logging
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s %(levelname)s: %(message)s'
        )
    else:
        # Development logging - only show INFO and above
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s %(levelname)s: %(message)s'
        )

def create_indexes(app):
    """Create database indexes for better performance"""
    with app.app_context():
        try:
            # Create index on users email field (unique)
            mongo.db.users.create_index("email", unique=True)
            
            # Create index on users tenant_id field
            mongo.db.users.create_index("tenant_id")
            
            # Create index on users reset_token field
            mongo.db.users.create_index("reset_token", sparse=True)
            
            # Create index on tenants name field
            mongo.db.tenants.create_index("name")
            
            app.logger.info("Database indexes created successfully")
        except Exception as e:
            app.logger.warning(f"Index creation warning: {str(e)}")

def setup_error_handlers(app):
    """Setup global error handlers"""
    
    @app.errorhandler(400)
    def bad_request(error):
        return jsonify({'error': 'Bad request'}), 400
    
    @app.errorhandler(401)
    def unauthorized(error):
        return jsonify({'error': 'Unauthorized'}), 401
    
    @app.errorhandler(403)
    def forbidden(error):
        return jsonify({'error': 'Forbidden'}), 403
    
    @app.errorhandler(404)
    def not_found(error):
        return jsonify({'error': 'Not found'}), 404
    
    @app.errorhandler(405)
    def method_not_allowed(error):
        return jsonify({'error': 'Method not allowed'}), 405
    
    @app.errorhandler(500)
    def internal_error(error):
        return jsonify({'error': 'Internal server error'}), 500
    

def create_oauth(app):
    """Initialize OAuth for Google Calendar integration"""
    oauth = OAuth(app)
    app.oauth = oauth
    
    oauth.register(
        name='google_calendar',
        client_id=app.config.get('GOOGLE_CLIENT_ID'),
        client_secret=app.config.get('GOOGLE_CLIENT_SECRET'),
        access_token_url='https://oauth2.googleapis.com/token',
        access_token_params=None,
        authorize_url='https://accounts.google.com/o/oauth2/v2/auth',
        authorize_params=None,
        api_base_url='https://www.googleapis.com/calendar/v3/',
        server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
        client_kwargs={
            'scope': 'https://www.googleapis.com/auth/calendar https://www.googleapis.com/auth/userinfo.email',
            'access_type': 'offline',
            'prompt': 'consent',
            'include_granted_scopes': 'true'
        }
    )
    
    return oauth
# Create app instance
app = create_app()

if __name__ == '__main__':
    # Development server
    app.run(
        host='0.0.0.0',
        port=5000,
        debug=app.config.get('DEBUG', False)
    )