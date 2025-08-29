from datetime import datetime
from typing import Optional
from bson import ObjectId
from pydantic import BaseModel, EmailStr, Field
from enum import Enum

class UserRole(str, Enum):
    PLATFORM_ADMIN = "platform_admin"
    COMPANY_ADMIN = "company_admin"
    TENANT_USER = "tenant_user"

class UserStatus(str, Enum):
    PENDING = "pending"
    ACTIVE = "active"
    LOCKED = "locked"
    SUSPENDED = "suspended"
    INACTIVE = "inactive"

class User(BaseModel):
    id: Optional[str] = Field(None, alias="_id")
    email: EmailStr
    password_hash: str
    role: UserRole = UserRole.COMPANY_ADMIN
    status: UserStatus = UserStatus.PENDING

    google_id: Optional[str] = None
    profile_picture: Optional[str] = None
    
    # Company and Tenant associations (optional for platform admins)
    company_id: Optional[str] = None
    tenant_id: Optional[str] = None
    
    # Profile information
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone: Optional[str] = None
    
    # Security fields
    failed_login_attempts: int = 0
    locked_until: Optional[datetime] = None
    email_verified: bool = False
    email_verified_at: Optional[datetime] = None
    
    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    last_login: Optional[datetime] = None
    
    # MFA fields (optional)
    mfa_enabled: bool = False
    mfa_secret: Optional[str] = None
    
    class Config:
        populate_by_name = True
        json_encoders = {
            ObjectId: str,
            datetime: lambda v: v.isoformat()
        }

class UserCreate(BaseModel):
    """Model for company user registration"""
    email: EmailStr
    password: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone: Optional[str] = None
    vertical: str
    tenant_id: Optional[str] = None
    role: UserRole = UserRole.TENANT_USER

class PlatformAdminCreate(BaseModel):
    """Model for platform admin creation"""
    email: EmailStr
    password: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone: Optional[str] = None
    # Note: No vertical field needed for platform admins

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class UserResponse(BaseModel):
    id: str
    email: str
    role: str
    status: str
    company_id: Optional[str] = None
    tenant_id: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email_verified: bool = False
    created_at: datetime
    last_login: Optional[datetime] = None

class PasswordReset(BaseModel):
    email: EmailStr

class PasswordResetConfirm(BaseModel):
    token: str
    new_password: str

class EmailVerification(BaseModel):
    token: str

class GoogleUserInfo(BaseModel):
    id: str
    email: str
    verified_email: bool
    name: str
    given_name: str
    family_name: str
    picture: str


class GoogleUserData(BaseModel):
    id: str
    email: str
    verified_email: bool
    name: str
    given_name: str
    family_name: str
    picture: str


class GoogleCallbackRequest(BaseModel):
    code: str


class GoogleCheckUserRequest(BaseModel):
    code: str

class GoogleCompleteRegistrationRequest(BaseModel):
    temp_token: str  # Changed from code to temp_token
    vertical: str

class GoogleUserExistsResponse(BaseModel):
    userExists: bool
    userInfo: dict
    tempToken: Optional[str] = None  # Only provided for new users
    # JWT fields for existing users
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    token_type: Optional[str] = None
    role: Optional[str] = None
    company_id: Optional[str] = None
    tenant_id: Optional[str] = None
    vertical: Optional[str] = None
    expires_in: Optional[int] = None

class GoogleVerticalSelectionRequest(BaseModel):
    session_id: str
    vertical: str
