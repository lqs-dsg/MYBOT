"""评测入口

用法：
    python -m evals run                       # 跑全部用例（deterministic），打印报告并存档
    python -m evals run --compare last        # 跑完与上次存档对比
    python -m evals run --id read_file_basic  # 只跑一个
    python -m evals run --live --config "C:\\Users\\33020\\zhenshi\\config.json"
    python -m evals run --no-save             # 不存档
"""
import argparse
import asyncio
from pathlib import Path

from .loader import load_cases
from .report import CaseResult, compare_report, load_last, print_report, save_result, summarize
from .runner import run_case

CASES_ROOT = Path(__file__).parent / "cases"
RESULTS_ROOT = Path(__file__).parent / "results"


def _live_provider_factory(config_path: str):
    """用真实配置造 provider（延迟导入：deterministic 模式不依赖配置文件）"""
    from mybot.cli import build_provider
    from mybot.config.loader import load_config

    cfg = load_config(config_path)
    return lambda: build_provider(cfg)


async def _run_all(args) -> int:
    all_cases = load_cases(CASES_ROOT)
    if args.id:
        all_cases = [c for c in all_cases if c.id == args.id]
    if not all_cases:
        print("没有找到用例（检查 evals/cases/**/*.yaml）")
        return 1

    # 按模式过滤：modes 为 None 表示两种模式都适用
    mode_key = "live" if args.live else "deterministic"
    cases = [c for c in all_cases if c.modes is None or mode_key in c.modes]
    skipped = [c for c in all_cases if c.modes is not None and mode_key not in c.modes]

    if not cases:
        print(f"没有适用于 {mode_key} 模式的用例")
        return 1

    factory = _live_provider_factory(args.config) if args.live else None
    mode = "live（真实模型）" if args.live else "deterministic（剧本）"
    if skipped:
        print(f"  跳过 {len(skipped)} 个用例（不适用于 {mode_key} 模式）: "
              + ", ".join(c.id for c in skipped))

    results: list[CaseResult] = []
    for i, case in enumerate(cases, 1):
        print(f"  [{i}/{len(cases)}] {case.id:<26} ... ", end="", flush=True)
        try:
            res = await run_case(case, live_provider_factory=factory)
        except Exception as e:
            # 单个用例炸掉不能拖垮整场评测
            res = CaseResult(
                case_id=case.id,
                category=case.category,
                passed=False,
                reason=f"用例执行异常: {type(e).__name__}: {e}",
                iterations=0, tool_calls=0, tool_errors=0, latency_ms=0.0,
            )
        results.append(res)
        print("PASS" if res.passed else "FAIL", flush=True)

    summary = summarize(results, mode)
    summary["_results_pass"] = [r.case_id for r in results if r.passed]

    print()
    print_report(summary, results)

    if args.compare == "last":
        prev = load_last(RESULTS_ROOT)
        print()
        print(compare_report(prev, summary))

    if not args.no_save:
        path = save_result(summary, results, RESULTS_ROOT)
        print(f"\n存档: {path}")

    return 0 if summary["passed"] == summary["total"] else 1


def main() -> None:
    parser = argparse.ArgumentParser(prog="evals", description="mybot 的评测工具")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser("run", help="运行评测用例")
    p_run.add_argument("--id", help="只跑指定 id 的用例")
    p_run.add_argument("--live", action="store_true", help="用真实模型（需要 --config）")
    p_run.add_argument("--config", help="配置文件路径（live 模式必填）")
    p_run.add_argument("--compare", choices=["last"], help="与上次运行结果对比")
    p_run.add_argument("--no-save", action="store_true", help="不存档结果")

    args = parser.parse_args()

    if args.cmd == "run":
        if args.live and not args.config:
            parser.error("--live 模式需要 --config")
        raise SystemExit(asyncio.run(_run_all(args)))


if __name__ == "__main__":
    main()
