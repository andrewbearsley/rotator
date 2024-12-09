# Crypto Category Rotation Tracker

A real-time cryptocurrency category tracking application that helps monitor and analyze different cryptocurrency categories, their market performance, and trends.

## Features

- Real-time tracking of cryptocurrency categories
- Interactive charts showing price, market cap, and volume changes
- Search functionality to filter categories
- Customizable favorites system
- Sorting capabilities by various metrics
- 24-hour change indicators for market cap, volume, and price
- Responsive design for desktop and mobile viewing

## Tech Stack

- **Frontend**: React with Material-UI
- **Backend**: FastAPI
- **Database**: MongoDB
- **Containerization**: Docker
- **API**: CoinMarketCap

## Getting Started

### Prerequisites

- Node.js (v14 or higher)
- Python 3.8+
- Docker and Docker Compose
- CoinMarketCap API Key

### Environment Setup

1. Clone the repository:
```bash
git clone https://github.com/andrewbearsley/rotator.git
cd rotator
```

2. Create a `.env` file in the root directory with your CoinMarketCap API key:
```
CMC_API_KEY=your_api_key_here
```

3. Start the application using Docker Compose:
```bash
docker-compose up --build
```

The application will be available at:
- Frontend: http://localhost:3000
- Backend API: http://localhost:8000

## Development

### Frontend

```bash
cd frontend
npm install
npm start
```

### Backend

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload
```

## License

MIT License
