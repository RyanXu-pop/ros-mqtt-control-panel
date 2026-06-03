"""
Shared theme tokens for RobotPanel V2.
"""

from PySide6.QtCore import Qt


DARK_COLORS = {
    "background_main": "#0b0f15",
    "background_panel": "#111821",
    "background_card": "#1a2230",
    "text_primary": "#f5f8fc",
    "text_secondary": "#c5ccd8",
    "text_muted": "#9ba6b5",
    "primary": "#1f7aff",
    "primary_hover": "#4094ff",
    "primary_disabled": "#203957",
    "success": "#30d158",
    "warning": "#ffbf2f",
    "error": "#ff453a",
    "border": "#3a4658",
    "border_focus": "#7db7ff",
}

LIGHT_COLORS = {
    "background_main": "#eef2f7",
    "background_panel": "#ffffff",
    "background_card": "#f3f6fb",
    "text_primary": "#17202b",
    "text_secondary": "#344054",
    "text_muted": "#5b6675",
    "primary": "#0a66d8",
    "primary_hover": "#0057bd",
    "primary_disabled": "#c9d8ee",
    "success": "#16833a",
    "warning": "#8f5b00",
    "error": "#c72e29",
    "border": "#c8d0dc",
    "border_focus": "#0a66d8",
}

COLORS = DARK_COLORS


def _resolve_palette(app, mode: str | None):
    selected = (mode or "auto").lower()
    if selected == "light":
        return LIGHT_COLORS
    if selected == "dark":
        return DARK_COLORS
    try:
        scheme = app.styleHints().colorScheme()
        if scheme == Qt.ColorScheme.Light:
            return LIGHT_COLORS
    except Exception:
        pass
    return DARK_COLORS


def _build_stylesheet(colors: dict) -> str:
    return f"""
QWidget {{
    background-color: {colors['background_main']};
    color: {colors['text_primary']};
    font-family: 'SF Pro Display', 'Segoe UI', 'Microsoft YaHei', 'PingFang SC', sans-serif;
    font-size: 13px;
}}

.CardWidget, .PanelWidget {{
    background-color: {colors['background_panel']};
    border-radius: 10px;
    border: 1px solid {colors['border']};
}}

QLabel {{
    color: {colors['text_primary']};
    background-color: transparent;
}}

QPushButton {{
    background-color: {colors['background_card']};
    color: {colors['text_primary']};
    border: 1px solid {colors['border']};
    border-radius: 8px;
    padding: 8px 14px;
    font-weight: 800;
}}
QPushButton:hover {{
    background-color: {colors['border']};
}}
QPushButton:pressed {{
    background-color: {colors['background_panel']};
}}
QPushButton:disabled {{
    color: {colors['text_muted']};
    border-color: {colors['background_card']};
    background-color: rgba(100, 112, 130, 45);
}}

QPushButton.PrimaryAction {{
    background-color: {colors['primary']};
    color: white;
    border: none;
}}
QPushButton.PrimaryAction:hover {{
    background-color: {colors['primary_hover']};
}}
QPushButton.PrimaryAction:disabled {{
    background-color: {colors['primary_disabled']};
    color: {colors['text_secondary']};
}}

QPushButton.DangerAction {{
    background-color: {colors['error']};
    color: white;
    border: none;
}}
QPushButton.DangerAction:hover {{
    background-color: #ff6961;
}}

QPushButton.DisabledAction {{
    background-color: rgba(100, 112, 130, 45);
    color: {colors['text_secondary']};
    border: 1px solid {colors['border']};
}}

QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 0px;
}}
QScrollBar::handle:vertical {{
    background: {colors['border']};
    min-height: 24px;
    border-radius: 5px;
}}
QScrollBar::handle:vertical:hover {{
    background: {colors['text_muted']};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}

QGraphicsView {{
    background-color: {colors['background_main']};
    border: none;
}}

QLineEdit, QSpinBox, QComboBox {{
    background-color: {colors['background_card']};
    border: 1px solid {colors['border']};
    border-radius: 6px;
    padding: 6px;
    color: {colors['text_primary']};
}}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{
    border: 1px solid {colors['border_focus']};
}}

QTabWidget::pane {{
    border: 1px solid {colors['border']};
    border-radius: 8px;
}}
QTabBar::tab {{
    background: {colors['background_card']};
    color: {colors['text_secondary']};
    padding: 8px 12px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
}}
QTabBar::tab:selected {{
    color: white;
    background: {colors['primary']};
}}
"""


def apply_theme(app, mode: str | None = "auto") -> None:
    if app is None:
        return
    global COLORS
    COLORS = _resolve_palette(app, mode)
    app.setStyleSheet(_build_stylesheet(COLORS))
