"""
自定义 QHeaderView，支持按列独立锁定宽度。

Qt5 的 setMinimumSectionSize/setMaximumSectionSize 是全局方法（作用于所有列），
无法单独锁定某一列。本类通过 override resizeSection 实现按列宽约束。
"""
from PyQt5.QtWidgets import QHeaderView


class CustomHeader(QHeaderView):
    """支持按列锁定宽度的 QHeaderView。

    用法：
        header = CustomHeader()
        header.lock_column(0, 100)   # 锁定列0宽100px
        header.lock_column(5, 100)   # 锁定列5宽100px
        header.unlock_column(1)      # 解锁列1
    """

    # ── per-column constraint helpers ──────────────────────────────────
    def lock_column(self, index, width):
        self._locked_widths[index] = width

    def unlock_column(self, index):
        self._locked_widths.pop(index, None)

    def is_locked(self, index):
        return index in self._locked_widths

    # ── QHeaderView overrides ─────────────────────────────────────────
    def __init__(self, orientation, parent=None):
        super().__init__(orientation, parent)
        self._locked_widths = {}          # {logicalIndex: fixed_width}
        self._resize_guard = False        # 防止 resizeSection → sectionResized → 循环

    def resizeSection(self, logicalIndex, size):
        """拦截 resizeSection，对锁定列强制保持既定宽度。"""
        locked = self._locked_widths.get(logicalIndex)
        if locked is not None and size != locked:
            size = locked
        if self._resize_guard:
            super().resizeSection(logicalIndex, size)
        else:
            self._resize_guard = True
            super().resizeSection(logicalIndex, size)
            self._resize_guard = False
