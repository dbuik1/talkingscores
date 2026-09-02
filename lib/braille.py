"""
Encode plain text as uncontracted Unified English Braille in BRF form.

BRF files hold North American ASCII braille: one printable character per
cell, 40 cells per line, 25 lines per page and a form feed between pages.
This is text braille, not braille music notation; note names, values and
octaves are spelled out as words and numbers.
"""

import re
import unicodedata

CELLS_PER_LINE = 40
LINES_PER_PAGE = 25
FORM_FEED = "\f"
LINE_END = "\r\n"

CAPITAL = ","
NUMBER = "#"
UNKNOWN = "="   # a full cell stands in for a character with no braille here

DIGITS = {
    "1": "a", "2": "b", "3": "c", "4": "d", "5": "e",
    "6": "f", "7": "g", "8": "h", "9": "i", "0": "j",
}

PUNCTUATION = {
    " ": " ", ".": "4", ",": "1", ";": "2", ":": "3", "!": "6", "?": "8",
    "'": "'", "-": "-", "(": "\"<", ")": "\">", "/": "_/", "[": ".<", "]": ".>",
    "=": "\"7", "+": "\"6", "*": "\"9", "&": "@&", "%": ".0", "#": "_?",
    "\"": "8", "@": "@a", "~": "@9", "|": "_\\", "_": ".-",
}

WORD_SUBSTITUTIONS = {
    "♯": " sharp", "♭": " flat", "♮": " natural", "𝄪": " double sharp",
    "–": "-", "—": "-", "‘": "'", "’": "'", "“": "\"", "”": "\"", "…": "...",
}


def normalise(text):
    """Accented letters lose their accents; everything else keeps its meaning."""
    for source, target in WORD_SUBSTITUTIONS.items():
        text = text.replace(source, target)
    text = "".join(ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch))
    return re.sub(r"[ \t]+", " ", text)


def encode_word(word):
    """Encode one run of non-space characters."""
    cells = []
    in_number = False
    for char in word:
        if char.isdigit():
            if not in_number:
                cells.append(NUMBER)
                in_number = True
            cells.append(DIGITS[char])
            continue
        if char.isalpha() and char.isascii():
            if in_number:
                # A letter a to j straight after digits would read as another digit.
                if char.lower() in DIGITS.values():
                    cells.append(";")
                in_number = False
            if char.isupper():
                cells.append(CAPITAL)
            cells.append(char.lower())
            continue
        in_number = False
        cells.append(PUNCTUATION.get(char, UNKNOWN))
    return "".join(cells)


def wrap_cells(encoded_words, width=CELLS_PER_LINE):
    """Wrap encoded words at cell boundaries, splitting only oversize words."""
    lines = []
    current = ""
    for word in encoded_words:
        while len(word) > width:
            if current:
                lines.append(current)
                current = ""
            lines.append(word[:width])
            word = word[width:]
        if not current:
            current = word
        elif len(current) + 1 + len(word) <= width:
            current = f"{current} {word}"
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def text_to_brf(text):
    """Turn a block of text into paginated BRF content."""
    braille_lines = []
    for source_line in normalise(text).split("\n"):
        stripped = source_line.strip()
        if not stripped:
            braille_lines.append("")
            continue
        braille_lines.extend(wrap_cells([encode_word(word) for word in stripped.split(" ")]))

    pages = []
    for start in range(0, len(braille_lines), LINES_PER_PAGE):
        page_lines = braille_lines[start:start + LINES_PER_PAGE]
        pages.append(LINE_END.join(page_lines) + LINE_END)
    return FORM_FEED.join(pages)
