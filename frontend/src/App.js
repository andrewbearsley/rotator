import React, { useState, useEffect } from 'react';
import { 
  Container, 
  Typography, 
  Box, 
  Grid, 
  Card, 
  CardContent,
  CircularProgress,
  Pagination,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  TextField,
  IconButton,
  Tooltip,
  Switch,
  FormControlLabel
} from '@mui/material';
import { ArrowUpward, ArrowDownward, Clear as ClearIcon, Star, StarBorder } from '@mui/icons-material';
import axios from 'axios';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip as ChartTooltip, Legend } from 'recharts';

const API_BASE_URL = process.env.REACT_APP_API_URL || 'http://localhost:8000';

const DEFAULT_FAVORITES = [
  'Memes',
  'AI & Big Data',
  'DeFi',
  'Gaming',
  'Metaverse',
  'NFTs & Collectibles',
  'Ethereum Ecosystem',
  'Solana Ecosystem',
  'Layer 1',
  'Layer 2',
  '2017/18 Alt season'
];

const SORT_OPTIONS = [
  { value: 'market_cap', label: 'Market Cap' },
  { value: 'market_cap_change_24h', label: 'Market Cap 24h Change' },
  { value: 'volume_change_24h', label: 'Volume 24h Change' },
  { value: 'price_change_24h', label: 'Price 24h Change' },
  { value: 'name', label: 'Name' }
];

function App() {
  const [categories, setCategories] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [page, setPage] = useState(1);
  const [itemsPerPage, setItemsPerPage] = useState(20);
  const [searchTerm, setSearchTerm] = useState('');
  const [sortBy, setSortBy] = useState('market_cap');
  const [sortDirection, setSortDirection] = useState('desc');
  const [showFavoritesOnly, setShowFavoritesOnly] = useState(false);
  const [favorites, setFavorites] = useState(new Set(DEFAULT_FAVORITES));
  const [selectedCategory, setSelectedCategory] = useState(null);
  const [historicalData, setHistoricalData] = useState([]);
  const [historicalLoading, setHistoricalLoading] = useState(false);

  useEffect(() => {
    const fetchCategories = async () => {
      try {
        const response = await axios.get(`${API_BASE_URL}/api/categories`);
        setCategories(response.data.data);
        setLoading(false);
      } catch (err) {
        setError('Failed to fetch category data');
        setLoading(false);
      }
    };

    fetchCategories();
    const interval = setInterval(fetchCategories, 300000);

    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    const savedFavorites = localStorage.getItem('favorites');
    if (savedFavorites) {
      setFavorites(new Set(JSON.parse(savedFavorites)));
    }
  }, []);

  useEffect(() => {
    const fetchHistoricalData = async () => {
      if (!selectedCategory) return;
      
      setHistoricalLoading(true);
      try {
        const response = await axios.get(`${API_BASE_URL}/api/categories/${selectedCategory.id}/historical`);
        setHistoricalData(response.data.data);
      } catch (err) {
        console.error('Failed to fetch historical data:', err);
      } finally {
        setHistoricalLoading(false);
      }
    };

    fetchHistoricalData();
  }, [selectedCategory]);

  const toggleFavorite = (categoryName) => {
    setFavorites(prevFavorites => {
      const newFavorites = new Set(prevFavorites);
      if (newFavorites.has(categoryName)) {
        newFavorites.delete(categoryName);
      } else {
        newFavorites.add(categoryName);
      }
      localStorage.setItem('favorites', JSON.stringify([...newFavorites]));
      return newFavorites;
    });
  };

  const isFavorite = (categoryName) => favorites.has(categoryName);

  const handleSortChange = (event) => {
    setSortBy(event.target.value);
  };

  const toggleSortDirection = () => {
    setSortDirection(prev => prev === 'asc' ? 'desc' : 'asc');
  };

  const sortCategories = (categories) => {
    return [...categories].sort((a, b) => {
      let aValue = a[sortBy];
      let bValue = b[sortBy];
      
      if (typeof aValue === 'string') {
        aValue = aValue.toLowerCase();
        bValue = bValue.toLowerCase();
      }
      
      if (aValue == null) aValue = sortDirection === 'asc' ? Infinity : -Infinity;
      if (bValue == null) bValue = sortDirection === 'asc' ? Infinity : -Infinity;
      
      if (aValue < bValue) return sortDirection === 'asc' ? -1 : 1;
      if (aValue > bValue) return sortDirection === 'asc' ? 1 : -1;
      return 0;
    });
  };

  const filteredCategories = categories
    .filter(category => {
      const searchLower = searchTerm.toLowerCase();
      const matches = (
        category.name.toLowerCase().includes(searchLower) ||
        category.title?.toLowerCase().includes(searchLower) ||
        category.description?.toLowerCase().includes(searchLower)
      );
      
      if (showFavoritesOnly) {
        return matches && isFavorite(category.name);
      }
      
      return matches;
    });

  const sortedCategories = sortCategories(filteredCategories);
  
  // Add ranking to categories based on market cap
  const rankedCategories = sortedCategories.map((category, index) => ({
    ...category,
    rank: categories
      .slice()
      .sort((a, b) => (b.market_cap || 0) - (a.market_cap || 0))
      .findIndex(c => c.id === category.id) + 1
  }));

  const startIndex = (page - 1) * itemsPerPage;
  const displayedCategories = rankedCategories.slice(startIndex, startIndex + itemsPerPage);

  const handlePageChange = (event, value) => {
    setPage(value);
  };

  const handleItemsPerPageChange = (event) => {
    setItemsPerPage(event.target.value);
    setPage(1);
  };

  const handleCategoryClick = (category) => {
    setSelectedCategory(category);
  };

  if (loading) {
    return (
      <Box display="flex" justifyContent="center" alignItems="center" minHeight="100vh">
        <CircularProgress />
      </Box>
    );
  }

  if (error) {
    return (
      <Box display="flex" justifyContent="center" alignItems="center" minHeight="100vh">
        <Typography color="error">{error}</Typography>
      </Box>
    );
  }

  const formatPercentage = (value) => {
    if (value == null) return 'N/A';
    const formatted = value.toFixed(2);
    const color = value > 0 ? 'success.main' : value < 0 ? 'error.main' : 'text.secondary';
    return <Typography color={color} component="span">{formatted}%</Typography>;
  };

  return (
    <Container maxWidth="lg">
      <Box py={4}>
        <Typography variant="h4" component="h1" gutterBottom>
          Crypto Category Rotation Tracker
        </Typography>

        <Box mb={3} display="flex" gap={2} alignItems="center" flexWrap="wrap">
          <TextField
            label="Search Categories"
            variant="outlined"
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            size="small"
            placeholder="Search by name, title, or description"
            sx={{ minWidth: 250 }}
            InputProps={{
              endAdornment: searchTerm && (
                <IconButton
                  size="small"
                  onClick={() => setSearchTerm('')}
                  edge="end"
                >
                  <ClearIcon />
                </IconButton>
              ),
            }}
          />
          <FormControlLabel
            control={
              <Switch
                checked={showFavoritesOnly}
                onChange={(e) => setShowFavoritesOnly(e.target.checked)}
              />
            }
            label="Favorites Only"
          />
          <FormControl size="small" sx={{ minWidth: 200 }}>
            <InputLabel>Sort By</InputLabel>
            <Select
              value={sortBy}
              label="Sort By"
              onChange={handleSortChange}
            >
              {SORT_OPTIONS.map(option => (
                <MenuItem key={option.value} value={option.value}>
                  {option.label}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
          <Tooltip title={sortDirection === 'asc' ? 'Sort Ascending' : 'Sort Descending'}>
            <IconButton onClick={toggleSortDirection} size="small">
              {sortDirection === 'asc' ? <ArrowUpward /> : <ArrowDownward />}
            </IconButton>
          </Tooltip>
          <FormControl size="small">
            <InputLabel>Items per page</InputLabel>
            <Select
              value={itemsPerPage}
              label="Items per page"
              onChange={handleItemsPerPageChange}
            >
              <MenuItem value={10}>10</MenuItem>
              <MenuItem value={20}>20</MenuItem>
              <MenuItem value={50}>50</MenuItem>
              <MenuItem value={100}>100</MenuItem>
            </Select>
          </FormControl>
        </Box>

        <Grid container spacing={3}>
          {displayedCategories.map((category) => (
            <Grid item xs={12} md={6} key={category.id}>
              <Card 
                sx={{ 
                  cursor: 'pointer',
                  '&:hover': { boxShadow: 6 }
                }}
                onClick={() => handleCategoryClick(category)}
              >
                <CardContent>
                  <Box display="flex" justifyContent="space-between" alignItems="center">
                    <Box display="flex" alignItems="center" gap={1}>
                      <Typography variant="body2" color="textSecondary" sx={{ minWidth: '3rem' }}>
                        #{category.rank}
                      </Typography>
                      <Typography variant="h6" component="h2">
                        {category.name}
                      </Typography>
                    </Box>
                    <IconButton 
                      onClick={(e) => {
                        e.stopPropagation();
                        toggleFavorite(category.name);
                      }}
                      size="small"
                      sx={{ ml: 1 }}
                    >
                      {isFavorite(category.name) ? (
                        <Star color="primary" />
                      ) : (
                        <StarBorder />
                      )}
                    </IconButton>
                  </Box>
                  <Typography color="textSecondary">
                    Market Cap: ${Number(category.market_cap).toLocaleString()}
                  </Typography>
                  <Typography color="textSecondary">
                    Market Cap 24h: {formatPercentage(category.market_cap_change_24h)}
                  </Typography>
                  <Typography color="textSecondary">
                    Volume 24h: {formatPercentage(category.volume_change_24h)}
                  </Typography>
                  <Typography color="textSecondary">
                    Price 24h: {formatPercentage(category.price_change_24h)}
                  </Typography>
                  {selectedCategory?.id === category.id && (
                    <Box mt={2}>
                      {historicalLoading ? (
                        <Box display="flex" justifyContent="center" p={2}>
                          <CircularProgress size={24} />
                        </Box>
                      ) : historicalData && historicalData.length > 0 ? (
                        <LineChart
                          width={500}
                          height={300}
                          data={historicalData}
                          margin={{
                            top: 5,
                            right: 30,
                            left: 20,
                            bottom: 5,
                          }}
                        >
                          <CartesianGrid strokeDasharray="3 3" />
                          <XAxis 
                            dataKey="timestamp" 
                            tickFormatter={(timestamp) => new Date(timestamp).toLocaleDateString()}
                          />
                          <YAxis 
                            yAxisId="left"
                            tickFormatter={(value) => `$${(value / 1e9).toFixed(1)}B`}
                          />
                          <YAxis 
                            yAxisId="right" 
                            orientation="right"
                            tickFormatter={(value) => `$${(value / 1e9).toFixed(1)}B`}
                          />
                          <Tooltip
                            content={({ active, payload, label }) => {
                              if (active && payload && payload.length) {
                                return (
                                  <Box sx={{ bgcolor: 'background.paper', p: 1, border: 1, borderColor: 'divider' }}>
                                    <Typography variant="body2">
                                      {new Date(label).toLocaleDateString()}
                                    </Typography>
                                    {payload.map((entry) => (
                                      <Typography
                                        key={entry.name}
                                        variant="body2"
                                        sx={{ color: entry.color }}
                                      >
                                        {entry.name}: ${(entry.value / 1e9).toFixed(2)}B
                                      </Typography>
                                    ))}
                                  </Box>
                                );
                              }
                              return null;
                            }}
                          />
                          <Legend />
                          <Line
                            yAxisId="left"
                            type="monotone"
                            dataKey="market_cap"
                            stroke="#8884d8"
                            name="Market Cap"
                          />
                          <Line
                            yAxisId="right"
                            type="monotone"
                            dataKey="volume_24h"
                            stroke="#82ca9d"
                            name="Volume 24h"
                          />
                        </LineChart>
                      ) : (
                        <Typography color="text.secondary" align="center">
                          No historical data available
                        </Typography>
                      )}
                    </Box>
                  )}
                </CardContent>
              </Card>
            </Grid>
          ))}
        </Grid>

        <Box mt={3} display="flex" justifyContent="center">
          <Pagination 
            count={Math.ceil(rankedCategories.length / itemsPerPage)} 
            page={page} 
            onChange={handlePageChange}
            color="primary"
          />
        </Box>

        <Box mt={4}>
          <Typography variant="h5" component="h2" gutterBottom>
            Top Categories Performance
          </Typography>
          <LineChart
            width={800}
            height={400}
            data={sortedCategories.slice(0, 10)}
            margin={{ top: 5, right: 30, left: 20, bottom: 5 }}
          >
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="name" />
            <YAxis />
            <ChartTooltip />
            <Legend />
            <Line type="monotone" dataKey="price_change_24h" name="Price 24h Change" stroke="#8884d8" />
            <Line type="monotone" dataKey="market_cap_change_24h" name="Market Cap 24h Change" stroke="#82ca9d" />
            <Line type="monotone" dataKey="volume_change_24h" name="Volume 24h Change" stroke="#ffc658" />
          </LineChart>
        </Box>
      </Box>
    </Container>
  );
}

export default App;
