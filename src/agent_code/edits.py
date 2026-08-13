"""待确认编辑、原子写入与最小审计服务。"""

import hashlib
import os
import secrets
import stat
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

MAX_FILE_BYTES = 100 * 1024
MAX_AUDIT_EVENTS = 20


@dataclass(frozen=True)
class PendingEdit:
    """一项已经预览、等待用户确认的编辑。"""

    operation: str
    path: str
    expected_sha256: str | None
    old_text: str | None
    new_text: str


@dataclass(frozen=True)
class EditAuditEvent:
    """不含文件内容的编辑审计摘要。"""

    timestamp: datetime
    operation: str
    status: str
    path: str
    before_sha256: str | None
    after_sha256: str | None


class EditAuditLog:
    """仅在当前 CLI 进程中保存最小编辑审计摘要。"""

    def __init__(self) -> None:
        self._events: list[EditAuditEvent] = []

    def record(
        self,
        operation: str,
        status: str,
        path: str,
        before_sha256: str | None = None,
        after_sha256: str | None = None,
    ) -> None:
        """记录一次不含文件内容的编辑结果。"""
        self._events.append(
            EditAuditEvent(
                timestamp=datetime.now(UTC),
                operation=operation,
                status=status,
                path=path,
                before_sha256=before_sha256,
                after_sha256=after_sha256,
            )
        )
        self._events = self._events[-MAX_AUDIT_EVENTS:]

    def render(self) -> str:
        """以可读形式返回当前进程内的编辑审计。"""
        if not self._events:
            return "当前会话没有编辑审计记录。"

        lines = [
            f"当前会话编辑审计：{len(self._events)} 条",
            "---",
        ]

        for event in self._events:
            before_sha256 = event.before_sha256 or "-"
            after_sha256 = event.after_sha256 or "-"
            timestamp = event.timestamp.isoformat(timespec="seconds")

            lines.append(
                f"{timestamp} | {event.status} | {event.operation} | "
                f"{event.path} | 前={before_sha256} | 后={after_sha256}"
            )

        return "\n".join(lines)


class PendingEditStore:
    """仅在当前 CLI 进程存活期间保存待确认编辑。"""

    def __init__(self) -> None:
        self._pending: dict[str, PendingEdit] = {}

    def create_replace(
        self,
        path: str,
        expected_sha256: str,
        old_text: str,
        new_text: str,
    ) -> str:
        """保存待确认的精确替换，并返回一次性确认 ID。"""
        return self._create(
            PendingEdit(
                operation="replace",
                path=path,
                expected_sha256=expected_sha256,
                old_text=old_text,
                new_text=new_text,
            )
        )

    def create_file(self, path: str, content: str) -> str:
        """保存待确认的新文件创建，并返回一次性确认 ID。"""
        return self._create(
            PendingEdit(
                operation="create",
                path=path,
                expected_sha256=None,
                old_text=None,
                new_text=content,
            )
        )

    def _create(self, pending_edit: PendingEdit) -> str:
        approval_id = secrets.token_urlsafe(12)
        self._pending[approval_id] = pending_edit
        return approval_id

    def consume(self, approval_id: str) -> PendingEdit:
        """取出并立即作废一项待确认编辑。"""
        if not isinstance(approval_id, str) or not approval_id:
            raise ValueError("确认 ID 不能为空。")

        try:
            return self._pending.pop(approval_id)
        except KeyError as error:
            raise ValueError("确认 ID 不存在、已过期，或已经执行过。") from error


def apply_pending_edit(
    store: PendingEditStore,
    workspace_root: Path | str,
    approval_id: str,
    audit_log: EditAuditLog | None = None,
) -> str:
    """执行一项由用户在 REPL 中明确确认过的编辑。"""
    pending_edit = store.consume(approval_id)
    audit_log = audit_log or EditAuditLog()
    root = Path(workspace_root).resolve()

    if not root.is_dir():
        raise ValueError("工作区根目录必须是存在的目录。")

    try:
        if pending_edit.operation == "replace":
            result = _apply_replace(root, pending_edit)
        elif pending_edit.operation == "create":
            result = _apply_create(root, pending_edit)
        else:
            raise ValueError("待确认编辑类型无效，已拒绝写入。")
    except (OSError, RuntimeError, ValueError):
        audit_log.record(
            operation=pending_edit.operation,
            status="已拒绝",
            path=pending_edit.path,
        )
        raise

    audit_log.record(
        operation=pending_edit.operation,
        status="已完成",
        path=pending_edit.path,
        before_sha256=result.before_sha256,
        after_sha256=result.after_sha256,
    )
    return result.render()


@dataclass(frozen=True)
class EditResult:
    """一次成功写入的最小结果。"""

    operation: str
    path: str
    before_sha256: str | None
    after_sha256: str

    def render(self) -> str:
        """返回不含文件内容的写入结果。"""
        lines = [
            f"已写入：{self.path}",
            f"操作：{self.operation}",
            "替换次数：1" if self.operation == "replace" else "新建文件：1",
        ]

        if self.before_sha256 is not None:
            lines.append(f"写入前 SHA-256：{self.before_sha256}")

        lines.append(f"写入后 SHA-256：{self.after_sha256}")
        return "\n".join(lines)


def _apply_replace(root: Path, pending_edit: PendingEdit) -> EditResult:
    if pending_edit.expected_sha256 is None or pending_edit.old_text is None:
        raise ValueError("待确认替换内容无效，已拒绝写入。")

    file_path, display_path = _resolve_existing_file(root, pending_edit.path)
    raw_content = _read_file_bytes(file_path, display_path)
    current_sha256 = hashlib.sha256(raw_content).hexdigest()

    if current_sha256 != pending_edit.expected_sha256:
        raise ValueError("文件内容已变化，已拒绝写入。请重新读取并生成预览。")

    try:
        original_text = raw_content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError(f"拒绝写入非 UTF-8 文本文件：{display_path}。") from error

    occurrence_count = _count_overlapping_matches(
        original_text,
        pending_edit.old_text,
    )

    if occurrence_count != 1:
        raise ValueError("文件中的替换目标已变化或不再唯一，已拒绝写入。")

    updated_text = original_text.replace(
        pending_edit.old_text,
        pending_edit.new_text,
        1,
    )
    updated_bytes = updated_text.encode("utf-8")
    updated_sha256 = hashlib.sha256(updated_bytes).hexdigest()

    _atomic_replace_file(file_path, updated_bytes)
    _verify_written_sha256(file_path, updated_sha256)

    return EditResult(
        operation="replace",
        path=display_path,
        before_sha256=current_sha256,
        after_sha256=updated_sha256,
    )


def _apply_create(root: Path, pending_edit: PendingEdit) -> EditResult:
    file_path, display_path = _resolve_new_file(root, pending_edit.path)
    content = pending_edit.new_text.encode("utf-8")

    if len(content) > MAX_FILE_BYTES:
        raise ValueError(
            f"新文件内容超过 {MAX_FILE_BYTES // 1024} KiB 上限，已拒绝写入。"
        )

    updated_sha256 = hashlib.sha256(content).hexdigest()
    _atomic_create_file(file_path, content)
    _verify_written_sha256(file_path, updated_sha256)

    return EditResult(
        operation="create",
        path=display_path,
        before_sha256=None,
        after_sha256=updated_sha256,
    )


def _resolve_existing_file(root: Path, path: str) -> tuple[Path, str]:
    requested_path = _validate_relative_path(path)
    candidate_path = root / requested_path
    _reject_symlink_path(root, requested_path)
    resolved_path = candidate_path.resolve(strict=False)
    display_path = _display_path(root, resolved_path)

    if not resolved_path.exists():
        raise ValueError(f"文件不存在：{display_path}。")

    if not resolved_path.is_file():
        raise ValueError(f"目标不是普通文件：{display_path}。")

    return resolved_path, display_path


def _resolve_new_file(root: Path, path: str) -> tuple[Path, str]:
    requested_path = _validate_relative_path(path)

    if requested_path == Path("."):
        raise ValueError("新文件路径无效，已拒绝写入。")

    _reject_symlink_path(root, requested_path.parent)
    parent_directory = root / requested_path.parent

    if not parent_directory.exists() or not parent_directory.is_dir():
        raise ValueError("新文件的父目录不存在，已拒绝写入。")

    candidate_path = root / requested_path

    if candidate_path.exists() or candidate_path.is_symlink():
        raise ValueError("目标文件已存在，拒绝覆盖。")

    resolved_path = candidate_path.resolve(strict=False)
    display_path = _display_path(root, resolved_path)
    return resolved_path, display_path


def _validate_relative_path(path: str) -> Path:
    requested_path = Path(path)

    if requested_path.is_absolute() or ".." in requested_path.parts:
        raise ValueError("待确认编辑的路径无效，已拒绝写入。")

    return requested_path


def _reject_symlink_path(root: Path, relative_path: Path) -> None:
    current_path = root

    for part in relative_path.parts:
        current_path /= part

        if current_path.is_symlink():
            raise ValueError("拒绝写入包含符号链接的路径。")


def _display_path(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError as error:
        raise ValueError("拒绝写入工作区外的路径。") from error


def _read_file_bytes(file_path: Path, display_path: str) -> bytes:
    try:
        if file_path.stat().st_size > MAX_FILE_BYTES:
            raise ValueError(
                f"文件过大：{display_path} 超过 {MAX_FILE_BYTES // 1024} KiB 上限。"
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


def _atomic_replace_file(file_path: Path, content: bytes) -> None:
    """以同目录临时文件加原子替换，避免产生半写入文件。"""
    temporary_file = _write_temporary_file(
        file_path.parent,
        content,
        mode=stat.S_IMODE(file_path.stat().st_mode),
    )

    try:
        os.replace(temporary_file, file_path)
    except OSError as error:
        raise RuntimeError("原子写入失败，原文件未被部分覆盖。") from error
    finally:
        if temporary_file.exists():
            temporary_file.unlink()


def _atomic_create_file(file_path: Path, content: bytes) -> None:
    """通过临时文件和硬链接创建新文件，拒绝覆盖已有文件。"""
    temporary_file = _write_temporary_file(
        file_path.parent,
        content,
        mode=0o644,
    )

    try:
        os.link(temporary_file, file_path)
    except FileExistsError as error:
        raise ValueError("目标文件已存在，拒绝覆盖。") from error
    except OSError as error:
        raise RuntimeError("创建新文件失败，未产生部分文件。") from error
    finally:
        if temporary_file.exists():
            temporary_file.unlink()


def _write_temporary_file(
    directory: Path,
    content: bytes,
    mode: int,
) -> Path:
    try:
        descriptor, temporary_path = tempfile.mkstemp(
            prefix=".agent-code-",
            dir=directory,
        )
    except OSError as error:
        raise RuntimeError("无法创建临时文件，已取消写入。") from error

    temporary_file = Path(temporary_path)

    try:
        with os.fdopen(descriptor, "wb") as file:
            file.write(content)
            file.flush()
            os.fsync(file.fileno())

        os.chmod(temporary_file, mode)
    except OSError as error:
        raise RuntimeError("临时文件写入失败，已取消写入。") from error

    return temporary_file


def _verify_written_sha256(file_path: Path, expected_sha256: str) -> None:
    try:
        actual_sha256 = hashlib.sha256(file_path.read_bytes()).hexdigest()
    except OSError as error:
        raise RuntimeError("写入后无法复核文件，请立即人工检查。") from error

    if actual_sha256 != expected_sha256:
        raise RuntimeError("写入后校验失败，请立即人工检查文件。")
