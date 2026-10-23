"""Validate the bounded opening list for one serialized Argo research batch."""


def plan(openings):
    if not isinstance(openings, list) or not 1 <= len(openings) <= 50:
        raise ValueError("Provide a JSON list of 1 to 50 opening names")
    if any(not isinstance(name, str) or not name.strip() for name in openings):
        raise ValueError("Opening names must be nonempty strings")
    names = [name.strip() for name in openings]
    if len({name.casefold() for name in names}) != len(names):
        raise ValueError("Duplicate opening names are not allowed")
    return {"runs": [{"opening": name} for name in names]}
