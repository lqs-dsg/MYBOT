"""用例加载：遍历 cases/ 下的 YAML 文件，解析成 Case 对象

（原文件名叫 cases.py，与数据目录 evals/cases/ 同名容易混淆，故改名 loader.py）
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import yaml


@dataclass
class Case:
    id: str
    category: str
    input: str
    graders: List[Dict]
    description: str = ""
    setup_files: Dict[str, str] = field(default_factory=dict)   # 相对路径 -> 文件内容
    script: Optional[List[Dict]] = None                         # deterministic 模式的剧本
    modes: Optional[List[str]] = None                           # 适用模式；None = 两种都适用
                                                                # 例：["deterministic"] 表示只在剧本模式跑


def load_cases(root: Path) -> List[Case]:
    """加载 root 下所有 YAML 用例（按 id 排序，保证执行顺序稳定）"""
    cases: List[Case] = []
    seen_ids = set()

    for fpath in sorted(Path(root).rglob("*.yaml")):
        raw = yaml.safe_load(fpath.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError(f"{fpath}: 用例必须是 YAML 字典")

        case = Case(**raw)

        if case.id in seen_ids:
            raise ValueError(f"重复的用例 id: {case.id}（{fpath}）")
        seen_ids.add(case.id)
        cases.append(case)

    cases.sort(key=lambda c: c.id)
    return cases
