import React, { useEffect, useState } from 'react';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';
import axios from 'axios';

const API_BASE_URL = process.env.REACT_APP_API_URL || 'http://localhost:8000';

const CustomTooltip = ({ active, payload, label }) => {
  if (active && payload && payload.length) {
    const data = payload[0].payload;
    return (
      <div style={{ 
        backgroundColor: 'white', 
        padding: '10px', 
        border: '1px solid #ccc',
        borderRadius: '4px'
      }}>
        <p style={{ margin: '0 0 5px 0' }}><strong>Date:</strong> {label}</p>
        <p style={{ margin: '0 0 5px 0' }}>
          <strong>Price:</strong> ${data.price.toFixed(6)}
        </p>
        <p style={{ 
          margin: '0',
          color: data.percent_change >= 0 ? '#4caf50' : '#f44336'
        }}>
          <strong>Change:</strong> {data.percent_change >= 0 ? '+' : ''}{data.percent_change.toFixed(2)}%
        </p>
      </div>
    );
  }
  return null;
};

const DogeChart = () => {
  const [chartData, setChartData] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const response = await axios.get(`${API_BASE_URL}/api/doge-history`);
        const data = response.data.map(item => ({
          timestamp: new Date(item.timestamp).toLocaleDateString(),
          price: item.price,
          percent_change: item.percent_change
        }));
        setChartData(data);
        setLoading(false);
      } catch (err) {
        console.error('Error fetching DOGE data:', err);
        setError(err.message);
        setLoading(false);
      }
    };

    fetchData();
  }, []);

  if (loading) return <div>Loading chart...</div>;
  if (error) return <div>Error loading chart: {error}</div>;
  if (!chartData.length) return null;

  return (
    <ResponsiveContainer width="100%" height={400}>
      <LineChart data={chartData} margin={{ top: 20, right: 30, left: 20, bottom: 50 }}>
        <CartesianGrid strokeDasharray="3 3" />
        <XAxis
          dataKey="timestamp"
          angle={-45}
          textAnchor="end"
          height={60}
        />
        <YAxis
          tickFormatter={(value) => `${value >= 0 ? '+' : ''}${value.toFixed(2)}%`}
          domain={['dataMin', 'dataMax']}
        />
        <Tooltip content={<CustomTooltip />} />
        <Line
          type="monotone"
          dataKey="percent_change"
          stroke="#f6b93b"
          strokeWidth={2}
          dot={false}
          activeDot={{ r: 8 }}
        />
      </LineChart>
    </ResponsiveContainer>
  );
};

export default DogeChart;
