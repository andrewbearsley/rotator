from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel
import httpx
import os
from dotenv import load_dotenv
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

app = FastAPI(title="Crypto Category Rotation API")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Database connection
@app.on_event("startup")
async def startup_db_client():
    app.mongodb_client = AsyncIOMotorClient(os.getenv("MONGODB_URL"))
    app.mongodb = app.mongodb_client.crypto_rotation
    logger.info("Database connection established")

@app.on_event("shutdown")
async def shutdown_db_client():
    app.mongodb_client.close()
    logger.info("Database connection closed")

# CoinMarketCap API configuration
CMC_API_KEY = os.getenv("CMC_API_KEY").strip()
logger.info(f"API Key present: {bool(CMC_API_KEY)}")
logger.info(f"API Key length: {len(CMC_API_KEY) if CMC_API_KEY else 0}")

if not CMC_API_KEY:
    logger.error("CMC_API_KEY environment variable is not set")
    raise ValueError("CMC_API_KEY environment variable is not set")

CMC_BASE_URL = "https://pro-api.coinmarketcap.com/v1"

headers = {
    "X-CMC_PRO_API_KEY": CMC_API_KEY,
    "Accept": "application/json"
}

@app.get("/api/categories")
async def get_categories():
    """Fetch all cryptocurrency categories and their market data"""
    logger.info("Attempting to fetch categories")
    
    if not CMC_API_KEY:
        logger.error("API key not configured")
        raise HTTPException(status_code=500, detail="API key not configured")
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(
                f"{CMC_BASE_URL}/cryptocurrency/categories",
                headers=headers
            )
            
            if response.status_code == 401:
                logger.error("Invalid API key")
                raise HTTPException(status_code=401, detail="Invalid API key")
            elif response.status_code != 200:
                logger.error(f"Failed to fetch categories: {response.text}")
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Failed to fetch categories: {response.text}"
                )
            
            data = response.json()
            # Transform the data to include clearer field names
            if data.get('data'):
                for category in data['data']:
                    category['market_cap_change_24h'] = category.pop('market_cap_change', 0)
                    category['volume_change_24h'] = category.pop('volume_change', 0)
                    category['price_change_24h'] = category.pop('avg_price_change', 0)
            
            return data
        except httpx.RequestError as e:
            logger.error(f"Request error: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/category/{category_id}")
async def get_category_details(category_id: str):
    """Fetch detailed information about a specific category"""
    logger.info(f"Attempting to fetch category details for {category_id}")
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{CMC_BASE_URL}/cryptocurrency/category",
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
    analysis = await app.mongodb.rotation_analysis.find_one(
        {},
        sort=[('timestamp', -1)]
    )
    if not analysis:
        logger.info("No analysis data available")
        return {"message": "No analysis data available"}
    logger.info("Analysis data available")
    return analysis
