import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from app.config.model_config import get_model_config
from app.deepclaude.deepclaude import DeepClaude
from app.utils.auth import verify_api_key
from app.utils.config.loader import load_model_config, load_shown_model_config
from app.utils.config.processor import generate_shown_models
from app.utils.logger import logger

# 加载环境变量
load_dotenv()

app = FastAPI(title="DeepClaude API")

# 从环境变量获取 CORS配置, API 密钥、地址以及模型名称
ALLOW_ORIGINS = os.getenv("ALLOW_ORIGINS", "*")

# CORS设置
allow_origins_list = (
    ALLOW_ORIGINS.split(",") if ALLOW_ORIGINS else []
)  # 将逗号分隔的字符串转换为列表

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Load model_config from model.example.yaml
try:
    load_model_config(Path(__file__).parent.parent / "model.yaml")
except Exception as e:
    logger.error(
        f"Failed to load model config: {e}\n\nPlease check the model.yaml file."
    )
    sys.exit(1)

logger.info("App config loaded successfully")
logger.debug(get_model_config())

generate_shown_models(Path(__file__).parent / "shown_models.yaml")
logger.info(
    "Shown models generated at {}".format(Path(__file__).parent / "shown_models.yaml")
)

# 创建 DeepClaude 实例
deep_claude = DeepClaude()

# 验证日志级别
logger.debug("当前日志级别为 DEBUG")
logger.info("开始请求")


@app.get("/", dependencies=[Depends(verify_api_key)])
async def root():
    logger.info("访问了根路径")
    return {"message": "Welcome to DeepClaude API"}


@app.get("/v1/models")
async def list_models():
    """
    获取可用模型列表
    返回格式遵循 OpenAI API 标准
    """
    logger.info("获取可用模型列表")
    try:
        config = load_shown_model_config()
        return {"object": "list", "data": config["models"]}
    except Exception as e:
        logger.error(f"加载模型配置时发生错误: {e}")
        return {"error": str(e)}


@app.post("/v1/chat/completions", dependencies=[Depends(verify_api_key)])
async def chat_completions(request: Request):
    """处理聊天完成请求，支持流式和非流式输出

    请求体格式应与 OpenAI API 保持一致，包含：
    - messages: 消息列表
    - model: 模型名称（必需）
    - stream: 是否使用流式输出（可选，默认为 True)
    - temperature: 随机性 (可选)
    - top_p: top_p (可选)
    - presence_penalty: 话题新鲜度（可选）
    - frequency_penalty: 频率惩罚度（可选）
    """

    try:
        # 1. 获取基础信息
        body = await request.json()
        messages = body.get("messages")
        model = body.get("model")
        model_config = get_model_config()

        if not model:
            raise ValueError("必须指定模型名称")

        # 2. 获取并验证参数
        model_arg = get_and_validate_params(body)
        stream = model_arg[4]

        # 3. Select Model
        deep_model = model_config.get_deep_model(model)
        if deep_model not in model_config.deep_models:
            logger.error(f"Cannot find model {model}")
            raise ValueError(f"Cannot find model {model}")

        # TODO: Add context limit check

        # 4. Start Processing
        if stream:
            return StreamingResponse(
                deep_claude.chat_completions_with_stream(
                    deep_model,
                    messages,
                    model_arg=model_arg[:4],
                ),
                media_type="text/event-stream",
            )
        else:
            return await deep_claude.chat_completions_without_stream(
                deep_model,
                messages,
                model_arg=model_arg[:4],
            )

    except Exception as e:
        logger.error(f"处理请求时发生错误: {e}")
        return {"error": str(e)}


def get_and_validate_params(body):
    """提取获取和验证请求参数的函数"""
    # TODO: 默认值设定允许自定义
    temperature: float = body.get("temperature", 0.5)
    top_p: float = body.get("top_p", 0.9)
    presence_penalty: float = body.get("presence_penalty", 0.0)
    frequency_penalty: float = body.get("frequency_penalty", 0.0)
    stream: bool = body.get("stream", True)

    if "sonnet" in body.get(
        "model", ""
    ):  # Only Sonnet 设定 temperature 必须在 0 到 1 之间
        if (
            not isinstance(temperature, (float))
            or temperature < 0.0
            or temperature > 1.0
        ):
            raise ValueError("Sonnet 设定 temperature 必须在 0 到 1 之间")

    return (temperature, top_p, presence_penalty, frequency_penalty, stream)
