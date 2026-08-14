import json
from typing import Any,Optional,Dict,List
from mybot.agent.base import Tool,ToolResult
class ToolRegistry:
    def __init__(self) ->None:
       self._tools:Dict[str,Tool]={}
    def register(self,tool:Tool)->None:
        self._tools[tool.name]=tool
    def get(self,name:str)->Optional[Tool]:
        return self._tools.get(name)
@property
def tool_names(self)->List[str]:
    """返回全部已注册工具列表"""
    return list(self._tools.keys())
async def execute(self,name:str,params:Any)->ToolResult:
     try:
         normalized_params = self._normalize_params(params)
     except json.JSONDecodeError:
         return ToolResult.error(message="参数JSON解析失败")
     except TypeError:
         return ToolResult.error(message="参数格式非法，无法转为字典")
     tool = self.get(name)
     if tool is None:
         return ToolResult.error(message=f"工具不存在: {name}")
     try:
         result = await tool.execute(**normalized_params)
         return result
     except Exception as e:
         return ToolResult.error(message=f"工具执行异常：{str(e)}")

     def _normalize_params(self, params: Any) -> Dict[str, Any]:
         """私有辅助：把输入参数统一转为dict"""
         # None / 空字符串 => {}
         if params is None or params == "":
             return {}
         # 已经是dict直接返回
         if isinstance(params, dict):
             return params
         # 如果是字符串，尝试json解析
         if isinstance(params, str):
             parsed = json.loads(params)
             if not isinstance(parsed, dict):
                 raise TypeError("json解析结果不是字典")
             return parsed
         # 其他类型直接报错
         raise TypeError(f"不支持的参数类型：{type(params)}")
