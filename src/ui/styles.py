"""
Modern glassmorphism dark QSS styles for Bomzh Assistant HUD.
"""

HUD_STYLESHEET = """
QWidget#centralWidget {
    background-color: rgba(20, 22, 32, 0.94);
    border: 1px solid rgba(255, 255, 255, 0.12);
    border-radius: 16px;
}

QLabel#titleLabel {
    color: #FFFFFF;
    font-size: 15px;
    font-weight: 700;
    font-family: 'Segoe UI', sans-serif;
}

QLabel#statusBadge {
    color: #94A3B8;
    font-size: 11px;
    font-weight: 600;
    font-family: 'Segoe UI', sans-serif;
    padding: 2px 8px;
    border-radius: 10px;
    background-color: rgba(255, 255, 255, 0.06);
}

QPushButton#modelChip {
    background-color: rgba(99, 102, 241, 0.2);
    color: #818CF8;
    border: 1px solid rgba(129, 140, 248, 0.35);
    border-radius: 12px;
    padding: 3px 10px;
    font-size: 11px;
    font-weight: 600;
    font-family: 'Segoe UI', sans-serif;
}
QPushButton#modelChip:hover {
    background-color: rgba(99, 102, 241, 0.35);
    color: #A5B4FC;
    border: 1px solid rgba(165, 180, 252, 0.6);
}

QPushButton#iconButton {
    background-color: rgba(255, 255, 255, 0.05);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 8px;
    color: #94A3B8;
    font-size: 12px;
    padding: 4px 8px;
}
QPushButton#iconButton:hover {
    background-color: rgba(255, 255, 255, 0.15);
    color: #FFFFFF;
}

QPushButton#stopButton {
    background-color: rgba(239, 68, 68, 0.16);
    border: 1px solid rgba(239, 68, 68, 0.45);
    border-radius: 8px;
    color: #F87171;
    font-size: 12px;
    padding: 4px 8px;
}
QPushButton#stopButton:hover {
    background-color: rgba(239, 68, 68, 0.35);
    border: 1px solid rgba(248, 113, 113, 0.8);
    color: #FFFFFF;
}

QLineEdit#promptInput {
    background-color: rgba(30, 32, 46, 0.85);
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 10px;
    color: #F8FAFC;
    font-size: 13px;
    font-family: 'Segoe UI', sans-serif;
    padding: 8px 12px;
    selection-background-color: #6366F1;
}
QLineEdit#promptInput:focus {
    border: 1px solid #818CF8;
    background-color: rgba(30, 32, 46, 0.98);
}

QLabel#activityBanner {
    background-color: rgba(99, 102, 241, 0.16);
    border: 1px solid rgba(129, 140, 248, 0.45);
    border-radius: 8px;
    color: #A5B4FC;
    font-size: 11px;
    font-weight: 600;
    font-family: 'Consolas', 'Segoe UI', monospace;
    padding: 6px 10px;
}

QTextBrowser#responseBrowser {
    background-color: transparent;
    border: none;
    color: #E2E8F0;
    font-size: 13px;
    font-family: 'Segoe UI', sans-serif;
    line-height: 1.5;
    selection-background-color: #4F46E5;
}

/* Custom Scrollbar */
QScrollBar:vertical {
    border: none;
    background: transparent;
    width: 6px;
    margin: 4px 0 4px 0;
}
QScrollBar::handle:vertical {
    background: rgba(255, 255, 255, 0.18);
    border-radius: 3px;
    min-height: 20px;
}
QScrollBar::handle:vertical:hover {
    background: rgba(255, 255, 255, 0.35);
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}
"""
