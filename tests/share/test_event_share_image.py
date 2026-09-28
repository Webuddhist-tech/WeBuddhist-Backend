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


def _photo_bytes(width: int, height: int, color=(20, 140, 90), fmt="WEBP") -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), color).save(buffer, format=fmt)
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

    card = Image.open(output)
    assert card.size == (1200, 630)
    # JPEG, not the PNG the cards use: WebP is not a format link-preview
    # crawlers render, which is the whole reason this is re-encoded.
    assert card.format == "JPEG"
    # No red band, no title, no logo - just the photo.
    corners = [
        card.convert("RGB").getpixel(point)
        for point in ((0, 0), (1199, 0), (0, 629), (1199, 629))
    ]
    assert all(abs(r - 20) < 12 and abs(g - 140) < 12 and abs(b - 90) < 12
               for r, g, b in corners)


def test_a_webp_photo_comes_out_as_jpeg():
    """Every image this system stores is WebP, so this is the only real case."""
    output = io.BytesIO()

    generate_event_share_image(
        title="Losar", output_path=output, photo_bytes=_photo_bytes(800, 800, fmt="WEBP")
    )

    assert Image.open(output).format == "JPEG"


def test_event_photo_is_cropped_to_fill_not_letterboxed():
    """Bars around a photo read as a broken image in a link preview."""
    output = io.BytesIO()

    generate_event_share_image(
        title="Losar",
        logo_path=LOGO_PATH,
        output_path=output,
        photo_bytes=_photo_bytes(600, 600),
    )

    card = Image.open(output).convert("RGB")
    assert card.size == (1200, 630)
    r, g, b = card.getpixel((0, 0))
    assert abs(r - 20) < 12 and abs(g - 140) < 12 and abs(b - 90) < 12


def test_exif_orientation_is_applied_before_cropping():
    """A phone photo can carry its rotation in EXIF rather than its pixels.
    Without this the card comes out sideways, or crops the wrong part."""
    # Tall image with a distinctive top band, tagged as needing a 90 degree turn.
    source = Image.new("RGB", (400, 800), (10, 10, 200))
    for y in range(80):
        for x in range(400):
            source.putpixel((x, y), (200, 10, 10))
    exif = source.getexif()
    exif[274] = 6  # Orientation: rotate 90 CW on display.
    raw = io.BytesIO()
    source.save(raw, format="JPEG", exif=exif)

    upright = io.BytesIO()
    generate_event_share_image(
        title="Losar", output_path=upright, photo_bytes=raw.getvalue()
    )
    rotated = Image.open(upright).convert("RGB")

    ignored = io.BytesIO()
    source_without_tag = io.BytesIO()
    source.save(source_without_tag, format="JPEG")
    generate_event_share_image(
        title="Losar", output_path=ignored, photo_bytes=source_without_tag.getvalue()
    )

    # The orientation tag has to change what comes out, or it was not read.
    assert list(rotated.getdata()) != list(Image.open(ignored).convert("RGB").getdata())


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
