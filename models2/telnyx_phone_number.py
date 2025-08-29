# models/telnyx_phone_number.py
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
from datetime import datetime
from enum import Enum

class NumberStatus(str, Enum):
    AVAILABLE = "available"
    ASSIGNED = "assigned"
    SUSPENDED = "suspended"
    PORTING = "porting"
    PORT_FAILED = "port_failed"

class NumberType(str, Enum):
    LOCAL = "local"
    TOLL_FREE = "toll_free"
    MOBILE = "mobile"
    NATIONAL = "national"

class TelnyxPhoneNumber(BaseModel):
    id: str = Field(alias="_id")
    phone_number: str = Field(..., description="E.164 format phone number")
    telnyx_number_id: str = Field(..., description="Telnyx unique number ID")
    company_id: str = Field(..., description="Company that ordered this number")
    
    # Assignment info
    assigned_to_user_id: Optional[str] = None
    assigned_to_tenant_id: Optional[str] = None
    status: NumberStatus = NumberStatus.AVAILABLE
    
    # Telnyx-specific data
    number_type: NumberType
    country_code: str = "US"
    region: Optional[str] = None  # State/province
    locality: Optional[str] = None  # City
    rate_center: Optional[str] = None
    
    # Billing and features
    monthly_cost: float = 0.0
    setup_cost: float = 0.0
    features: list[str] = []  # ["voice", "sms", "mms", "fax"]
    
    # Telnyx order information
    telnyx_order_id: Optional[str] = None
    telnyx_order_status: Optional[str] = None
    ordered_date: datetime
    activated_date: Optional[datetime] = None
    
    # Metadata from Telnyx
    telnyx_metadata: Optional[Dict[str, Any]] = None
    
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    
    class Config:
        populate_by_name = True


# Pydantic schemas
class NumberSearchRequest(BaseModel):
    area_code: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    country_code: str = "US"
    number_type: str = "local"
    limit: int = Field(default=10, le=50)
    features: List[str] = ["voice", "sms"]

class NumberOrderRequest(BaseModel):
    phone_numbers: List[str] = Field(..., min_items=1, max_items=10)
    connection_id: Optional[str] = None
    messaging_profile_id: Optional[str] = None

class AssignNumberRequest(BaseModel):
    user_id: Optional[str] = None
    tenant_id: Optional[str] = None
    reason: Optional[str] = None

class TelnyxNumberResponse(BaseModel):
    id: str
    phone_number: str
    telnyx_number_id: str
    status: NumberStatus
    number_type: NumberType
    assigned_to_user_id: Optional[str]
    assigned_to_tenant_id: Optional[str]
    assigned_to_user_name: Optional[str]
    monthly_cost: float
    setup_cost: float
    features: List[str]
    ordered_date: datetime
    activated_date: Optional[datetime]
    region: Optional[str]
    locality: Optional[str]