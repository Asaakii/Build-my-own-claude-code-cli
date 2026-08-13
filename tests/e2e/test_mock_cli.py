"""无需密钥的已安装模块级 Mock CLI 演示。"""

import os
import subprocess
import sys
from pathlib import Path


def test_module_entrypoint_runs_mock_demo_in_an_empty_workspace(tmp_path) -> None:
    """模块入口应在新的工作目录中完成不联网的演示调用。"""
    source_root = Path(__file__).resolve().parents[2] / "src"
    environment = {**os.environ, "PYTHONPATH": str(source_root)}
    result = subprocess.run(
        [sys.executable, "-m", "agent_code", "run", "你好"],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == 0
    assert "演示完成：你好" in result.stdout
