from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict


@dataclass
class ToolResult:
    """
    工具执行结果，字符串兼容对象：
    - str(tool_result) 直接拿到给LLM的tool‑message文本
    - is_error 标记是否为错误结果
    - 提供 error() 工厂方法快速构造错误返回
    """
    text: str
    is_error: bool = False

    def __str__(self) -> str:
        """转字符串：直接作为LLM tool message的content"""
        return self.text

    @classmethod
    def error(cls, message: str) -> "ToolResult":
        """工厂方法：生成错误结果"""
        return cls(text=message, is_error=True)

    @classmethod
    def ok(cls, message: str) -> "ToolResult":
        """工厂方法：生成正常成功结果"""
        return cls(text=message, is_error=False)


class Tool(ABC):
    """所有工具的抽象基类"""

    @property
    @abstractmethod
    def name(self) -> str:
        """工具唯一名称，对应tool_calls里function.name"""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """工具功能描述，给LLM理解"""
        ...

    @property
    @abstractmethod
    def parameters(self) -> Dict[str, Any]:
        """
        JSON Schema parameters object（type:object + properties + required）
        示例：
        {
            "type": "object",
            "properties": {"command": {"type":"string", "description":"shell命令"}},
            "required": ["command"]
        }
        """
        ...

    def to_schema(self) -> Dict[str, Any]:
        """
        输出OpenAI function‑call标准schema，由工具自身实现组装
        registry直接拿该结果投喂给LLM API
        """
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            }
        }

    @abstractmethod
    async def execute(self, **kwargs) -> ToolResult:
        """
        执行工具逻辑，接收LLM解析出的参数字典
        :return: ToolResult，str()即可获取传给LLM的消息内容
        """
        ...