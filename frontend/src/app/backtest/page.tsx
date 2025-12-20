"use client";

import { useEffect, useState } from "react";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { EquityCurve } from "@/components/charts/EquityCurve";
import { TradesTable } from "@/components/charts/TradesTable";
import {
  loadSweepResults,
  loadEquityCurve,
  loadTrades,
  BacktestResult,
  EquityPoint,
  Trade,
} from "@/utils/dataLoader";

export default function BacktestPage() {
  const [results, setResults] = useState<BacktestResult[]>([]);
  const [equityCurve, setEquityCurve] = useState<EquityPoint[]>([]);
  const [trades, setTrades] = useState<Trade[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedIndex, setSelectedIndex] = useState<number | null>(null);
  const [selectedSymbol, setSelectedSymbol] = useState<string>("全部");
  const [loadingCurve, setLoadingCurve] = useState(false);
  const [loadingTrades, setLoadingTrades] = useState(false);

  useEffect(() => {
    async function loadData() {
      try {
        const [sweepData, equityData] = await Promise.all([
          loadSweepResults(200),  // Load top 200 results from API
          loadEquityCurve(),
        ]);
        setResults(sweepData);
        
        // Auto-select first result and try to load its equity
        if (sweepData.length > 0) {
          const firstResult = sweepData[0];
          setSelectedIndex(0);
          setSelectedSymbol(firstResult.symbol);
          
          // Try to load equity and trades for first result
          const [firstEquity, firstTrades] = await Promise.all([
            loadEquityCurve(firstResult.id),
            loadTrades(firstResult.id),
          ]);
          
          if (firstEquity.length > 0) {
            setEquityCurve(firstEquity);
          } else {
            // If first doesn't have equity, use fallback
            setEquityCurve(equityData);
          }
          
          setTrades(firstTrades);
        } else {
          setEquityCurve(equityData);
        }
      } catch (error) {
        console.error("Failed to load data:", error);
      } finally {
        setLoading(false);
      }
    }
    loadData();
  }, []);

  const handleRowClick = async (index: number, result: BacktestResult) => {
    setSelectedIndex(index);
    setSelectedSymbol(result.symbol);
    setLoadingCurve(true);
    setLoadingTrades(true);
    
    try {
      // Load equity curve and trades concurrently
      const [equityData, tradesData] = await Promise.all([
        loadEquityCurve(result.id),
        loadTrades(result.id),
      ]);
      
      if (equityData.length > 0) {
        setEquityCurve(equityData);
      } else {
        console.warn(`No equity data for ${result.id}`);
      }
      
      setTrades(tradesData);
    } catch (error) {
      console.error("Failed to load data for selected result:", error);
    } finally {
      setLoadingCurve(false);
      setLoadingTrades(false);
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-slate-50 to-slate-100 dark:from-slate-950 dark:to-slate-900 p-8">
        <div className="container mx-auto">
          <Skeleton className="h-12 w-64 mb-8" />
          <Skeleton className="h-64 w-full mb-8" />
          <Skeleton className="h-32 w-full" />
        </div>
      </div>
    );
  }

  // Calculate metrics safely
  const hasData = results.length > 0;
  const maxReturn = hasData ? Math.max(...results.map(r => r.metrics.total_return || 0)) : 0;
  const maxSharpe = hasData ? Math.max(...results.map(r => r.metrics.sharpe || 0)) : 0;
  const minDrawdown = hasData ? Math.min(...results.map(r => r.metrics.max_drawdown || 0)) : 0;

  // Empty state
  if (!hasData) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-slate-50 to-slate-100 dark:from-slate-950 dark:to-slate-900">
        <div className="container mx-auto p-8">
          <header className="mb-8">
            <h1 className="text-4xl font-bold mb-2">回测结果</h1>
            <p className="text-slate-600 dark:text-slate-400">
              策略性能分析与参数对比
            </p>
          </header>

          <Card className="p-12 text-center">
            <div className="max-w-md mx-auto">
              <div className="text-6xl mb-4">📊</div>
              <h2 className="text-2xl font-semibold mb-4">暂无回测数据</h2>
              <p className="text-slate-600 dark:text-slate-400 mb-6">
                数据库中还没有回测结果。运行参数扫描后，结果会自动显示在这里。
              </p>
              <div className="bg-slate-100 dark:bg-slate-800 rounded-lg p-4 text-left">
                <p className="font-mono text-sm mb-2">运行 sweep 生成数据：</p>
                <code className="block bg-slate-900 dark:bg-slate-950 text-green-400 p-3 rounded">
                  cd backend<br/>
                  uv run python main.py sweep --config config/config.yml
                </code>
              </div>
            </div>
          </Card>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 to-slate-100 dark:from-slate-950 dark:to-slate-900">
      <div className="container mx-auto p-8">
        <header className="mb-8">
          <h1 className="text-4xl font-bold mb-2">回测结果</h1>
          <p className="text-slate-600 dark:text-slate-400">
            策略性能分析与参数对比 - {selectedSymbol} (Top 200)
          </p>
          <p className="text-sm text-slate-500 dark:text-slate-500 mt-2">
            💡 点击表格中的任意行查看对应的收益曲线 {equityCurve.length === 0 && selectedIndex !== null && "(当前选中结果无收益曲线)"}
          </p>
        </header>

        {/* 数据展示 Tabs */}
        <Card className="p-6 mb-8">
          <Tabs defaultValue="equity" className="w-full">
            <TabsList className="grid w-full grid-cols-2 mb-4">
              <TabsTrigger value="equity">收益曲线</TabsTrigger>
              <TabsTrigger value="trades">
                交易记录 {trades.length > 0 && `(${trades.length})`}
              </TabsTrigger>
            </TabsList>
            
            <TabsContent value="equity" className="mt-0">
              {loadingCurve ? (
                <Skeleton className="h-64 w-full" />
              ) : equityCurve.length > 0 ? (
                <>
                  <div className="flex items-center justify-between mb-4">
                    <h3 className="text-lg font-semibold">收益曲线</h3>
                    {selectedIndex !== null && (
                      <Badge variant="outline">
                        当前查看: #{selectedIndex + 1} 排名
                      </Badge>
                    )}
                  </div>
                  <EquityCurve data={equityCurve} title="" />
                </>
              ) : (
                <div className="flex flex-col items-center justify-center h-64 text-slate-500">
                  <div className="text-4xl mb-3">📈</div>
                  <p>该回测无收益曲线数据</p>
                  <p className="text-sm mt-2">仅存储了摘要指标</p>
                </div>
              )}
            </TabsContent>
            
            <TabsContent value="trades" className="mt-0">
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-lg font-semibold">交易详情</h3>
                {selectedIndex !== null && (
                  <Badge variant="outline">
                    当前查看: #{selectedIndex + 1} 排名
                  </Badge>
                )}
              </div>
              <TradesTable trades={trades} loading={loadingTrades} />
            </TabsContent>
          </Tabs>
        </Card>

        {/* 性能指标卡片 */}
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-8">
          <Card className="p-4">
            <p className="text-sm text-slate-500 dark:text-slate-400 mb-1">
              最高收益率
            </p>
            <p className={`text-2xl font-bold ${maxReturn > 0 ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'}`}>
              {(maxReturn * 100).toFixed(2)}%
            </p>
          </Card>
          <Card className="p-4">
            <p className="text-sm text-slate-500 dark:text-slate-400 mb-1">
              最高夏普
            </p>
            <p className="text-2xl font-bold">{maxSharpe.toFixed(2)}</p>
          </Card>
          <Card className="p-4">
            <p className="text-sm text-slate-500 dark:text-slate-400 mb-1">
              最小回撤
            </p>
            <p className="text-2xl font-bold text-red-600 dark:text-red-400">
              {(minDrawdown * 100).toFixed(2)}%
            </p>
          </Card>
          <Card className="p-4">
            <p className="text-sm text-slate-500 dark:text-slate-400 mb-1">
              总测试数
            </p>
            <p className="text-2xl font-bold">{results.length}</p>
          </Card>
        </div>

        {/* 参数对比表格 */}
        <Card className="p-6">
          <h2 className="text-2xl font-semibold mb-4">参数对比 (Top 20)</h2>
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>排名</TableHead>
                  <TableHead>品种</TableHead>
                  <TableHead>窗口</TableHead>
                  <TableHead>K值</TableHead>
                  <TableHead className="text-right">总收益</TableHead>
                  <TableHead className="text-right">夏普比率</TableHead>
                  <TableHead className="text-right">最大回撤</TableHead>
                  <TableHead className="text-right">胜率</TableHead>
                  <TableHead className="text-right">交易次数</TableHead>
                  <TableHead className="text-right">综合评分</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {results
                  .sort((a, b) => b.score - a.score)
                  .slice(0, 20)
                  .map((result, index) => (
                    <TableRow 
                      key={index}
                      onClick={() => handleRowClick(index, result)}
                      className={`cursor-pointer transition-colors hover:bg-slate-100 dark:hover:bg-slate-800 ${
                        selectedIndex === index ? 'bg-blue-50 dark:bg-blue-950' : ''
                      }`}
                    >
                      <TableCell>
                        <Badge
                          variant={index === 0 ? "default" : "secondary"}
                          className={index === 0 ? "bg-yellow-500" : ""}
                        >
                          #{index + 1}
                        </Badge>
                      </TableCell>
                      <TableCell className="font-medium">
                        {result.symbol}
                      </TableCell>
                      <TableCell>{result.params.window}</TableCell>
                      <TableCell>{result.params.k}</TableCell>
                      <TableCell
                        className={`text-right font-semibold ${
                          (result.metrics.total_return || 0) > 0
                            ? "text-green-600 dark:text-green-400"
                            : "text-red-600 dark:text-red-400"
                        }`}
                      >
                        {((result.metrics.total_return || 0) * 100).toFixed(2)}%
                      </TableCell>
                      <TableCell className="text-right">
                        {result.metrics.sharpe?.toFixed(2) || "N/A"}
                      </TableCell>
                      <TableCell className="text-right text-red-600 dark:text-red-400">
                        {((result.metrics.max_drawdown || 0) * 100).toFixed(2)}%
                      </TableCell>
                      <TableCell className="text-right">
                        {((result.metrics.win_rate || 0) * 100).toFixed(1)}%
                      </TableCell>
                      <TableCell className="text-right">
                        {result.metrics.total_trades}
                      </TableCell>
                      <TableCell className="text-right font-bold">
                        {result.score.toFixed(3)}
                      </TableCell>
                    </TableRow>
                  ))}
              </TableBody>
            </Table>
          </div>
        </Card>

        <div className="mt-8 text-center text-sm text-slate-500 dark:text-slate-400">
          <p>数据来源: backend/results/ | 显示 Top 20 策略参数组合</p>
          <p className="mt-1 text-xs">
            ⚠️ 注意：当前版本使用统一的收益曲线数据。待 Go API 完成后，将显示每个参数组合的真实曲线。
          </p>
        </div>
      </div>
    </div>
  );
}
