"""报告：指标统计 + 终端输出 + 存档 + 两次运行对比"""
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List


@dataclass
class CaseResult:
    """一个用例的执行结果（含指标）"""
    case_id: str
    category: str
    passed: bool
    reason: str
    iterations: int
    tool_calls: int
    tool_errors: int
    latency_ms: float
    prompt_tokens: int = 0
    completion_tokens: int = 0
    tool_call_names: List[str] = field(default_factory=list)   # 调试用：模型实际调了哪些工具

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


def summarize(results: list[CaseResult], mode: str) -> dict:
    """汇总总体指标 + 分类成功率 + 失败归因"""
    total = len(results)

    by_cat: dict[str, dict] = {}
    for r in results:
        d = by_cat.setdefault(r.category, {"total": 0, "passed": 0})
        d["total"] += 1
        d["passed"] += 1 if r.passed else 0

    failures = [r for r in results if not r.passed]
    attribution: dict[str, int] = {}
    for r in failures:
        # 粗略归因：取失败原因的"类型前缀"
        key = r.reason.split("：")[0].split("，")[0][:36] or "未知原因"
        attribution[key] = attribution.get(key, 0) + 1

    return {
        "mode": mode,
        "time": datetime.now().isoformat(timespec="seconds"),
        "total": total,
        "passed": sum(1 for r in results if r.passed),
        "pass_rate": round(sum(1 for r in results if r.passed) / total * 100, 1) if total else 0.0,
        "by_category": {
            k: {**v, "rate": round(v["passed"] / v["total"] * 100, 1)}
            for k, v in by_cat.items()
        },
        "avg_iterations": round(sum(r.iterations for r in results) / total, 2) if total else 0,
        "avg_tool_calls": round(sum(r.tool_calls for r in results) / total, 2) if total else 0,
        "total_tool_errors": sum(r.tool_errors for r in results),
        "avg_latency_ms": round(sum(r.latency_ms for r in results) / total, 1) if total else 0,
        "total_tokens": sum(r.total_tokens for r in results),
        "failure_attribution": attribution,
    }


def print_report(summary: dict, results: list[CaseResult]) -> None:
    """终端表格输出"""
    line = "-" * 78
    print(line)
    print(f"模式: {summary['mode']:<22} 时间: {summary['time']}")
    print(line)

    for i, r in enumerate(results, 1):
        status = "PASS" if r.passed else "FAIL"
        tok = f"{r.total_tokens / 1000:.1f}k" if r.total_tokens else "-"
        print(f"[{i}/{len(results)}] {r.category:<16} {r.case_id:<24} {status}  "
              f"{r.latency_ms:>7.1f}ms  {r.iterations}轮  {tok}")
        if not r.passed:
            print(f"       ↳ {r.reason}")

    print(line)
    print("按类别成功率:")
    for cat, d in sorted(summary["by_category"].items()):
        print(f"  {cat:<18} {d['passed']}/{d['total']}  {d['rate']:>5.1f}%")

    print()
    print("行为指标:")
    print(f"  平均迭代轮数   {summary['avg_iterations']}")
    print(f"  平均工具调用   {summary['avg_tool_calls']}")
    print(f"  工具错误总数   {summary['total_tool_errors']}")
    print(f"  平均延迟       {summary['avg_latency_ms']}ms")
    print(f"  总 token       {summary['total_tokens']}"
          + ("（deterministic 模式不消耗 token）" if summary["mode"].startswith("deterministic") else ""))

    print()
    print("失败归因:")
    if summary["failure_attribution"]:
        for k, v in summary["failure_attribution"].items():
            print(f"  [{v}] {k}")
    else:
        print("  （无）")

    print()
    print(f"结果: {summary['passed']}/{summary['total']} passed ({summary['pass_rate']}%)")


def save_result(summary: dict, results: list[CaseResult], results_dir: Path) -> Path:
    """存档到 results_dir/<时间戳>.json"""
    results_dir = Path(results_dir)
    results_dir.mkdir(parents=True, exist_ok=True)
    path = results_dir / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    payload = {"summary": summary, "results": [asdict(r) for r in results]}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_last(results_dir: Path) -> dict | None:
    """读取最近一次存档（用于 --compare last）"""
    files = sorted(Path(results_dir).glob("*.json"))
    if not files:
        return None
    try:
        return json.loads(files[-1].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def compare_report(prev: dict | None, cur: dict) -> str:
    """生成"本次 vs 上次"的对比文本"""
    if prev is None:
        return "（没有历史记录可对比 —— 这是第一次运行）"

    ps, cs = prev["summary"], cur
    lines = [f"与上次对比（{ps.get('time', '?')}）:"]

    def delta(cur_v, prev_v, fmt="{:+g}", label=""):
        diff = cur_v - prev_v
        return f"{label}{prev_v} → {cur_v}  ({fmt.format(diff)})"

    lines.append("  通过率:    " + delta(cs["pass_rate"], ps["pass_rate"], "{:+.1f}%"))
    lines.append("  平均迭代:  " + delta(cs["avg_iterations"], ps["avg_iterations"]))
    lines.append("  平均延迟:  " + delta(cs["avg_latency_ms"], ps["avg_latency_ms"], "{:+.1f}ms"))
    if cs["mode"] == ps.get("mode"):
        lines.append("  总 token:  " + delta(cs["total_tokens"], ps["total_tokens"], "{:+d}"))

    prev_pass = {r["case_id"] for r in prev.get("results", []) if r["passed"]}
    cur_pass = set(cur.get("_results_pass", []))          # 是 case_id 字符串列表
    newly_failed = prev_pass - cur_pass
    newly_passed = cur_pass - prev_pass
    if newly_failed:
        lines.append("  ⬇ 新失败:  " + ", ".join(sorted(newly_failed)))
    if newly_passed:
        lines.append("  ⬆ 新通过:  " + ", ".join(sorted(newly_passed)))
    if not newly_failed and not newly_passed:
        lines.append("  用例结果无变化")

    return "\n".join(lines)
