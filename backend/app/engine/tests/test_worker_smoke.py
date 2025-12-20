from unittest.mock import MagicMock, patch
import json
import pytest
from zenith.core.worker import JobConsumer

def test_worker_initialization():
    """验证 Worker 初始化是否连接 Redis。"""
    with patch("redis.from_url") as mock_redis:
        worker = JobConsumer(redis_url="redis://localhost:6379/0")
        mock_redis.assert_called_once_with("redis://localhost:6379/0", decode_responses=True)
        assert worker.queue_key == "zenith:jobs:queue"

def test_worker_process_invalid_job():
    """验证处理无效 Job 时是否上报错误。"""
    with patch("redis.from_url") as mock_redis_cls:
        mock_redis_instance = MagicMock()
        mock_redis_cls.return_value = mock_redis_instance
        
        worker = JobConsumer()
        
        # 构造一个无效的 Job Payload (缺少 config)
        invalid_job = json.dumps({"job_id": "job_123", "config": {}})
        
        # 调用处理逻辑
        worker._process_job(invalid_job)
        
        # 验证是否发布了 error 消息
        assert mock_redis_instance.publish.called
        args, _ = mock_redis_instance.publish.call_args
        channel, message = args
        assert channel == "zenith:jobs:updates"
        msg_data = json.loads(message)
        assert msg_data["type"] == "error"
        assert msg_data["job_id"] == "job_123"
