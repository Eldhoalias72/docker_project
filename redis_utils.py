import asyncio
import redis.asyncio as redis
import json
import os
from datetime import datetime, timedelta

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")

class RedisManager:
    def __init__(self):
        self.redis_client = None
    
    async def connect(self):
        """Connect to Redis"""
        try:
            self.redis_client = redis.from_url(REDIS_URL)
            await self.redis_client.ping()
            print("Connected to Redis successfully!")
            return True
        except Exception as e:
            print(f"Failed to connect to Redis: {e}")
            return False
    
    async def close(self):
        """Close Redis connection"""
        if self.redis_client:
            await self.redis_client.close()
    
    async def set_item_cache(self, item_id: str, item_data: dict, expiry_hours: int = 24):
        """Cache item data with expiration"""
        if not self.redis_client:
            return False
        
        try:
            key = f"item:{item_id}"
            value = json.dumps(item_data, default=str)
            expiry_seconds = expiry_hours * 3600
            
            await self.redis_client.setex(key, expiry_seconds, value)
            print(f"Cached item {item_id} for {expiry_hours} hours")
            return True
        except Exception as e:
            print(f"Error caching item {item_id}: {e}")
            return False
    
    async def get_item_cache(self, item_id: str):
        """Get cached item data"""
        if not self.redis_client:
            return None
        
        try:
            key = f"item:{item_id}"
            cached_data = await self.redis_client.get(key)
            
            if cached_data:
                return json.loads(cached_data)
            return None
        except Exception as e:
            print(f"Error getting cached item {item_id}: {e}")
            return None
    
    async def delete_item_cache(self, item_id: str):
        """Delete cached item data"""
        if not self.redis_client:
            return False
        
        try:
            key = f"item:{item_id}"
            result = await self.redis_client.delete(key)
            return bool(result)
        except Exception as e:
            print(f"Error deleting cached item {item_id}: {e}")
            return False
    
    async def set_counter(self, counter_name: str, value: int = 1):
        """Set or increment a counter"""
        if not self.redis_client:
            return None
        
        try:
            key = f"counter:{counter_name}"
            result = await self.redis_client.incr(key, value)
            return result
        except Exception as e:
            print(f"Error setting counter {counter_name}: {e}")
            return None
    
    async def get_counter(self, counter_name: str):
        """Get counter value"""
        if not self.redis_client:
            return None
        
        try:
            key = f"counter:{counter_name}"
            result = await self.redis_client.get(key)
            return int(result) if result else 0
        except Exception as e:
            print(f"Error getting counter {counter_name}: {e}")
            return None
    
    async def set_session(self, session_id: str, session_data: dict, expiry_hours: int = 24):
        """Set session data"""
        if not self.redis_client:
            return False
        
        try:
            key = f"session:{session_id}"
            value = json.dumps(session_data, default=str)
            expiry_seconds = expiry_hours * 3600
            
            await self.redis_client.setex(key, expiry_seconds, value)
            return True
        except Exception as e:
            print(f"Error setting session {session_id}: {e}")
            return False
    
    async def get_session(self, session_id: str):
        """Get session data"""
        if not self.redis_client:
            return None
        
        try:
            key = f"session:{session_id}"
            session_data = await self.redis_client.get(key)
            
            if session_data:
                return json.loads(session_data)
            return None
        except Exception as e:
            print(f"Error getting session {session_id}: {e}")
            return None
    
    async def get_all_keys(self, pattern: str = "*"):
        """Get all keys matching pattern"""
        if not self.redis_client:
            return []
        
        try:
            keys = await self.redis_client.keys(pattern)
            return [key.decode() if isinstance(key, bytes) else key for key in keys]
        except Exception as e:
            print(f"Error getting keys with pattern {pattern}: {e}")
            return []
    
    async def get_redis_info(self):
        """Get Redis server information"""
        if not self.redis_client:
            return None
        
        try:
            info = await self.redis_client.info()
            return {
                "redis_version": info.get("redis_version"),
                "used_memory_human": info.get("used_memory_human"),
                "connected_clients": info.get("connected_clients"),
                "uptime_in_seconds": info.get("uptime_in_seconds"),
                "keyspace": {k: v for k, v in info.items() if k.startswith("db")}
            }
        except Exception as e:
            print(f"Error getting Redis info: {e}")
            return None

# Example usage and testing
async def main():
    """Test Redis functionality"""
    redis_manager = RedisManager()
    
    if not await redis_manager.connect():
        return
    
    try:
        # Test basic operations
        print("\n=== Testing Redis Operations ===")
        
        # Test item caching
        test_item = {
            "id": "test_123",
            "name": "Test Item",
            "price": 99.99,
            "created_at": datetime.now().isoformat()
        }
        
        await redis_manager.set_item_cache("test_123", test_item, 1)
        cached_item = await redis_manager.get_item_cache("test_123")
        print(f"Cached item: {cached_item}")
        
        # Test counters
        await redis_manager.set_counter("items_created", 1)
        await redis_manager.set_counter("items_created", 5)
        counter_value = await redis_manager.get_counter("items_created")
        print(f"Counter value: {counter_value}")
        
        # Test session
        session_data = {"user_id": "user_123", "login_time": datetime.now().isoformat()}
        await redis_manager.set_session("session_abc", session_data, 2)
        retrieved_session = await redis_manager.get_session("session_abc")
        print(f"Session data: {retrieved_session}")
        
        # Get all keys
        all_keys = await redis_manager.get_all_keys()
        print(f"All keys: {all_keys}")
        
        # Get Redis info
        redis_info = await redis_manager.get_redis_info()
        print(f"Redis info: {redis_info}")
        
    finally:
        await redis_manager.close()

if __name__ == "__main__":
    asyncio.run(main())