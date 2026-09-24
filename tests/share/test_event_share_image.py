import io

from PIL import Image

from pecha_api.share.pecha_text_image_generator import generate_event_share_image
from pecha_api.share.pecha_text_image_generator_config import CONFIG

LOGO_PATH = "pecha_api/share/static/img/pecha-logo.png"


def test_event_share_image_centers_name_on_red_with_logo():
    output = io.BytesIO()

    generate_event_share_image(
        title="Losar",
        lang="en",
        logo_path=LOGO_PATH,
        output_path=output,
    )

    card = Image.open(output).convert("RGBA")
    assert card.size == (1200, 630)
    assert card.getpixel((20, 20))[:3] == CONFIG["EVENT_FALLBACK_BG"][:3]
    assert card.getpixel((20, 20))[:3] == (255, 0, 0)

    logo_pixel = card.getpixel((1200 - 70, 630 - 70))
    assert logo_pixel[3] > 0

    title_region = card.crop((400, 240, 800, 390))
    assert any(pixel[0] > 220 and pixel[1] > 220 and pixel[2] > 220 for pixel in title_region.getdata())
