import json
import time
import requests
import websocket
import threading
import sys
from datetime import datetime

# Configuration
API_URL = "http://localhost:8080/api"
WS_URL = "ws://localhost:8080/api/ws"
SAMPLE_JOB_CONFIG = {
    "symbol": "SOLUSDT",
    "mode": "backtest",
    "backtest": {
        "symbol": "SOLUSDT",
        "interval": "1h",
        "start": "2024-01-01",
        "end": "2024-02-01",
        "auto_download": True,
        "strategy": {
            "type": "simple_ma",
            "params": {"short_window": 10, "long_window": 30}
        }
    }
}

def on_message(ws, message):
    data = json.loads(message)
    msg_type = data.get("type")
    
    if msg_type == "progress":
        progress = data.get("progress", 0.0)
        state = data.get("state", {})
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Progress: {progress*100:.1f}% | Equity: {state.get('equity', 0):.2f}")
    
    elif msg_type == "success":
        print(f"\n✅ Job Completed! JobID: {data.get('job_id')}")
        print(f"Summary: {json.dumps(data.get('summary'), indent=2)}")
        ws.close()
        sys.exit(0)
        
    elif msg_type == "error":
        print(f"\n❌ Job Failed! Error: {data.get('error')}")
        ws.close()
        sys.exit(1)

def on_error(ws, error):
    print(f"WS Error: {error}")

def on_close(ws, close_status_code, close_msg):
    print("WS Closed")

def on_open(ws):
    print("WS Connected. Submitting Job...")
    
    # Submit Job via HTTP
    try:
        resp = requests.post(f"{API_URL}/backtest", json={"config": SAMPLE_JOB_CONFIG})
        resp.raise_for_status()
        job_data = resp.json()
        print(f"Job Submitted. Job ID: {job_data['job_id']}")
    except Exception as e:
        print(f"Failed to submit job: {e}")
        ws.close()
        sys.exit(1)

def run_test():
    print(f"Connecting to {WS_URL}...")
    ws = websocket.WebSocketApp(WS_URL,
                                on_open=on_open,
                                on_message=on_message,
                                on_error=on_error,
                                on_close=on_close)
    ws.run_forever()

if __name__ == "__main__":
    # Ensure backend services are running before executing this
    run_test()
