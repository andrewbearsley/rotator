from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel
import httpx
import os
from dotenv import load_dotenv
import logging
from datetime import datetime, timedelta
from typing import List, Optional, Dict
from bson import ObjectId
import json
import asyncio
from cachetools import TTLCache
import time

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

# Cache configuration
TOKEN_INFO_CACHE = TTLCache(maxsize=1000, ttl=3600)  # 1 hour TTL
HISTORICAL_CACHE = TTLCache(maxsize=1000, ttl=3600)  # 1 hour TTL
CATEGORY_CACHE = TTLCache(maxsize=100, ttl=300)  # 5 minutes TTL

# Rate limiting configuration
RATE_LIMIT_CALLS = 30  # calls per minute
RATE_LIMIT_WINDOW = 60  # seconds
last_calls = []

async def check_rate_limit():
    """Implement rate limiting"""
    current_time = time.time()
    # Remove calls older than the window
    global last_calls
    last_calls = [call_time for call_time in last_calls if current_time - call_time < RATE_LIMIT_WINDOW]
    
    if len(last_calls) >= RATE_LIMIT_CALLS:
        wait_time = RATE_LIMIT_WINDOW - (current_time - last_calls[0])
        if wait_time > 0:
            logger.info(f"Rate limit reached, waiting {wait_time:.2f} seconds")
            await asyncio.sleep(wait_time)
            return await check_rate_limit()
    
    last_calls.append(current_time)
    return True

async def batch_get_token_info(token_ids: List[int], client: httpx.AsyncClient) -> Dict:
    """Get token info in batches to reduce API calls"""
    if not token_ids:
        return {}
    
    # Check cache first
    result = {}
    uncached_ids = []
    for token_id in token_ids:
        cached = TOKEN_INFO_CACHE.get(token_id)
        if cached:
            result[str(token_id)] = cached
        else:
            uncached_ids.append(token_id)
    
    if not uncached_ids:
        return result
    
    # Split into batches of 100 (CMC limit)
    BATCH_SIZE = 100
    batches = [uncached_ids[i:i + BATCH_SIZE] for i in range(0, len(uncached_ids), BATCH_SIZE)]
    
    for batch in batches:
        await check_rate_limit()
        try:
            response = await client.get(
                f"{CMC_BASE_URL}/v2/cryptocurrency/info",
                headers=headers,
                params={"id": ",".join(map(str, batch))}
            )
            response.raise_for_status()
            data = response.json().get("data", {})
            
            # Update cache and result
            for token_id, token_data in data.items():
                TOKEN_INFO_CACHE[int(token_id)] = token_data
                result[token_id] = token_data
                
        except httpx.HTTPError as e:
            logger.error(f"Error fetching token info batch: {str(e)}")
            # Continue with partial results rather than failing completely
            continue
    
    return result

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
            await check_rate_limit()
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
                    else:
                        category['id'] = str(category['id'])
                
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
    logger.info(f"Attempting to fetch historical data for category_id: {category_id}")
    try:
        # First check if the category exists
        category = await db.categories.find_one({"id": category_id})
        if not category:
            logger.error(f"Category not found in database: {category_id}")
            raise HTTPException(status_code=404, detail=f"Category not found: {category_id}")
        
        logger.info(f"Found category in database: {category.get('name', 'Unknown')} (ID: {category_id})")
        
        # Check for cached data
        cached_data = await db.historical_data.find({
            "category_id": category_id,
            "timestamp": {"$gte": datetime.utcnow() - timedelta(hours=1)}
        }).sort("timestamp", 1).to_list(None)
        
        if cached_data:
            logger.info(f"Using cached historical data for {category_id} ({len(cached_data)} points)")
            return serialize_mongo({"data": cached_data})
        
        logger.info(f"No recent cache found for {category_id}, fetching from CoinMarketCap")
        
        # If no cached data, fetch from CoinMarketCap
        async with httpx.AsyncClient() as client:
            await check_rate_limit()
            url = f"{CMC_BASE_URL}/v1/cryptocurrency/category/historical"
            params = {
                "id": category_id,
                "interval": "1d",
                "count": str(days),
                "convert": "USD"
            }
            logger.info(f"Making request to CoinMarketCap: {url} with params: {params}")
            
            response = await client.get(url, params=params, headers=headers)
            response.raise_for_status()
            data = response.json()
            
            if not data.get("data", {}).get("points"):
                logger.error(f"No historical data points returned for category {category_id}")
                raise HTTPException(status_code=404, detail="No historical data found")
            
            logger.info(f"Received {len(data['data']['points'])} historical data points from CoinMarketCap")
            
            # Process and store historical data
            historical_data = []
            for point, values in data["data"]["points"].items():
                try:
                    entry = {
                        "category_id": category_id,
                        "timestamp": datetime.fromtimestamp(int(point)),
                        "market_cap": values["market_cap"]["USD"],
                        "volume_24h": values["volume_24h"]["USD"],
                        "market_cap_change_24h": values.get("market_cap_change_24h", {}).get("USD", 0),
                        "volume_change_24h": values.get("volume_change_24h", {}).get("USD", 0)
                    }
                    historical_data.append(entry)
                except Exception as e:
                    logger.error(f"Error processing data point {point}: {str(e)}")
            
            if historical_data:
                # Sort by timestamp
                historical_data.sort(key=lambda x: x["timestamp"])
                logger.info(f"Processed {len(historical_data)} valid data points")
                
                # Store in MongoDB
                await db.historical_data.delete_many({
                    "category_id": category_id,
                    "timestamp": {"$gte": datetime.utcnow() - timedelta(days=days)}
                })
                await db.historical_data.insert_many(historical_data)
                logger.info(f"Stored historical data in MongoDB for category {category_id}")
            else:
                logger.error(f"No valid historical data points processed for category {category_id}")
            
            return serialize_mongo({"data": historical_data})
            
    except httpx.HTTPError as e:
        logger.error(f"HTTP error occurred: {str(e)}")
        if hasattr(e, 'response'):
            logger.error(f"Response status: {e.response.status_code}")
            logger.error(f"Response body: {e.response.text}")
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
        await check_rate_limit()
        response = await client.get(
            f"{CMC_BASE_URL}/v1/cryptocurrency/category/historical",
            headers=headers,
            params={
                "id": category_id,
                "interval": "1d",
                "count": "60",
                "convert": "USD"
            }
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

@app.get("/api/categories/compare")
async def compare_categories(category_ids: str, days: int = 30):
    """Fetch and compare historical data for multiple categories"""
    logger.info(f"Comparing categories: {category_ids} over {days} days")
    try:
        # Split category IDs into a list
        category_list = category_ids.split(',')
        
        # Fetch historical data for each category
        categories_data = {}
        async with httpx.AsyncClient() as client:
            for category_id in category_list:
                # First get the category details to get the coins
                await check_rate_limit()
                response = await client.get(
                    f"{CMC_BASE_URL}/v1/cryptocurrency/category",
                    params={"id": category_id},
                    headers=headers
                )
                if response.status_code != 200:
                    error_data = response.json()
                    logger.error(f"Failed to fetch category details: {error_data}")
                    raise HTTPException(status_code=response.status_code, detail=str(error_data))
                
                category_data = response.json()["data"]
                coins = category_data.get("coins", [])
                if not coins:
                    logger.error(f"No coins found in category {category_id}")
                    continue
                
                # Get the top 5 coins by market cap
                top_coins = sorted(coins, key=lambda x: x.get("marketCap", 0), reverse=True)[:5]
                coin_symbols = ",".join(coin["symbol"] for coin in top_coins)
                
                # Get historical data for these coins
                url = f"{CMC_BASE_URL}/v2/cryptocurrency/quotes/historical"
                params = {
                    "symbol": coin_symbols,
                    "interval": "1d",
                    "count": str(days),
                    "convert": "USD"
                }
                logger.info(f"Making request to CoinMarketCap: {url} with params: {params}")
                
                await check_rate_limit()
                response = await client.get(url, params=params, headers=headers)
                logger.info(f"Response status code: {response.status_code}")
                
                if response.status_code != 200:
                    error_data = response.json()
                    logger.error(f"Failed to fetch historical data: {error_data}")
                    continue
                
                data = response.json()
                logger.info("Processing API response...")
                logger.info(f"Response data structure: {type(data)}")
                logger.info(f"Response data keys: {data.keys() if isinstance(data, dict) else 'Not a dict'}")
                
                # Process the data points - aggregate the market caps
                historical_data = []
                
                if isinstance(data, dict) and 'data' in data:
                    quotes_data = data['data']
                    logger.info(f"Quotes data type: {type(quotes_data)}")
                    
                    if isinstance(quotes_data, dict):
                        doge_data = quotes_data.get('DOGE', {})
                        quotes = doge_data.get('quotes', [])
                    else:
                        quotes = quotes_data if isinstance(quotes_data, list) else []
                    
                    logger.info(f"Found {len(quotes)} quotes")
                    
                    for quote in quotes:
                        try:
                            timestamp_str = quote.get('timestamp')
                            if not timestamp_str:
                                continue
                                
                            timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                            quote_usd = quote.get('quote', {}).get('USD', {})
                            
                            if not quote_usd:
                                continue
                            
                            data_point = {
                                'timestamp': timestamp.isoformat(),
                                'market_cap': quote_usd.get('market_cap', 0),
                                'volume_24h': quote_usd.get('volume_24h', 0),
                                'market_cap_change_24h': quote_usd.get('percent_change_24h', 0),
                                'volume_change_24h': 0  # CoinMarketCap doesn't provide volume change
                            }
                            
                            historical_data.append(data_point)
                                
                        except (KeyError, TypeError, ValueError) as e:
                            logger.error(f"Error processing quote: {e}")
                            continue
            
                logger.info(f"Processed {len(historical_data)} data points")
                categories_data[category_id] = historical_data
        
        return serialize_mongo({"data": categories_data})
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error comparing categories: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/memes-top-tokens")
async def get_top_meme_tokens():
    """Fetch historical data for top 5 meme tokens"""
    logger.info("Fetching top meme tokens historical data")
    try:
        # First, get the meme category tokens
        async with httpx.AsyncClient() as client:
            # Get all categories to find the meme category ID
            await check_rate_limit()
            categories_response = await client.get(
                f"{CMC_BASE_URL}/v1/cryptocurrency/categories",
                headers=headers
            )
            categories_response.raise_for_status()
            categories_data = categories_response.json()
            
            logger.info(f"Found {len(categories_data.get('data', []))} categories")
            
            # Find the meme category ID
            meme_category = None
            for cat in categories_data.get("data", []):
                name = cat.get("name", "").lower()
                logger.info(f"Category: {name} (ID: {cat.get('id')})")
                if name == "memes":  # Exact match for "memes"
                    meme_category = cat
                    break
            
            if not meme_category:
                raise HTTPException(status_code=500, detail="Meme category not found")
            
            logger.info(f"Found meme category: {meme_category.get('name')} (ID: {meme_category.get('id')})")
            
            # Get tokens in the meme category
            await check_rate_limit()
            response = await client.get(
                f"{CMC_BASE_URL}/v1/cryptocurrency/category",
                headers=headers,
                params={
                    "id": meme_category["id"]
                }
            )
            response.raise_for_status()
            data = response.json()
            
            if not data.get("data"):
                raise HTTPException(status_code=500, detail="No data received from CoinMarketCap")
            
            # Get top 5 tokens by market cap
            tokens = sorted(
                data["data"]["coins"],
                key=lambda x: float(x.get("marketCap", 0) or 0),
                reverse=True
            )[:5]
            
            # Get current timestamp and 7 days ago timestamp
            end_time = datetime.now()
            start_time = end_time - timedelta(days=7)
            
            # Fetch historical data for each token
            all_tokens_history = []
            for token in tokens:
                try:
                    hist_response = await client.get(
                        f"{CMC_BASE_URL}/v2/cryptocurrency/quotes/historical",
                        headers=headers,
                        params={
                            "id": str(token["id"]),
                            "time_start": start_time.strftime("%Y-%m-%dT%H:%M:%S"),
                            "time_end": end_time.strftime("%Y-%m-%dT%H:%M:%S"),
                            "interval": "1d",
                            "count": 7,
                        }
                    )
                    hist_response.raise_for_status()
                    hist_data = hist_response.json()
                    
                    if not hist_data.get("data"):
                        logger.warning(f"No historical data for token {token['symbol']}")
                        continue
                    
                    # Process historical data
                    quotes = hist_data["data"]["quotes"]
                    price_history = []
                    prev_price = None
                    
                    # Sort quotes by timestamp
                    sorted_quotes = sorted(quotes, key=lambda x: x["timestamp"])
                    
                    for quote in sorted_quotes:
                        current_price = quote["quote"]["USD"]["price"]
                        
                        # Calculate percentage change
                        percent_change = 0
                        if prev_price is not None:
                            percent_change = ((current_price - prev_price) / prev_price) * 100
                        
                        price_history.append({
                            "timestamp": quote["timestamp"],
                            "price": current_price,
                            "percent_change": round(percent_change, 2)
                        })
                        
                        prev_price = current_price
                    
                    all_tokens_history.append({
                        "id": token["id"],
                        "symbol": token["symbol"],
                        "name": token["name"],
                        "history": price_history
                    })
                    
                except Exception as e:
                    logger.error(f"Error fetching historical data for {token['symbol']}: {str(e)}")
                    continue
            
            return all_tokens_history
            
    except httpx.HTTPError as e:
        logger.error(f"HTTP error occurred: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch meme tokens data: {str(e)}")
    except Exception as e:
        logger.error(f"Error fetching meme tokens: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/memes/historical")
async def get_memes_historical():
    try:
        api_key = os.getenv('CMC_API_KEY')
        if not api_key:
            logger.error("CMC_API_KEY environment variable is not set")
            raise HTTPException(status_code=500, detail="API key not configured")

        # Make request to CoinMarketCap
        params = {
            'symbol': 'DOGE',  # Only fetch DOGE data
            'interval': '1d',
            'count': '7',
            'convert': 'USD'
        }
        
        headers = {
            'X-CMC_PRO_API_KEY': api_key,
            'Accept': 'application/json'
        }
        
        url = "https://pro-api.coinmarketcap.com/v2/cryptocurrency/quotes/historical"
        logger.info(f"Making request to CoinMarketCap: {url} with params: {params}")
        logger.info(f"Using headers: {headers}")
        
        async with httpx.AsyncClient() as client:
            await check_rate_limit()
            response = await client.get(
                url,
                params=params,
                headers=headers
            )
            
            logger.info(f"Response status code: {response.status_code}")
            
            if response.status_code != 200:
                error_data = response.json()
                logger.error(f"Error response from CoinMarketCap: {error_data}")
                raise HTTPException(status_code=response.status_code, detail=str(error_data))
            
            data = response.json()
            logger.info("Processing API response...")
            logger.info(f"Response data structure: {type(data)}")
            logger.info(f"Response data keys: {data.keys() if isinstance(data, dict) else 'Not a dict'}")
            
            # Process the data points
            historical_data = []
            
            if isinstance(data, dict) and 'data' in data:
                quotes_data = data['data']
                logger.info(f"Quotes data type: {type(quotes_data)}")
                
                if isinstance(quotes_data, dict) and 'DOGE' in quotes_data:
                    doge_data = quotes_data['DOGE']
                    logger.info(f"DOGE data type: {type(doge_data)}")
                    
                    if isinstance(doge_data, list):
                        logger.info(f"Found {len(doge_data)} DOGE entries")
                        
                        for entry in doge_data:
                            if not isinstance(entry, dict) or 'quotes' not in entry:
                                continue
                                
                            quotes = entry.get('quotes', [])
                            if not isinstance(quotes, list):
                                continue
                                
                            logger.info(f"Processing quotes from entry: {entry.get('name', 'Unknown')}")
                            
                            for quote in quotes:
                                try:
                                    timestamp_str = quote.get('timestamp')
                                    if not timestamp_str:
                                        logger.warning("Missing timestamp in quote")
                                        continue
                                        
                                    timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                                    quote_usd = quote.get('quote', {}).get('USD', {})
                                    
                                    if not quote_usd:
                                        logger.warning("Missing USD quote data")
                                        continue
                                    
                                    data_point = {
                                        'timestamp': timestamp.isoformat(),
                                        'market_cap': quote_usd.get('market_cap', 0),
                                        'volume_24h': quote_usd.get('volume_24h', 0),
                                        'market_cap_change_24h': quote_usd.get('percent_change_24h', 0),
                                        'volume_change_24h': 0  # CoinMarketCap doesn't provide volume change
                                    }
                                    
                                    historical_data.append(data_point)
                                    logger.info(f"Added data point: {data_point}")
                                        
                                except (KeyError, TypeError, ValueError) as e:
                                    logger.error(f"Error processing quote: {e}")
                                    continue
            
            logger.info(f"Processed {len(historical_data)} data points")
            return serialize_mongo({"data": historical_data})
            
    except Exception as e:
        logger.error(f"Error fetching Memes historical data: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/doge-history")
async def get_doge_history():
    """Fetch DOGE price history for the last 7 days"""
    logger.info("Fetching DOGE price history")
    try:
        # Get current timestamp and 7 days ago timestamp
        end_time = datetime.now()
        start_time = end_time - timedelta(days=7)
        
        async with httpx.AsyncClient() as client:
            # CoinMarketCap ID for DOGE is 74
            await check_rate_limit()
            response = await client.get(
                f"{CMC_BASE_URL}/v2/cryptocurrency/quotes/historical",
                headers=headers,
                params={
                    "id": "74",  # DOGE's ID
                    "time_start": start_time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "time_end": end_time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "interval": "1d",  # daily intervals
                    "count": 7,
                }
            )
            response.raise_for_status()
            data = response.json()
            
            logger.info(f"Received response from CoinMarketCap: {json.dumps(data)[:200]}...")
            
            if not data.get("data"):
                raise HTTPException(status_code=500, detail="No data received from CoinMarketCap")
            
            # Extract quotes from the response
            quotes = data["data"]["quotes"]
            
            # Transform the data into a list of price points with percentage changes
            price_history = []
            prev_price = None
            
            # Sort quotes by timestamp first
            sorted_quotes = sorted(quotes, key=lambda x: x["timestamp"])
            
            for quote in sorted_quotes:
                timestamp = quote["timestamp"]
                current_price = quote["quote"]["USD"]["price"]
                
                # Calculate percentage change from previous day
                percent_change = 0
                if prev_price is not None:
                    percent_change = ((current_price - prev_price) / prev_price) * 100
                
                price_history.append({
                    "timestamp": timestamp,
                    "price": current_price,
                    "percent_change": round(percent_change, 2)
                })
                
                prev_price = current_price
            
            return price_history
            
    except httpx.HTTPError as e:
        logger.error(f"HTTP error occurred: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch DOGE data: {str(e)}")
    except Exception as e:
        logger.error(f"Error fetching DOGE history: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/memes-top-tokens")
async def get_top_meme_tokens():
    """Fetch historical data for top 5 meme tokens"""
    logger.info("Fetching top meme tokens historical data")
    try:
        # First, get the meme category tokens
        async with httpx.AsyncClient() as client:
            # Get all categories to find the meme category ID
            await check_rate_limit()
            categories_response = await client.get(
                f"{CMC_BASE_URL}/v1/cryptocurrency/categories",
                headers=headers
            )
            categories_response.raise_for_status()
            categories_data = categories_response.json()
            
            # Find the meme category ID
            meme_category = next(
                (cat for cat in categories_data["data"] if cat["name"].lower() == "meme"),
                None
            )
            
            if not meme_category:
                raise HTTPException(status_code=500, detail="Meme category not found")
            
            # Get tokens in the meme category
            await check_rate_limit()
            response = await client.get(
                f"{CMC_BASE_URL}/v1/cryptocurrency/category",
                headers=headers,
                params={
                    "id": meme_category["id"]
                }
            )
            response.raise_for_status()
            data = response.json()
            
            if not data.get("data"):
                raise HTTPException(status_code=500, detail="No data received from CoinMarketCap")
            
            # Get top 5 tokens by market cap
            tokens = sorted(
                data["data"]["coins"],
                key=lambda x: float(x.get("marketCap", 0) or 0),
                reverse=True
            )[:5]
            
            # Get current timestamp and 7 days ago timestamp
            end_time = datetime.now()
            start_time = end_time - timedelta(days=7)
            
            # Fetch historical data for each token
            all_tokens_history = []
            for token in tokens:
                try:
                    hist_response = await client.get(
                        f"{CMC_BASE_URL}/v2/cryptocurrency/quotes/historical",
                        headers=headers,
                        params={
                            "id": str(token["id"]),
                            "time_start": start_time.strftime("%Y-%m-%dT%H:%M:%S"),
                            "time_end": end_time.strftime("%Y-%m-%dT%H:%M:%S"),
                            "interval": "1d",
                            "count": 7,
                        }
                    )
                    hist_response.raise_for_status()
                    hist_data = hist_response.json()
                    
                    if not hist_data.get("data"):
                        logger.warning(f"No historical data for token {token['symbol']}")
                        continue
                    
                    # Process historical data
                    quotes = hist_data["data"]["quotes"]
                    price_history = []
                    prev_price = None
                    
                    # Sort quotes by timestamp
                    sorted_quotes = sorted(quotes, key=lambda x: x["timestamp"])
                    
                    for quote in sorted_quotes:
                        current_price = quote["quote"]["USD"]["price"]
                        
                        # Calculate percentage change
                        percent_change = 0
                        if prev_price is not None:
                            percent_change = ((current_price - prev_price) / prev_price) * 100
                        
                        price_history.append({
                            "timestamp": quote["timestamp"],
                            "price": current_price,
                            "percent_change": round(percent_change, 2)
                        })
                        
                        prev_price = current_price
                    
                    all_tokens_history.append({
                        "id": token["id"],
                        "symbol": token["symbol"],
                        "name": token["name"],
                        "history": price_history
                    })
                    
                except Exception as e:
                    logger.error(f"Error fetching historical data for {token['symbol']}: {str(e)}")
                    continue
            
            return all_tokens_history
            
    except httpx.HTTPError as e:
        logger.error(f"HTTP error occurred: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch meme tokens data: {str(e)}")
    except Exception as e:
        logger.error(f"Error fetching meme tokens: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/category/{category_name}/top-tokens")
async def get_top_tokens_by_category(category_name: str, limit: int = 10):
    """Fetch top tokens from a specific category"""
    logger.info(f"Fetching top {limit} tokens from category: {category_name}")
    try:
        # Check category cache
        target_category = CATEGORY_CACHE.get(category_name.lower())
        
        async with httpx.AsyncClient() as client:
            if not target_category:
                await check_rate_limit()
                # Get all categories to find the target category ID
                categories_response = await client.get(
                    f"{CMC_BASE_URL}/v1/cryptocurrency/categories",
                    headers=headers
                )
                categories_response.raise_for_status()
                categories_data = categories_response.json()
                
                # Find the category ID
                for cat in categories_data.get("data", []):
                    if cat.get("name", "").lower() == category_name.lower():
                        target_category = cat
                        CATEGORY_CACHE[category_name.lower()] = cat
                        break
            
            if not target_category:
                raise HTTPException(status_code=404, detail=f"Category '{category_name}' not found")
            
            logger.info(f"Found category: {target_category.get('name')} (ID: {target_category.get('id')})")
            
            await check_rate_limit()
            # Get tokens in the category
            response = await client.get(
                f"{CMC_BASE_URL}/v1/cryptocurrency/category",
                headers=headers,
                params={
                    "id": target_category["id"]
                }
            )
            response.raise_for_status()
            data = response.json()
            
            if not data.get("data"):
                raise HTTPException(status_code=500, detail="No data received from CoinMarketCap")
            
            # Get top tokens by market cap
            tokens = sorted(
                data["data"]["coins"],
                key=lambda x: float(x.get("marketCap", 0) or 0),
                reverse=True
            )[:limit]
            
            # Cache token info
            for token in tokens:
                TOKEN_INFO_CACHE[token["id"]] = {
                    "symbol": token["symbol"],
                    "name": token["name"]
                }
            
            # Return simplified token info
            return [{
                "id": token["id"],
                "symbol": token["symbol"],
                "name": token["name"],
                "market_cap": token.get("marketCap", 0)
            } for token in tokens]
            
    except httpx.HTTPError as e:
        logger.error(f"HTTP error occurred: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch category tokens: {str(e)}")
    except Exception as e:
        logger.error(f"Error fetching category tokens: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/tokens/historical")
async def get_tokens_historical_data(token_ids: List[int], days: int = 7):
    """Fetch historical data for a list of token IDs"""
    logger.info(f"Fetching {days} days of historical data for tokens: {token_ids}")
    try:
        end_time = datetime.now()
        start_time = end_time - timedelta(days=days)
        
        all_tokens_history = []
        async with httpx.AsyncClient() as client:
            # Batch get token info
            token_info = await batch_get_token_info(token_ids, client)
            
            for token_id in token_ids:
                # Check historical cache
                cache_key = f"{token_id}_{days}"
                cached_history = HISTORICAL_CACHE.get(cache_key)
                if cached_history:
                    all_tokens_history.append(cached_history)
                    continue
                
                try:
                    token_data = token_info.get(str(token_id))
                    if not token_data:
                        logger.warning(f"No info found for token ID {token_id}")
                        continue
                    
                    await check_rate_limit()
                    # Get historical data
                    hist_response = await client.get(
                        f"{CMC_BASE_URL}/v2/cryptocurrency/quotes/historical",
                        headers=headers,
                        params={
                            "id": str(token_id),
                            "time_start": start_time.strftime("%Y-%m-%dT%H:%M:%S"),
                            "time_end": end_time.strftime("%Y-%m-%dT%H:%M:%S"),
                            "interval": "1d",
                            "count": days,
                        }
                    )
                    hist_response.raise_for_status()
                    hist_data = hist_response.json()
                    
                    if not hist_data.get("data"):
                        logger.warning(f"No historical data for token {token_id}")
                        continue
                    
                    # Process historical data
                    quotes = hist_data["data"]["quotes"]
                    price_history = []
                    prev_price = None
                    
                    # Sort quotes by timestamp
                    sorted_quotes = sorted(quotes, key=lambda x: x["timestamp"])
                    
                    for quote in sorted_quotes:
                        current_price = quote["quote"]["USD"]["price"]
                        
                        # Calculate percentage change
                        percent_change = 0
                        if prev_price is not None:
                            percent_change = ((current_price - prev_price) / prev_price) * 100
                        
                        price_history.append({
                            "timestamp": quote["timestamp"],
                            "price": current_price,
                            "percent_change": round(percent_change, 2)
                        })
                        
                        prev_price = current_price
                    
                    token_history = {
                        "id": token_id,
                        "symbol": token_data["symbol"],
                        "name": token_data["name"],
                        "history": price_history
                    }
                    
                    # Cache the results
                    HISTORICAL_CACHE[cache_key] = token_history
                    all_tokens_history.append(token_history)
                    
                except Exception as e:
                    logger.error(f"Error fetching data for token {token_id}: {str(e)}")
                    continue
            
            return all_tokens_history
            
    except Exception as e:
        logger.error(f"Error fetching historical data: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
