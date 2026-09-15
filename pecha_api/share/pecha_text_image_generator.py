import logging
import textwrap
from typing import BinaryIO, Union
from PIL import Image, ImageDraw, ImageFont
from bs4 import BeautifulSoup
from pecha_api.share.pecha_text_image_generator_config import CONFIG

# A render destination: either a filesystem path or an open binary buffer.
ImageDestination = Union[str, BinaryIO]
IMAGE_FORMAT = "PNG"

class SyntheticImageGenerator:
    def __init__(
        self,
        image_width: int,
        image_height: int,
        font_size: int = CONFIG["DEFAULT_FONT_SIZE"],
        font_type: str = None,
        bg_color: str = None
    ) -> None:
        self.image_width = int(image_width)
        self.image_height = int(image_height)
        self.font_size = int(font_size)
        self.font_type = font_type or CONFIG["DEFAULT_LANG"]
        self.bg_color = self._parse_hex_color(bg_color or CONFIG["BG_COLOR"]["DEFAULT"])

    def _parse_hex_color(self, hex_color: str) -> tuple:
        """Parse a hex color string (e.g., '#ff0000') to an RGB tuple using config indices."""
        hex_color = hex_color.lstrip('#')
        return tuple(int(hex_color[i:i+2], 16) for i in CONFIG["HEX_COLOR_INDICES"])

    def calc_letters_per_line(self, font: ImageFont.FreeTypeFont, max_width: int) -> int:
        """Calculate approximately how many characters can fit in the given width."""
        avg_char_width = font.getlength(CONFIG["TYPICAL_CHAR"])
        return int(max_width / avg_char_width)

    def add_borders(self, draw: ImageDraw.ImageDraw) -> None:
        """Add borders to the image."""
        draw.line((0, 0, self.image_width, 0), fill=CONFIG["COLOR_GRAY_BORDER"], width=1)  # Top
        draw.line((0, 0, 0, self.image_height), fill=CONFIG["COLOR_GRAY_BORDER"], width=1)  # Left
        draw.line((self.image_width-1, 0, self.image_width-1, self.image_height), fill=CONFIG["COLOR_GRAY_BORDER"], width=1)  # Right
        draw.line((0, self.image_height-1, self.image_width, self.image_height-1), fill=CONFIG["COLOR_GRAY_BORDER"], width=1)  # Bottom

    def add_header(self, draw: ImageDraw.ImageDraw) -> None:
        """Add white header section."""
        header_height = int(self.image_height * CONFIG["HEADER_RATIO"])
        # White header background
        draw.line(
            (0, header_height, self.image_width, header_height),
            fill=CONFIG["COLOR_WHITE"],
            width=int(self.image_height * CONFIG["HEADER_LINE_WIDTH_RATIO"])
        )
        # Gray separator line
        draw.line(
            (0, header_height * 2, self.image_width, header_height * 2),
            fill=CONFIG["COLOR_GRAY_SEPARATOR"],
            width=int(self.image_height * CONFIG["HEADER_SEPARATOR_RATIO"])
        )

    def _draw_text_and_reference(
        self,
        draw: ImageDraw.ImageDraw,
        main_text: str,
        ref_text: str,
        main_font: ImageFont.FreeTypeFont,
        ref_font: ImageFont.FreeTypeFont,
        text_color: tuple,
        main_font_size: int
    ) -> None:
        draw.text(
            xy=(self.image_width / 2, self.image_height / 2),
            text=main_text,
            font=main_font,
            fill=text_color,
            anchor=CONFIG["ANCHOR_MIDDLE"],
            align=CONFIG["ALIGN_CENTER"],
            spacing=int(main_font_size * 0.5)
        )
        draw.text(
            xy=(self.image_width / 2, self.image_height - CONFIG["REF_TEXT_Y_OFFSET"]),
            text=ref_text,
            font=ref_font,
            fill=text_color,
            anchor=CONFIG["ANCHOR_MIDDLE"]
        )

    def save_image(
        self,
        text: str,
        ref_str: str,
        img_file_name: ImageDestination = None,
        text_color: str = None,
        logo_path: str = None
    ) -> None:
        """
        Generate and save a synthetic image with the given text, reference, and options.
        """
        font_file_name = CONFIG["FONT_PATHS"].get(self.font_type, CONFIG["FONT_PATHS"]["FALL_BACK"])
        # Define fonts and text color
        if len(text) < 100:
            main_font_size = int(self.font_size * 1.5)
        else:
            main_font_size = self.font_size
        main_font = ImageFont.truetype(font_file_name, size=main_font_size, encoding=CONFIG["ENCODING_UTF16"])
        ref_font = ImageFont.truetype(font_file_name, size=int(main_font_size/2), encoding=CONFIG["ENCODING_UTF16"])
        text_color_tuple = CONFIG["TEXT_COLOR"].get(text_color, CONFIG["TEXT_COLOR"]["DEFAULT"])
        # Calculate padding and max width
        max_width = self.image_width - (CONFIG["PADDING_X"] * 2)
        # Wrap text using textwrap
        chars_per_line = self.calc_letters_per_line(main_font, max_width)
        wrapped_text = textwrap.fill(text=text, width=chars_per_line)
        # Draw main text
        img = Image.new(CONFIG["RGBA_MODE"], (self.image_width, self.image_height), color=self.bg_color + (255,))
        draw = ImageDraw.Draw(img)
        self.add_header(draw)
        self.add_borders(draw)
        self._draw_text_and_reference(
            draw=draw,
            main_text=wrapped_text,
            ref_text=ref_str,
            main_font=main_font,
            ref_font=ref_font,
            text_color=text_color_tuple,
            main_font_size=main_font_size
        )
        # Add logo if provided
        if logo_path:
            img = _add_logo_to_image(img, logo_path, self.image_width, self.image_height)
        # Save the image
        destination = img_file_name if img_file_name is not None else CONFIG["IMG_OUTPUT_PATH"]
        img.save(destination, format=IMAGE_FORMAT)

def create_synthetic_data(
    text: str,
    ref_str: str,
    lang: str,
    bg_color: str,
    text_color: str = None,
    logo_path: str = None,
    output_path: ImageDestination = None
) -> None:
    """
    Generate a synthetic image from text and reference string, saving to output_path.
    """
    cleaned_text = _clean_text(text)
    font_type_lang = lang
    generator = SyntheticImageGenerator(
        image_width=CONFIG["IMAGE_WIDTH"],
        image_height=CONFIG["IMAGE_HEIGHT"],
        font_size=CONFIG["FONT_SIZE"].get(font_type_lang, CONFIG["FONT_SIZE"]["FALL_BACK"]),
        font_type=font_type_lang,
        bg_color=CONFIG["BG_COLOR"].get(bg_color, CONFIG["BG_COLOR"]["DEFAULT"])
    )
    destination = output_path if output_path is not None else CONFIG["IMG_OUTPUT_PATH"]
    generator.save_image(cleaned_text, ref_str, img_file_name=destination, text_color=text_color, logo_path=logo_path)

def generate_segment_image(
    text: str = None,
    ref_str: str = None,
    lang: str = None,
    bg_color: str = None,
    text_color: str = None,
    logo_path: str = None,
    output_path: ImageDestination = None
) -> None:
    """
    Main entry to generate a text image or fallback logo image.
    """
    if text is not None and text != "":
        create_synthetic_data(
            text=text,
            ref_str=ref_str,
            lang=lang,
            bg_color=bg_color,
            text_color=text_color,
            logo_path=logo_path,
            output_path=output_path
        )
    else:
        img = Image.new(
            CONFIG["RGBA_MODE"], 
            (CONFIG["FALLBACK_IMAGE_WIDTH"], CONFIG["FALLBACK_IMAGE_HEIGHT"]), 
            color=CONFIG["BG_COLOR"].get(bg_color, CONFIG["BG_COLOR"]["DEFAULT"])
        )
        try:
            img = _add_logo_to_image(
                img,
                CONFIG["IMG_LOGO_PATH"],
                CONFIG["FALLBACK_IMAGE_WIDTH"],
                CONFIG["FALLBACK_IMAGE_HEIGHT"],
                header_ratio=CONFIG["FALLBACK_HEADER_RATIO"],
                logo_height_ratio=CONFIG["FALLBACK_LOGO_HEIGHT_RATIO"]
            )
        except (OSError, ValueError) as e:
            logging.warning(f"Error adding fallback logo: {e}")
        destination = output_path if output_path is not None else CONFIG["IMG_OUTPUT_PATH"]
        img.save(destination, format=IMAGE_FORMAT)

def _clean_text(content: str, max_lines: int = 4) -> str:
    """
    Clean HTML content to plain text, limit to max_lines, add ellipsis if truncated.
    """
    soup = BeautifulSoup(content, CONFIG["HTML_PARSER"])
    for br in soup.find_all(CONFIG["HTML_TAG_BR"]):
        br.replace_with(CONFIG["HTML_NEWLINE"])
    for tag in soup.find_all():
        tag.decompose()
    text = soup.get_text()
    lines = text.strip().splitlines()
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines.append(CONFIG["ELLIPSIS"])
    return CONFIG["HTML_NEWLINE"].join(lines)

def _add_logo_to_image(
    img: Image.Image,
    logo_path: str,
    image_width: int,
    image_height: int,
    header_ratio: float = None,
    logo_height_ratio: float = None
) -> Image.Image:
    """
    Add a centered logo to an RGBA image, returns composited image.
    """
    try:
        logo = Image.open(logo_path).convert('RGBA')
        logo_height = int(image_height * (logo_height_ratio or CONFIG["LOGO_HEIGHT_RATIO"]))
        logo_ratio = logo.size[0] / logo.size[1]
        logo_width = int(logo_height * logo_ratio)
        logo = logo.resize((logo_width, logo_height), Image.Resampling.LANCZOS)
        logo_padded = Image.new('RGBA', (image_width, image_height), CONFIG["RGBA_TRANSPARENT"])
        logo_x = int(image_width/2 - logo_width/2)
        logo_y = int(image_height * (header_ratio or CONFIG["HEADER_RATIO"]) - logo_height/2)
        logo_padded.paste(logo, (logo_x, logo_y))
        return Image.alpha_composite(img, logo_padded)
    except (OSError, ValueError) as e:
        logging.warning(f"Error adding logo: {e}")
        return img

