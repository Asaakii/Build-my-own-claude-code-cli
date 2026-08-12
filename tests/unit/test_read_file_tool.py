"""ReadFileTool 的单元测试。"""

from agent_code.tools.read_file import ReadFileTool


def test_read_file_reads_workspace_text_with_line_numbers(tmp_path) -> None:
    """工具应读取工作区文件，并支持行号范围。"""
    (tmp_path / "notes.txt").write_text(
        "第一行\n第二行\n第三行\n",
        encoding="utf-8",
    )
    tool = ReadFileTool(tmp_path)

    result = tool.run(
        {
            "path": "notes.txt",
            "start_line": 2,
            "end_line": 3,
        }
    )

    assert "文件：notes.txt" in result
    assert "内容 SHA-256：" in result
    assert "   2: 第二行" in result
    assert "   3: 第三行" in result
    assert "第一行" not in result


def test_read_file_rejects_workspace_escape_and_symlink(tmp_path) -> None:
    """.. 和指向工作区外的符号链接都必须被拒绝。"""
    outside_file = tmp_path.parent / "outside.txt"
    outside_file.write_text("不应被读取", encoding="utf-8")
    link = tmp_path / "outside-link.txt"
    link.symlink_to(outside_file)

    tool = ReadFileTool(tmp_path)

    for path in ("../outside.txt", "outside-link.txt"):
        try:
            tool.run({"path": path})
        except ValueError as error:
            assert "工作区外" in str(error)
        else:
            raise AssertionError(f"应拒绝路径：{path}")


def test_read_file_rejects_binary_and_oversized_files(tmp_path) -> None:
    """二进制文件与超出上限的文件都不能被读取。"""
    binary_file = tmp_path / "image.bin"
    binary_file.write_bytes(b"\x00\x01\x02")

    large_file = tmp_path / "large.txt"
    large_file.write_bytes(b"a" * (ReadFileTool.max_file_bytes + 1))

    tool = ReadFileTool(tmp_path)

    for path, expected_message in (
        ("image.bin", "二进制文件"),
        ("large.txt", "文件过大"),
    ):
        try:
            tool.run({"path": path})
        except ValueError as error:
            assert expected_message in str(error)
        else:
            raise AssertionError(f"应拒绝文件：{path}")


def test_read_file_truncates_long_output(tmp_path) -> None:
    """工具输出必须有行数上限，并提示如何继续读取。"""
    content = "\n".join(
        f"第 {number} 行"
        for number in range(1, ReadFileTool.max_output_lines + 2)
    )
    (tmp_path / "many-lines.txt").write_text(content, encoding="utf-8")
    tool = ReadFileTool(tmp_path)

    result = tool.run({"path": "many-lines.txt"})

    assert " 200: 第 200 行" in result
    assert "输出已截断" in result