from pydantic import BaseModel, Field


class Review(BaseModel):
    id: str = Field(min_length=8, max_length=100, pattern=r"^[A-Za-z0-9:_-]+$")
    card_id: str = Field(min_length=1, max_length=100)
    rating: int = Field(ge=1, le=3)
    device_id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9:_-]+$")
    reviewed_at: str | None = Field(default=None, max_length=64)
