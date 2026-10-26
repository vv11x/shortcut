"""
shortcut 统一主题与视觉系统 (Theme & Design System)
提供“轻二次元品牌感 + 简洁桌面效率工具”的透明玻璃质感 (Translucent Glassmorphism) 调色板与 QSS 样式。
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ThemeTokens:
    theme_name: str
    is_dark: bool

    # 背景与面板
    dock_bg: str
    panel_bg: str
    card_bg: str
    field_bg: str
    menu_bg: str
    tooltip_bg: str

    # 表面状态
    surface_hover: str
    surface_active: str
    surface_pressed: str

    # 边框与阴影
    border: str
    border_subtle: str
    border_focus: str
    drop_active_border: str

    # 文字层级
    text_primary: str
    text_secondary: str
    text_muted: str

    # 品牌强调色 (星云蓝紫 / Moe Periwinkle)
    accent: str
    accent_hover: str
    accent_pressed: str
    accent_subtle: str
    accent_text: str

    # 胶囊角标与状态
    badge_bg: str
    badge_text: str
    danger: str
    danger_hover: str

    # 滚动条
    scrollbar_handle: str
    scrollbar_hover: str


DARK_TOKENS = ThemeTokens(
    theme_name="dark",
    is_dark=True,
    dock_bg="rgba(20, 24, 34, 0.88)",
    panel_bg="rgba(24, 28, 40, 0.92)",
    card_bg="rgba(32, 38, 54, 0.72)",
    field_bg="rgba(30, 36, 50, 0.80)",
    menu_bg="rgba(24, 28, 40, 0.94)",
    tooltip_bg="rgba(28, 34, 48, 0.95)",
    surface_hover="rgba(50, 60, 84, 0.65)",
    surface_active="rgba(91, 124, 246, 0.22)",
    surface_pressed="rgba(91, 124, 246, 0.32)",
    border="rgba(255, 255, 255, 0.16)",
    border_subtle="rgba(255, 255, 255, 0.08)",
    border_focus="#5b7cf6",
    drop_active_border="#708df8",
    text_primary="#f4f6fb",
    text_secondary="#9ca3af",
    text_muted="#6b7280",
    accent="#5b7cf6",
    accent_hover="#708df8",
    accent_pressed="#4361ee",
    accent_subtle="rgba(91, 124, 246, 0.18)",
    accent_text="#ffffff",
    badge_bg="rgba(91, 124, 246, 0.88)",
    badge_text="#ffffff",
    danger="#ef4444",
    danger_hover="#dc2626",
    scrollbar_handle="rgba(255, 255, 255, 0.18)",
    scrollbar_hover="rgba(91, 124, 246, 0.65)",
)

LIGHT_TOKENS = ThemeTokens(
    theme_name="light",
    is_dark=False,
    dock_bg="rgba(246, 248, 253, 0.90)",
    panel_bg="rgba(255, 255, 255, 0.94)",
    card_bg="rgba(242, 245, 252, 0.80)",
    field_bg="rgba(236, 240, 249, 0.85)",
    menu_bg="rgba(255, 255, 255, 0.96)",
    tooltip_bg="rgba(248, 250, 255, 0.96)",
    surface_hover="rgba(224, 232, 248, 0.70)",
    surface_active="rgba(91, 124, 246, 0.14)",
    surface_pressed="rgba(91, 124, 246, 0.24)",
    border="rgba(99, 102, 241, 0.20)",
    border_subtle="rgba(0, 0, 0, 0.08)",
    border_focus="#5b7cf6",
    drop_active_border="#5b7cf6",
    text_primary="#1e2432",
    text_secondary="#525d73",
    text_muted="#8c97aa",
    accent="#5b7cf6",
    accent_hover="#4f70e8",
    accent_pressed="#3b59d0",
    accent_subtle="rgba(91, 124, 246, 0.12)",
    accent_text="#ffffff",
    badge_bg="rgba(91, 124, 246, 0.90)",
    badge_text="#ffffff",
    danger="#ef4444",
    danger_hover="#dc2626",
    scrollbar_handle="rgba(0, 0, 0, 0.18)",
    scrollbar_hover="rgba(91, 124, 246, 0.65)",
)


def get_tokens(theme: str) -> ThemeTokens:
    if theme == "dark":
        return DARK_TOKENS
    elif theme == "light":
        return LIGHT_TOKENS
    raise ValueError(f"Unsupported theme: {theme}")


def get_dock_qss(theme: str, edge: str = "bottom") -> str:
    t = get_tokens(theme)
    # 悬浮栏背景与各控件
    return f"""
    QWidget#dock {{
        background: {t.dock_bg};
        color: {t.text_primary};
        border: 1.5px solid {t.border};
        border-radius: 22px;
    }}
    QToolButton {{
        font-family: "Segoe UI", "Microsoft YaHei UI", "Microsoft YaHei", "PingFang SC", sans-serif;
        color: {t.text_primary};
        background: transparent;
        border: 1px solid transparent;
        border-radius: 14px;
        padding: 6px 4px;
        font-size: 13.5px;
        font-weight: 600;
    }}
    QToolButton:hover {{
        background: {t.surface_hover};
        border: 1px solid {t.border_subtle};
    }}
    QToolButton:pressed {{
        background: {t.surface_pressed};
        border: 1px solid {t.border_focus};
    }}
    QToolButton[drag_active="true"] {{
        background: {t.surface_active};
        border: 1.5px dashed {t.drop_active_border};
    }}
    QLineEdit#search_box {{
        font-family: "Segoe UI", "Microsoft YaHei UI", "Microsoft YaHei", "PingFang SC", sans-serif;
        color: {t.text_primary};
        background: {t.field_bg};
        border: 1px solid {t.border_subtle};
        border-radius: 12px;
        padding: 7px 14px;
        font-size: 13.5px;
        min-width: 130px;
        min-height: 28px;
    }}
    QLineEdit#search_box:hover {{
        border: 1px solid {t.border};
    }}
    QLineEdit#search_box:focus {{
        border: 1.5px solid {t.border_focus};
        background: {t.dock_bg};
    }}
    QPushButton {{
        font-family: "Segoe UI", "Microsoft YaHei UI", "Microsoft YaHei", "PingFang SC", sans-serif;
        color: {t.text_primary};
        background: {t.card_bg};
        border: 1px solid {t.border_subtle};
        border-radius: 10px;
        padding: 6px 13px;
        font-size: 13px;
        font-weight: 500;
        min-height: 28px;
    }}
    QPushButton:hover {{
        background: {t.surface_hover};
        border: 1px solid {t.border};
    }}
    QPushButton:pressed {{
        background: {t.surface_pressed};
        border: 1px solid {t.border_focus};
    }}
    QPushButton#add_button {{
        font-size: 16px;
        font-weight: 700;
        padding: 6px 12px;
    }}
    """


def get_panel_qss(theme: str) -> str:
    t = get_tokens(theme)
    return f"""
    QWidget#entry_panel {{
        color: {t.text_primary};
        background: {t.panel_bg};
        border: 1px solid {t.border};
        border-radius: 14px;
    }}
    QLabel#panel_title {{
        color: {t.text_primary};
        font-size: 15px;
        font-weight: 600;
    }}
    QLabel#count_badge {{
        color: {t.badge_text};
        background: {t.badge_bg};
        border-radius: 9px;
        padding: 1px 7px;
        font-size: 11px;
        font-weight: 600;
    }}
    QPushButton#panel_close_button {{
        color: {t.text_secondary};
        background: transparent;
        border: 0;
        border-radius: 12px;
        font-size: 16px;
        font-weight: 500;
    }}
    QPushButton#panel_close_button:hover {{
        background: {t.danger};
        color: #ffffff;
    }}
    QLabel#empty_hint {{
        color: {t.text_muted};
        font-size: 13px;
        padding: 24px;
        background: {t.card_bg};
        border: 1.5px dashed {t.border};
        border-radius: 10px;
    }}
    QListWidget {{
        border: 0;
        background: transparent;
        outline: none;
    }}
    QListWidget[drag_active="true"] {{
        background: {t.accent_subtle};
        border: 1.5px dashed {t.drop_active_border};
        border-radius: 8px;
    }}
    QListWidget::item {{
        color: {t.text_primary};
        border: 1px solid transparent;
        border-radius: 8px;
        padding: 5px;
        font-size: 12px;
    }}
    QListWidget::item:hover {{
        background: {t.surface_hover};
        border: 1px solid {t.border_subtle};
    }}
    QListWidget::item:selected {{
        background: {t.surface_active};
        border: 1px solid {t.border_focus};
        color: {t.text_primary};
    }}
    QScrollBar:vertical {{
        background: transparent;
        width: 6px;
        margin: 4px 1px 4px 1px;
    }}
    QScrollBar::handle:vertical {{
        background: {t.scrollbar_handle};
        border-radius: 3px;
        min-height: 24px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: {t.scrollbar_hover};
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
        background: none;
        border: none;
    }}
    """


def get_search_popup_qss(theme: str) -> str:
    t = get_tokens(theme)
    return f"""
    QWidget#search_popup {{
        background: {t.panel_bg};
        color: {t.text_primary};
        border: 1px solid {t.border};
        border-radius: 12px;
    }}
    QListWidget {{
        border: 0;
        background: transparent;
        outline: none;
    }}
    QListWidget::item {{
        color: {t.text_primary};
        min-height: 38px;
        padding: 6px 10px;
        border: 1px solid transparent;
        border-radius: 8px;
        margin-bottom: 2px;
    }}
    QListWidget::item:hover {{
        background: {t.surface_hover};
        border: 1px solid {t.border_subtle};
    }}
    QListWidget::item:selected {{
        background: {t.surface_active};
        border: 1px solid {t.border_focus};
        color: {t.text_primary};
    }}
    QLabel#search_empty_hint {{
        color: {t.text_muted};
        font-size: 13px;
        padding: 24px;
        text-align: center;
    }}
    QScrollBar:vertical {{
        background: transparent;
        width: 6px;
        margin: 4px 1px;
    }}
    QScrollBar::handle:vertical {{
        background: {t.scrollbar_handle};
        border-radius: 3px;
        min-height: 20px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: {t.scrollbar_hover};
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
        background: none;
        border: none;
    }}
    """


def get_settings_qss(theme: str) -> str:
    t = get_tokens(theme)
    return f"""
    QDialog#settings_dialog {{
        background: {t.panel_bg};
        color: {t.text_primary};
    }}
    QWidget#brand_header {{
        background: {t.card_bg};
        border: 1px solid {t.border};
        border-radius: 10px;
    }}
    QLabel#brand_title {{
        color: {t.text_primary};
        font-size: 16px;
        font-weight: 700;
    }}
    QLabel#brand_subtitle {{
        color: {t.text_secondary};
        font-size: 12px;
    }}
    QGroupBox {{
        font-size: 13px;
        font-weight: 600;
        color: {t.accent};
        background: {t.card_bg};
        border: 1px solid {t.border};
        border-radius: 10px;
        margin-top: 14px;
        padding-top: 14px;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        subcontrol-position: top left;
        left: 14px;
        padding: 0 6px;
        background: transparent;
    }}
    QLabel {{
        color: {t.text_primary};
        font-size: 12px;
    }}
    QLabel#form_tip {{
        color: {t.text_muted};
        font-size: 11px;
        padding-top: 4px;
    }}
    QLineEdit, QComboBox, QListWidget {{
        color: {t.text_primary};
        background: {t.field_bg};
        border: 1px solid {t.border_subtle};
        border-radius: 7px;
        padding: 6px 9px;
        font-size: 12px;
    }}
    QLineEdit:hover, QComboBox:hover {{
        border: 1px solid {t.border};
    }}
    QLineEdit:focus, QComboBox:focus {{
        border: 1.5px solid {t.border_focus};
    }}
    QComboBox::drop-down {{
        border: 0;
        width: 20px;
    }}
    QComboBox QAbstractItemView {{
        color: {t.text_primary};
        background: {t.menu_bg};
        border: 1px solid {t.border};
        border-radius: 6px;
        selection-background-color: {t.surface_active};
        selection-color: {t.text_primary};
        outline: none;
        padding: 4px;
    }}
    QListWidget::item {{
        min-height: 26px;
        padding: 3px 6px;
        border-radius: 5px;
    }}
    QListWidget::item:hover {{
        background: {t.surface_hover};
    }}
    QListWidget::item:selected {{
        background: {t.surface_active};
        color: {t.text_primary};
        border: 1px solid {t.border_focus};
    }}
    QPushButton {{
        color: {t.text_primary};
        background: {t.card_bg};
        border: 1px solid {t.border};
        border-radius: 7px;
        padding: 6px 14px;
        font-size: 12px;
        font-weight: 500;
    }}
    QPushButton:hover {{
        background: {t.surface_hover};
        border: 1px solid {t.border_focus};
    }}
    QPushButton:pressed {{
        background: {t.surface_pressed};
    }}
    QPushButton#primary_button {{
        color: #ffffff;
        background: {t.accent};
        border: 1px solid transparent;
        font-weight: 600;
    }}
    QPushButton#primary_button:hover {{
        background: {t.accent_hover};
    }}
    QPushButton#primary_button:pressed {{
        background: {t.accent_pressed};
    }}
    QScrollBar:vertical {{
        background: transparent;
        width: 6px;
        margin: 2px 1px;
    }}
    QScrollBar::handle:vertical {{
        background: {t.scrollbar_handle};
        border-radius: 3px;
        min-height: 18px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: {t.scrollbar_hover};
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
        background: none;
        border: none;
    }}
    """


def get_menu_qss(theme: str) -> str:
    t = get_tokens(theme)
    return f"""
    QMenu {{
        background: {t.menu_bg};
        color: {t.text_primary};
        border: 1px solid {t.border};
        border-radius: 10px;
        padding: 6px 4px;
        font-size: 12px;
    }}
    QMenu::item {{
        padding: 6px 24px 6px 12px;
        border-radius: 6px;
        margin: 1px 4px;
        background: transparent;
    }}
    QMenu::item:selected {{
        background: {t.surface_active};
        color: {t.text_primary};
    }}
    QMenu::item:disabled {{
        color: {t.text_muted};
    }}
    QMenu::separator {{
        height: 1px;
        background: {t.border_subtle};
        margin: 4px 6px;
    }}
    QMenu::indicator {{
        width: 14px;
        height: 14px;
        margin-left: 6px;
    }}
    """


def get_tooltip_qss(theme: str) -> str:
    t = get_tokens(theme)
    return f"""
    QToolTip {{
        background: {t.tooltip_bg};
        color: {t.text_primary};
        border: 1px solid {t.border};
        border-radius: 6px;
        padding: 5px 8px;
        font-size: 12px;
    }}
    """
