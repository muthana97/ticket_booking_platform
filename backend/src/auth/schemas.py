from pydantic import BaseModel, Field

class OTPRequest(BaseModel):
    # Validates that it's a string, you can add regex later for specific formats
    phone_number: str = Field(..., example="+60123456789")

class OTPVerify(BaseModel):
    phone_number: str
    otp_code: str = Field(..., min_length=6, max_length=6)

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
