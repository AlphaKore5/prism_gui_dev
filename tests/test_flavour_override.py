"""PRISM_FLAVOUR: honoured only by a source run, never by a frozen build."""
import channel
import flavour


def _run(env, frozen):
    saved = flavour.FLAVOUR
    try:
        return channel.apply_flavour_override(env, frozen)
    finally:
        flavour.FLAVOUR = saved


def test_default_stays_complete_without_the_variable():
    import re
    src = open(flavour.__file__, encoding="utf-8").read()
    assert re.search(r'^FLAVOUR = "complete"', src, re.M)
    assert _run({}, False) == flavour.FLAVOUR


def test_source_run_honours_it():
    assert _run({"PRISM_FLAVOUR": "sales"}, False) == "sales"


def test_frozen_build_ignores_it():
    assert _run({"PRISM_FLAVOUR": "sales"}, True) == flavour.FLAVOUR


def test_unknown_value_ignored():
    assert _run({"PRISM_FLAVOUR": "nope"}, False) == flavour.FLAVOUR
