from typing import Dict, Any

# 策略配置注册表
# 这里记录了通过 optimize.py 跑出来的最佳参数
ASSET_CONFIGS = {
    "BTC": {
        "description": "BTC - 稳健趋势型 (高门槛)",
        "params": {
            "fast": 12,
            "slow": 26,
            "signal": 9,
            "atr_multiplier": 3.0,  # 宽止损
            "adx_limit": 25,        # 强趋势才进
            "trailing_pct": 0.10,   # 吃大波段
            "rsi_limit": 80
        }
    },
    "ETH": {
        "description": "ETH - 跟随型 (中门槛)",
        "params": {
            "fast": 12,
            "slow": 26,
            "signal": 9,
            "atr_multiplier": 3.0,
            "adx_limit": 15,        # ✨ 降低 ADX 门槛
            "trailing_pct": 0.08,
            "rsi_limit": 75
        }
    },
    "SOL": {
        "description": "SOL - 高波动作手 (防洗盘)",
        "params": {
            "fast": 12,
            "slow": 26,
            "signal": 9,
            "atr_multiplier": 4.5,  # ✨ 超宽止损
            "adx_limit": 20,
            "trailing_pct": 0.15,   # 忍受大回撤
            "rsi_limit": 80
        }
    }
}

def get_strategy_config(symbol: str) -> Dict[str, Any]:
    """
    根据币种获取配置。
    支持输入 'BTCUSDT', 'ETH_USDT', 'BTC' 等格式
    """
    # 简单的清洗逻辑：取前三个字母作为 Key
    # 实际项目中可能需要更严谨的解析
    base_symbol = symbol.upper()[0:3] 
    
    # 默认返回 BTC 配置
    return ASSET_CONFIGS.get(base_symbol, ASSET_CONFIGS["BTC"])
