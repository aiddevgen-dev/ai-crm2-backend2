# models/telnyx_order.py
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional, Dict, Any, List
from enum import Enum

class OrderStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

class TelnyxOrder(BaseModel):
    id: str = Field(alias="_id")
    company_id: str
    telnyx_order_id: str
    
    # Order details
    order_type: str  # "number_search", "number_order", "port_request"
    requested_numbers: List[str] = []  # Numbers that were requested
    fulfilled_numbers: List[str] = []  # Numbers that were actually obtained
    failed_numbers: List[str] = []  # Numbers that failed to order
    
    # Search criteria used
    search_criteria: Optional[Dict[str, Any]] = None
    
    # Order status and tracking
    status: OrderStatus = OrderStatus.PENDING
    telnyx_status: Optional[str] = None
    
    # Costs
    total_setup_cost: float = 0.0
    total_monthly_cost: float = 0.0
    
    # Timestamps
    ordered_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    
    # Telnyx response data
    telnyx_response: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    
    # Admin who placed the order
    ordered_by_user_id: str
    
    class Config:
        populate_by_name = True