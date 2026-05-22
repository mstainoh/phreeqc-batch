"""Composition classes for PHREEQC input.

Provides a base class with alias resolution and dict-unpacking support,
plus three concrete implementations:

- ``GenericComposition``: open dict, no structure.
- ``BrineComposition``: typed conditions + open ion dict.
- ``LithiumBrineComposition``: fully typed fields for lithium brine panels.
"""
from dataclasses import dataclass, asdict, field
from typing import KeysView, List, Optional, Any
from abc import ABC, abstractmethod
from collections.abc import Iterable

# ---------------------------------------------------------------------------
# Alias registry: alternative names -> canonical field name.
# Extend here without touching the dataclass.
# ---------------------------------------------------------------------------

_ALIASES: dict[str, str] = {
    "HCO3-": "HCO3",
    "bicarbonate": "HCO3",
    "carbonate": "CO3",
    "CO3=": "CO3",
    "sulfate": "SO4",
    "sulphate": "SO4",
    "lithium": "Li",
    "sodium": "Na",
    "potassium": "K",
    "calcium": "Ca",
    "magnesium": "Mg",
    "chloride": "Cl",
    "boron": "B",
    "dens": "density",
    "temperature": "temp",
    "ph": "pH",
}


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------

class BaseComposition(ABC):
    """Abstract base for all composition objects.

    Provides alias resolution via ``_resolve_dict``, dict-unpacking
    support via ``keys()`` and ``__getitem__``, and enforces
    ``to_dict`` / ``from_dict`` on subclasses.

    Dict-unpacking allows passing any composition directly to
    ``PhreeqcTemplate.fill``::

        comp = BrineComposition.from_dict(row)
        template.fill(**comp)  # works like fill(**comp.to_dict())
    """

    @abstractmethod
    def to_dict(self, ignore_nulls: bool = True) -> dict[str, Any]:
        """Return a dict representation of the composition.

        Parameters
        ----------
        ignore_nulls : bool, default True
            If ``True``, fields with ``None`` values are excluded.

        Returns
        -------
        dict of str to any
        """
        raise NotImplementedError

    @classmethod
    @abstractmethod
    def from_dict(cls, d: dict, **kwargs) -> "BaseComposition":
        """Construct a composition from a dict.

        Parameters
        ----------
        d : dict
            Raw input dict, possibly containing aliased keys.

        Returns
        -------
        BaseComposition
        """
        raise NotImplementedError

    @staticmethod
    def _resolve_dict(
        d: dict[str, Any],
        aliases: Optional[dict[str, str]] = _ALIASES,
        keys: Optional[Iterable[str]] = None,
    ) -> dict[str, Any]:
        """Resolve aliases and optionally filter keys.

        Centralizes the alias-resolution logic shared by all subclass
        ``from_dict`` implementations.

        Parameters
        ----------
        d : dict
            Raw input dict.
        aliases : dict, optional
            Alias mapping applied to input keys. Defaults to
            ``_ALIASES``. Pass ``None`` to skip resolution.
        keys : list of str, optional
            If provided, only these keys are kept after alias
            resolution.

        Returns
        -------
        dict
            Resolved (and optionally filtered) dict.
        """
        resolved = (
            {aliases.get(k, k): v for k, v in d.items()}
            if aliases
            else dict(d)
        )
        if keys:
            resolved = {k: v for k, v in resolved.items() if k in keys}
        return resolved

    def keys(self) -> KeysView:
        """Keys of the non-null composition fields.

        Supports dict-unpacking: ``**composition`` works like
        ``**composition.to_dict()``.

        Returns
        -------
        KeysView
        """
        return self.to_dict(ignore_nulls=True).keys()

    def __getitem__(self, key: str) -> Any:
        """Retrieve a composition value by key.

        Supports dict-unpacking together with ``keys()``.

        Parameters
        ----------
        key : str

        Returns
        -------
        any

        Raises
        ------
        KeyError
            If ``key`` is not present in the composition.
        """
        return self.to_dict()[key]

    @abstractmethod
    def _update_field(self, key: str, value: Any) -> None:
        """Update a single field on the composition.

        Subclasses can implement this to support field updates without
        reconstructing the whole object. By default, does nothing.

        Parameters
        ----------
        key : str
            Field name to update.
        value : any
            New value for the field.
        """
        raise NotImplementedError

    def update(self, other: dict[str, Any], aliases: Optional[dict[str, str]] = _ALIASES) -> None:
        """Update the composition or attributes with values from another dict.

        Resolves aliases in the input dict before updating.

        Parameters
        ----------
        other : dict
            Input dict with new values to update the composition.
        aliases : dict, optional
            Alias mapping applied to input keys. Defaults to
            ``_ALIASES``. Pass ``None`` to skip resolution.
        """
        resolved = self._resolve_dict(other, aliases=aliases)
        for k, v in resolved.items():
            if k in self.keys():
                self._update_field(k, v)

# ---------------------------------------------------------------------------
# GenericComposition
# ---------------------------------------------------------------------------

class GenericComposition(BaseComposition):
    """Generic composition container backed by a plain dictionary.

    Use when the ion panel is not known in advance or does not map to
    the standard brine fields.

    Parameters
    ----------
    composition : dict of str to any
        Arbitrary key-value pairs representing the composition.

    Examples
    --------
    >>> comp = GenericComposition({"Na": 1e5, "Cl": 1.7e5})
    >>> comp.keys()
    dict_keys(['Na', 'Cl'])
    >>> {**comp}
    {'Na': 100000.0, 'Cl': 170000.0}
    """

    def __init__(self, composition: dict[str, Any]):
        self.composition = composition

    def to_dict(self, ignore_nulls: bool = True) -> dict[str, Any]:
        """Return a copy of the underlying composition dict.

        Parameters
        ----------
        ignore_nulls : bool, default True
            Accepted for interface consistency; ignored internally
            since ``GenericComposition`` contains no nullable fields.

        Returns
        -------
        dict
        """
        return dict(self.composition)

    @classmethod
    def from_dict(
        cls,
        d: dict[str, Any],
        aliases: Optional[dict[str, str]] = _ALIASES,
        keys: Optional[Iterable[str]] = None,
    ) -> "GenericComposition":
        """Construct a ``GenericComposition`` resolving aliases.

        Parameters
        ----------
        d : dict
            Input dict, possibly containing aliased keys.
        aliases : dict, optional
            Alias dictionary for key mapping. Defaults to ``_ALIASES``.
            Pass ``None`` to skip alias resolution.
        keys : list of str, optional
            If provided, only these keys are included after alias
            resolution.

        Returns
        -------
        GenericComposition
        """
        return cls(cls._resolve_dict(d, aliases, keys))
    
    def _update_field(self, key: str, value: Any) -> None:
        self.composition[key] = value


# ---------------------------------------------------------------------------
# BrineComposition
# ---------------------------------------------------------------------------

@dataclass
class BrineComposition(BaseComposition):
    """Brine composition with typed conditions and an open ion panel.

    Conditions (density, temp, pH, units) are typed fields. Ions are
    stored in a free dict, allowing arbitrary species without modifying
    the class.

    Parameters
    ----------
    density : float, optional
        Brine density in g/cm³.
    temp : float, optional
        Temperature in °C.
    pH : float, optional
        pH of the sample.
    units : str, default "mg/kgw"
        Concentration units passed verbatim to PHREEQC.
    ions : dict of str to float, optional
        Ion concentrations keyed by field name.

    Examples
    --------
    >>> comp = BrineComposition(pH=6.2, temp=25.0, ions={"Na": 1e5, "Cl": 1.7e5})
    >>> comp.keys()
    dict_keys(['pH', 'temp', 'units', 'Na', 'Cl'])
    >>> {**comp}
    {'pH': 6.2, 'temp': 25.0, 'units': 'mg/kgw', 'Na': 100000.0, 'Cl': 170000.0}
    """

    density: Optional[float] = None
    temp: Optional[float] = None
    pH: Optional[float] = None
    units: str = "mg/kgw"
    ions: dict[str, float] = field(default_factory=dict)

    @property
    def conditions(self) -> dict:
        """Dict of the condition fields (density, temp, pH, units).

        Returns
        -------
        dict
        """
        return {
            "density": self.density,
            "temp": self.temp,
            "pH": self.pH,
            "units": self.units,
        }

    def ion_keys(self) -> KeysView:
        """Keys of the ion dict.

        Returns
        -------
        KeysView
        """
        return self.ions.keys()

    def to_dict(self, ignore_nulls: bool = True) -> dict[str, Any]:
        """Return a flat dict of conditions and ions.

        Parameters
        ----------
        ignore_nulls : bool, default True
            If ``True``, condition fields with ``None`` values are excluded.

        Returns
        -------
        dict
        """
        conditions = {
            "density": self.density,
            "temp": self.temp,
            "pH": self.pH,
            "units": self.units,
        }
        base = {
            k: v for k, v in conditions.items()
            if not (ignore_nulls and v is None)
        }
        return {**base, **self.ions}

    @classmethod
    def from_dict(
        cls,
        d: dict[str, Any],
        aliases: Optional[dict[str, str]] = _ALIASES,
        keys: Optional[Iterable[str]] = None,
    ) -> "BrineComposition":
        """Construct a ``BrineComposition`` from a dict.

        Condition fields (density, temp, pH, units) are mapped to typed
        attributes; everything else goes into ``ions``.

        Parameters
        ----------
        d : dict
            Mapping of field names or aliases to values.
        aliases : dict, optional
            Alias dictionary for key mapping. Defaults to ``_ALIASES``.
            Pass ``None`` to skip alias resolution.
        keys : list of str, optional
            If provided, only these keys are included after alias
            resolution.

        Returns
        -------
        BrineComposition
        """
        resolved = cls._resolve_dict(d, aliases, keys)
        condition_fields = {"density", "temp", "pH", "units"}
        conditions = {k: v for k, v in resolved.items() if k in condition_fields}
        ions = {k: v for k, v in resolved.items() if k not in condition_fields}
        return cls(**conditions, ions=ions)

    def _update_field(self, key: str, value: Any) -> None:
        if key in self.conditions.keys():
            setattr(self, key, value)
        else:
            self.ions[key] = value

# ---------------------------------------------------------------------------
# LithiumBrineComposition
# ---------------------------------------------------------------------------

@dataclass
class LithiumBrineComposition(BaseComposition):
    """Ionic composition of a lithium brine sample.

    All concentration fields are optional to accommodate varying ion
    panels across different salars and sampling campaigns. The dataclass
    reflects measured reality — fields absent from the sample are ``None``,
    not defaulted.

    The field set is intentionally maximal. When filling a template, only
    the keys the template requests are used; unused fields are silently
    dropped.

    Parameters
    ----------
    density : float, optional
        Brine density in g/cm³.
    temp : float, optional
        Temperature in °C.
    pH : float, optional
        pH of the sample.
    Na, Cl, Ca, Mg, K, SO4, Li, B : float, optional
        Ion concentrations in ``units``.
    HCO3 : float, optional
        Bicarbonate concentration in ``units``.
    CO3, S : float, optional
        Carbonate species in ``units``.
    As, Fe, Ba, Si : float, optional
        Trace species in ``units``.
    units : str, default "mg/kgw"
        Concentration units string passed verbatim to PHREEQC input.

    Examples
    --------
    >>> comp = LithiumBrineComposition(Na=100235.0, Cl=169717.0, pH=6.2)
    >>> "Na" in comp.keys()
    True
    >>> {**comp}
    {'Na': 100235.0, 'Cl': 169717.0, 'pH': 6.2, 'units': 'mg/kgw'}
    """

    # conditions
    density: Optional[float] = None
    temp: Optional[float] = None
    pH: Optional[float] = None

    # major ions
    Na: Optional[float] = None
    Cl: Optional[float] = None
    Ca: Optional[float] = None
    Mg: Optional[float] = None
    K: Optional[float] = None
    SO4: Optional[float] = None
    Li: Optional[float] = None
    B: Optional[float] = None

    # carbonate / variable species
    HCO3: Optional[float] = None
    CO3: Optional[float] = None
    S: Optional[float] = None

    # trace species
    As: Optional[float] = None
    Fe: Optional[float] = None
    Ba: Optional[float] = None
    Si: Optional[float] = None

    units: str = "mg/kgw"

    def to_dict(self, ignore_nulls: bool = True) -> dict[str, Any]:
        """Return a dict suitable for filling a PHREEQC template.

        Parameters
        ----------
        ignore_nulls : bool, default True
            If ``True``, fields with ``None`` values are excluded.

        Returns
        -------
        dict
        """
        result = {}
        for name, val in asdict(self).items():
            if ignore_nulls and val is None:
                continue
            result[name] = val
        return result

    @classmethod
    def fields(cls) -> list[str]:
        """Return all field names defined on this dataclass.

        Returns
        -------
        list of str
        """
        return list(cls.__dataclass_fields__)

    @classmethod
    def from_dict(
        cls,
        d: dict[str, Any],
        aliases: Optional[dict[str, str]] = _ALIASES,
        keys: Optional[Iterable[str]] = None,
        strict: bool = False,
    ) -> "LithiumBrineComposition":
        """Construct a ``LithiumBrineComposition`` from a dict.

        Resolves aliases to canonical field names before mapping to
        dataclass fields.

        Parameters
        ----------
        d : dict
            Mapping of field names or aliases to values.
        aliases : dict, optional
            Alias dictionary for key mapping. Defaults to ``_ALIASES``.
            Pass ``None`` to skip alias resolution.
        keys : list of str, optional
            If provided, only these keys are included after alias
            resolution.
        strict : bool, default False
            If ``True``, raises ``ValueError`` for keys that cannot be
            mapped to a known field.

        Returns
        -------
        LithiumBrineComposition

        Raises
        ------
        ValueError
            If ``strict=True`` and unrecognized keys are present.

        Examples
        --------
        >>> LithiumBrineComposition.from_dict({"Na": 1e5, "HCO3-": 1125.0})
        LithiumBrineComposition(Na=100000.0, HCO3=1125.0, ...)
        """
        resolved = cls._resolve_dict(d, aliases, keys)
        known_fields = set(cls.__dataclass_fields__)
        kwargs: dict = {}
        unrecognized: list = []

        for k, v in resolved.items():
            if k in known_fields:
                kwargs[k] = v
            else:
                unrecognized.append(k)

        if strict and unrecognized:
            raise ValueError(
                f"Unrecognized keys in from_dict: {sorted(unrecognized)}"
            )

        return cls(**kwargs)
    
    def _update_field(self, key: str, value: Any) -> None:
        setattr(self, key, value)