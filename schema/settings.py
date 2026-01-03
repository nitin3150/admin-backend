from typing import Optional
from pydantic import BaseModel, Field

class Pincodes(BaseModel):
    _id: Optional[str] = None
    pincode: str
    city: str
    state: str
    status: Optional[bool] = False

class UpdatePincodes(BaseModel):
    id: str = Field(..., alias="_id")
    pincode: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None

    status: Optional[bool] = Field(None, alias="is_active")

    model_config = {
        "populate_by_name": True
    }