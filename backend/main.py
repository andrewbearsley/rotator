from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel
import httpx
import os
from dotenv import load_dotenv
import logging
from datetime import datetime, timedelta
from typing import List, Optional
from bson import ObjectId
import json

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

app = FastAPI(title="Crypto Category Rotation API")

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# MongoDB setup
MONGO_URL = os.getenv("MONGODB_URL")
client = AsyncIOMotorClient(MONGO_URL)
db = client.crypto_rotation

# CoinMarketCap API configuration
CMC_API_KEY = os.getenv("CMC_API_KEY")
CMC_BASE_URL = "https://pro-api.coinmarketcap.com"
headers = {
    "X-CMC_PRO_API_KEY": CMC_API_KEY,
    "Accept": "application/json"
}

class HistoricalData(BaseModel):
    category_id: str
    timestamp: datetime
    market_cap: float
    volume_24h: float
    market_cap_change_24h: Optional[float]
    volume_change_24h: Optional[float]

# Custom JSON encoder to handle ObjectId
class MongoJSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, ObjectId):
            return str(obj)
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)

def serialize_mongo(data):
    """Serialize MongoDB data to JSON"""
    if isinstance(data, list):
        return [serialize_mongo(item) for item in data]
    elif isinstance(data, dict):
        return {key: serialize_mongo(value) for key, value in data.items()}
    elif isinstance(data, ObjectId):
        return str(data)
    elif isinstance(data, datetime):
        return data.isoformat()
    return data

@app.on_event("startup")
async def startup_db_client():
    logger.info("Database connection established")

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
    logger.info("Database connection closed")

@app.get("/api/categories")
async def get_categories():
    """Fetch all cryptocurrency categories and their market data"""
    logger.info("Attempting to fetch categories")
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{CMC_BASE_URL}/v1/cryptocurrency/categories",
                headers=headers
            )
            response.raise_for_status()
            data = response.json()
            
            # Process the data
            if data.get("data"):
                for category in data["data"]:
                    # Clean up field names
                    category['market_cap_change_24h'] = category.pop('market_cap_change', 0)
                    category['volume_change_24h'] = category.pop('volume_change', 0)
                    category['price_change_24h'] = category.pop('avg_price_change', 0)
                    # Ensure we have the CMC ID
                    if 'id' not in category:
                        category['id'] = str(category.get('cmc_id', ''))
                
                # Store in MongoDB
                await db.categories.delete_many({})
                await db.categories.insert_many(data["data"])
            
            # Return serialized data
            return serialize_mongo(data)
            
    except Exception as e:
        logger.error(f"Error fetching categories: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/categories/{category_id}/historical")
async def get_category_historical(category_id: str, days: int = 30):
    """Fetch historical data for a specific category"""
    logger.info(f"Attempting to fetch historical data for {category_id}")
    try:
        # First check if we have cached data
        cached_data = await db.historical_data.find_one({
            "category_id": category_id,
            "timestamp": {"$gte": datetime.utcnow() - timedelta(hours=1)}
        })
        
        if cached_data:
            logger.info("Using cached historical data")
            return serialize_mongo(cached_data)
        
        # If no cached data, fetch from CoinMarketCap
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{CMC_BASE_URL}/v1/cryptocurrency/category",
                params={
                    "id": category_id,
                    "aux": "market_cap,volume_24h,market_cap_change_24h,volume_change_24h"
                },
                headers=headers
            )
            response.raise_for_status()
            data = response.json()
            
            if not data.get("data"):
                raise HTTPException(status_code=404, detail="Category not found")
            
            # Process and store historical data
            historical_data = {
                "category_id": category_id,
                "timestamp": datetime.utcnow(),
                "market_cap": data["data"].get("market_cap", 0),
                "volume_24h": data["data"].get("volume_24h", 0),
                "market_cap_change_24h": data["data"].get("market_cap_change_24h", 0),
                "volume_change_24h": data["data"].get("volume_change_24h", 0)
            }
            
            # Store in MongoDB
            await db.historical_data.insert_one(historical_data)
            
            return serialize_mongo(historical_data)
            
    except httpx.HTTPError as e:
        logger.error(f"HTTP error occurred: {str(e)}")
        raise HTTPException(status_code=e.response.status_code if hasattr(e, 'response') else 500, 
                          detail=str(e))
    except Exception as e:
        logger.error(f"Error fetching historical data: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/categories/{category_id}")
async def get_category_details(category_id: str):
    """Fetch detailed information about a specific category"""
    logger.info(f"Attempting to fetch category details for {category_id}")
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{CMC_BASE_URL}/v1/cryptocurrency/category",
            headers=headers,
            params={"id": category_id}
        )
        logger.info(f"Response status code: {response.status_code}")
        logger.info(f"Response headers: {response.headers}")
        
        if response.status_code != 200:
            logger.error(f"Failed to fetch category details: {response.text}")
            raise HTTPException(status_code=response.status_code, detail="Failed to fetch category details")
        return response.json()

@app.get("/api/rotation-analysis")
async def get_rotation_analysis():
    """Calculate and return the rotation analysis between categories"""
    logger.info("Attempting to fetch rotation analysis")
    # Fetch historical data from MongoDB and perform analysis
    analysis = await db.rotation_analysis.find_one(
        {},
        sort=[('timestamp', -1)]
    )
    if not analysis:
        logger.info("No analysis data available")
        return {"message": "No analysis data available"}
    logger.info("Analysis data available")
    return serialize_mongo(analysis)
