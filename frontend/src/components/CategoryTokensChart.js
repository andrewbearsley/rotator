import React, { useEffect, useState } from 'react';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from 'recharts';
import axios from 'axios';

const API_BASE_URL = process.env.REACT_APP_API_URL || 'http://localhost:8000';

// Array of colors for different tokens
const TOKEN_COLORS = [
  '#f6b93b', '#4caf50', '#2196f3', '#9c27b0', '#f44336',
  '#ff9800', '#795548', '#607d8b', '#e91e63', '#00bcd4'
];

const CustomTooltip = ({ active, payload, label }) => {
  if (active && payload && payload.length) {
    return (
      <div style={{ 
        backgroundColor: 'white', 
        padding: '10px', 
        border: '1px solid #ccc',
        borderRadius: '4px'
      }}>
        <p style={{ margin: '0 0 5px 0' }}><strong>Date:</strong> {label}</p>
        {payload.map((entry, index) => (
          <p key={index} style={{ 
            margin: '0 0 5px 0',
            color: entry.color
          }}>
            <strong>{entry.name}:</strong>{' '}
            ${entry.payload[`${entry.dataKey}_price`].toFixed(6)}{' '}
            ({entry.value >= 0 ? '+' : ''}{entry.value.toFixed(2)}%)
          </p>
        ))}
      </div>
    );
  }
  return null;
};

const CategoryTokensChart = ({ categoryName }) => {
  const [chartData, setChartData] = useState([]);
  const [tokens, setTokens] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    const fetchData = async () => {
      if (!categoryName) return;
      
      setLoading(true);
      setError(null);
      
      try {
        // First, get top tokens for the category
        const tokensResponse = await axios.get(`${API_BASE_URL}/api/category/${categoryName}/top-tokens?limit=10`);
        const topTokens = tokensResponse.data;
        
        // Get historical data for these tokens
        const historicalResponse = await axios.post(
          `${API_BASE_URL}/api/tokens/historical?days=7`,
          topTokens.map(token => token.id)
        );
        const tokensData = historicalResponse.data;
        
        // Store token info
        setTokens(tokensData.map(token => ({
          id: token.id,
          symbol: token.symbol,
          name: token.name
        })));
        
        // Transform data for the chart
        const transformedData = {};
        tokensData.forEach(token => {
          token.history.forEach(point => {
            const date = new Date(point.timestamp).toLocaleDateString();
            if (!transformedData[date]) {
              transformedData[date] = { date };
            }
            transformedData[date][`${token.symbol}`] = point.percent_change;
            transformedData[date][`${token.symbol}_price`] = point.price;
          });
        });
        
        setChartData(Object.values(transformedData));
        setLoading(false);
      } catch (err) {
        console.error('Error fetching category tokens data:', err);
        setError(err.message);
        setLoading(false);
      }
    };

    fetchData();
  }, [categoryName]);

  if (loading) return <div>Loading chart...</div>;
  if (error) return <div>Error loading chart: {error}</div>;
  if (!chartData.length) return null;

  return (
    <>
      <h2 style={{ textAlign: 'center', marginBottom: '20px' }}>
        Top 10 {categoryName} Tokens Performance
      </h2>
      <ResponsiveContainer width="100%" height={400}>
        <LineChart data={chartData} margin={{ top: 20, right: 30, left: 20, bottom: 50 }}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis
            dataKey="date"
            angle={-45}
            textAnchor="end"
            height={60}
          />
          <YAxis
            tickFormatter={(value) => `${value >= 0 ? '+' : ''}${value.toFixed(2)}%`}
            domain={['dataMin', 'dataMax']}
          />
          <Tooltip content={<CustomTooltip />} />
          <Legend />
          {tokens.map((token, index) => (
            <Line
              key={token.symbol}
              type="monotone"
              dataKey={token.symbol}
              name={`${token.name} (${token.symbol})`}
              stroke={TOKEN_COLORS[index % TOKEN_COLORS.length]}
              dot={false}
              strokeWidth={2}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </>
  );
};

export default CategoryTokensChart;
