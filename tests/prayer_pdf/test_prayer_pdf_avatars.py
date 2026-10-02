import base64
import io
from unittest.mock import patch

from PIL import Image, ImageDraw

from pecha_api.prayer_pdf import prayer_pdf_avatars as avatars

_MOD = "pecha_api.prayer_pdf.prayer_pdf_avatars"


def _png(image: Image.Image, fmt: str = "PNG") -> bytes:
    out = io.BytesIO()
    image.save(out, format=fmt)
    return out.getvalue()


def _photo() -> Image.Image:
    """Noise-like gradient: thousands of colours, like a real photo."""
    image = Image.new("RGB", (120, 90))
    image.putdata([((x * 7 + y * 3) % 256, (x * 5) % 256, (y * 11) % 256) for y in range(90) for x in range(120)])
    return image


def _letter_tile() -> Image.Image:
    image = Image.new("RGB", (96, 96), "#8e24aa")
    ImageDraw.Draw(image).text((40, 40), "T", fill="white")
    return image


def test_placeholder_urls():
    assert avatars.is_placeholder_url("https://cdn.auth0.com/avatars/td.png")
    assert avatars.is_placeholder_url("https://s.gravatar.com/avatar/x?d=https://cdn.auth0.com/avatars/td.png")
    assert not avatars.is_placeholder_url("https://lh3.googleusercontent.com/a/ACg8oc")


def test_generated_avatar_detection():
    assert avatars.is_generated_avatar(_letter_tile(), is_png=True)
    assert not avatars.is_generated_avatar(_photo(), is_png=True)


def test_two_colour_check_only_for_png():
    half = Image.new("RGB", (64, 64), "white")
    half.putdata([(255, 255, 255)] * 2000 + [(0, 0, 0)] * 1000 + [((i * 37) % 256, (i * 11) % 256, (i * 5) % 256) for i in range(1096)])
    assert avatars.is_generated_avatar(half, is_png=True)
    assert not avatars.is_generated_avatar(half, is_png=False)


def test_s3_key_photo_becomes_square_jpeg_data_uri():
    with patch(f"{_MOD}.download_bytes", return_value=_png(_photo())) as mock_download, patch(
        f"{_MOD}.get", return_value="bucket"
    ):
        uri = avatars.load_avatar("/avatars/u1.png")
    mock_download.assert_called_once_with(bucket_name="bucket", s3_key="avatars/u1.png", max_bytes=avatars.MAX_AVATAR_BYTES)
    assert uri.startswith("data:image/jpeg;base64,")
    with Image.open(io.BytesIO(base64.b64decode(uri.split(",", 1)[1]))) as image:
        assert image.size == (160, 160)


def test_letter_tile_falls_back_to_initials():
    with patch(f"{_MOD}.download_bytes", return_value=_png(_letter_tile())), patch(f"{_MOD}.get", return_value="b"):
        assert avatars.load_avatar("avatars/u1.png") is None


def test_untrusted_and_placeholder_hosts_are_not_fetched():
    with patch(f"{_MOD}.httpx.Client") as mock_client:
        assert avatars.load_avatar("https://evil.example/me.jpg") is None
        assert avatars.load_avatar("https://cdn.auth0.com/avatars/td.png") is None
    mock_client.assert_not_called()


def test_failures_and_blanks_are_none():
    assert avatars.load_avatar(None) is None
    assert avatars.load_avatar("  ") is None
    with patch(f"{_MOD}.download_bytes", side_effect=RuntimeError("boom")), patch(f"{_MOD}.get", return_value="b"):
        assert avatars.load_avatar("avatars/u1.png") is None


def test_load_avatars_fetches_each_user_once():
    with patch(f"{_MOD}.load_avatar", side_effect=lambda ref: f"uri:{ref}") as mock_load:
        result = avatars.load_avatars([("u1", "a.png"), ("u2", None), ("u1", "a.png")])
    assert result == {"u1": "uri:a.png", "u2": "uri:None"}
    assert mock_load.call_count == 2
    assert avatars.load_avatars([]) == {}
