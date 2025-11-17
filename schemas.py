"""
Database Schemas for GBU Sports Portal

Each Pydantic model corresponds to a MongoDB collection. The collection
name is the lowercase of the class name.
"""

from pydantic import BaseModel, Field, EmailStr
from typing import Optional, Literal
from datetime import datetime


class User(BaseModel):
    name: str = Field(..., description="Full name")
    email: EmailStr = Field(..., description="Email address")
    password_hash: str = Field(..., description="Hashed password")
    role: Literal["student", "staff", "admin"] = Field("student")
    phone: Optional[str] = Field(None)
    is_active: bool = Field(True)


class Gymmembership(BaseModel):
    # collection name will be "gymmembership"
    email: EmailStr = Field(..., description="User email")
    plan: Literal["monthly", "quarterly", "yearly"]
    status: Literal["pending", "active", "expired"] = Field("pending")
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None


class Payment(BaseModel):
    email: EmailStr
    amount: float = Field(..., ge=0)
    purpose: Literal["gym_membership", "booking", "other"] = "gym_membership"
    method: Literal["upi", "card", "netbanking", "cash"] = "upi"
    status: Literal["success", "failed", "pending"] = "success"
    reference: Optional[str] = None


class Match(BaseModel):
    sport: Literal["cricket", "indoor"]
    team_a: str = Field(..., description="Team A name")
    team_b: str = Field(..., description="Team B name")
    venue: str
    start_time: datetime
    status: Literal["upcoming", "live", "finished"] = "upcoming"
    score_a: Optional[str] = None
    score_b: Optional[str] = None
    details: Optional[str] = None
