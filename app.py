"""
Main Flask application file for multi-tenant authentication system
samad.aidevgen@gmail.com
test123-45
"""
import os
import logging
from flask import Flask, jsonify
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
from flask_mail import Mail 
mail = Mail()

def create_app(config_name=None):
    """Application factory pattern"""
    if config_name is None:
        config_name = os.getenv('FLASK_ENV', 'default')
    
    app = Flask(__name__)
    
    # Load configuration
    app.config.from_object(config[config_name])
    
    # Initialize extensions
    mongo.init_app(app)
    bcrypt.init_app(app)

    
    # Initialize CORS
    CORS(app, 
         origins=['http://localhost:3000', 'http://127.0.0.1:3000', 'https://the-crm-ai.vercel.app' ], 
         supports_credentials=True,
         allow_headers=['Content-Type', 'Authorization'],
         methods=['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS'])
    
    # Register blueprints
    app.register_blueprint(auth_bp)
    app.register_blueprint(campaign_bp)
    app.register_blueprint(lead_bp)
    app.register_blueprint(appointment_bp)
    app.register_blueprint(recording_bp)
    app.register_blueprint(knowledge_bp)
    app.register_blueprint(register_tenants_bp)
    
    # Setup logging
    setup_logging(app)
    
    # Create database indexes
    create_indexes(app)
    
    # Error handlers
    setup_error_handlers(app)
    mail.init_app(app)
    
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

# Create app instance
app = create_app()

if __name__ == '__main__':
    # Development server
    app.run(
        host='0.0.0.0',
        port=5000,
        debug=app.config.get('DEBUG', False)
    )