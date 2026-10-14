import theme


def test_light_when_the_registry_says_light():
    assert theme.system_prefers_dark(lambda: 1) is False


def test_dark_when_the_registry_says_dark():
    assert theme.system_prefers_dark(lambda: 0) is True


def test_dark_when_the_registry_cannot_be_read():
    assert theme.system_prefers_dark(lambda: None) is True


def test_background_matches_the_page():
    assert theme.background(True) == "#000000"
    assert theme.background(False) == "#f5f5f7"


def test_title_bar_colours_are_bgr_integers():
    caption, text = theme.title_bar_colours(False)
    assert caption == 0x00F7F5F5          # #f5f5f7 as 0x00BBGGRR
    assert text == 0x001F1D1D             # #1d1d1f
    assert theme.title_bar_colours(True)[0] == 0
