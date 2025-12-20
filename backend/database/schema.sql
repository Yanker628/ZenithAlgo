-- ZenithAlgo Database Schema
-- PostgreSQL 15+

-- 1. 回测主表
CREATE TABLE IF NOT EXISTS backtests (
    id SERIAL PRIMARY KEY,
    run_id VARCHAR(100) UNIQUE NOT NULL,
    symbol VARCHAR(20) NOT NULL,
    timeframe VARCHAR(10) NOT NULL,
    start_date TIMESTAMP NOT NULL,
    end_date TIMESTAMP NOT NULL,
    
    -- 策略信息
    strategy_name VARCHAR(50) NOT NULL DEFAULT 'VolatilityBreakout',
    params JSONB NOT NULL,
    
    -- 性能指标
    total_return DECIMAL(12, 6),
    sharpe_ratio DECIMAL(10, 4),
    max_drawdown DECIMAL(12, 6),
    win_rate DECIMAL(8, 6),
    total_trades INTEGER,
    
    -- 额外指标
    avg_win DECIMAL(12, 6),
    avg_loss DECIMAL(12, 6),
    profit_factor DECIMAL(10, 4),
    expectancy DECIMAL(12, 6),
    avg_trade_return DECIMAL(12, 6),
    std_trade_return DECIMAL(12, 6),
    exposure DECIMAL(8, 6),
    turnover DECIMAL(8, 6),
    
    -- 评分
    score DECIMAL(10, 6),
    passed BOOLEAN DEFAULT TRUE,
    filter_reason TEXT,
    
    -- 元数据
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 索引
CREATE INDEX IF NOT EXISTS idx_backtests_symbol ON backtests(symbol);
CREATE INDEX IF NOT EXISTS idx_backtests_score ON backtests(score DESC);
CREATE INDEX IF NOT EXISTS idx_backtests_symbol_score ON backtests(symbol, score DESC);
CREATE INDEX IF NOT EXISTS idx_backtests_created_at ON backtests(created_at DESC);

-- 2. 权益曲线表
CREATE TABLE IF NOT EXISTS equity_curves (
    id BIGSERIAL PRIMARY KEY,
    backtest_id INTEGER NOT NULL REFERENCES backtests(id) ON DELETE CASCADE,
    timestamp TIMESTAMP NOT NULL,
    equity DECIMAL(14, 2) NOT NULL,
    drawdown DECIMAL(12, 6),
    drawdown_pct DECIMAL(10, 6)
);

-- 索引
CREATE INDEX IF NOT EXISTS idx_equity_backtest ON equity_curves(backtest_id);
CREATE INDEX IF NOT EXISTS idx_equity_timestamp ON equity_curves(backtest_id, timestamp);
CREATE UNIQUE INDEX IF NOT EXISTS idx_equity_unique ON equity_curves(backtest_id, timestamp);

-- 3. 交易记录表
CREATE TABLE IF NOT EXISTS trades (
    id BIGSERIAL PRIMARY KEY,
    backtest_id INTEGER NOT NULL REFERENCES backtests(id) ON DELETE CASCADE,
    timestamp TIMESTAMP NOT NULL,
    symbol VARCHAR(20) NOT NULL,
    side VARCHAR(10) NOT NULL CHECK (side IN ('buy', 'sell', 'long', 'short')),
    price DECIMAL(14, 6) NOT NULL,
    qty DECIMAL(14, 6) NOT NULL,
    pnl DECIMAL(14, 6),
    commission DECIMAL(12, 6),
    cumulative_pnl DECIMAL(14, 6)
);

-- 索引
CREATE INDEX IF NOT EXISTS idx_trades_backtest ON trades(backtest_id);
CREATE INDEX IF NOT EXISTS idx_trades_timestamp ON trades(timestamp);
CREATE INDEX IF NOT EXISTS idx_trades_backtest_timestamp ON trades(backtest_id, timestamp);

-- 4. 参数扫描批次表
CREATE TABLE IF NOT EXISTS sweep_runs (
    id SERIAL PRIMARY KEY,
    sweep_id VARCHAR(100) UNIQUE NOT NULL,
    symbol VARCHAR(20) NOT NULL,
    timeframe VARCHAR(10) NOT NULL,
    start_date TIMESTAMP NOT NULL,
    end_date TIMESTAMP NOT NULL,
    strategy_name VARCHAR(50) NOT NULL,
    total_combinations INTEGER,
    completed_combinations INTEGER DEFAULT 0,
    status VARCHAR(20) DEFAULT 'running' CHECK (status IN ('running', 'completed', 'failed')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP
);

-- 索引
CREATE INDEX IF NOT EXISTS idx_sweeps_symbol ON sweep_runs(symbol);
CREATE INDEX IF NOT EXISTS idx_sweeps_status ON sweep_runs(status);

-- 5. 创建更新时间触发器
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_backtests_updated_at 
    BEFORE UPDATE ON backtests 
    FOR EACH ROW 
    EXECUTE FUNCTION update_updated_at_column();

-- 6. 创建视图 - 带 equity 文件的回测
CREATE OR REPLACE VIEW backtests_with_equity AS
SELECT DISTINCT b.*
FROM backtests b
INNER JOIN equity_curves e ON b.id = e.backtest_id;

-- 7. 创建视图 - 汇总统计
CREATE OR REPLACE VIEW backtest_summary AS
SELECT 
    symbol,
    COUNT(*) as total_backtests,
    COUNT(DISTINCT CASE WHEN total_return > 0 THEN id END) as profitable_count,
    AVG(total_return) as avg_return,
    MAX(total_return) as max_return,
    MIN(total_return) as min_return,
    AVG(sharpe_ratio) as avg_sharpe,
    MAX(score) as max_score
FROM backtests
GROUP BY symbol;

-- 完成
SELECT 'Database schema created successfully' AS status;
