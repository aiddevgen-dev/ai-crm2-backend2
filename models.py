"""
Database models for the multi-tenant application
"""
from datetime import datetime, timedelta
from bson import ObjectId
from flask_pymongo import PyMongo
from flask_bcrypt import Bcrypt
import secrets
import uuid

mongo = PyMongo()
bcrypt = Bcrypt()

class TenantModel:
    """Model for handling tenant operations"""
    
    @staticmethod
    def create_tenant(name=None):
        """Create a new tenant"""
        if not name:
            name = f"Tenant-{str(uuid.uuid4())[:8]}"
        
        tenant_data = {
            'name': name,
            'created_at': datetime.utcnow(),
            'updated_at': datetime.utcnow(),
            'status': 'active'
        }
        
        result = mongo.db.tenants.insert_one(tenant_data)
        return str(result.inserted_id)
    
    @staticmethod
    def get_tenant_by_id(tenant_id):
        """Get tenant by ID"""
        try:
            return mongo.db.tenants.find_one({'_id': ObjectId(tenant_id)})
        except:
            return None

class UserModel:
    """Model for handling user operations"""
    
    @staticmethod
    def create_user(email, password, tenant_id):
        """Create a new user"""
        # Check if user already exists
        if UserModel.get_user_by_email(email):
            return None
        
        hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')
        
        user_data = {
            'email': email.lower(),
            'password': hashed_password,
            'tenant_id': ObjectId(tenant_id),
            'created_at': datetime.utcnow(),
            'updated_at': datetime.utcnow(),
            'status': 'active',
            'reset_token': None,
            'reset_token_expires': None
        }
        
        result = mongo.db.users.insert_one(user_data)
        return str(result.inserted_id)
    
    @staticmethod
    def get_user_by_email(email):
        """Get user by email"""
        return mongo.db.users.find_one({'email': email.lower()})
    
    @staticmethod
    def get_user_by_id(user_id):
        """Get user by ID"""
        try:
            return mongo.db.users.find_one({'_id': ObjectId(user_id)})
        except:
            return None
    
    @staticmethod
    def verify_password(stored_password, provided_password):
        """Verify password"""
        return bcrypt.check_password_hash(stored_password, provided_password)
    
    @staticmethod
    def generate_reset_token(email):
        """Generate password reset token"""
        user = UserModel.get_user_by_email(email)
        if not user:
            return None
        
        # Generate secure token
        reset_token = secrets.token_urlsafe(32)
        expires_at = datetime.utcnow() + timedelta(hours=1)  # Token expires in 1 hour
        
        # Update user with reset token
        mongo.db.users.update_one(
            {'_id': user['_id']},
            {
                '$set': {
                    'reset_token': reset_token,
                    'reset_token_expires': expires_at,
                    'updated_at': datetime.utcnow()
                }
            }
        )
        
        return reset_token
    
    @staticmethod
    def reset_password(token, new_password):
        """Reset password using token"""
        user = mongo.db.users.find_one({
            'reset_token': token,
            'reset_token_expires': {'$gt': datetime.utcnow()}
        })
        
        if not user:
            return False
        
        # Hash new password
        hashed_password = bcrypt.generate_password_hash(new_password).decode('utf-8')
        
        # Update user password and clear reset token
        mongo.db.users.update_one(
            {'_id': user['_id']},
            {
                '$set': {
                    'password': hashed_password,
                    'updated_at': datetime.utcnow()
                },
                '$unset': {
                    'reset_token': '',
                    'reset_token_expires': ''
                }
            }
        )
        
        return True
    
    @staticmethod
    def update_user(user_id, update_data):
        """Update user data"""
        try:
            update_data['updated_at'] = datetime.utcnow()
            result = mongo.db.users.update_one(
                {'_id': ObjectId(user_id)},
                {'$set': update_data}
            )
            return result.modified_count > 0
        except:
            return False
        

class CampaignModel:
    """Model for handling campaign operations"""
    
    @staticmethod
    def create_campaign(name, description, tenant_id, user_id):
        """Create a new campaign"""
        campaign_data = {
            'name': name,
            'description': description,
            'tenant_id': ObjectId(tenant_id),
            'created_by': ObjectId(user_id),
            'status': 'draft',
            'leads_count': 0,
            'created_at': datetime.utcnow(),
            'updated_at': datetime.utcnow()
        }
        
        result = mongo.db.campaigns.insert_one(campaign_data)
        return str(result.inserted_id)
    
    @staticmethod
    def get_campaigns_by_tenant(tenant_id, skip=0, limit=10):
        """Get campaigns for a tenant with pagination"""
        try:
            campaigns = list(mongo.db.campaigns.find(
                {'tenant_id': ObjectId(tenant_id)}
            ).skip(skip).limit(limit).sort('created_at', -1))
            
            # Convert ObjectIds to strings
            for campaign in campaigns:
                campaign['_id'] = str(campaign['_id'])
                campaign['tenant_id'] = str(campaign['tenant_id'])
                campaign['created_by'] = str(campaign['created_by'])
            
            return campaigns
        except:
            return []
    
    @staticmethod
    def get_campaign_by_id(campaign_id, tenant_id):
        """Get campaign by ID (with tenant isolation)"""
        try:
            campaign = mongo.db.campaigns.find_one({
                '_id': ObjectId(campaign_id),
                'tenant_id': ObjectId(tenant_id)
            })
            
            if campaign:
                campaign['_id'] = str(campaign['_id'])
                campaign['tenant_id'] = str(campaign['tenant_id'])
                campaign['created_by'] = str(campaign['created_by'])
            
            return campaign
        except:
            return None

class LeadModel:
    """Model for handling lead operations"""
    
    @staticmethod
    def create_lead(name, email, phone, campaign_id, tenant_id, user_id):
        """Create a new lead"""
        lead_data = {
            'name': name,
            'email': email.lower() if email else None,
            'phone': phone,
            'campaign_id': ObjectId(campaign_id) if campaign_id else None,
            'tenant_id': ObjectId(tenant_id),
            'created_by': ObjectId(user_id),
            'status': 'new',
            'notes': [],
            'created_at': datetime.utcnow(),
            'updated_at': datetime.utcnow()
        }
        
        result = mongo.db.leads.insert_one(lead_data)
        return str(result.inserted_id)
    
    @staticmethod
    def get_leads_by_tenant(tenant_id, skip=0, limit=10):
        """Get leads for a tenant with pagination"""
        try:
            leads = list(mongo.db.leads.find(
                {'tenant_id': ObjectId(tenant_id)}
            ).skip(skip).limit(limit).sort('created_at', -1))
            
            # Convert ObjectIds to strings
            for lead in leads:
                lead['_id'] = str(lead['_id'])
                lead['tenant_id'] = str(lead['tenant_id'])
                lead['created_by'] = str(lead['created_by'])
                if lead.get('campaign_id'):
                    lead['campaign_id'] = str(lead['campaign_id'])
            
            return leads
        except:
            return []

class AppointmentModel:
    """Model for handling appointment operations"""
    
    @staticmethod
    def create_appointment(title, description, lead_id, scheduled_at, tenant_id, user_id):
        """Create a new appointment"""
        appointment_data = {
            'title': title,
            'description': description,
            'lead_id': ObjectId(lead_id) if lead_id else None,
            'scheduled_at': scheduled_at,
            'tenant_id': ObjectId(tenant_id),
            'created_by': ObjectId(user_id),
            'status': 'scheduled',
            'created_at': datetime.utcnow(),
            'updated_at': datetime.utcnow()
        }
        
        result = mongo.db.appointments.insert_one(appointment_data)
        return str(result.inserted_id)
    
    @staticmethod
    def get_appointments_by_tenant(tenant_id, skip=0, limit=10):
        """Get appointments for a tenant with pagination"""
        try:
            appointments = list(mongo.db.appointments.find(
                {'tenant_id': ObjectId(tenant_id)}
            ).skip(skip).limit(limit).sort('scheduled_at', 1))
            
            # Convert ObjectIds to strings
            for appointment in appointments:
                appointment['_id'] = str(appointment['_id'])
                appointment['tenant_id'] = str(appointment['tenant_id'])
                appointment['created_by'] = str(appointment['created_by'])
                if appointment.get('lead_id'):
                    appointment['lead_id'] = str(appointment['lead_id'])
            
            return appointments
        except:
            return []

class RecordingModel:
    """Model for handling recording operations"""
    
    @staticmethod
    def create_recording(title, file_path, duration, appointment_id, tenant_id, user_id):
        """Create a new recording"""
        recording_data = {
            'title': title,
            'file_path': file_path,
            'duration': duration,
            'appointment_id': ObjectId(appointment_id) if appointment_id else None,
            'tenant_id': ObjectId(tenant_id),
            'created_by': ObjectId(user_id),
            'transcription': None,
            'created_at': datetime.utcnow(),
            'updated_at': datetime.utcnow()
        }
        
        result = mongo.db.recordings.insert_one(recording_data)
        return str(result.inserted_id)
    
    @staticmethod
    def get_recordings_by_tenant(tenant_id, skip=0, limit=10):
        """Get recordings for a tenant with pagination"""
        try:
            recordings = list(mongo.db.recordings.find(
                {'tenant_id': ObjectId(tenant_id)}
            ).skip(skip).limit(limit).sort('created_at', -1))
            
            # Convert ObjectIds to strings
            for recording in recordings:
                recording['_id'] = str(recording['_id'])
                recording['tenant_id'] = str(recording['tenant_id'])
                recording['created_by'] = str(recording['created_by'])
                if recording.get('appointment_id'):
                    recording['appointment_id'] = str(recording['appointment_id'])
            
            return recordings
        except:
            return []

class KnowledgeBaseModel:
    """Model for handling knowledge base operations"""
    
    @staticmethod
    def create_article(title, content, category, tenant_id, user_id):
        """Create a new knowledge base article"""
        article_data = {
            'title': title,
            'content': content,
            'category': category,
            'tenant_id': ObjectId(tenant_id),
            'created_by': ObjectId(user_id),
            'status': 'published',
            'views': 0,
            'created_at': datetime.utcnow(),
            'updated_at': datetime.utcnow()
        }
        
        result = mongo.db.knowledge_base.insert_one(article_data)
        return str(result.inserted_id)
    
    @staticmethod
    def get_articles_by_tenant(tenant_id, skip=0, limit=10):
        """Get knowledge base articles for a tenant with pagination"""
        try:
            articles = list(mongo.db.knowledge_base.find(
                {'tenant_id': ObjectId(tenant_id)}
            ).skip(skip).limit(limit).sort('created_at', -1))
            
            # Convert ObjectIds to strings
            for article in articles:
                article['_id'] = str(article['_id'])
                article['tenant_id'] = str(article['tenant_id'])
                article['created_by'] = str(article['created_by'])
            
            return articles
        except:
            return []
