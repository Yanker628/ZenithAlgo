"use client";

import { useState, useEffect, useRef } from "react";
import yaml from "js-yaml";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { EquityCurve, EquityPoint } from "@/components/charts/EquityCurve";
import { Play, RotateCcw, Activity, Calendar } from "lucide-react";

type BacktestState = {
  status: "idle" | "running" | "completed" | "failed";
  progress: number;
  jobId: string | null;
  logs: string[];
  equity: EquityPoint[];
  metrics?: any;
};

interface BacktestDashboardProps {
  onRefreshHistory?: () => void;
}

// ... imports remain the same

export default function BacktestDashboard(props: BacktestDashboardProps) {
  // Initialize dates
  const today = new Date();
  const thirtyDaysAgo = new Date();
  thirtyDaysAgo.setDate(today.getDate() - 30);

  const [mode, setMode] = useState<"simple" | "advanced">("simple");

  const [config, setConfig] = useState({
    symbol: "SOLUSDT",
    interval: "1h",
    startDate: thirtyDaysAgo.toISOString().split("T")[0],
    endDate: today.toISOString().split("T")[0],
    strategy: "simple_ma",
  });

  const defaultYaml = `mode: backtest
symbol: ETHUSDT
backtest:
  symbol: ETHUSDT
  interval: 1h
  start: "2024-01-01"
  end: "2024-02-01"
  initial_equity: 10000.0
  auto_download: true
  strategy:
    type: volatility_breakout
    params:
      window: 20
      k: 2.0
      atr_period: 14
      atr_stop_multiplier: 1.5`;

  const [yamlConfig, setYamlConfig] = useState(defaultYaml);
  
  const [state, setState] = useState<BacktestState>({
    status: "idle",
    progress: 0,
    jobId: null,
    logs: [],
    equity: [],
  });
  
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    return () => {
      if (wsRef.current) wsRef.current.close();
    };
  }, []);

  const getStrategyParams = (strategy: string) => {
    if (strategy === "volatility_breakout") {
       return { window: 20, k: 2.0, atr_period: 14, atr_stop_multiplier: 1.5 };
    }
    // Default simple_ma
    return { short_window: 10, long_window: 30 };
  };

  const startBacktest = async () => {
    // 1. Reset State
    setState({
      status: "running",
      progress: 0,
      jobId: null,
      logs: ["Starting backtest..."],
      equity: [],
    });

    try {
      let payload;

      if (mode === "advanced") {
        try {
          // Parse YAML
          const parsed = yaml.load(yamlConfig) as any;
          if (!parsed || !parsed.backtest) {
             throw new Error("Invalid YAML: missing 'backtest' section");
          }
          payload = parsed;
          // Ensure mode is backtest
          payload.mode = "backtest";
        } catch (e: any) {
           throw new Error(`YAML Parse Error: ${e.message}`);
        }
      } else {
        // Simple Mode Construction
        payload = {
          symbol: config.symbol,
          mode: "backtest",
          backtest: {
            symbol: config.symbol,
            interval: config.interval,
            start: config.startDate,
            end: config.endDate,
            initial_equity: 10000.0,
            auto_download: true,
            strategy: {
              type: config.strategy,
              params: getStrategyParams(config.strategy)
            }
          }
        };
      }

      // 2. Submit Job via HTTP Proxy
      const res = await fetch("/api/backtest", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ config: payload }),
      });

      if (!res.ok) throw new Error("Failed to submit job");
      const data = await res.json();
      const jobId = data.job_id;

      setState(prev => ({ ...prev, jobId, logs: [...prev.logs, `Job Submitted: ${jobId} (${mode.toUpperCase()})`] }));

      // 3. Connect Log Stream (WebSocket)
      connectWebSocket(jobId);

    } catch (e: any) {
      setState(prev => ({ 
        ...prev, 
        status: "failed", 
        logs: [...prev.logs, `Error: ${e.message}`] 
      }));
    }
  };

  const connectWebSocket = (jobId: string) => {
    if (wsRef.current) wsRef.current.close();

    const wsUrl = `ws://localhost:8080/api/ws`; 
    
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onopen = () => {
      setState(prev => ({ ...prev, logs: [...prev.logs, "WebSocket Connected"] }));
    };

    ws.onmessage = (event) => {
      const msg = JSON.parse(event.data);
      
      if (msg.job_id !== jobId) return;

      if (msg.type === "progress") {
        setState(prev => ({
          ...prev,
          progress: msg.progress * 100,
          equity: [
            ...prev.equity, 
            { timestamp: new Date(), equity: msg.state.equity }
          ]
        }));
      } else if (msg.type === "success") {
          
          // Trigger history refresh with delay to allow DB persistence
          setTimeout(() => {
            if (props.onRefreshHistory) {
               props.onRefreshHistory();
            }
          }, 1000);
          
          setState(prev => ({
            ...prev,
            status: "completed",
            progress: 100,
            logs: [...prev.logs, "Job Completed Successfully!"],
            metrics: msg.summary.metrics,
          equity: msg.summary.equity_curve 
            ? msg.summary.equity_curve.map((p: any) => ({
                timestamp: p.ts,
                equity: p.equity
              }))
            : prev.equity
        }));
        ws.close();
      } else if (msg.type === "error") {
        setState(prev => ({
          ...prev,
          status: "failed",
          logs: [...prev.logs, `Job Failed: ${msg.error}`]
        }));
        ws.close();
      }
    };

    ws.onerror = () => {
       setState(prev => ({ ...prev, logs: [...prev.logs, "WebSocket Error"] }));
    };
  };

  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-8">
      {/* 1. Control Panel */}
      <Card className="p-6 lg:col-span-1 h-fit flex flex-col">
        <div className="flex items-center justify-between mb-4">
           <h2 className="text-xl font-semibold flex items-center gap-2">
             <Activity className="w-5 h-5" /> 配置策略
           </h2>
           <div className="flex bg-slate-100 dark:bg-slate-800 rounded-lg p-1 text-xs">
              <button 
                onClick={() => setMode("simple")}
                className={`px-3 py-1 rounded-md transition-all ${mode === "simple" ? "bg-white dark:bg-slate-600 shadow-sm font-medium" : "text-slate-500"}`}
              >
                Simple
              </button>
              <button 
                onClick={() => setMode("advanced")}
                className={`px-3 py-1 rounded-md transition-all ${mode === "advanced" ? "bg-white dark:bg-slate-600 shadow-sm font-medium" : "text-slate-500"}`}
              >
                YAML
              </button>
           </div>
        </div>
        
        <div className="space-y-4 flex-1">
          {mode === "simple" ? (
            <>
              <div>
                <label className="text-sm font-medium mb-1 block">交易对</label>
                <Select 
                  value={config.symbol} 
                  onValueChange={(v) => setConfig({...config, symbol: v})}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="SOLUSDT">SOLUSDT</SelectItem>
                    <SelectItem value="BTCUSDT">BTCUSDT</SelectItem>
                    <SelectItem value="ETHUSDT">ETHUSDT</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              <div>
                <label className="text-sm font-medium mb-1 block">时间周期</label>
                <Select 
                  value={config.interval} 
                  onValueChange={(v) => setConfig({...config, interval: v})}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="15m">15m</SelectItem>
                    <SelectItem value="1h">1h</SelectItem>
                    <SelectItem value="4h">4h</SelectItem>
                    <SelectItem value="1d">1d</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              {/* Date Range Selection */}
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="text-sm font-medium mb-1 block flex items-center gap-1">
                     开始 <Calendar className="w-3 h-3"/>
                  </label>
                  <Input 
                    type="date" 
                    value={config.startDate} 
                    onChange={(e) => setConfig({...config, startDate: e.target.value})} 
                  />
                </div>
                <div>
                  <label className="text-sm font-medium mb-1 block flex items-center gap-1">
                     结束 <Calendar className="w-3 h-3"/>
                  </label>
                  <Input 
                    type="date" 
                    value={config.endDate} 
                    onChange={(e) => setConfig({...config, endDate: e.target.value})} 
                  />
                </div>
              </div>

              <div>
                <label className="text-sm font-medium mb-1 block">策略类型</label>
                <Select 
                  value={config.strategy} 
                  onValueChange={(v) => setConfig({...config, strategy: v})}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="simple_ma">Simple MA</SelectItem>
                    <SelectItem value="volatility_breakout">Volatility Breakout</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </>
          ) : (
            <div className="flex flex-col h-full">
               <label className="text-sm font-medium mb-1 block flex justify-between">
                 <span>Config YAML</span>
                 <span className="text-xs text-slate-400 font-normal">Full control</span>
               </label>
               <Textarea 
                 value={yamlConfig}
                 onChange={(e) => setYamlConfig(e.target.value)}
                 className="font-mono text-xs flex-1 min-h-[300px] resize-none bg-slate-50 dark:bg-slate-900"
                 spellCheck={false}
               />
               <p className="text-[10px] text-slate-400 mt-2">
                 * Edit `backtest` section to change params.
               </p>
            </div>
          )}

          <Button 
            className="w-full mt-4" 
            onClick={startBacktest}
            disabled={state.status === "running"}
          >
            {state.status === "running" ? (
              <RotateCcw className="w-4 h-4 mr-2 animate-spin" />
            ) : (
              <Play className="w-4 h-4 mr-2" />
            )}
            {state.status === "running" ? "运行中 (Running)..." : `开始回测 (${mode === 'simple' ? 'Simple' : 'Adv'})`}
          </Button>

          {/* Logs Terminal */}
          <div className="bg-slate-950 text-slate-300 p-3 rounded-md text-xs font-mono h-48 overflow-y-auto w-full">
            {state.logs.map((log, i) => (
              <div key={i}>{log}</div>
            ))}
            {state.logs.length === 0 && <span className="opacity-50">Wait for logs...</span>}
          </div>
        </div>
      </Card>

      {/* 2. Real-time Chart */}
      <Card className="p-6 lg:col-span-2 min-h-[500px] flex flex-col">
        <div className="flex justify-between items-center mb-6">
          <h2 className="text-xl font-semibold">实时权益曲线</h2>
          <Badge variant={state.status === "completed" ? "default" : "secondary"}>
             Status: {state.status.toUpperCase()}
          </Badge>
        </div>

        {state.status !== "idle" && (
           <div className="mb-4 space-y-2">
             <div className="flex justify-between text-sm">
               <span>回测进度 (Progress)</span>
               <span>{state.progress.toFixed(1)}%</span>
             </div>
             <Progress value={state.progress} className="h-2" />
           </div>
        )}

        <div className="flex-1 w-full h-full min-h-[300px]">
          {state.equity.length > 0 ? (
             <EquityCurve data={state.equity} title="实时权益" />
          ) : (
             <div className="h-full flex items-center justify-center text-slate-400 border-2 border-dashed rounded-lg">
                等待数据推送...
             </div>
          )}
        </div>

        {/* Metrics Summary */}
        {state.metrics && (
          <div className="grid grid-cols-4 gap-4 mt-6 pt-6 border-t">
            <div>
              <div className="text-xs text-slate-500">累计收益 (Return)</div>
              <div className="font-bold text-lg text-green-600">
                {(state.metrics.total_return * 100).toFixed(2)}%
              </div>
            </div>
            <div>
              <div className="text-xs text-slate-500">夏普比率 (Sharpe)</div>
              <div className="font-bold text-lg">
                {state.metrics.sharpe.toFixed(2)}
              </div>
            </div>
            <div>
              <div className="text-xs text-slate-500">最大回撤 (MDD)</div>
              <div className="font-bold text-lg text-red-600">
                {(state.metrics.max_drawdown * 100).toFixed(2)}%
              </div>
            </div>
            <div>
              <div className="text-xs text-slate-500">交易次数 (Trades)</div>
              <div className="font-bold text-lg">
                {state.metrics.total_trades}
              </div>
            </div>
          </div>
        )}
      </Card>
    </div>
  );
}
