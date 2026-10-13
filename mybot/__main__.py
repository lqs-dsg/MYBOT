"""让 `python -m mybot` 可用

用法：
    python -m mybot agent -m "你好"
    python -m mybot agent
    python -m mybot --help
"""
from mybot.cli import app

if __name__ == "__main__":
    app()
