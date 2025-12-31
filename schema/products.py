# from typing import List, Optional, Union
# from pydantic import BaseModel, Field

# class Image(BaseModel):
#     url: str
#     thumbnail: str
#     public_id: str
#     index: int
#     is_primary: bool

# class CategoryRef(BaseModel):
#     id: str = Field(alias="_id")
#     name: str

# class BrandRef(BaseModel):
#     id: str = Field(alias="_id")
#     name: str

# class ProductBase(BaseModel):
#     name: str = Field(..., min_length=1, max_length=200)
#     description: str = Field(..., min_length=1)
#     actual_price: float = Field(..., gt=0)
#     selling_price: float = Field(..., gt=0)
#     discount: float = Field(..., gt=0)
#     images: Optional[List[Image]] = Field(default_factory=list)
#     category: str
#     brand: str
#     stock: int = Field(default=0, ge=0)
#     is_active: bool = True
#     keywords: Optional[List[str]] = Field(default_factory=list)

# class ProductCreate(ProductBase):
#     pass

# class ProductUpdate(BaseModel):
#     name: Optional[str] = Field(None, min_length=1, max_length=200)
#     description: Optional[str] = Field(None, min_length=1)
#     actual_price: float = Field(..., gt=0)
#     selling_price: float = Field(..., gt=0)
#     discount: float = Field(..., gt=0)
#     images: Optional[List[Image]] = None
#     category: Optional[str] = None
#     brand: Optional[str] = None
#     stock: Optional[int] = Field(None, ge=0)
#     is_active: Optional[bool] = None
#     keywords: Optional[List[str]] = None

# class ProductInDB(ProductBase):
#     pass

# class ProductResponse(ProductBase):
#     category: Union[CategoryRef, dict]
#     brand: Union[BrandRef, dict]

from typing import List, Optional, Union
from pydantic import BaseModel, Field, validator
from datetime import datetime

class Image(BaseModel):
    url: str
    thumbnail: str
    public_id: str
    index: int
    is_primary: bool = False

class CategoryRef(BaseModel):
    """Reference to a category - used in product responses"""
    id: str = Field(alias="_id")
    name: str
    
    class Config:
        populate_by_name = True
        allow_population_by_field_name = True

class BrandRef(BaseModel):
    """Reference to a brand - used in product responses"""
    id: str = Field(alias="_id")
    name: str
    
    class Config:
        populate_by_name = True
        allow_population_by_field_name = True

class ProductBase(BaseModel):
    """Base product model with common fields"""
    name: str = Field(..., min_length=1, max_length=200)
    description: str = Field(..., min_length=1)
    actual_price: float = Field(..., gt=0)
    selling_price: float = Field(..., gt=0)
    discount: float = Field(default=0, ge=0)  # ✅ Changed: gt=0 to ge=0 (allow 0)
    images: Optional[List[Image]] = Field(default_factory=list)
    category: str  # Category ID
    brand: str  # Brand ID
    stock: int = Field(default=0, ge=0)
    status: str = Field(default="active")  # ✅ Added: Frontend expects "status" not "is_active"
    is_active: bool = True  # Keep for backward compatibility
    keywords: Optional[List[str]] = Field(default_factory=list)
    allow_user_images: bool = Field(default=False)  # ✅ Added: New fields from frontend
    allow_user_description: bool = Field(default=False)  # ✅ Added: New fields from frontend
    
    @validator('status', pre=True, always=True)
    def set_status_from_is_active(cls, v, values):
        """Convert is_active to status for frontend compatibility"""
        if v is None and 'is_active' in values:
            return 'active' if values['is_active'] else 'inactive'
        return v or 'active'

class ProductCreate(ProductBase):
    """Schema for creating a new product"""
    pass

class ProductUpdate(BaseModel):
    """Schema for updating an existing product - all fields optional"""
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = None
    actual_price: Optional[float] = Field(None, gt=0)  # ✅ Fixed: Made optional
    selling_price: Optional[float] = Field(None, gt=0)  # ✅ Fixed: Made optional
    discount: Optional[float] = Field(None, ge=0)  # ✅ Fixed: Made optional, allow 0
    images: Optional[List[Image]] = None
    category: Optional[str] = None
    brand: Optional[str] = None
    stock: Optional[int] = Field(None, ge=0)
    status: Optional[str] = None  # ✅ Added: Use status instead of is_active
    is_active: Optional[bool] = None  # Keep for backward compatibility
    keywords: Optional[List[str]] = None
    allow_user_images: Optional[bool] = None  # ✅ Added
    allow_user_description: Optional[bool] = None  # ✅ Added

class ProductInDB(ProductBase):
    """Product as stored in database"""
    id: str = Field(alias="_id")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    
    class Config:
        populate_by_name = True
        allow_population_by_field_name = True

class ProductResponse(BaseModel):
    """Product response for API/WebSocket - with populated references"""
    id: str = Field(alias="_id")  # ✅ Added: Frontend needs id field
    name: str
    description: str
    actual_price: float
    selling_price: float
    discount: float
    images: List[Image] = Field(default_factory=list)
    category: Union[str, CategoryRef, dict]  # Can be ID string or populated object
    brand: Union[str, BrandRef, dict]  # Can be ID string or populated object
    stock: int
    status: str = "active"  # ✅ Frontend expects "status"
    is_active: bool = True  # Keep for backward compatibility
    keywords: List[str] = Field(default_factory=list)
    allow_user_images: bool = False
    allow_user_description: bool = False
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    
    class Config:
        populate_by_name = True
        allow_population_by_field_name = True

class ProductListResponse(BaseModel):
    """Response for listing products with metadata"""
    products: List[ProductResponse]
    categories: List[dict]  # List of category objects
    brands: List[dict]  # List of brand objects
    total: Optional[int] = None
    page: Optional[int] = None
    limit: Optional[int] = None