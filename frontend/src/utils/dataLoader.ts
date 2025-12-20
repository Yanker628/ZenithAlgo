import Papa from "papaparse";

export interface BacktestResult {
  id?: string;
  symbol: string;
  params: Record<string, any>;
  metrics: {
    total_return?: number;
    sharpe?: number;
    max_drawdown?: number;
    win_rate?: number;
    total_trades?: number;
  };
  score: number;
}

export interface EquityPoint {
  timestamp: Date;
  equity: number;
  drawdown?: number;
  drawdown_pct?: number;
}

export interface Trade {
  timestamp: Date;
  symbol: string;
  side: string;
  price: number;
  qty: number;
  pnl?: number;
  commission?: number;
  cumulative_pnl?: number;
}

const API_BASE_URL = "http://localhost:8080/api";

/**
 * 从 Go API 加载参数扫描结果
 */
export async function loadSweepResults(limit: number = 20): Promise<BacktestResult[]> {
  try {
    const response = await fetch(`${API_BASE_URL}/sweep/results?limit=${limit}`);
    if (!response.ok) {
      throw new Error(`API error: ${response.status}`);
    }
    const data = await response.json();
    return data.results || [];
  } catch (error) {
    console.error("Failed to load sweep results from API:", error);
    // Fallback to CSV if API fails
    return loadSweepResultsFromCSV();
  }
}

/**
 * 从静态 CSV 文件加载（备用方案）
 */
async function loadSweepResultsFromCSV(): Promise<BacktestResult[]> {
  try {
    const response = await fetch('/data/sweep.csv');
    const csvText = await response.text();

    return new Promise((resolve, reject) => {
      Papa.parse(csvText, {
        header: true,
        dynamicTyping: true,
        skipEmptyLines: true,
        complete: (results) => {
          const data = results.data as any[];
          const processed: BacktestResult[] = data
            .filter((row) => row.symbol)
            .map((row) => ({
              symbol: row.symbol || "",
              params: {
                window: row.window,
                k: row.k,
                atr_stop_multiplier: row.atr_stop_multiplier,
                atr_period: row.atr_period,
              },
              metrics: {
                total_return: row.total_return,
                sharpe: row.sharpe,
                max_drawdown: row.max_drawdown,
                win_rate: row.win_rate,
                total_trades: row.total_trades,
              },
              score: row.score || 0,
            }));
          resolve(processed);
        },
        error: (error: any) => reject(error),
      });
    });
  } catch (error) {
    console.error("Failed to load sweep results from CSV:", error);
    return [];
  }
}

/**
 * 从 Go API 加载收益曲线
 */
export async function loadEquityCurve(backtestId?: string): Promise<EquityPoint[]> {
  if (backtestId) {
    try {
      const response = await fetch(`${API_BASE_URL}/backtest/${backtestId}/equity`);
      if (response.ok) {
        const data = await response.json();
        if (data.data && Array.isArray(data.data)) {
          return data.data.map((point: any) => ({
            timestamp: new Date(point.timestamp),
            equity: point.equity,
            drawdown: point.drawdown,
            drawdown_pct: point.drawdown_pct,
          }));
        }
      }
    } catch (error) {
      console.error("Failed to load equity from API:", error);
    }
  }
  
  // Fallback to CSV if no backtestId or API fails
  return loadEquityCurveFromCSV();
}

/**
 * 从静态 CSV 文件加载收益曲线
 */
async function loadEquityCurveFromCSV(): Promise<EquityPoint[]> {
  try {
    const response = await fetch('/data/equity.csv');
    const csvText = await response.text();

    return new Promise((resolve, reject) => {
      Papa.parse(csvText, {
        header: true,
        dynamicTyping: true,
        skipEmptyLines: true,
        complete: (results) => {
          const data = results.data as any[];
          const processed: EquityPoint[] = data
            .filter((row) => row.ts && row.equity !== undefined)
            .map((row) => ({
              timestamp: new Date(row.ts),
              equity: row.equity,
            }));
          resolve(processed);
        },
        error: (error: any) => reject(error),
      });
    });
  } catch (error) {
    console.error("Failed to load equity curve:", error);
    return [];
  }
}

/**
 * 加载交易记录数据
 * @param backtestId - 回测ID（可选，如果提供则从API加载）
 * @returns 交易记录数组
 */
export async function loadTrades(backtestId?: string): Promise<Trade[]> {
  // 如果提供了 backtestId，尝试从 API 加载
  if (backtestId) {
    try {
      const response = await fetch(`${API_BASE_URL}/backtest/${backtestId}/trades`);
      if (response.ok) {
        const data = await response.json();
        return data.trades || [];
      }
    } catch (error) {
      console.warn(`Failed to load trades from API for ${backtestId}:`, error);
    }
  }

  // 降级：从本地 CSV 加载
  try {
    const response = await fetch("/data/trades.csv");
    const text = await response.text();
    const parsed = Papa.parse<Record<string, string>>(text, {
      header: true,
      dynamicTyping: true,
      skipEmptyLines: true,
    });

    return parsed.data.map((row) => ({
      timestamp: new Date(row.ts || row.timestamp),
      symbol: row.symbol || "",
      side: row.side || "",
      price: parseFloat(row.price) || 0,
      qty: parseFloat(row.qty) || 0,
      pnl: row.pnl ? parseFloat(row.pnl) : undefined,
      commission: row.commission ? parseFloat(row.commission) : undefined,
      cumulative_pnl: row.cumulative_pnl ? parseFloat(row.cumulative_pnl) : undefined,
    }));
  } catch (error) {
    console.error("Failed to load trades:", error);
    return [];
  }
}

/**
 * 生成模拟数据（保留作为最后备用）
 */
export function generateMockData() {
  const results: BacktestResult[] = [
    {
      symbol: "SOLUSDT",
      params: { window: 20, k: 2.0, atr_stop: 2.0 },
      metrics: {
        total_return: 0.125,
        sharpe: 1.85,
        max_drawdown: -0.08,
        win_rate: 0.62,
        total_trades: 45,
      },
      score: 0.85,
    },
  ];

  const equityCurve: EquityPoint[] = [];
  let equity = 10000;
  const startDate = new Date("2024-01-01");

  for (let i = 0; i < 100; i++) {
    const date = new Date(startDate);
    date.setDate(date.getDate() + i);
    const change = (Math.random() - 0.45) * 100;
    equity += change;
    equityCurve.push({
      timestamp: date,
      equity: Math.round(equity * 100) / 100,
    });
  }

  return { results, equityCurve };
}
