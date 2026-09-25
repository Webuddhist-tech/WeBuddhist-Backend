import io

from PIL import Image

from pecha_api.share.pecha_text_image_generator import generate_event_share_image
from pecha_api.share.pecha_text_image_generator_config import CONFIG

LOGO_PATH = "pecha_api/share/static/img/pecha-logo.png"


def _photo_bytes(width: int, height: int, color=(20, 140, 90, 255)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGBA", (width, height), color).save(buffer, format="PNG")
    return buffer.getvalue()


def test_event_photo_is_the_card_with_nothing_drawn_over_it():
    """The preview renders the title as text underneath; burning it into the
    image only competes with it."""
    output = io.BytesIO()

    generate_event_share_image(
        title="Losar",
        lang="en",
        logo_path=LOGO_PATH,
        output_path=output,
        photo_bytes=_photo_bytes(1200, 630),
    )

    card = Image.open(output).convert("RGBA")
    assert card.size == (1200, 630)
    # Every pixel is the photo: no red band, no title, no logo.
    assert set(card.getdata()) == {(20, 140, 90, 255)}


def test_event_photo_is_cropped_to_fill_not_letterboxed():
    """Bars around a photo read as a broken image in a link preview."""
    output = io.BytesIO()

    generate_event_share_image(
        title="Losar",
        logo_path=LOGO_PATH,
        output_path=output,
        photo_bytes=_photo_bytes(600, 600),
    )

    card = Image.open(output).convert("RGBA")
    assert card.size == (1200, 630)
    corners = [
        card.getpixel((0, 0)),
        card.getpixel((1199, 0)),
        card.getpixel((0, 629)),
        card.getpixel((1199, 629)),
    ]
    assert all(pixel == (20, 140, 90, 255) for pixel in corners)


def test_unreadable_photo_falls_back_to_the_title_card():
    """A blank preview is worse than a plain one."""
    output = io.BytesIO()

    generate_event_share_image(
        title="Losar",
        lang="en",
        logo_path=LOGO_PATH,
        output_path=output,
        photo_bytes=b"not an image",
    )

    card = Image.open(output).convert("RGBA")
    assert card.size == (1200, 630)
    assert card.getpixel((20, 20))[:3] == (255, 0, 0)


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
