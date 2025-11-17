import os
import hashlib
from datetime import datetime, timezone
from typing import Optional, List
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
from bson import ObjectId

from database import db, create_document, get_documents
from schemas import User as UserSchema, Gymmembership as GymMembershipSchema, Payment as PaymentSchema, Match as MatchSchema


def serialize_doc(doc: dict):
    if not doc:
        return doc
    d = {**doc}
    if d.get("_id"):
        d["id"] = str(d.pop("_id"))
    # convert datetimes to iso
    for k, v in list(d.items()):
        if isinstance(v, datetime):
            d[k] = v.isoformat()
    return d


def collection(name: str):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    return db[name]


def hash_password(password: str, salt: str) -> str:
    return hashlib.sha256((password + salt).encode()).hexdigest()


SECRET = os.getenv("AUTH_SECRET", "gbu-sports-portal-secret")


class RegisterRequest(BaseModel):
    name: str
    email: EmailStr
    password: str
    phone: Optional[str] = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class GymPlanRequest(BaseModel):
    email: EmailStr
    plan: str  # monthly | quarterly | yearly


class PaymentRequest(BaseModel):
    email: EmailStr
    amount: float
    purpose: str = "gym_membership"
    method: str = "upi"
    reference: Optional[str] = None


class MatchCreateRequest(BaseModel):
    sport: str  # cricket | indoor
    team_a: str
    team_b: str
    venue: str
    start_time: datetime
    status: str = "upcoming"  # upcoming | live | finished
    details: Optional[str] = None


class MatchUpdateRequest(BaseModel):
    status: Optional[str] = None
    score_a: Optional[str] = None
    score_b: Optional[str] = None
    details: Optional[str] = None


app = FastAPI(title="GBU Sports Portal API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root():
    return {"message": "GBU Sports Portal Backend Running"}


@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set",
        "database_name": "✅ Set" if os.getenv("DATABASE_NAME") else "❌ Not Set",
        "connection_status": "Not Connected",
        "collections": []
    }
    try:
        if db is not None:
            response["database"] = "✅ Available"
            response["connection_status"] = "Connected"
            response["collections"] = db.list_collection_names()
            response["database"] = "✅ Connected & Working"
    except Exception as e:
        response["database"] = f"⚠️ Error: {str(e)[:80]}"
    return response


# Auth endpoints
@app.post("/api/auth/register")
def register(req: RegisterRequest):
    users = collection("user")
    if users.find_one({"email": req.email}):
        raise HTTPException(status_code=400, detail="Email already registered")
    password_hash = hash_password(req.password, SECRET)
    user = UserSchema(
        name=req.name,
        email=req.email,
        password_hash=password_hash,
        role="student",
        phone=req.phone,
        is_active=True,
    )
    user_id = create_document("user", user)
    token = hash_password(req.email, SECRET)
    return {"id": user_id, "token": token, "email": req.email, "name": req.name}


@app.post("/api/auth/login")
def login(req: LoginRequest):
    users = collection("user")
    u = users.find_one({"email": req.email})
    if not u:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    expected = u.get("password_hash")
    if expected != hash_password(req.password, SECRET):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = hash_password(req.email, SECRET)
    return {"token": token, "email": req.email, "name": u.get("name")}


@app.get("/api/profile")
def profile(email: EmailStr):
    users = collection("user")
    u = users.find_one({"email": email})
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    u.pop("password_hash", None)
    return serialize_doc(u)


# Gym membership
@app.post("/api/gym/membership")
def create_membership(req: GymPlanRequest):
    memberships = collection("gymmembership")
    existing = memberships.find_one({"email": req.email, "status": {"$in": ["pending", "active"]}})
    if existing:
        return serialize_doc(existing)
    gm = GymMembershipSchema(email=req.email, plan=req.plan)
    _id = create_document("gymmembership", gm)
    return {"id": _id, "email": req.email, "plan": req.plan, "status": "pending"}


@app.get("/api/gym/membership")
def get_membership(email: EmailStr):
    memberships = collection("gymmembership")
    m = memberships.find_one({"email": email}, sort=[("created_at", -1)])
    if not m:
        raise HTTPException(status_code=404, detail="No membership found")
    return serialize_doc(m)


@app.post("/api/payments/create")
def create_payment(req: PaymentRequest):
    # Simulate payment success and activate membership
    payment = PaymentSchema(
        email=req.email,
        amount=req.amount,
        purpose=req.purpose,
        method=req.method,
        status="success",
        reference=req.reference or f"REF-{int(datetime.now().timestamp())}"
    )
    pay_id = create_document("payment", payment)

    memberships = collection("gymmembership")
    m = memberships.find_one({"email": req.email}, sort=[("created_at", -1)])
    if m:
        start = datetime.now(timezone.utc)
        if m.get("plan") == "monthly":
            delta_days = 30
        elif m.get("plan") == "quarterly":
            delta_days = 90
        else:
            delta_days = 365
        end = start + (datetime.utcfromtimestamp(0) - datetime.utcfromtimestamp(0))  # placeholder, we'll set below
        # compute end with timedelta without importing separately
        from datetime import timedelta
        end = start + timedelta(days=delta_days)
        memberships.update_one({"_id": m["_id"]}, {"$set": {"status": "active", "start_date": start, "end_date": end}})
        m = memberships.find_one({"_id": m["_id"]})

    return {"payment_id": pay_id, "status": "success", "membership": serialize_doc(m) if m else None}


# Matches
@app.get("/api/matches")
def list_matches(sport: Optional[str] = None, status: Optional[str] = None, limit: int = 20):
    filt = {}
    if sport:
        filt["sport"] = sport
    if status:
        filt["status"] = status
    docs = get_documents("match", filt, limit)
    return [serialize_doc(d) for d in docs]


@app.post("/api/matches")
def create_match(req: MatchCreateRequest):
    match = MatchSchema(**req.model_dump())
    _id = create_document("match", match)
    return {"id": _id}


@app.patch("/api/matches/{match_id}")
def update_match(match_id: str, req: MatchUpdateRequest):
    try:
        oid = ObjectId(match_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid match id")
    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    if not updates:
        return {"updated": False}
    updates["updated_at"] = datetime.now(timezone.utc)
    collection("match").update_one({"_id": oid}, {"$set": updates})
    doc = collection("match").find_one({"_id": oid})
    return serialize_doc(doc)


# Simple seed endpoint to add sample matches
@app.post("/api/seed")
def seed():
    if not collection("match").find_one({"sport": "cricket"}):
        now = datetime.now(timezone.utc)
        create_document("match", MatchSchema(sport="cricket", team_a="GBU Warriors", team_b="Noida Knights", venue="GBU Cricket Ground", start_time=now, status="live", details="Friendly match"))
        create_document("match", MatchSchema(sport="cricket", team_a="GBU Titans", team_b="Delhi Dynamos", venue="GBU Cricket Ground", start_time=now.replace(hour=(now.hour+2)%24), status="upcoming"))
    if not collection("match").find_one({"sport": "indoor"}):
        now = datetime.now(timezone.utc)
        create_document("match", MatchSchema(sport="indoor", team_a="GBU Falcons", team_b="GBU Hawks", venue="Indoor Stadium", start_time=now, status="live", details="Badminton Doubles"))
        create_document("match", MatchSchema(sport="indoor", team_a="GBU Lions", team_b="Lucknow Legends", venue="Indoor Stadium", start_time=now.replace(hour=(now.hour+3)%24), status="upcoming", details="Table Tennis"))
    return {"seeded": True}


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
