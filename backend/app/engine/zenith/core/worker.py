import json
import logging
import time
from typing import Optional, Dict, Any
import redis
from pydantic import BaseModel

from zenith.core.backtest_engine import BacktestEngine
from zenith.common.config.config_loader import MainConfig

logger = logging.getLogger(__name__)

class BacktestJob(BaseModel):
    """任务负载结构。"""
    job_id: str
    config: Dict[str, Any]  # 原始 config 字典
    
class JobConsumer:
    """RaaS Worker: 负责从 Redis 消费任务并在本地执行回测。"""
    
    def __init__(self, redis_url: str = "redis://localhost:6379/0"):
        self.redis = redis.from_url(redis_url, decode_responses=True)
        self.queue_key = "zenith:jobs:queue"
        self.updates_channel = "zenith:jobs:updates"
        
    def run_forever(self):
        """阻塞运行 Worker 主循环。"""
        logger.info(f"Worker started. Listening on {self.queue_key}...")
        try:
            while True:
                # 阻塞式右侧弹出 (BRPOP)
                # result is tuple: (key, value)
                result = self.redis.brpop(self.queue_key, timeout=5)
                if result:
                    _, payload_str = result
                    self._process_job(payload_str)
        except KeyboardInterrupt:
            logger.info("Worker stopped by user.")
        except Exception as e:
            logger.exception(f"Worker crashed: {e}")
            time.sleep(5)  # 避免死循环快速重启
            self.run_forever()

    def _process_job(self, payload_str: str):
        try:
            job_dict = json.loads(payload_str)
            job = BacktestJob(**job_dict)
            logger.info(f"Processing Job {job.job_id}...")
            
            # TODO: 将字典转换为 MainConfig 对象
            # 注意: config_loader 通常从文件加载，这里需要支持从 dict 加载
            # 暂时假设 MainConfig 可以直接 parse_obj，或者我们需要扩展 config_loader
            try:
                # 尝试构建配置对象 (此处简化，实际可能需要更稳健的构建逻辑)
                cfg = MainConfig.model_validate(job.config)
            except Exception as e:
                self._report_error(job.job_id, f"Invalid Config: {str(e)}")
                return

            # 定义进度回调
            def on_progress(progress: float, state: Dict[str, Any]):
                self._report_progress(job.job_id, progress, state)

            # 运行回测
            engine = BacktestEngine(cfg_obj=cfg, artifacts_dir=None) 
            result = engine.run(progress_callback=on_progress)
            
            # 上报最终结果
            summary = result.summary.model_dump(mode='json')
            self._report_success(job.job_id, summary)
            
        except Exception as e:
            logger.exception("Job processing failed")
            if 'job' in locals():
                self._report_error(job.job_id, str(e))

    def _report_progress(self, job_id: str, progress: float, state: Dict[str, Any]):
        msg = {
            "type": "progress",
            "job_id": job_id,
            "progress": progress,
            "state": state
        }
        self.redis.publish(self.updates_channel, json.dumps(msg))

    def _report_success(self, job_id: str, summary: Dict[str, Any]):
        msg = {
            "type": "success",
            "job_id": job_id,
            "summary": summary
        }
        self.redis.publish(self.updates_channel, json.dumps(msg))
        logger.info(f"Job {job_id} completed.")

    def _report_error(self, job_id: str, error: str):
        msg = {
            "type": "error",
            "job_id": job_id,
            "error": error
        }
        self.redis.publish(self.updates_channel, json.dumps(msg))
        logger.error(f"Job {job_id} failed: {error}")
