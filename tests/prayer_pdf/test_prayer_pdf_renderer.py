import json
import re

from pecha_api.prayer_pdf.prayer_pdf_content import PrayerRow, build_cards
from pecha_api.prayer_pdf.prayer_pdf_renderer import (
    PrayerPdfDocument,
    RenderCard,
    content_size_mm,
    footer_template,
    render_html,
)


def _cards(*messages, avatar=None):
    rows = [PrayerRow(user_id=str(i), posted_by=f"Person {i}", message=m) for i, m in enumerate(messages)]
    return [RenderCard(card=c, avatar=avatar) for c in build_cards(rows, skip=set(), columns=5).cards]


def _document(**overrides) -> PrayerPdfDocument:
    values = dict(
        title_bo="སྐྱབས་ཞུ།",
        title="Prayer Requests",
        title_zh="迴向祈願名單",
        subtitle_bo=None,
        subtitle="Received during <Zabtik>",
        subtitle_zh=None,
        date_label="26 September 2026",
        zh_date="2026年9月26日",
        day_number=2,
        day_number_bo="༢",
        closing_bo=["རྗེ་བཙུན་འཕགས་མ་སྒྲོལ་མ་ཁྱེད་མཁྱེན་ནོ།།"],
        closing_mantra="ཨོཾ་ཏཱ་རེ་ཏུཏྟཱ་རེ་ཏུ་རེ་སྭཱ་ཧཱ།",
        closing_zh=[],
        closing_en=["Noble Arya Tara,", "Protect us"],
        closing_emoji="🙏🙏🙏",
        page_size="A3",
        columns=5,
        primary_color="#7a1f1f",
        secondary_color="#b8872b",
        cards=_cards("May all beings be happy", "x" * 600),
    )
    values.update(overrides)
    return PrayerPdfDocument(**values)


def test_header_and_meta():
    html = render_html(_document())
    assert '<div class="t">སྐྱབས་ཞུ།</div>' in html
    assert "<h1>Prayer Requests</h1>" in html
    assert '<div class="zht">迴向祈願名單</div>' in html
    assert "Received during &lt;Zabtik&gt;" in html
    assert "26 September 2026 &nbsp;·&nbsp; 2 requests" in html
    assert "2026年9月26日 &nbsp;2 則祈願" in html
    assert "Day: 2" in html
    assert "ཉིན། ༢" in html
    assert "第 2 天" in html


def test_empty_header_fields_are_left_out():
    html = render_html(_document(title_bo=None, title_zh=None, subtitle=None, day_number=0))
    assert 'class="t"' not in html
    assert 'class="zht"' not in html
    assert 'class="sub"' not in html
    assert 'class="dayline"' not in html
    assert "則祈願" not in html


def test_cards_numbered_with_spans_and_initials():
    html = render_html(_document())
    assert "No. 01" in html
    assert "No. 02" in html
    assert 'class="e" data-span="1"' in html
    assert 'class="e wide w2" data-span="2"' in html
    assert 'class="av ini"' in html


def test_avatar_photo_used_when_present():
    html = render_html(_document(cards=_cards("Peace", avatar="data:image/jpeg;base64,AAA")))
    assert '<img class="av" src="data:image/jpeg;base64,AAA">' in html
    assert 'class="av ini"' not in html


def test_closing_block_and_its_absence():
    html = render_html(_document())
    assert '<span class="mantra">ཨོཾ་ཏཱ་རེ་ཏུཏྟཱ་རེ་ཏུ་རེ་སྭཱ་ཧཱ།</span>' in html
    assert '<span class="tr en">Noble Arya Tara,<br>Protect us</span>' in html
    assert 'class="tr tc"' not in html
    bare = render_html(
        _document(closing_bo=[], closing_mantra=None, closing_zh=[], closing_en=[], closing_emoji=None)
    )
    assert 'class="end"' not in bare


def test_layout_config_and_colors():
    html = render_html(_document(page_size="A4", columns=3, primary_color="#112233"))
    config = json.loads(re.search(r"window.PRAYER_LAYOUT=(\{.*?\});", html).group(1))
    assert config == {"columns": 3, "contentW": 180, "contentH": 261, "dateLabel": "26 September 2026"}
    assert "@page{size:A4;" in html
    assert "--maroon:#112233" in html
    assert content_size_mm("A3") == (267, 384)


def test_fonts_are_embedded():
    html = render_html(_document())
    assert html.count("data:font/ttf;base64,") == 3


def test_footer_template_escapes():
    footer = footer_template("<b>26 September</b>", "#b8872b")
    assert "&lt;b&gt;26 September&lt;/b&gt;" in footer
    assert "pageNumber" in footer
    assert "totalPages" in footer


def test_preview_mode_links_fonts_and_lays_out_itself():
    html = render_html(_document(), preview=True)
    assert 'src:url("fonts/EBGaramond.ttf")' in html
    assert 'src:url("fonts/MonlamUniOuChan2.ttf")' in html
    assert "data:font/ttf" not in html
    assert "class='sheet'" in html or "className='sheet'" in html
    assert "prayer-pdf-preview-scroll" in html
    print_html = render_html(_document())
    assert "prayer-pdf-preview-scroll" not in print_html


def test_layout_json_cannot_close_the_script():
    html = render_html(_document(date_label="</script><b>x"))
    config = re.search(r"window.PRAYER_LAYOUT=(\{.*?\});", html).group(1)
    assert "</script>" not in config
    assert json.loads(config)["dateLabel"] == "</script><b>x"


def test_font_path_only_serves_known_fonts():
    from pecha_api.prayer_pdf.prayer_pdf_renderer import font_path

    assert font_path("EBGaramond.ttf").is_file()
    assert font_path("MonlamUniOuChan2.ttf").is_file()
    assert font_path("../../config.py") is None
