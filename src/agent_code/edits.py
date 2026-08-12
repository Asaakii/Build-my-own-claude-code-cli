"""待确认编辑的内存状态与原子写入服务。"""

import hashlib
import os
import secrets
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path

MAX_FILE_BYTES = 100 * 1024


@dataclass(frozen=True)
class PendingEdit:
    """一项已经预览、等待用户确认的精确替换。"""

    path: str
    expected_sha256: str
    old_text: str
    new_text: str


class PendingEditStore:
    """仅在当前 CLI 进程存活期间保存待确认编辑。"""

    def __init__(self) -> None:
        self._pending: dict[str, PendingEdit] = {}

    def create(
        self,
        path: str,
        expected_sha256: str,
        old_text: str,
        new_text: str,
    ) -> str:
        """保存预览内容并返回一次性确认 ID。"""
        approval_id = secrets.token_urlsafe(12)
        self._pending[approval_id] = PendingEdit(
            path=path,
            expected_sha256=expected_sha256,
            old_text=old_text,
            new_text=new_text,
        )
        return approval_id

    def consume(self, approval_id: str) -> PendingEdit:
        """取出并立即作废一项待确认编辑。"""
        if not isinstance(approval_id, str) or not approval_id:
            raise ValueError("确认 ID 不能为空。")

        try:
            return self._pending.pop(approval_id)
        except KeyError as error:
            raise ValueError(
                "确认 ID 不存在、已过期，或已经执行过。"
            ) from error


def apply_pending_edit(
    store: PendingEditStore,
    workspace_root: Path | str,
    approval_id: str,
) -> str:
    """执行一项由用户在 REPL 中明确确认过的精确替换。"""
    pending_edit = store.consume(approval_id)
    root = Path(workspace_root).resolve()

    if not root.is_dir():
        raise ValueError("工作区根目录必须是存在的目录。")

    file_path, display_path = _resolve_existing_file(
        root,
        pending_edit.path,
    )
    raw_content = _read_file_bytes(file_path, display_path)
    current_sha256 = hashlib.sha256(raw_content).hexdigest()

    if current_sha256 != pending_edit.expected_sha256:
        raise ValueError(
            "文件内容已变化，已拒绝写入。请重新读取并生成预览。"
        )

    try:
        original_text = raw_content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError(
            f"拒绝写入非 UTF-8 文本文件：{display_path}。"
        ) from error

    occurrence_count = _count_overlapping_matches(
        original_text,
        pending_edit.old_text,
    )

    if occurrence_count != 1:
        raise ValueError(
            "文件中的替换目标已变化或不再唯一，已拒绝写入。"
        )

    updated_text = original_text.replace(
        pending_edit.old_text,
        pending_edit.new_text,
        1,
    )
    updated_bytes = updated_text.encode("utf-8")
    updated_sha256 = hashlib.sha256(updated_bytes).hexdigest()

    _atomic_write(file_path, updated_bytes)

    try:
        actual_sha256 = hashlib.sha256(file_path.read_bytes()).hexdigest()
    except OSError as error:
        raise RuntimeError(
            "写入后无法复核文件，请立即人工检查。"
        ) from error

    if actual_sha256 != updated_sha256:
        raise RuntimeError("写入后校验失败，请立即人工检查文件。")

    return "\n".join(
        [
            f"已写入：{display_path}",
            "替换次数：1",
            f"写入前 SHA-256：{current_sha256}",
            f"写入后 SHA-256：{updated_sha256}",
        ]
    )


def _resolve_existing_file(root: Path, path: str) -> tuple[Path, str]:
    requested_path = Path(path)

    if requested_path.is_absolute() or ".." in requested_path.parts:
        raise ValueError("待确认编辑的路径无效，已拒绝写入。")

    candidate_path = root / requested_path
    current_path = root

    for part in requested_path.parts:
        current_path /= part

        if current_path.is_symlink():
            raise ValueError("拒绝写入包含符号链接的路径。")

    resolved_path = candidate_path.resolve(strict=False)

    try:
        display_path = resolved_path.relative_to(root).as_posix()
    except ValueError as error:
        raise ValueError("拒绝写入工作区外的路径。") from error

    if not resolved_path.exists():
        raise ValueError(f"文件不存在：{display_path}。")

    if not resolved_path.is_file():
        raise ValueError(f"目标不是普通文件：{display_path}。")

    return resolved_path, display_path


def _read_file_bytes(file_path: Path, display_path: str) -> bytes:
    try:
        if file_path.stat().st_size > MAX_FILE_BYTES:
            raise ValueError(
                f"文件过大：{display_path} 超过 "
                f"{MAX_FILE_BYTES // 1024} KiB 上限。"
            )

        raw_content = file_path.read_bytes()
    except OSError as error:
        raise ValueError("无法读取文件，请检查访问权限。") from error

    if b"\x00" in raw_content:
        raise ValueError(f"拒绝写入二进制文件：{display_path}。")

    return raw_content


def _count_overlapping_matches(text: str, target: str) -> int:
    count = 0
    start = 0

    while True:
        found_at = text.find(target, start)

        if found_at == -1:
            return count

        count += 1
        start = found_at + 1


def _atomic_write(file_path: Path, content: bytes) -> None:
    """以同目录临时文件加原子替换，避免产生半写入文件。"""
    try:
        original_mode = stat.S_IMODE(file_path.stat().st_mode)
        descriptor, temporary_path = tempfile.mkstemp(
            prefix=".agent-code-",
            dir=file_path.parent,
        )
    except OSError as error:
        raise RuntimeError("无法创建临时文件，已取消写入。") from error

    temporary_file = Path(temporary_path)

    try:
        with os.fdopen(descriptor, "wb") as file:
            file.write(content)
            file.flush()
            os.fsync(file.fileno())

        os.chmod(temporary_file, original_mode)
        os.replace(temporary_file, file_path)
    except OSError as error:
        raise RuntimeError("原子写入失败，原文件未被部分覆盖。") from error
    finally:
        if temporary_file.exists():
            temporary_file.unlink()