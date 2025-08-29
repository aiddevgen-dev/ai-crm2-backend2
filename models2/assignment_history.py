# models/assignment_history.py
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional

class AssignmentHistory(BaseModel):
    id: str = Field(alias="_id")
    phone_number_id: str
    company_id: str
    previous_user_id: Optional[str] = None
    new_user_id: Optional[str] = None
    previous_tenant_id: Optional[str] = None
    new_tenant_id: Optional[str] = None
    action: str  # "assigned", "unassigned", "reassigned"
    reason: Optional[str] = None
    performed_by_user_id: str  # Company admin who made the change
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    
    class Config:
        populate_by_name = True