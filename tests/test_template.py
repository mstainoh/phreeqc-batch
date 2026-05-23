"""Tests for PhreeqcTemplate."""
import pytest
from phreeqc_batch.templates import PhreeqcTemplate


SIMPLE = PhreeqcTemplate("pH {pH}\ntemp {temp}\n")


class TestPhreeqcTemplateKeys:
    def test_extracts_keys(self):
        assert SIMPLE.keys() == {"pH", "temp"}

    def test_empty_template(self):
        assert PhreeqcTemplate("no placeholders").keys() == set()

    def test_ignores_positional(self):
        t = PhreeqcTemplate("val {} named {x}")
        assert t.keys() == {"x"}


class TestPhreeqcTemplateFill:
    def test_fills_correctly(self):
        result = SIMPLE.fill(pH=7.2, temp=25.0)
        assert "pH 7.2" in result
        assert "temp 25.0" in result

    def test_raises_on_missing_key(self):
        with pytest.raises(KeyError, match="Missing template keys"):
            SIMPLE.fill(pH=7.2)

    def test_raises_on_extra_keys_by_default(self):
        with pytest.raises(ValueError, match="Unrecognized keys"):
            SIMPLE.fill(pH=7.2, temp=25.0, Na=100.0)

    def test_ignore_extra_keys(self):
        result = SIMPLE.fill(pH=7.2, temp=25.0, Na=100.0, ignore_extra=True)
        assert "pH 7.2" in result
        assert "Na" not in result