-- Create Tables
CREATE TABLE IF NOT EXISTS backtests (
    id SERIAL PRIMARY KEY,
    run_id VARCHAR(50) UNIQUE NOT NULL,
    symbol VARCHAR(20),
    timeframe VARCHAR(10),
    start_date TIMESTAMP,
    end_date TIMESTAMP,
    strategy_name VARCHAR(50),
    params JSONB,
    total_return FLOAT,
    sharpe_ratio FLOAT,
    max_drawdown FLOAT,
    win_rate FLOAT,
    total_trades INT,
    score FLOAT,
    passed BOOLEAN,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS trades (
    id SERIAL PRIMARY KEY,
    backtest_id INT REFERENCES backtests(id),
    timestamp TIMESTAMP,
    symbol VARCHAR(20),
    side VARCHAR(10),
    price FLOAT,
    qty FLOAT,
    pnl FLOAT,
    commission FLOAT,
    cumulative_pnl FLOAT
);

CREATE TABLE IF NOT EXISTS equity_curves (
    id SERIAL PRIMARY KEY,
    backtest_id INT REFERENCES backtests(id),
    timestamp TIMESTAMP,
    equity FLOAT,
    drawdown FLOAT,
    drawdown_pct FLOAT
);
