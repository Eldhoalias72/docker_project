import asyncio
import aio_pika
import json
import os
from datetime import datetime

RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@rabbitmq:5672/")

async def process_message(message: aio_pika.IncomingMessage):
    """Process incoming notification messages"""
    try:
        # Decode message
        body = message.body.decode()
        notification_data = json.loads(body)
        
        # Process the notification (you can add your custom logic here)
        print(f"[{datetime.now()}] Processing notification:")
        print(f"  Message: {notification_data.get('message', 'N/A')}")
        print(f"  Item ID: {notification_data.get('item_id', 'N/A')}")
        print(f"  Timestamp: {notification_data.get('timestamp', 'N/A')}")
        print("-" * 50)
        
        # Here you could:
        # - Send emails
        # - Send push notifications
        # - Log to external systems
        # - Trigger webhooks
        # - etc.
        
        # Acknowledge the message
        await message.ack()
        
    except Exception as e:
        print(f"Error processing message: {e}")
        # Reject the message and requeue it
        await message.nack(requeue=True)

async def main():
    """Main consumer function"""
    print("Starting RabbitMQ consumer...")
    
    try:
        # Connect to RabbitMQ
        connection = await aio_pika.connect_robust(RABBITMQ_URL)
        channel = await connection.channel()
        
        # Set QoS to process one message at a time
        await channel.set_qos(prefetch_count=1)
        
        # Declare the queue (ensure it exists)
        queue = await channel.declare_queue("notifications", durable=True)
        
        print(f"Connected to RabbitMQ. Waiting for messages...")
        print("To exit press CTRL+C")
        
        # Start consuming messages
        await queue.consume(process_message)
        
        # Keep the consumer running
        await asyncio.Future()  # Run forever
        
    except KeyboardInterrupt:
        print("\nShutting down consumer...")
    except Exception as e:
        print(f"Consumer error: {e}")
    finally:
        if 'connection' in locals():
            await connection.close()

if __name__ == "__main__":
    asyncio.run(main())