"""
Configuration constants for pecha_text_image_generator.py
"""

FONTS_WUJIN_GANGBI = "pecha_api/share/static/fonts/wujin+gangbi.ttf"
FONTS_NOTO_EN = "pecha_api/share/static/fonts/Noto-font/NotoFont-en.ttf"
IMG_OUTPUT_PATH = "pecha_api/share/static/img/output.png"
IMG_LOGO_PATH = "pecha_api/share/static/img/pecha-logo.png"

CONFIG = {
    # Font Paths and Sizes
    "FONTS_WUJIN_GANGBI": FONTS_WUJIN_GANGBI,
    "FONTS_NOTO_EN": FONTS_NOTO_EN,
    "FONT_PATHS": {
        "bo": FONTS_WUJIN_GANGBI,
        "en": FONTS_NOTO_EN,
        "FALL_BACK": FONTS_NOTO_EN
    },
    "FONT_SIZE": {
        "bo": 25,
        "en": 22,
        "FALL_BACK": 22
    },
    # Colors
    "COLOR_WHITE": (255, 255, 255),
    "COLOR_BLACK": (0, 0, 0),
    "COLOR_GRAY_BORDER": (102, 102, 102),
    "COLOR_GRAY_SEPARATOR": (204, 204, 204),
    "TEXT_COLOR": {
        "DEFAULT": (255, 255, 255),
        "black": (0, 0, 0),
    },
    "BG_COLOR": {
        "DEFAULT": "#ff0000",
        "red": "#ff0000",
        "yellow": "#deac2c",
        "black": "#000000"
    },
    # String Literals
    "HTML_PARSER": "html.parser",
    "HTML_TAG_BR": "br",
    "HTML_NEWLINE": "\n",
    "ELLIPSIS": "...",
    "ENCODING_UTF16": "utf-16",
    "ANCHOR_MIDDLE": "mm",
    "ALIGN_CENTER": "center",
    "RGBA_MODE": "RGBA",
    # File Paths
    "IMG_OUTPUT_PATH": IMG_OUTPUT_PATH,
    "IMG_LOGO_PATH": IMG_LOGO_PATH,
    # Layout
    "IMAGE_WIDTH": 700,
    "IMAGE_HEIGHT": 400,
    "FALLBACK_IMAGE_WIDTH": 1200,
    "FALLBACK_IMAGE_HEIGHT": 630,
    "PADDING_X": 5,
    "HEADER_RATIO": 0.05,
    "HEADER_LINE_WIDTH_RATIO": 0.1,
    "HEADER_SEPARATOR_RATIO": 0.0025,
    "LOGO_HEIGHT_RATIO": 0.06,
    "FALLBACK_HEADER_RATIO": 0.5,
    "FALLBACK_LOGO_HEIGHT_RATIO": 0.3,
    "REF_TEXT_Y_OFFSET": 40,
    # Default font size
    "DEFAULT_FONT_SIZE": 24,
    # Default language code
    "DEFAULT_LANG": "en",
    # Typical character for width estimation
    "TYPICAL_CHAR": "བ",
    # Hex color parsing indices
    "HEX_COLOR_INDICES": (0, 2, 4),
    # RGBA transparent color
    "RGBA_TRANSPARENT": (0, 0, 0, 0),
} 