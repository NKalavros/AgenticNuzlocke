"""Gen 1 evolution families; acquisition history survives deaths and evolution."""

from nuzlocke.assets import data

_GROUPS = data("families-groups.json")


def canonical(name: str) -> str:
    return "".join(c for c in name.upper().replace("♀", "F").replace("♂", "M") if c.isalnum())


_FAMILIES = {canonical(n): canonical(line.split()[0]) for line in _GROUPS.splitlines() for n in line.split()}


def family(name: str) -> str:
    key = canonical(name)
    return _FAMILIES.get(key, key)
