from __future__ import annotations

import time
from datetime import date, datetime, timedelta

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import (
    QColor,
    QCloseEvent,
    QFont,
    QIcon,
    QPainter,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QBoxLayout,
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSystemTrayIcon,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .autostart import is_autostart_enabled, set_autostart_enabled
from .database import ActivityStore, TodoItem
from .stats import DayStats, get_daily_key_totals, get_day_stats
from .tracker import ActivityTracker


COLORS = {
    "background": QColor("#0b1020"),
    "panel": QColor("#151c2f"),
    "panel_alt": QColor("#1b2540"),
    "text": QColor("#f3f6ff"),
    "muted": QColor("#8f9bb3"),
    "accent": QColor("#6d8cff"),
    "accent_light": QColor("#9eafff"),
    "grid": QColor("#2b3651"),
    "green": QColor("#43d39e"),
}

TODO_TITLE_ROLE = Qt.ItemDataRole.UserRole.value + 1
TODO_COMPLETED_ROLE = Qt.ItemDataRole.UserRole.value + 2


def _format_number(value: int) -> str:
    return f"{value:,}"


def _format_clock(timestamp: int | None) -> str:
    return datetime.fromtimestamp(timestamp).strftime("%H:%M") if timestamp else "—"


def _format_duration(seconds: int) -> str:
    minutes = max(0, seconds // 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}시간 {minutes}분"
    return f"{minutes}분"


def make_app_icon(size: int = 64) -> QIcon:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(COLORS["accent"])
    painter.drawRoundedRect(QRectF(2, 2, size - 4, size - 4), size * 0.22, size * 0.22)
    painter.setPen(QPen(QColor("white"), max(2, size // 12), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    for x, height in ((0.28, 0.26), (0.50, 0.48), (0.72, 0.34)):
        bottom = size * 0.73
        painter.drawLine(int(size * x), int(bottom), int(size * x), int(bottom - size * height))
    painter.end()
    return QIcon(pixmap)


class StatCard(QFrame):
    def __init__(self, title: str):
        super().__init__()
        self.setObjectName("card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 10, 18, 10)
        layout.setSpacing(4)
        title_label = QLabel(title)
        title_label.setObjectName("muted")
        self.value_label = QLabel("—")
        self.value_label.setObjectName("cardValue")
        layout.addWidget(title_label)
        layout.addWidget(self.value_label)

    def set_value(self, value: str) -> None:
        self.value_label.setText(value)


class HourlyChart(QWidget):
    def __init__(self):
        super().__init__()
        self._values = [0] * 24
        self.setMinimumHeight(110)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_values(self, values: tuple[int, ...]) -> None:
        self._values = list(values)
        self.update()

    def paintEvent(self, _event) -> None:  # type: ignore[no-untyped-def]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width, height = self.width(), self.height()
        left, right, top, bottom = 48, 16, 18, 40
        chart_width = max(1, width - left - right)
        chart_height = max(1, height - top - bottom)
        maximum = max(self._values, default=0)
        ceiling = max(10, maximum)

        painter.setFont(QFont("Malgun Gothic", 8))
        painter.setPen(COLORS["grid"])
        for step in range(5):
            y = top + chart_height * step / 4
            painter.drawLine(left, int(y), width - right, int(y))
            label = str(round(ceiling * (4 - step) / 4))
            painter.setPen(COLORS["muted"])
            painter.drawText(QRectF(0, y - 8, left - 8, 16), Qt.AlignmentFlag.AlignRight, label)
            painter.setPen(COLORS["grid"])

        slot = chart_width / 24
        bar_width = max(3.0, slot * 0.58)
        busiest = max(range(24), key=self._values.__getitem__) if maximum else -1
        label_step = 3 if chart_width >= 420 else 6
        for hour, value in enumerate(self._values):
            bar_height = chart_height * value / ceiling
            x = left + hour * slot + (slot - bar_width) / 2
            y = top + chart_height - bar_height
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(COLORS["accent_light"] if hour == busiest else COLORS["accent"])
            painter.drawRoundedRect(QRectF(x, y, bar_width, bar_height), 3, 3)
            if hour % label_step == 0:
                painter.setPen(COLORS["muted"])
                painter.drawText(
                    QRectF(left + hour * slot - slot / 2, height - bottom + 10, slot * 2, 18),
                    Qt.AlignmentFlag.AlignCenter,
                    f"{hour:02d}",
                )
        painter.end()


class WeekChart(QWidget):
    def __init__(self):
        super().__init__()
        self._values: list[tuple[date, int]] = []
        self.setMinimumHeight(92)

    def set_values(self, values: list[tuple[date, int]]) -> None:
        self._values = values
        self.update()

    def paintEvent(self, _event) -> None:  # type: ignore[no-untyped-def]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self._values:
            painter.end()
            return
        width, height = self.width(), self.height()
        left, right, top, bottom = 6, 6, 18, 38
        chart_width = max(1, width - left - right)
        chart_height = max(1, height - top - bottom)
        maximum = max((value for _, value in self._values), default=0)
        ceiling = max(10, maximum)
        slot = chart_width / len(self._values)
        bar_width = max(10.0, slot * 0.52)
        today = date.today()
        weekdays = "월화수목금토일"
        painter.setFont(QFont("Malgun Gothic", 7 if chart_width < 150 else 8))
        for index, (day, value) in enumerate(self._values):
            bar_height = chart_height * value / ceiling
            x = left + index * slot + (slot - bar_width) / 2
            y = top + chart_height - bar_height
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(COLORS["green"] if day == today else COLORS["accent"])
            painter.drawRoundedRect(QRectF(x, y, bar_width, bar_height), 4, 4)
            painter.setPen(COLORS["muted"])
            painter.drawText(
                QRectF(left + index * slot, height - bottom + 6, slot, 30),
                Qt.AlignmentFlag.AlignCenter,
                f"{weekdays[day.weekday()]}\n{day.day}",
            )
            if value:
                painter.setPen(COLORS["text"])
                painter.drawText(
                    QRectF(left + index * slot, max(0, y - 19), slot, 18),
                    Qt.AlignmentFlag.AlignCenter,
                    _format_number(value),
                )
        painter.end()


class DashboardWindow(QMainWindow):
    def __init__(self, store: ActivityStore, tracker: ActivityTracker):
        super().__init__()
        self.store = store
        self.tracker = tracker
        self.selected_day = date.today()
        self._quitting = False
        self._tray_notice_shown = False
        self._todos: list[TodoItem] = []
        self._loading_todos = False
        self._loading_sessions = False
        self._selected_session_start: int | None = None
        self.idle_minutes = int(store.get_setting("idle_minutes", "10"))

        self.setWindowTitle("MyWorkLog")
        self.setWindowIcon(make_app_icon())
        self.resize(1080, 760)
        self.setMinimumSize(800, 600)
        self._build_ui()
        self._build_tray()
        self._apply_style()
        self._refresh()

        self.refresh_timer = QTimer(self)
        self.refresh_timer.setInterval(15_000)
        self.refresh_timer.timeout.connect(self._refresh_if_visible)
        self.refresh_timer.start()

    def _build_ui(self) -> None:
        page = QWidget()
        page.setObjectName("page")
        self.outer_layout = QVBoxLayout(page)
        self.outer_layout.setContentsMargins(20, 18, 20, 16)
        self.outer_layout.setSpacing(12)

        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel("MyWorkLog")
        title.setObjectName("title")
        subtitle = QLabel("입력 내용 없이, 일한 흐름만 기록합니다")
        subtitle.setObjectName("muted")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        header.addLayout(title_box)
        header.addStretch()

        previous_button = QPushButton("‹")
        previous_button.setFixedWidth(42)
        previous_button.clicked.connect(lambda: self._move_day(-1))
        self.day_label = QPushButton()
        self.day_label.setMinimumWidth(145)
        self.day_label.clicked.connect(self._go_today)
        next_button = QPushButton("›")
        next_button.setFixedWidth(42)
        next_button.clicked.connect(lambda: self._move_day(1))
        header.addWidget(previous_button)
        header.addWidget(self.day_label)
        header.addWidget(next_button)
        self.outer_layout.addLayout(header)

        self.cards_layout = QGridLayout()
        self.cards_layout.setHorizontalSpacing(12)
        self.cards_layout.setVerticalSpacing(12)
        self.key_card = StatCard("키 입력")
        self.work_card = StatCard("추정 업무 시간")
        self.session_card = StatCard("업무 세션")
        self.range_card = StatCard("첫 활동 → 마지막 활동")
        self.stat_cards = (
            self.key_card,
            self.work_card,
            self.session_card,
            self.range_card,
        )
        for column, card in enumerate(self.stat_cards):
            self.cards_layout.addWidget(card, 0, column)
            self.cards_layout.setColumnStretch(column, 1)
        self.outer_layout.addLayout(self.cards_layout)

        self.hourly_panel = QFrame()
        self.hourly_panel.setObjectName("panel")
        left_layout = QVBoxLayout(self.hourly_panel)
        left_layout.setContentsMargins(18, 16, 18, 14)
        chart_header = QHBoxLayout()
        chart_title = QLabel("시간대별 키 입력")
        chart_title.setObjectName("sectionTitle")
        self.peak_label = QLabel()
        self.peak_label.setObjectName("muted")
        chart_header.addWidget(chart_title)
        chart_header.addStretch()
        chart_header.addWidget(self.peak_label)
        left_layout.addLayout(chart_header)
        self.hourly_chart = HourlyChart()
        left_layout.addWidget(self.hourly_chart)

        self.weekly_panel = QFrame()
        self.weekly_panel.setObjectName("panel")
        right_layout = QVBoxLayout(self.weekly_panel)
        right_layout.setContentsMargins(12, 12, 12, 10)
        week_title = QLabel("최근 7일")
        week_title.setObjectName("sectionTitle")
        right_layout.addWidget(week_title)
        self.week_chart = WeekChart()
        right_layout.addWidget(self.week_chart)
        self.session_panel = QFrame()
        self.session_panel.setObjectName("panel")
        session_layout = QVBoxLayout(self.session_panel)
        session_layout.setContentsMargins(12, 12, 12, 10)
        session_header = QHBoxLayout()
        session_title = QLabel("업무 세션")
        session_title.setObjectName("sectionTitle")
        session_header.addWidget(session_title)
        session_header.addStretch()
        session_header.addWidget(QLabel("무입력 기준"))
        self.idle_combo = QComboBox()
        for value in (5, 10, 15, 20, 30):
            self.idle_combo.addItem(f"{value}분", value)
        selected_index = self.idle_combo.findData(self.idle_minutes)
        self.idle_combo.setCurrentIndex(max(0, selected_index))
        self.idle_combo.currentIndexChanged.connect(self._change_idle_minutes)
        session_header.addWidget(self.idle_combo)
        session_layout.addLayout(session_header)

        self.session_table = QTableWidget(0, 5)
        self.session_table.setHorizontalHeaderLabels(
            ["시작", "마지막 활동", "세션 길이", "키 입력", "수행 업무"]
        )
        table_header = self.session_table.horizontalHeader()
        for column in range(4):
            table_header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        table_header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.session_table.verticalHeader().setVisible(False)
        self.session_table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
        )
        self.session_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.session_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.session_table.setToolTip(
            "세션 행을 선택한 뒤 Todo를 체크하면 수행 업무에 추가됩니다."
        )
        self.session_table.itemSelectionChanged.connect(
            self._session_selection_changed
        )
        self.session_table.itemChanged.connect(self._session_item_changed)
        self.session_table.setMinimumHeight(82)
        self.session_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        session_layout.addWidget(self.session_table)

        self.todo_panel = QFrame()
        self.todo_panel.setObjectName("panel")
        todo_layout = QVBoxLayout(self.todo_panel)
        todo_layout.setContentsMargins(14, 12, 14, 10)
        todo_layout.setSpacing(7)
        todo_header = QHBoxLayout()
        todo_title = QLabel("Todo List")
        todo_title.setObjectName("sectionTitle")
        self.todo_count_label = QLabel("0개")
        self.todo_count_label.setObjectName("muted")
        self.delete_todo_button = QPushButton("삭제")
        self.delete_todo_button.setObjectName("deleteTodoButton")
        self.delete_todo_button.setToolTip("선택한 Todo 삭제")
        self.delete_todo_button.setFixedWidth(46)
        self.delete_todo_button.setEnabled(False)
        self.delete_todo_button.clicked.connect(self._delete_selected_todo)
        todo_header.addWidget(todo_title)
        todo_header.addStretch()
        todo_header.addWidget(self.delete_todo_button)
        todo_header.addWidget(self.todo_count_label)
        todo_layout.addLayout(todo_header)

        self.todo_list = QListWidget()
        self.todo_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.todo_list.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
        )
        self.todo_list.setToolTip(
            "체크하면 선택한 업무 세션에 기록 · 더블클릭하면 이름 수정"
        )
        self.todo_list.itemChanged.connect(self._todo_item_changed)
        self.todo_list.currentItemChanged.connect(
            lambda current, _previous: self.delete_todo_button.setEnabled(
                current is not None
            )
        )
        todo_layout.addWidget(self.todo_list)

        todo_input_row = QHBoxLayout()
        todo_input_row.setSpacing(6)
        self.todo_input = QLineEdit()
        self.todo_input.setPlaceholderText("할 일 추가")
        self.todo_input.setMaxLength(100)
        self.todo_input.returnPressed.connect(self._add_todo)
        add_todo_button = QPushButton("+")
        add_todo_button.setObjectName("addTodoButton")
        add_todo_button.setFixedWidth(34)
        add_todo_button.clicked.connect(self._add_todo)
        todo_input_row.addWidget(self.todo_input)
        todo_input_row.addWidget(add_todo_button)
        todo_layout.addLayout(todo_input_row)

        self.weekly_panel.setMinimumHeight(145)
        self.weekly_panel.setMaximumHeight(185)
        self.session_panel.setMinimumHeight(145)
        self.session_panel.setMaximumHeight(185)
        self.todo_panel.setMinimumHeight(145)
        self.weekly_panel.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )
        self.session_panel.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )
        self.todo_panel.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        lower_container = QWidget()
        lower_container.setMinimumHeight(145)
        lower_container.setMaximumHeight(185)
        lower_row = QHBoxLayout(lower_container)
        lower_row.setContentsMargins(0, 0, 0, 0)
        lower_row.setSpacing(12)
        lower_row.addWidget(self.weekly_panel, 3)
        lower_row.addWidget(self.session_panel, 8)

        content_layout = QGridLayout()
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setHorizontalSpacing(12)
        content_layout.setVerticalSpacing(12)
        content_layout.addWidget(self.hourly_panel, 0, 0)
        content_layout.addWidget(lower_container, 1, 0)
        content_layout.addWidget(self.todo_panel, 0, 1, 2, 1)
        content_layout.setColumnStretch(0, 11)
        content_layout.setColumnStretch(1, 3)
        content_layout.setRowStretch(0, 1)
        self.outer_layout.addLayout(content_layout, 3)

        self.footer_layout = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        self.privacy_label = QLabel(
            "자동 내용 수집 없음 · Todo 제목만 로컬 저장"
        )
        self.privacy_label.setObjectName("muted")
        self.privacy_label.setWordWrap(False)
        self.privacy_label.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Preferred,
        )
        self.footer_layout.addWidget(self.privacy_label)
        self.footer_layout.addStretch()
        self.autostart_checkbox = QCheckBox("Windows 로그인 시 자동 실행")
        self.autostart_checkbox.setChecked(is_autostart_enabled())
        self.autostart_checkbox.toggled.connect(self._toggle_autostart)
        self.footer_layout.addWidget(self.autostart_checkbox)
        self.pause_button = QPushButton("기록 일시정지")
        self.pause_button.setObjectName("pauseButton")
        self.pause_button.clicked.connect(self._toggle_pause)
        self.footer_layout.addWidget(self.pause_button)
        self.outer_layout.addLayout(self.footer_layout)

        self.setCentralWidget(page)

    def _build_tray(self) -> None:
        self.tray = QSystemTrayIcon(make_app_icon(32), self)
        self.tray.setToolTip("MyWorkLog · 활동 기록 중")
        menu = QMenu()
        open_action = menu.addAction("대시보드 열기")
        open_action.triggered.connect(self.show_dashboard)
        self.pause_action = menu.addAction("기록 일시정지")
        self.pause_action.triggered.connect(self._toggle_pause)
        menu.addSeparator()
        quit_action = menu.addAction("종료")
        quit_action.triggered.connect(self.quit_app)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._tray_activated)
        self.tray.show()

    def _apply_style(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow, QWidget#page { background: #0b1020; }
            QWidget { color: #f3f6ff; font-family: 'Malgun Gothic'; font-size: 13px; }
            QLabel#title { font-size: 27px; font-weight: 700; }
            QLabel#sectionTitle { font-size: 15px; font-weight: 600; }
            QLabel#muted { color: #8f9bb3; }
            QLabel#cardValue { font-size: 21px; font-weight: 700; }
            QFrame#card, QFrame#panel { background: #151c2f; border: 1px solid #25304a; border-radius: 12px; }
            QPushButton, QComboBox, QLineEdit { background: #1b2540; border: 1px solid #33405e; border-radius: 8px; padding: 7px 11px; }
            QPushButton:hover, QComboBox:hover, QLineEdit:focus { background: #253150; }
            QPushButton#pauseButton { background: #263456; min-width: 110px; }
            QPushButton#addTodoButton { font-size: 18px; font-weight: 600; padding: 2px; }
            QPushButton#deleteTodoButton { font-size: 11px; padding: 3px 5px; }
            QPushButton#deleteTodoButton:disabled { color: #59657d; background: #151c2f; }
            QComboBox QLineEdit { background: transparent; border: 0; color: #f3f6ff; padding: 0 4px; }
            QComboBox QAbstractItemView { background: #151c2f; border: 1px solid #33405e; selection-background-color: #263456; padding: 4px; }
            QTableWidget { background: transparent; border: 0; gridline-color: #25304a; alternate-background-color: #11182a; }
            QHeaderView::section { background: #1b2540; color: #aab4c8; border: 0; border-bottom: 1px solid #33405e; padding: 7px; }
            QTableWidget::item { padding: 6px; border-bottom: 1px solid #202a42; }
            QTableWidget::item:selected { background: #31436d; color: #ffffff; }
            QListWidget { background: transparent; border: 0; outline: 0; }
            QListWidget::item { padding: 4px 2px; border-bottom: 1px solid #202a42; }
            QListWidget::item:hover { background: #1b2540; }
            QTableWidget QLineEdit, QListWidget QLineEdit {
                background: #0f1628;
                color: #ffffff;
                selection-background-color: #6d8cff;
                selection-color: #ffffff;
                border: 1px solid #6d8cff;
                border-radius: 3px;
                padding: 1px 4px;
            }
            QMessageBox { background-color: #151c2f; }
            QMessageBox QLabel {
                background: transparent;
                color: #f3f6ff;
                min-width: 300px;
                padding: 2px;
            }
            QMessageBox QPushButton {
                background: #263456;
                color: #f3f6ff;
                border: 1px solid #435478;
                border-radius: 7px;
                min-width: 70px;
                padding: 7px 12px;
            }
            QMessageBox QPushButton:hover { background: #33456f; }
            QAbstractScrollArea::corner { background: #151c2f; }
            QScrollBar:vertical { background: #0f1628; width: 11px; margin: 0; border: 0; }
            QScrollBar::handle:vertical { background: #3a496c; min-height: 28px; border-radius: 5px; }
            QScrollBar::handle:vertical:hover { background: #52648f; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
            QScrollBar:horizontal { background: #0f1628; height: 11px; margin: 0; border: 0; }
            QScrollBar::handle:horizontal { background: #3a496c; min-width: 28px; border-radius: 5px; }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
            QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: transparent; }
            QMenu { background: #151c2f; border: 1px solid #33405e; padding: 5px; }
            QMenu::item { padding: 7px 24px; border-radius: 5px; }
            QMenu::item:selected { background: #263456; }
            """
        )

    def _refresh_if_visible(self) -> None:
        if self.isVisible():
            self._refresh()

    def _refresh(self) -> None:
        # Include up to the latest 10 seconds of buffered activity.
        self.tracker.flush()
        self._refresh_todos()
        stats = get_day_stats(self.store, self.selected_day, self.idle_minutes)
        self._render_stats(stats)
        week_start = self.selected_day - timedelta(days=6)
        self.week_chart.set_values(get_daily_key_totals(self.store, week_start, 7))

    def _render_stats(self, stats: DayStats) -> None:
        today_suffix = " · 오늘" if stats.day == date.today() else ""
        self.day_label.setText(stats.day.strftime("%Y.%m.%d") + today_suffix)
        self.key_card.set_value(_format_number(stats.key_count))
        self.work_card.set_value(_format_duration(stats.estimated_work_seconds))
        self.session_card.set_value(f"{len(stats.sessions)}회")
        self.range_card.set_value(
            f"{_format_clock(stats.first_activity)} → {_format_clock(stats.last_activity)}"
        )
        if stats.busiest_hour is None:
            self.peak_label.setText("아직 기록 없음")
        else:
            self.peak_label.setText(f"피크 {stats.busiest_hour:02d}시")
        self.hourly_chart.set_values(stats.hourly_keys)

        notes = self.store.get_session_notes(
            session.start for session in stats.sessions
        )
        session_starts = [session.start for session in stats.sessions]
        if self._selected_session_start not in session_starts:
            self._selected_session_start = (
                session_starts[-1] if session_starts else None
            )
        self._loading_sessions = True
        try:
            self.session_table.setRowCount(len(stats.sessions))
            now = int(time.time())
            for row_index, session in enumerate(stats.sessions):
                ongoing = (
                    stats.day == date.today()
                    and row_index == len(stats.sessions) - 1
                    and now - session.end <= self.idle_minutes * 60
                )
                values = (
                    _format_clock(session.start),
                    "진행 중" if ongoing else _format_clock(session.end),
                    _format_duration(session.span_seconds),
                    _format_number(session.key_count),
                )
                for column, value in enumerate(values):
                    item = QTableWidgetItem(value)
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    if column == 2:
                        item.setToolTip(
                            f"실제 입력이 있던 시간: {session.active_minutes}분"
                        )
                    self.session_table.setItem(row_index, column, item)

                note_item = QTableWidgetItem(notes.get(session.start, ""))
                note_item.setData(Qt.ItemDataRole.UserRole, session.start)
                note_item.setToolTip(
                    "선택한 세션에는 Todo 체크 시 자동 추가 · 더블클릭해서 직접 수정"
                )
                self.session_table.setItem(row_index, 4, note_item)

            if self._selected_session_start is None:
                self.session_table.clearSelection()
            else:
                selected_row = session_starts.index(self._selected_session_start)
                self.session_table.selectRow(selected_row)
        finally:
            self._loading_sessions = False

    def _refresh_todos(self, force: bool = False) -> None:
        todos = self.store.list_todos()
        if not force and todos == self._todos:
            return
        self._todos = todos
        self._loading_todos = True
        try:
            self.todo_list.clear()
            for todo in todos:
                item = QListWidgetItem(todo.title)
                item.setData(Qt.ItemDataRole.UserRole, todo.id)
                item.setData(TODO_TITLE_ROLE, todo.title)
                item.setData(TODO_COMPLETED_ROLE, todo.completed)
                item.setFlags(
                    item.flags()
                    | Qt.ItemFlag.ItemIsUserCheckable
                    | Qt.ItemFlag.ItemIsEditable
                )
                item.setCheckState(
                    Qt.CheckState.Checked
                    if todo.completed
                    else Qt.CheckState.Unchecked
                )
                font = item.font()
                font.setStrikeOut(todo.completed)
                item.setFont(font)
                if todo.completed:
                    item.setForeground(COLORS["muted"])
                self.todo_list.addItem(item)
        finally:
            self._loading_todos = False
        active_count = sum(not todo.completed for todo in todos)
        self.todo_count_label.setText(f"{active_count}개")

    def _add_todo(self) -> None:
        title = self.todo_input.text().strip()
        if not title:
            return
        self.store.add_todo(title)
        self.todo_input.clear()
        self._refresh_todos(force=True)
        self._refresh()

    def _delete_selected_todo(self) -> None:
        item = self.todo_list.currentItem()
        if item is None:
            return
        todo_id = int(item.data(Qt.ItemDataRole.UserRole))
        title = item.text().strip()
        message_box = QMessageBox(self)
        message_box.setWindowTitle("Todo 삭제")
        message_box.setIcon(QMessageBox.Icon.Question)
        message_box.setText(f"'{title}'을 Todo 목록에서 삭제할까요?")
        message_box.setInformativeText("과거 업무 세션 기록은 유지됩니다.")
        delete_button = message_box.addButton(
            "삭제", QMessageBox.ButtonRole.DestructiveRole
        )
        cancel_button = message_box.addButton(
            "취소", QMessageBox.ButtonRole.RejectRole
        )
        message_box.setDefaultButton(cancel_button)
        message_box.setEscapeButton(cancel_button)
        message_box.exec()
        if message_box.clickedButton() is not delete_button:
            return
        self.store.delete_todo(todo_id)
        self._refresh_todos(force=True)
        self._refresh()
        self.todo_input.setFocus()

    def _todo_item_changed(self, item: QListWidgetItem) -> None:
        if self._loading_todos:
            return
        todo_id = int(item.data(Qt.ItemDataRole.UserRole))
        previous_title = str(item.data(TODO_TITLE_ROLE))
        previous_completed = bool(item.data(TODO_COMPLETED_ROLE))
        title = item.text().strip()
        if not title:
            self._loading_todos = True
            item.setText(previous_title)
            self._loading_todos = False
            return

        completed = item.checkState() == Qt.CheckState.Checked
        if title != previous_title:
            self.store.update_todo_title(todo_id, title)
        if completed != previous_completed:
            self.store.set_todo_completed(todo_id, completed)
            if completed:
                self._record_todo_in_target_session(title)
        self._refresh_todos(force=True)
        self._refresh()

    def _record_todo_in_target_session(self, title: str) -> None:
        session_start = self._selected_session_start
        if session_start is None:
            if self.tracker.mark_app_activity() is None:
                return
            self.tracker.flush()
            today_stats = get_day_stats(
                self.store, date.today(), self.idle_minutes
            )
            if not today_stats.sessions:
                return
            session_start = today_stats.sessions[-1].start
        self.store.append_session_note(session_start, title)

    def _session_selection_changed(self) -> None:
        if self._loading_sessions:
            return
        selected_rows = self.session_table.selectionModel().selectedRows()
        if not selected_rows:
            self._selected_session_start = None
            return
        note_item = self.session_table.item(selected_rows[0].row(), 4)
        if note_item is not None:
            session_start = note_item.data(Qt.ItemDataRole.UserRole)
            self._selected_session_start = (
                int(session_start) if session_start is not None else None
            )

    def _session_item_changed(self, item: QTableWidgetItem) -> None:
        if self._loading_sessions or item.column() != 4:
            return
        session_start = item.data(Qt.ItemDataRole.UserRole)
        if session_start is not None:
            self.store.set_session_note(int(session_start), item.text())

    def _move_day(self, offset: int) -> None:
        candidate = self.selected_day + timedelta(days=offset)
        if candidate <= date.today():
            self.selected_day = candidate
            self._refresh()

    def _go_today(self) -> None:
        self.selected_day = date.today()
        self._refresh()

    def _change_idle_minutes(self) -> None:
        self.idle_minutes = int(self.idle_combo.currentData())
        self.store.set_setting("idle_minutes", str(self.idle_minutes))
        self._refresh()

    def _toggle_pause(self) -> None:
        self.tracker.set_paused(not self.tracker.paused)
        if self.tracker.paused:
            self.pause_button.setText("기록 다시 시작")
            self.pause_action.setText("기록 다시 시작")
            self.tray.setToolTip("MyWorkLog · 기록 일시정지됨")
        else:
            self.pause_button.setText("기록 일시정지")
            self.pause_action.setText("기록 일시정지")
            self.tray.setToolTip("MyWorkLog · 활동 기록 중")

    def _toggle_autostart(self, enabled: bool) -> None:
        try:
            set_autostart_enabled(enabled)
        except OSError as exc:
            self.autostart_checkbox.blockSignals(True)
            self.autostart_checkbox.setChecked(not enabled)
            self.autostart_checkbox.blockSignals(False)
            QMessageBox.warning(
                self,
                "자동 실행 설정 실패",
                f"Windows 자동 실행 설정을 변경하지 못했습니다.\n\n{exc}",
            )

    def _tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.show_dashboard()

    def show_dashboard(self) -> None:
        self._go_today()
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._quitting:
            event.accept()
            return
        event.ignore()
        self.hide()
        if not self._tray_notice_shown:
            self.tray.showMessage(
                "MyWorkLog",
                "창을 닫아도 트레이에서 가볍게 기록하고 있어요.",
                QSystemTrayIcon.MessageIcon.Information,
                2500,
            )
            self._tray_notice_shown = True

    def quit_app(self) -> None:
        self._quitting = True
        self.refresh_timer.stop()
        self.tracker.stop()
        self.tray.hide()
        QApplication.instance().quit()
