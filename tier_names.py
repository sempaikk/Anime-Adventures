"""Read simple identity declarations as text; never execute the Wiki's Lua."""

import re


DECLARATION = re.compile(
    r"""^\s*\[(?:"(?P<double>[^"\n]+)"|'(?P<single>[^'\n]+)')\]"""
    r"""\s*=\s*\{\s*name\s*=\s*(?P<quote>["'])(?P<uid>[A-Za-z0-9_]+)(?P=quote)[ \t]*(?=[,}])""",
    re.M,
)


def parse_names(text):
    """Support either Lua quote style without accepting comments or expressions."""
    return [
        (match["double"] or match["single"], match["uid"])
        for match in DECLARATION.finditer(text)
        if "\\" not in (match["double"] or match["single"])
    ]
