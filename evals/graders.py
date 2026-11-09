"""评分器：根据执行轨迹判断一个用例是否通过

设计原则：
- 评分器可组合：一个用例可以有多个 grader，全部通过才算通过
- 失败要说明原因（用于失败归因分析）
- 未知评分器 / 未知模式 → 必须报错，绝不能静默通过（否则拼写错误会变成"假绿"）
"""
from dataclasses import dataclass
from typing import Dict, List

from .loader import Case


@dataclass
class Trajectory:
    """一次用例运行的完整轨迹"""
    final_answer: str          # 模型最终回复
    messages: List[Dict]       # 从 session 读回的全量消息
    tool_calls: List[Dict]     # [{"function": {"name": ..., "arguments": ...}}]
    iterations: int            # 模型被调用了几次
    tool_error_count: int      # 工具返回过几次错误（靠 _is_error 标记）


def grade(case: Case, traj: Trajectory) -> tuple[bool, str]:
    """逐个执行 case.graders，全部通过才 True；否则返回 (False, 失败原因)"""
    for grader in case.graders:
        gtype = grader.get("type")

        # ---- 最终答案包含关键词 ----
        if gtype == "final_answer_contains":
            text = traj.final_answer
            any_of = grader.get("any_of")
            all_of = grader.get("all_of")
            if any_of and not any(kw in text for kw in any_of):
                return False, f"final_answer 缺少任一关键字: {any_of}"
            if all_of and not all(kw in text for kw in all_of):
                return False, f"final_answer 缺少全部关键字: {all_of}"

        # ---- 工具调用序列 ----
        elif gtype == "tool_sequence":
            expect = grader["expect"]
            mode = grader.get("mode", "exact")
            names = [c["function"]["name"] for c in traj.tool_calls]

            if mode == "exact":
                if names != expect:
                    return False, f"工具调用序列不匹配：期望 {expect}，实际 {names}"
            elif mode == "prefix":
                if names[:len(expect)] != expect:
                    return False, f"工具调用前缀不匹配：期望以 {expect} 开头，实际 {names}"
            elif mode == "contains":
                if not set(expect).issubset(set(names)):
                    return False, f"未包含期望的工具 {expect}，实际 {names}"
            else:
                return False, f"未知的 tool_sequence mode: {mode!r}"

        # ---- 迭代次数上限（防止瞎试） ----
        elif gtype == "max_iterations":
            if traj.iterations > grader["value"]:
                return False, f"迭代次数 {traj.iterations} 超过上限 {grader['value']}"

        # ---- 不该用工具时没用工具（防止过度调用） ----
        elif gtype == "not_tool_used":
            if traj.tool_calls:
                return False, f"不允许调用工具，但实际调用了: {traj.tool_calls}"

        # ---- 工具结果内容（轨迹级断言：验证工具真的执行了且结果进了对话） ----
        elif gtype == "tool_result_contains":
            texts = [m.get("content") or "" for m in traj.messages if m.get("role") == "tool"]
            any_of = grader.get("any_of")
            if any_of and not any(any(kw in t for kw in any_of) for t in texts):
                return False, f"工具结果里没有出现 {any_of}，实际: {texts[:3]}"

        # ---- 不允许出现工具错误（轨迹级断言：能抓住"工具坏了"这类回归） ----
        elif gtype == "no_tool_error":
            if traj.tool_error_count > 0:
                return False, f"期望没有工具错误，但出现了 {traj.tool_error_count} 次"

        # ---- 错误恢复：过程中出现过工具错误，但最终仍然成功 ----
        elif gtype == "recovered_after_error":
            if traj.tool_error_count == 0:
                return False, "期望过程中出现过工具错误（用于测试恢复能力），但实际一次都没有"
            keywords = grader.get("any_of")
            if keywords and not any(kw in traj.final_answer for kw in keywords):
                return False, f"出错后未能给出包含 {keywords} 的结果（未恢复）"

        # ---- 未知类型 → 报错，绝不静默通过 ----
        else:
            return False, f"未知的评分器类型: {gtype!r}（检查用例 YAML 是否拼错）"

    return True, "全部校验通过"
