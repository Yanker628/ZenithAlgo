import React from "react";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Trade } from "@/utils/dataLoader";

interface TradesTableProps {
  trades: Trade[];
  loading?: boolean;
}

export function TradesTable({ trades, loading }: TradesTableProps) {
  if (loading) {
    return (
      <div className="flex items-center justify-center p-8">
        <div className="text-slate-500">加载交易记录中...</div>
      </div>
    );
  }

  if (trades.length === 0) {
    return (
      <div className="flex items-center justify-center p-8">
        <div className="text-slate-500">暂无交易记录</div>
      </div>
    );
  }

  return (
    <div className="rounded-md border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>时间</TableHead>
            <TableHead>品种</TableHead>
            <TableHead>方向</TableHead>
            <TableHead className="text-right">价格</TableHead>
            <TableHead className="text-right">数量</TableHead>
            <TableHead className="text-right">盈亏</TableHead>
            <TableHead className="text-right">手续费</TableHead>
            <TableHead className="text-right">累计盈亏</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {trades.map((trade, index) => (
            <TableRow key={index}>
              <TableCell className="font-mono text-sm">
                {new Date(trade.timestamp).toLocaleString('zh-CN', {
                  year: 'numeric',
                  month: '2-digit',
                  day: '2-digit',
                  hour: '2-digit',
                  minute: '2-digit',
                  timeZone: 'Asia/Shanghai',
                })}
              </TableCell>
              <TableCell className="font-medium">{trade.symbol}</TableCell>
              <TableCell>
                <Badge 
                  className={
                    trade.side.toLowerCase() === 'buy' 
                      ? 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200' 
                      : 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200'
                  }
                >
                  {trade.side.toUpperCase()}
                </Badge>
              </TableCell>
              <TableCell className="text-right font-mono">
                ${trade.price.toFixed(4)}
              </TableCell>
              <TableCell className="text-right font-mono">
                {trade.qty.toFixed(2)}
              </TableCell>
              <TableCell className={`text-right font-mono ${
                trade.pnl !== undefined && trade.pnl !== null
                  ? trade.pnl > 0 
                    ? 'text-green-600 dark:text-green-400' 
                    : trade.pnl < 0
                    ? 'text-red-600 dark:text-red-400'
                    : ''
                  : 'text-slate-400'
              }`}>
                {trade.pnl !== undefined && trade.pnl !== null 
                  ? `$${trade.pnl.toFixed(2)}` 
                  : '-'}
              </TableCell>
              <TableCell className="text-right font-mono text-slate-600 dark:text-slate-400">
                {trade.commission !== undefined && trade.commission !== null
                  ? `$${trade.commission.toFixed(4)}`
                  : '-'}
              </TableCell>
              <TableCell className={`text-right font-mono font-semibold ${
                trade.cumulative_pnl !== undefined && trade.cumulative_pnl !== null
                  ? trade.cumulative_pnl > 0 
                    ? 'text-green-600 dark:text-green-400' 
                    : trade.cumulative_pnl < 0
                    ? 'text-red-600 dark:text-red-400'
                    : ''
                  : 'text-slate-400'
              }`}>
                {trade.cumulative_pnl !== undefined && trade.cumulative_pnl !== null
                  ? `$${trade.cumulative_pnl.toFixed(2)}`
                  : '-'}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
