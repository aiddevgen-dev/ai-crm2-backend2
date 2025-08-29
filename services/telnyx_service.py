# services/telnyx_service.py - Fixed order_phone_numbers method
import telnyx
from typing import List, Dict, Any, Optional
from datetime import datetime
import uuid
from models2.telnyx_phone_number import TelnyxPhoneNumber, NumberType, NumberStatus
from models2.telnyx_order import TelnyxOrder, OrderStatus
from utils.utils import get_database
import os

# Configure Telnyx
telnyx.api_key = os.getenv("TELNYX_API_KEY")

class TelnyxService:
    
    @staticmethod
    def search_available_numbers(
        area_code: Optional[str] = None,
        city: Optional[str] = None,
        state: Optional[str] = None,
        country_code: str = "US",
        number_type: str = "local",
        limit: int = 10,
        features: List[str] = None
    ) -> Dict[str, Any]:
        """Search for available phone numbers on Telnyx."""
        
        if features is None:
            features = ["voice", "sms"]
        
        try:
            search_params = {
                "filter[country_code]": country_code,
                "filter[features]": features,
                "filter[limit]": limit
            }
            
            if area_code:
                search_params["filter[national_destination_code]"] = area_code
            if city:
                search_params["filter[locality]"] = city
            if state:
                search_params["filter[administrative_area]"] = state
            
            # Search for available numbers
            if number_type == "toll_free":
                response = telnyx.AvailablePhoneNumber.list(**search_params)
            else:
                response = telnyx.AvailablePhoneNumber.list(**search_params)
            
            return {
                "success": True,
                "numbers": response.data,
                "search_params": search_params
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "numbers": []
            }
    
    @staticmethod
    def order_phone_numbers(
        phone_numbers: List[str],
        company_id: str,
        ordered_by_user_id: str,
        connection_id: Optional[str] = None,
        messaging_profile_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Order phone numbers from Telnyx."""
        
        db = get_database()

        try:
            ordered_numbers = []
            failed_numbers = []
            total_setup_cost = 0.0
            total_monthly_cost = 0.0
            
            # Create order record
            order_id = str(uuid.uuid4())
            telnyx_order_id = f"order_{int(datetime.utcnow().timestamp())}"
            
            order = TelnyxOrder(
                id=order_id,
                company_id=company_id,
                telnyx_order_id=telnyx_order_id,
                order_type="number_order",
                requested_numbers=phone_numbers,
                ordered_by_user_id=ordered_by_user_id,
                status=OrderStatus.PROCESSING
            )
            
            # Prepare the phone numbers array in the correct format
            phone_numbers_array = []
            for phone_number in phone_numbers:
                phone_numbers_array.append({"phone_number": phone_number})
            
            # Create the main order payload
            order_payload = {
                "phone_numbers": phone_numbers_array
            }
            
            # Add optional parameters if provided
            if connection_id:
                order_payload["connection_id"] = connection_id
            if messaging_profile_id:
                order_payload["messaging_profile_id"] = messaging_profile_id
            
            try:
                # Order all numbers at once using the correct Telnyx API method
                number_order = telnyx.NumberOrder.create(**order_payload)
                
                # Process each number from the response
                if hasattr(number_order, 'phone_numbers') and number_order.phone_numbers:
                    for phone_number_data in number_order.phone_numbers:
                        phone_number = phone_number_data.get('phone_number')
                        if not phone_number:
                            continue
                            
                        try:
                    
                            # Extract pricing information
                            monthly_cost = 1.0  # Default value - update based on your Telnyx plan
                            setup_cost = 1.0   # Default value - update based on your Telnyx plan
                            
                            # Get the phone number ID from the phone number data
                            telnyx_number_id = phone_number_data.get('id')
                            
                            # Determine number type from phone number
                            number_type = NumberType.LOCAL
                            if phone_number.startswith("+1800") or phone_number.startswith("+1888") or phone_number.startswith("+1877") or phone_number.startswith("+1866"):
                                number_type = NumberType.TOLL_FREE
                            
                            # Create phone number record in database
                            phone_record = TelnyxPhoneNumber(
                                id=str(uuid.uuid4()),
                                phone_number=phone_number,
                                tenant_id = company_id,
                                telnyx_number_id=str(telnyx_number_id),
                                company_id=company_id,
                                number_type=number_type,
                                monthly_cost=monthly_cost,
                                setup_cost=setup_cost,
                                features=["voice", "sms"],  # Default features
                                telnyx_order_id=telnyx_order_id,
                                telnyx_order_status="completed",
                                ordered_date=datetime.utcnow(),
                                activated_date=datetime.utcnow(),
                                telnyx_metadata=phone_number_data,
                                status=NumberStatus.AVAILABLE
                            )
                            
                            # Save to database
                            db.telnyx_phone_numbers.insert_one(phone_record.dict(by_alias=True))
                            
                            ordered_numbers.append(phone_number)
                            total_setup_cost += phone_record.setup_cost
                            total_monthly_cost += phone_record.monthly_cost
                            
                        except Exception as number_error:
                            print(f"Failed to process number {phone_number}: {str(number_error)}")
                            failed_numbers.append({
                                "phone_number": phone_number,
                                "error": str(number_error)
                            })
                else:
                    # If no phone_numbers in response, try to handle single order response
                    for phone_number in phone_numbers:
                        failed_numbers.append({
                            "phone_number": phone_number,
                            "error": "No phone numbers returned in order response"
                        })
                        
            except Exception as order_error:
                print(f"Failed to create number order: {str(order_error)}")
                # If the batch order fails, mark all numbers as failed
                for phone_number in phone_numbers:
                    failed_numbers.append({
                        "phone_number": phone_number,
                        "error": f"Order creation failed: {str(order_error)}"
                    })
            
            # Update order record
            order.fulfilled_numbers = ordered_numbers
            order.failed_numbers = [item["phone_number"] for item in failed_numbers]
            order.total_setup_cost = total_setup_cost
            order.total_monthly_cost = total_monthly_cost
            order.status = OrderStatus.COMPLETED if ordered_numbers else OrderStatus.FAILED
            order.completed_at = datetime.utcnow()
            
            db.telnyx_orders.insert_one(order.dict(by_alias=True))
            
            return {
                "success": True,
                "order_id": order_id,
                "telnyx_order_id": telnyx_order_id,
                "ordered_numbers": ordered_numbers,
                "failed_numbers": failed_numbers,
                "total_setup_cost": total_setup_cost,
                "total_monthly_cost": total_monthly_cost
            }
            
        except Exception as e:
            print(f"Error in order_phone_numbers: {str(e)}")
            return {
                "success": False,
                "error": str(e),
                "order_id": None
            }
    
    @staticmethod
    def release_phone_number(telnyx_number_id: str) -> Dict[str, Any]:
        """Release a phone number back to Telnyx."""
        
        try:
            # Release the number - correct method is to delete the PhoneNumber
            response = telnyx.PhoneNumber.delete(telnyx_number_id)
            
            return {
                "success": True,
                "message": "Number released successfully",
                "telnyx_response": response.to_dict() if hasattr(response, 'to_dict') else str(response)
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    @staticmethod
    def get_number_details(telnyx_number_id: str) -> Dict[str, Any]:
        """Get detailed information about a phone number from Telnyx."""
        
        try:
            number = telnyx.PhoneNumber.retrieve(telnyx_number_id)
            
            return {
                "success": True,
                "number_data": number.to_dict()
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }