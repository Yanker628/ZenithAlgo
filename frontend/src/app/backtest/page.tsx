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
import { EquityCurve, EquityPoint } from "@/components/charts/EquityCurve";
import { TradesTable } from "@/components/charts/TradesTable";
import BacktestDashboard from "@/components/BacktestDashboard";
import {
  loadSweepResults,
  loadEquityCurve,
  loadTrades,
  BacktestResult,
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

  const fetchHistory = async (background: boolean = false) => {
    if (!background) {
        setLoading(true);
    }
    try {
      const [sweepData, equityData] = await Promise.all([
        loadSweepResults(200),
        loadEquityCurve(), // Fallback/Default equity curve
      ]);
      setResults(sweepData);

      // Auto-select first result if available and no selection made
      if (sweepData.length > 0 && selectedIndex === null) {
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
          setEquityCurve(equityData);
        }
        setTrades(firstTrades);
      } else if (sweepData.length === 0) {
        setEquityCurve(equityData);
      }
    } catch (error) {
      console.error("Failed to load data:", error);
    } finally {
      if (!background) {
          setLoading(false);
      }
    }
  };

  useEffect(() => {
    fetchHistory(false);
  }, []);

  const handleRowClick = async (index: number, result: BacktestResult) => {
    setSelectedIndex(index);
    setSelectedSymbol(result.symbol);
    setLoadingCurve(true);
    setLoadingTrades(true);
    
    try {
      const [equityData, tradesData] = await Promise.all([
        loadEquityCurve(result.id),
        loadTrades(result.id),
      ]);
      
      if (equityData.length > 0) {
        setEquityCurve(equityData);
      } else {
        // Fallback or empty
        setEquityCurve([]);
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

  // Safe metrics usage
  const hasData = results.length > 0;
  const maxReturn = hasData ? Math.max(...results.map(r => r.metrics?.total_return || 0)) : 0;
  const maxSharpe = hasData ? Math.max(...results.map(r => r.metrics?.sharpe || 0)) : 0;
  const minDrawdown = hasData ? Math.min(...results.map(r => r.metrics?.max_drawdown || 0)) : 0;

  if (loading) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-slate-50 to-slate-100 dark:from-slate-950 dark:to-slate-900 p-8">
        <div className="container mx-auto">
          <Skeleton className="h-12 w-64 mb-8" />
          <Skeleton className="h-64 w-full mb-8" />
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 to-slate-100 dark:from-slate-950 dark:to-slate-900">
      <div className="container mx-auto p-8">
        <header className="mb-8 flex justify-between items-center">
          <div>
            <h1 className="text-4xl font-bold mb-2">Quant Lab</h1>
            <p className="text-slate-600 dark:text-slate-400">
              ZenithAlgo Research Platform
            </p>
          </div>
        </header>

        <Tabs defaultValue="run" className="w-full">
          <TabsList className="mb-6 w-full justify-start border-b rounded-none h-auto p-0 bg-transparent">
             <TabsTrigger value="run" className="px-6 py-3 rounded-t-lg data-[state=active]:bg-white dark:data-[state=active]:bg-slate-800 data-[state=active]:border-b-0 border border-transparent mx-1">
                🚀 运行回测 (Run)
             </TabsTrigger>
             <TabsTrigger value="history" className="px-6 py-3 rounded-t-lg data-[state=active]:bg-white dark:data-[state=active]:bg-slate-800 data-[state=active]:border-b-0 border border-transparent mx-1">
                📚 历史记录 (History)
             </TabsTrigger>
          </TabsList>

          <TabsContent value="run" className="mt-0">
             <BacktestDashboard onRefreshHistory={() => fetchHistory(true)} />
          </TabsContent>
          
          <TabsContent value="history" className="mt-0">
            <header className="mb-8">
              <h2 className="text-2xl font-semibold mb-2">历史回测结果 (History)</h2>
              <p className="text-slate-600 dark:text-slate-400">
                 显示 Top 200 结果 - {selectedSymbol !== "全部" ? selectedSymbol : "所有品种"}
              </p>
            </header>
            
            {!hasData ? (
               <Card className="p-12 text-center">
                 <div className="text-6xl mb-4">📊</div>
                 <h2 className="text-2xl font-semibold mb-4">暂无数据</h2>
                 <p className="text-slate-600 dark:text-slate-400">请在 "运行回测" 页面提交新任务。旧的失败任务可能显示为 0 收益。</p>
               </Card>
            ) : (
             <>
                {/* Visualizations */}
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
                        <div className="h-[350px]">
                           <EquityCurve data={equityCurve} title={`收益曲线 (${selectedSymbol})`} />
                        </div>
                      ) : (
                        <div className="flex flex-col items-center justify-center h-64 text-slate-500">
                          <p>无曲线数据 (点击表格行查看详情)</p>
                        </div>
                      )}
                    </TabsContent>
                    
                    <TabsContent value="trades" className="mt-0">
                       <TradesTable trades={trades} loading={loadingTrades} />
                    </TabsContent>
                  </Tabs>
                </Card>

                {/* Metrics Summary */}
                <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-8">
                  <Card className="p-4">
                     <p className="text-sm text-slate-500 mb-1">最高收益 (Max Return)</p>
                     <p className="text-2xl font-bold text-green-600">{(maxReturn * 100).toFixed(2)}%</p>
                  </Card>
                  <Card className="p-4">
                     <p className="text-sm text-slate-500 mb-1">最高夏普 (Max Sharpe)</p>
                     <p className="text-2xl font-bold">{maxSharpe.toFixed(2)}</p>
                  </Card>
                  <Card className="p-4">
                     <p className="text-sm text-slate-500 mb-1">最小回撤 (Min Drawdown)</p>
                     <p className="text-2xl font-bold text-red-600">{(minDrawdown * 100).toFixed(2)}%</p>
                  </Card>
                  <Card className="p-4">
                     <p className="text-sm text-slate-500 mb-1">总测试数 (Total)</p>
                     <p className="text-2xl font-bold">{results.length}</p>
                  </Card>
                </div>

                {/* Data Table */}
                <Card className="p-6">
                  <h3 className="text-lg font-semibold mb-4">详细对比 (Detailed Comparison)</h3>
                  <div className="overflow-x-auto">
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>排名</TableHead>
                          <TableHead>品种</TableHead>
                          <TableHead>策略参数</TableHead>
                          <TableHead className="text-right">收益率</TableHead>
                          <TableHead className="text-right">夏普比率</TableHead>
                          <TableHead className="text-right">最大回撤</TableHead>
                          <TableHead className="text-right">综合评分</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {results.slice(0, 50).map((r, i) => (
                           <TableRow 
                             key={i} 
                             onClick={() => handleRowClick(i, r)}
                             className={`cursor-pointer hover:bg-slate-100 dark:hover:bg-slate-800 ${selectedIndex === i ? 'bg-blue-50 dark:bg-blue-900/20' : ''}`}
                           >
                             <TableCell><Badge variant="outline">#{i+1}</Badge></TableCell>
                             <TableCell>{r.symbol}</TableCell>
                             <TableCell className="text-xs font-mono text-slate-500 max-w-[200px] truncate" title={JSON.stringify(r.params)}>
                               {r.params ? Object.entries(r.params).map(([k,v]) => `${k}:${v}`).join(', ') : '-'}
                             </TableCell>
                             <TableCell className="text-right font-mono font-medium text-green-600">
                               {((r.metrics?.total_return || 0) * 100).toFixed(2)}%
                             </TableCell>
                             <TableCell className="text-right font-mono">
                               {(r.metrics?.sharpe || 0).toFixed(2)}
                             </TableCell>
                             <TableCell className="text-right font-mono text-red-500">
                               {((r.metrics?.max_drawdown || 0) * 100).toFixed(2)}%
                             </TableCell>
                             <TableCell className="text-right font-bold">
                               {r.score.toFixed(3)}
                             </TableCell>
                           </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </div>
                </Card>
             </>
            )}

          </TabsContent>
        </Tabs>
      </div>
    </div>
  );
}
