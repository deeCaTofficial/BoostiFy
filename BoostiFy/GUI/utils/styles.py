# styles.py — все стили и константы для BoostiFy GUI

BG_COLOR = "#1a2028"
ELEMENT_BG_COLOR = "#2b3541"
TEXT_COLOR = "#dcdedf"
ACTIVE_COLOR = "#1A9AF3"
# Qt Style Sheets do not reliably parse a CSS-like family list wrapped in quotes.
# Segoe UI ships with supported Windows versions and includes full Cyrillic coverage.
FONT_FAMILY = "Segoe UI"
FONT_SIZE = 20
BORDER_RADIUS = 10

BUTTON_STYLE = f"""
    QPushButton {{
        color: {TEXT_COLOR};
        font-family: '{FONT_FAMILY}';
        font-size: {FONT_SIZE}px;
        font-weight: 400;
        background-color: {ELEMENT_BG_COLOR};
        border: none;
        border-radius: {BORDER_RADIUS}px;
    }}
    QPushButton:hover {{
        color: #1A9AF3;
        background-color: {ELEMENT_BG_COLOR};
    }}
    QPushButton:pressed {{
        color: {TEXT_COLOR};
        background-color: #1A9AF3;
    }}
"""

NAV_BUTTON_STYLE = BUTTON_STYLE + f"""
    QPushButton:checked {{
        color: white;
        background-color: {ACTIVE_COLOR};
        font-weight: 600;
    }}
"""

LABEL_STYLE = f"""
    color: {TEXT_COLOR};
    font-family: '{FONT_FAMILY}';
    font-size: {FONT_SIZE}px;
    font-weight: 400;
    background-color: transparent;
"""

LABEL_AS_BUTTON_STYLE = f"""
    color: {TEXT_COLOR};
    font-family: '{FONT_FAMILY}';
    font-size: {FONT_SIZE}px;
    font-weight: 400;
    qproperty-alignment: 'AlignCenter';
    background-color: {ELEMENT_BG_COLOR};
    border: none;
    border-radius: {BORDER_RADIUS}px;
"""

TOGGLE_BUTTON_STYLE = f"""
    QPushButton {{
        color: {TEXT_COLOR};
        font-family: '{FONT_FAMILY}';
        font-size: {FONT_SIZE}px;
        font-weight: 400;
        background-color: {ELEMENT_BG_COLOR};
        border: none;
        border-radius: {BORDER_RADIUS}px;
    }}
    QPushButton:checked {{
        background-color: {ACTIVE_COLOR};
    }}
"""
