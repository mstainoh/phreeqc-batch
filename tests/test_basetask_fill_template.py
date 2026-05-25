# tests/test_basetask_fill_template.py
import pytest
from phreeqc_batch.tasks import BaseTask
from phreeqc_batch.templates import PhreeqcTemplate


class TestFillTemplate:
    """BaseTask.fill_template accepts both str and PhreeqcTemplate."""

    def test_phreeqc_template_basic(self):
        t = PhreeqcTemplate("Na {Na}\nCl {Cl}")
        result = BaseTask.fill_template(t, Na=100, Cl=200)
        assert "Na 100" in result
        assert "Cl 200" in result

    def test_str_basic(self):
        result = BaseTask.fill_template("Na {Na}\nCl {Cl}", Na=100, Cl=200)
        assert "Na 100" in result
        assert "Cl 200" in result

    def test_phreeqc_template_ignores_extras(self):
        """PhreeqcTemplate path drops unused kwargs silently."""
        t = PhreeqcTemplate("Na {Na}")
        result = BaseTask.fill_template(t, Na=100, Cl=200, K=300)
        assert result.strip() == "Na 100"

    def test_str_ignores_extras(self):
        """str path also drops unused kwargs (Option A: str → PhreeqcTemplate)."""
        result = BaseTask.fill_template("Na {Na}", Na=100, Cl=200, K=300)
        assert result.strip() == "Na 100"

    def test_missing_key_raises(self):
        t = PhreeqcTemplate("Na {Na}\nCl {Cl}")
        with pytest.raises(KeyError):
            BaseTask.fill_template(t, Na=100)

    def test_missing_key_raises_with_str(self):
        with pytest.raises(KeyError):
            BaseTask.fill_template("Na {Na}\nCl {Cl}", Na=100)

    def test_str_and_template_produce_identical_output(self):
        """Same template content produces same output regardless of input type."""
        raw = "Na {Na}\nCl {Cl}\npH {pH}"
        from_str = BaseTask.fill_template(raw, Na=100, Cl=200, pH=7.0)
        from_template = BaseTask.fill_template(
            PhreeqcTemplate(raw), Na=100, Cl=200, pH=7.0
        )
        assert from_str == from_template