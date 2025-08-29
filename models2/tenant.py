from datetime import datetime
from typing import Optional, List
from bson import ObjectId
from pydantic import BaseModel, EmailStr, Field
from enum import Enum

class TenantType(str, Enum):
    BRANCH = "branch"
    LOCATION = "location"
    DEPARTMENT = "department"

class TenantStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"

class Tenant(BaseModel):
    id: Optional[str] = Field(None, alias="_id")
    name: str
    company_id: str
    type: TenantType = TenantType.BRANCH
    status: TenantStatus = TenantStatus.ACTIVE
    
    # Contact Information
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    
    # Address
    address_line1: Optional[str] = None
    address_line2: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip_code: Optional[str] = None
    country: str = "US"
    
    # Manager Information
    manager_name: Optional[str] = None
    manager_email: Optional[EmailStr] = None
    manager_phone: Optional[str] = None
    
    # Configuration
    settings: dict = Field(default_factory=dict)
    
    # Telephony Configuration (inherits from company but can override)
    telephony_config: dict = Field(default_factory=dict)
    
    # Operational hours
    business_hours: dict = Field(default_factory=dict)
    
    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    
    # Created by (Company Admin ID)
    created_by: str
    
    class Config:
        populate_by_name = True
        json_encoders = {
            ObjectId: str,
            datetime: lambda v: v.isoformat()
        }

class TenantCreate(BaseModel):
    name: str
    type: TenantType = TenantType.BRANCH
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    address_line1: Optional[str] = None
    address_line2: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip_code: Optional[str] = None
    manager_name: Optional[str] = None
    manager_email: Optional[EmailStr] = None
    manager_phone: Optional[str] = None

class TenantResponse(BaseModel):
    id: str
    name: str
    company_id: str
    type: str
    status: str
    email: Optional[str] = None
    phone: Optional[str] = None
    manager_name: Optional[str] = None
    manager_email: Optional[str] = None
    manager_phone: Optional[str] = None
    created_at: datetime

class TenantUpdate(BaseModel):
    name: Optional[str] = None
    status: Optional[TenantStatus] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    address_line1: Optional[str] = None
    address_line2: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip_code: Optional[str] = None
    manager_name: Optional[str] = None
    manager_email: Optional[EmailStr] = None
    manager_phone: Optional[str] = None
    settings: Optional[dict] = None


class TenantUserCreate(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8)
    first_name: str = Field(..., min_length=1, max_length=50)
    last_name: str = Field(..., min_length=1, max_length=50)
    phone: Optional[str] = None
    tenant_id: Optional[str] = None

class TenantUserResponse(BaseModel):
    id: str
    email: str
    first_name: str
    last_name: str
    phone: Optional[str]
    role: str
    status: str
    company_id: str
    tenant_id: Optional[str]
    assigned_phone_numbers: List[dict] = []  # Full phone number details
    created_at: datetime

