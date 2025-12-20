"use client";

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
  timestamp: string;
  equity: number;
}

interface EquityCurveProps {
  data: EquityPoint[];
  title?: string;
}

export function EquityCurve({ data, title = "收益曲线" }: EquityCurveProps) {
  return (
    <div className="w-full">
      <h3 className="text-lg font-semibold mb-4">{title}</h3>
      <ResponsiveContainer width="100%" height={300}>
        <LineChart data={data}>
          <CartesianGrid strokeDasharray="3 3" className="stroke-slate-200 dark:stroke-slate-700" />
          <XAxis
            dataKey="timestamp"
            tick={{ fontSize: 12 }}
            className="text-slate-600 dark:text-slate-400"
          />
          <YAxis
            tick={{ fontSize: 12 }}
            className="text-slate-600 dark:text-slate-400"
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
