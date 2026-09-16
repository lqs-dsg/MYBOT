from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional



@dataclass(frozen=True)
class GenerationSettings:
    """模型生成通用参数"""
    temperature: float = 0.7
    max_tokens: int = 4096


@dataclass(frozen=True)
class LLMResponse:
    """标准化大模型返回结构"""
    content: Optional[str] = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    finish_reason: Optional[str] = None
    # 工具调用列表，无工具调用时为空列表
    tool_calls: list = field(default_factory=list)


class LLMProvider(ABC):
    """
    LLM提供者抽象基类（接口契约）
    所有模型服务商实现类都必须继承此类
    """
    def __init__(self, api_key: str | None = None, api_base: str | None = None):
        self.api_key = api_key
        self.api_base = api_base
        self.generation = GenerationSettings()

    @abstractmethod
    async def chat(
            self,
            messages: List[dict],
            model: Optional[str] = None,
            tools: Optional[list] = None,
            tool_choice: Optional[dict] = None,
    ) -> LLMResponse:
        """
        对话请求统一入口
        :param messages: 消息列表，遵循 openai 消息格式 [{"role":"user","content":"xxx"}]
        :param model: 指定模型名称，为None时使用默认模型
        :return: 标准化 LLMResponse 对象
        """
        ...

    @abstractmethod
    def get_default_model(self) -> str:
        """获取该provider默认使用的模型名称"""
        ...