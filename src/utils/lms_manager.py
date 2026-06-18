import subprocess
import logging
import time

logger = logging.getLogger(__name__)

class LMSManager:
    """
    管理 LM Studio 命令行工具 (lms)
    用于在引擎运行期间动态加载和卸载本地模型，以最大化省电。
    """
    
    @staticmethod
    def is_installed() -> bool:
        """检查 lms 是否已安装"""
        try:
            result = subprocess.run(["lms", "--version"], capture_output=True, text=True)
            return result.returncode == 0
        except FileNotFoundError:
            return False
            
    @staticmethod
    def server_start():
        """启动后台服务"""
        try:
            subprocess.run(["lms", "server", "start"], capture_output=True, text=True)
            logger.info("LM Studio server started.")
        except Exception as e:
            logger.warning(f"Failed to start LM Studio server: {e}")

    @staticmethod
    def load_model(model_name: str):
        """动态加载模型"""
        logger.info(f"Loading local model {model_name} via lms...")
        try:
            # lms load 是同步命令，加载完成才会返回
            result = subprocess.run(["lms", "load", model_name], capture_output=True, text=True)
            if result.returncode == 0:
                logger.info(f"Model {model_name} loaded successfully.")
            else:
                logger.warning(f"Failed to load model {model_name}: {result.stderr}")
        except Exception as e:
            logger.error(f"Error executing lms load: {e}")

    @staticmethod
    def unload_all():
        """卸载所有模型以释放内存/显存"""
        logger.info("Unloading all models via lms...")
        try:
            result = subprocess.run(["lms", "unload", "--all"], capture_output=True, text=True)
            if result.returncode == 0:
                logger.info("All models unloaded successfully.")
            else:
                logger.warning(f"Failed to unload models: {result.stderr}")
        except Exception as e:
            logger.error(f"Error executing lms unload: {e}")

