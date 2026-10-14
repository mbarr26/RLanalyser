"""Light or dark: which one Windows is set to, and the native window colours that go with it.

The page itself follows the system through CSS (`prefers-color-scheme`), but the window is created before the
page loads, so its background (no wrong-coloured flash at start-up) and its title bar are chosen here. Pure logic
except `_read_apps_use_light_theme`, which reads one registry value and is replaceable in tests.
"""

# Page backgrounds, matching `--paper` in ui/styles.css
LIGHT_BACKGROUND = "#f5f5f7"
DARK_BACKGROUND = "#000000"

_KEY = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"


def _read_apps_use_light_theme():
    """The registry's AppsUseLightTheme (1 = light, 0 = dark), or None when it can't be read."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _KEY) as key:
            return int(winreg.QueryValueEx(key, "AppsUseLightTheme")[0])
    except Exception:
        return None


def system_prefers_dark(read=_read_apps_use_light_theme):
    """True when apps should be dark. Anything unreadable (older Windows, not Windows) counts as dark."""
    value = read()
    return value != 1


def background(dark):
    return DARK_BACKGROUND if dark else LIGHT_BACKGROUND


def _bgr(hex_colour):
    """'#rrggbb' as the 0x00BBGGRR integer that Windows' DWM calls want."""
    h = hex_colour.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return (b << 16) | (g << 8) | r


def title_bar_colours(dark):
    """(caption, text) as DWM colour integers, matching the page background and its text."""
    return (_bgr(background(dark)), _bgr("#f5f5f7" if dark else "#1d1d1f"))
