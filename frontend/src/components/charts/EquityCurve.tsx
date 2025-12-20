"use client";

import { useMemo } from "react";
import React from "react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";

interface EquityPoint {
  timestamp: Date;
  equity: number;
}

interface EquityCurveProps {
  data: EquityPoint[];
  title?: string;
}

// Downsample data to max points while keeping extremes
function downsampleData(data: EquityPoint[], maxPoints: number = 1000): EquityPoint[] {
  if (data.length <= maxPoints) return data;
  
  const step = Math.floor(data.length / maxPoints);
  const downsampled: EquityPoint[] = [];
  
  for (let i = 0; i < data.length; i += step) {
    downsampled.push(data[i]);
  }
  
  // Always include the last point
  if (downsampled[downsampled.length - 1] !== data[data.length - 1]) {
    downsampled.push(data[data.length - 1]);
  }
  
  return downsampled;
}

const EquityCurveComponent = ({ data, title = "收益曲线" }: EquityCurveProps) => {
  // Downsample and transform data - memoized to prevent re-calculation
  const chartData = useMemo(() => {
    const sampled = downsampleData(data, 1000);
    return sampled.map(d => ({
      date: d.timestamp instanceof Date ? d.timestamp.toISOString().split('T')[0] : d.timestamp,
      equity: d.equity
    }));
  }, [data]);

  return (
    <div className="w-full">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-lg font-semibold">{title}</h3>
        {data.length > 1000 && (
          <span className="text-xs text-slate-500">
            显示 {chartData.length.toLocaleString()} / {data.length.toLocaleString()} 点
          </span>
        )}
      </div>
      <ResponsiveContainer width="100%" height={300}>
        <LineChart data={chartData}>
          <CartesianGrid strokeDasharray="3 3" className="stroke-slate-200 dark:stroke-slate-700" />
          <XAxis
            dataKey="date"
            tick={{ fontSize: 12 }}
            className="text-slate-600 dark:text-slate-400"
          />
          <YAxis
            tick={{ fontSize: 12 }}
            className="text-slate-600 dark:text-slate-400"
            domain={[(dataMin: number) => Math.floor(dataMin - 10), (dataMax: number) => Math.ceil(dataMax + 10)]}
            tickFormatter={(value) => Math.round(value).toString()}
          />
          <Tooltip
            contentStyle={{
              backgroundColor: "hsl(var(--background))",
              border: "1px solid hsl(var(--border))",
              borderRadius: "0.5rem",
            }}
          />
          <Legend />
          <Line
            type="monotone"
            dataKey="equity"
            stroke="#3b82f6"
            strokeWidth={2}
            dot={false}
            name="权益"
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
};

// Export memoized component to prevent unnecessary re-renders
export const EquityCurve = React.memo(EquityCurveComponent);
