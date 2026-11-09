"""评测入口

用法：
    python -m evals run                  # 跑全部用例（deterministic，不联网）
    python -m evals run --id read_file_basic
    python -m evals run --live --config "C:\\Users\\33020\\zhenshi\\config.json"
"""
import argparse
import asyncio
from pathlib import Path

from .loader import load_cases
from .runner import run_case

CASES_ROOT = Path(__file__).parent / "cases"


def _live_provider_factory(config_path: str):
    """用真实配置造 provider（延迟导入：deterministic 模式不依赖配置文件）"""
    from mybot.cli import build_provider
    from mybot.config.loader import load_config

    cfg = load_config(config_path)
    return lambda: build_provider(cfg)


async def _run_all(args) -> int:
    cases = load_cases(CASES_ROOT)
    if args.id:
        cases = [c for c in cases if c.id == args.id]
    if not cases:
        print("没有找到用例（检查 evals/cases/**/*.yaml）")
        return 1

    factory = _live_provider_factory(args.config) if args.live else None

    print(f"模式: {'live（真实模型）' if args.live else 'deterministic（剧本）'}")
    print("-" * 72)

    passed = 0
    for i, case in enumerate(cases, 1):
        traj, ok, reason = await run_case(case, live_provider_factory=factory)
        status = "PASS" if ok else "FAIL"
        print(f"[{i}/{len(cases)}] {case.category:<16} {case.id:<26} {status}")
        if not ok:
            print(f"       ↳ {reason}")
        passed += 1 if ok else 0

    print("-" * 72)
    total = len(cases)
    print(f"结果: {passed}/{total} passed ({passed / total * 100:.1f}%)")
    return 0 if passed == total else 1


def main() -> None:
    parser = argparse.ArgumentParser(prog="evals", description="mybot 的评测工具")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser("run", help="运行评测用例")
    p_run.add_argument("--id", help="只跑指定 id 的用例")
    p_run.add_argument("--live", action="store_true", help="用真实模型（需要 --config）")
    p_run.add_argument("--config", help="配置文件路径（live 模式必填）")

    args = parser.parse_args()

    if args.cmd == "run":
        if args.live and not args.config:
            parser.error("--live 模式需要 --config")
        raise SystemExit(asyncio.run(_run_all(args)))


if __name__ == "__main__":
    main()
