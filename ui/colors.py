def _rgb(hex_color):
    hex_color = hex_color.lstrip("#")
    return tuple(int(hex_color[i:i + 2], 16) for i in (0, 2, 4))


def is_hex_color(value):
    if not isinstance(value, str) or len(value) != 7 or not value.startswith("#"):
        return False
    try:
        _rgb(value)
        return True
    except ValueError:
        return False


def mix(color, other, amount):
    """Mischt `other` zu `amount` (0..1) in `color`: mix(blau, weiß, 0.3) = 30 % heller."""
    a, b = _rgb(color), _rgb(other)
    return "#{:02X}{:02X}{:02X}".format(*(round(x + (y - x) * amount) for x, y in zip(a, b)))


def contrast_text(color):
    """Schwarz oder Weiß, je nachdem was auf der Farbe besser lesbar ist."""
    r, g, b = _rgb(color)
    luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255
    return "#111111" if luminance > 0.6 else "#FFFFFF"
