"use client";

import { useMemo } from "react";
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

export function EquityCurve({ data, title = "收益曲线" }: EquityCurveProps) {
  // Transform data for chart - memoized to prevent re-calculation
  const chartData = useMemo(() => 
    data.map(d => ({
      date: d.timestamp instanceof Date ? d.timestamp.toISOString().split('T')[0] : d.timestamp,
      equity: d.equity
    })),
    [data]
  );

  return (
    <div className="w-full">
      <h3 className="text-lg font-semibold mb-4">{title}</h3>
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
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
