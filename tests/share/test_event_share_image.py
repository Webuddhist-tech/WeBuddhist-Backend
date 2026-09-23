import io

from PIL import Image

from pecha_api.share.pecha_text_image_generator import generate_event_share_image
from pecha_api.share.share_service import _event_image_keys

LOGO_PATH = "pecha_api/share/static/img/webuddhist-logo.png"


def test_event_image_keys_prefer_medium_and_read_urls():
    assert _event_image_keys("images/events/losar/original/banner.webp") == [
        "images/events/losar/medium/banner.webp",
        "images/events/losar/original/banner.webp",
    ]
    assert _event_image_keys(
        "https://cdn.example.com/images/events/losar/original/banner.webp?X-Amz-Signature=abc"
    ) == [
        "images/events/losar/medium/banner.webp",
        "images/events/losar/original/banner.webp",
    ]
    assert _event_image_keys(None) == []


def test_event_share_image_uses_photo_name_and_logo():
    photo = Image.new("RGBA", (800, 500), (20, 140, 220, 255))
    photo_bytes = io.BytesIO()
    photo.save(photo_bytes, format="PNG")
    output = io.BytesIO()

    generate_event_share_image(
        title="Losar",
        lang="en",
        background=photo_bytes.getvalue(),
        logo_path=LOGO_PATH,
        output_path=output,
    )

    card = Image.open(output).convert("RGBA")
    assert card.size == (1200, 630)
    assert card.getpixel((20, 20))[:3] == (20, 140, 220)

    logo_pixel = card.getpixel((1200 - 70, 630 - 70))
    assert logo_pixel[3] > 0
    assert logo_pixel[:3] != (20, 140, 220)

    title_region = card.crop((36, 470, 500, 600))
    assert any(pixel[0] > 220 and pixel[1] > 220 and pixel[2] > 220 for pixel in title_region.getdata())
