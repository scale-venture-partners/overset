"""Importing a rule module registers its rules."""


def load_rules() -> None:
    from overset.rules import render_rules, structure  # noqa: F401

    try:
        from overset.rules import vision  # noqa: F401
    except ImportError:  # the [vision] extra isn't installed; those rules don't exist
        pass
