from dataclasses import dataclass
from string import Formatter


def _get_template_keys(template: str) -> set[str]:
    """Extract named placeholder keys from a Python format string.

    Parameters
    ----------
    template : str
        A string containing ``{key}`` style placeholders.

    Returns
    -------
    set of str
        All named placeholder keys found in the template.
        Positional placeholders (``{}``) and empty fields are ignored.

    Examples
    --------
    >>> _get_template_keys("density {density}\\ntemp {temp}")
    {'density', 'temp'}
    """
    return {
        field_name
        for _, field_name, _, _ in Formatter().parse(template)
        if field_name
    }


@dataclass
class PhreeqcTemplate:
    """A PHREEQC input template with named placeholders.

    Wraps a Python format string intended to produce a valid PHREEQC
    input block. Provides key introspection and safe filling with
    explicit validation of required fields before formatting.

    Parameters
    ----------
    template : str
        A string containing ``{key}`` style placeholders corresponding
        to PHREEQC input fields (e.g. ``{density}``, ``{pH}``).

    Examples
    --------
    >>> t = PhreeqcTemplate("density {density}\\npH {pH}")
    >>> t.keys()
    {'density', 'pH'}
    >>> t.fill(density=1.18, pH=6.2)
    'density 1.18\\npH 6.2'
    """

    template: str

    def keys(self) -> set[str]:
        """Named placeholder keys required by this template.

        Returns
        -------
        set of str
            All ``{key}`` placeholders present in the template string.
        """
        return _get_template_keys(self.template)

    def fill(self, ignore_extra:bool=False, **kwargs) -> str:
        """Fill the template with the provided values.

        Only the keys required by the template are used; extra kwargs
        are silently ignored, which allows passing a full composition
        dict without filtering upstream.

        Parameters
        ----------
        ignore_extra: bool. Default False
            If set to True, extra keys not required by the template are ignored.
            If set to False, raises ValueError if extra keys are present
        **kwargs : float or str
            Values for each placeholder in the template.

        Returns
        -------
        str
            The formatted PHREEQC input block.

        Raises
        ------
        KeyError
            If any placeholder required by the template is absent
            from ``kwargs``.
        ValueError
            If extra keys not present in the template are passed and
            ``ignore_extra`` is False.

        Examples
        --------
        >>> t = PhreeqcTemplate("density {density}\\npH {pH}")
        >>> t.fill(density=1.18, pH=6.2, Na=50000.0)  # Na ignored
        'density 1.18\\npH 6.2'
        """
        missing = self.keys() - set(kwargs)
        if missing:
            raise KeyError(f"Missing template keys: {sorted(missing)}")

        extra = set(kwargs) - self.keys()
        if extra and not ignore_extra:
            raise ValueError(f'Unrecognized keys: {sorted(extra)}')

        return self.template.format(**{k: kwargs[k] for k in self.keys()})

    def __repr__(self) -> str:
        return self.template


# ---------------------------------------------------------------------------
# Composition template: ions / density / ph
# no task parameters
# ---------------------------------------------------------------------------

DEFAULT_COMPOSITION_TEMPLATE = PhreeqcTemplate(r"""
    density {density}
    temp {temp}
    pH   {pH}
    units {units}
    Na   {Na}
    Cl   {Cl}
    Ca   {Ca}
    Mg   {Mg}
    K    {K}
    S(6) {SO4} as SO4
    B    {B} as B
    Li   {Li}
    C(4) {HCO3} as HCO3
""")


# no pH, no density, no temperature
DEFAULT_COMPOSITION_NO_CONDITIONS_TEMPLATE  = PhreeqcTemplate(r"""
    units {units}
    Na   {Na}
    Cl   {Cl}
    Ca   {Ca}
    Mg   {Mg}
    K    {K}
    S(6) {SO4} as SO4
    B    {B} as B
    Li   {Li}
    C(4) {HCO3} as HCO3
""")

# ---------------------------------------------------------------------------
# Run templates: get {composition_str} + task parameters
# ---------------------------------------------------------------------------

DEFAULT_SOLUTION_RUN_TEMPLATE = PhreeqcTemplate(r"""
SOLUTION 1  Brine Sample
{composition_str}

    USER_PUNCH
    -headings density
    10 PUNCH RHO

    SELECTED_OUTPUT
      -file solution.sel
      -reset False
END
""")