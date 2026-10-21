import re

from sqlalchemy import text

_QUOTED = re.compile(r"'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"")


def statement(sql):
    return text(_QUOTED.sub(lambda match: match.group().replace(":", r"\:"), sql))
