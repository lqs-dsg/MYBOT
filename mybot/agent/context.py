from pathlib import Path
import platform
from datetime import datetime

BASE_PROMPT = """你是一个个人AI助手，名字叫mybot。
你可以在需要时调用工具完成任务。
- 调用工具时先想清楚用哪个工具，参数是什么
- 工具返回错误时，分析原因并换一种方式重试
- 回答简洁准确，不要编造工具没有返回的消息"""


class ContextBuilder:
      #引导文件优先级
      BOOTSTRAP_FILES=("AGENTS.md","SOUL.md","USER.md")
      def __init__(self,workspace:Path,max_history_messages:int =50):
          self.workspace=workspace
          self.max_history_messages=max_history_messages

      def build_system_prompt(self) ->str:
          parts =[BASE_PROMPT]

          #读取引导文件，不存在就跳过，encoding=utf-8
          for filename in self.BOOTSTRAP_FILES:
              file_path =self.workspace / filename
              if file_path.exists() and file_path.is_file():
                  content = file_path.read_text(encoding="utf-8")
                  parts.append(f"\n---{filename}---\n{content}")
          #每次调用时生成环境信息
          now = datetime.now()
          os_name = platform.system()
          workspace_path=str(self.workspace.resolve())
          env_info = f"""
          --- 运行环境信息 ---
          当前时间：{now.strftime('%Y-%m-%d %H:%M:%S')}
          操作系统：{os_name}
          工作目录：{workspace_path}
          """
          parts.append(env_info)

          return "".join(parts)

      def build(self,history:list[dict],user_content:str):
          """组装最终messages:system +截断后的历史 +当前用户消息"""
          #要求：不修改传入的history,做切片拷贝，只保留最近max_history_messages条
          truncated_history = history[-self.max_history_messages:]

          system_msg ={"role":"system","content":self.build_system_prompt()}

          user_msg  ={"role":"user","content":user_content}
          messages =[system_msg]+truncated_history+[user_msg]
          return messages



