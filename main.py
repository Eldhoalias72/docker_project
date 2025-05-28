from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel
from motor.motor_asyncio import AsyncIOMotorClient
import redis.asyncio as redis
from pymongo import MongoClient
import aio_pika
import json
import os
import asyncio
from datetime import datetime
from typing import Optional
from fastapi import Depends
from fastapi.security import OAuth2PasswordRequestForm
from auth import (
    get_password_hash,
    verify_password,
    create_access_token,
    decode_access_token,
    oauth2_scheme
)


app = FastAPI(title="BugNotify FastAPI App", version="1.0.0")

# MongoDB connection
MONGODB_URL = os.getenv("MONGODB_URL", "mongodb://mongodb:27017")
DATABASE_NAME = os.getenv("DATABASE_NAME", "fastapi_db")
COLLECTION_NAME = os.getenv("COLLECTION_NAME", "items")

# Redis connection
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")

# RabbitMQ connection
RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@rabbitmq:5672/")

# Initialize connections
client = AsyncIOMotorClient(MONGODB_URL)
database = client[DATABASE_NAME]
collection = database[COLLECTION_NAME]
users_collection = database["users"]
redis_client = None
rabbitmq_connection = None
rabbitmq_channel = None

# Pydantic models
class Item(BaseModel):
    name: str
    description: str
    price: float
    category: Optional[str] = None

class ItemResponse(BaseModel):
    id: str
    name: str
    description: str
    price: float
    category: Optional[str] = None
    created_at: datetime

class NotificationMessage(BaseModel):
    message: str
    item_id: str
    timestamp: datetime

async def get_current_user(token: str = Depends(oauth2_scheme)):
    payload = decode_access_token(token)
    username = payload.get("sub")
    if username is None:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    user = await users_collection.find_one({"name": username})
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    
    return user

async def connect_rabbitmq():
    """Connect to RabbitMQ with retry logic"""
    global rabbitmq_connection, rabbitmq_channel
    max_retries = 5
    retry_delay = 2
    
    for attempt in range(max_retries):
        try:
            print(f"Attempting to connect to RabbitMQ (attempt {attempt + 1}/{max_retries})...")
            rabbitmq_connection = await aio_pika.connect_robust(
                RABBITMQ_URL,
                timeout=10,
                heartbeat=600
            )
            rabbitmq_channel = await rabbitmq_connection.channel()
            
            # Declare queue for notifications
            await rabbitmq_channel.declare_queue("notifications", durable=True)
            print("Connected to RabbitMQ successfully!")
            return True
        except Exception as e:
            print(f"RabbitMQ connection attempt {attempt + 1} failed: {e}")
            if attempt < max_retries - 1:
                await asyncio.sleep(retry_delay)
            else:
                print("Failed to connect to RabbitMQ after all retries")
                return False

@app.on_event("startup")
async def startup_event():
    global redis_client
    
    # Test MongoDB connection
    try:
        await client.admin.command('ping')
        print("Connected to MongoDB successfully!")
    except Exception as e:
        print(f"Failed to connect to MongoDB: {e}")
    
    # Initialize Redis connection
    try:
        redis_client = redis.from_url(REDIS_URL)
        await redis_client.ping()
        print("Connected to Redis successfully!")
    except Exception as e:
        print(f"Failed to connect to Redis: {e}")
    
    # Initialize RabbitMQ connection with retry
    await connect_rabbitmq()

@app.on_event("shutdown")
async def shutdown_event():
    global redis_client, rabbitmq_connection
    
    client.close()
    
    if redis_client:
        await redis_client.close()
    
    if rabbitmq_connection:
        await rabbitmq_connection.close()

@app.get("/")
async def root(current_user: str = Depends(get_current_user)):
    return {"message": f"FastAPI MongoDB App is running for user: {current_user}"}


@app.post("/items/", response_model=ItemResponse)
async def create_item(item: Item, background_tasks: BackgroundTasks):
    try:
        # Add timestamp
        item_dict = item.dict()
        item_dict["created_at"] = datetime.utcnow()
        
        # Insert into MongoDB
        result = await collection.insert_one(item_dict)
        item_id = str(result.inserted_id)
        
        # Cache in Redis
        if redis_client:
            await redis_client.setex(
                f"item:{item_id}", 
                3600,  # 1 hour expiration
                json.dumps(item_dict, default=str)
            )
        
        # Send notification to RabbitMQ
        if rabbitmq_channel:
            notification = NotificationMessage(
                message=f"New item created: {item.name}",
                item_id=item_id,
                timestamp=datetime.utcnow()
            )
            
            await rabbitmq_channel.default_exchange.publish(
                aio_pika.Message(
                    body=notification.json().encode(),
                    delivery_mode=aio_pika.DeliveryMode.PERSISTENT
                ),
                routing_key="notifications"
            )
        
        # Return the created item
        created_item = await collection.find_one({"_id": result.inserted_id})
        
        return ItemResponse(
            id=str(created_item["_id"]),
            name=created_item["name"],
            description=created_item["description"],
            price=created_item["price"],
            category=created_item.get("category"),
            created_at=created_item["created_at"]
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create item: {str(e)}")

@app.get("/items/")
async def get_items():
    try:
        items = []
        async for item in collection.find():
            items.append(ItemResponse(
                id=str(item["_id"]),
                name=item["name"],
                description=item["description"],
                price=item["price"],
                category=item.get("category"),
                created_at=item["created_at"]
            ))
        return items
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch items: {str(e)}")

@app.get("/health")
async def health_check():
    health_status = {"status": "healthy", "services": {}}
    
    # Check MongoDB
    try:
        await client.admin.command('ping')
        health_status["services"]["mongodb"] = "connected"
    except Exception as e:
        health_status["services"]["mongodb"] = f"error: {str(e)}"
        health_status["status"] = "degraded"
    
    # Check Redis
    if redis_client:
        try:
            await redis_client.ping()
            health_status["services"]["redis"] = "connected"
        except Exception as e:
            health_status["services"]["redis"] = f"error: {str(e)}"
            health_status["status"] = "degraded"
    else:
        health_status["services"]["redis"] = "not initialized"
        health_status["status"] = "degraded"
    
    # Check RabbitMQ
    try:
        if rabbitmq_connection and not rabbitmq_connection.is_closed:
            # Try to get queue info to verify connection is active
            if rabbitmq_channel:
                queue = await rabbitmq_channel.get_queue("notifications", ensure=False)
                health_status["services"]["rabbitmq"] = "connected"
            else:
                health_status["services"]["rabbitmq"] = "channel not available"
                health_status["status"] = "degraded"
        else:
            # Try to reconnect
            print("RabbitMQ connection lost, attempting to reconnect...")
            reconnected = await connect_rabbitmq()
            if reconnected:
                health_status["services"]["rabbitmq"] = "reconnected"
            else:
                health_status["services"]["rabbitmq"] = "disconnected"
                health_status["status"] = "degraded"
    except Exception as e:
        health_status["services"]["rabbitmq"] = f"error: {str(e)}"
        health_status["status"] = "degraded"
        # Try to reconnect on error
        try:
            await connect_rabbitmq()
        except:
            pass
    
    return health_status

# Redis-specific endpoints
@app.get("/cache/{item_id}")
async def get_cached_item(item_id: str):
    if not redis_client:
        raise HTTPException(status_code=503, detail="Redis not available")
    
    try:
        cached_item = await redis_client.get(f"item:{item_id}")
        if cached_item:
            return json.loads(cached_item)
        else:
            raise HTTPException(status_code=404, detail="Item not found in cache")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Cache error: {str(e)}")

@app.delete("/cache/{item_id}")
async def delete_cached_item(item_id: str):
    if not redis_client:
        raise HTTPException(status_code=503, detail="Redis not available")
    
    try:
        result = await redis_client.delete(f"item:{item_id}")
        return {"deleted": bool(result), "item_id": item_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Cache error: {str(e)}")

# RabbitMQ-specific endpoints
@app.post("/notify")
async def send_notification(message: str):
    if not rabbitmq_channel:
        # Try to reconnect if not connected
        reconnected = await connect_rabbitmq()
        if not reconnected:
            raise HTTPException(status_code=503, detail="RabbitMQ not available")
    
    try:
        notification = NotificationMessage(
            message=message,
            item_id="manual",
            timestamp=datetime.utcnow()
        )
        
        await rabbitmq_channel.default_exchange.publish(
            aio_pika.Message(
                body=notification.json().encode(),
                delivery_mode=aio_pika.DeliveryMode.PERSISTENT
            ),
            routing_key="notifications"
        )
        
        return {"status": "notification sent", "message": message}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"RabbitMQ error: {str(e)}")

@app.get("/queue/status")
async def get_queue_status():
    if not rabbitmq_channel:
        # Try to reconnect if not connected
        reconnected = await connect_rabbitmq()
        if not reconnected:
            raise HTTPException(status_code=503, detail="RabbitMQ not available")
    
    try:
        queue = await rabbitmq_channel.get_queue("notifications")
        return {
            "queue_name": "notifications",
            "message_count": queue.declaration_result.message_count,
            "consumer_count": queue.declaration_result.consumer_count
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"RabbitMQ error: {str(e)}")

@app.post("/signup")
async def signup(form_data: OAuth2PasswordRequestForm = Depends()):
    existing_user = await users_collection.find_one({"name": form_data.username})
    if existing_user:
        raise HTTPException(status_code=400, detail="Username already taken")
    
    hashed_password = get_password_hash(form_data.password)
    
    user_doc = {
        "name": form_data.username,
        "hashed_password": hashed_password,
        "created_at": datetime.utcnow()
    }
    
    await users_collection.insert_one(user_doc)
    return {"message": "User created successfully"}


@app.post("/token")
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    user = await users_collection.find_one({"name": form_data.username})
    if not user or not verify_password(form_data.password, user["hashed_password"]):
        raise HTTPException(status_code=401, detail="Incorrect username or password")
    
    token_data = {"sub": user["name"]}
    access_token = create_access_token(data=token_data)
    
    return {"access_token": access_token, "token_type": "bearer"}



