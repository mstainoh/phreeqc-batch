"""PHREEQC task definitions and result types.

Provides a base task class, two concrete task implementations and a result container:

- ``BaseTask``: abstract base — holds ``run_template``, implements ``run()``.
- ``SolutionTask``: single-composition workflow.
- ``MultiSolutionTask``: multi-composition workflow for MIX and multi-solution
  PHREEQC blocks.
- ``PhreeqcResult``: typed output container, backend-agnostic.
"""
from __future__ import annotations

import logging
import pandas as pd
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar, Optional, Union

from .backend import PhreeqcBackend
from .templates import PhreeqcTemplate

logger = logging.getLogger(__name__)

Id = TypeVar("Id")


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------

@dataclass
class PhreeqcResult(Generic[Id]):
    """Output container for a single PHREEQC task execution.

    Decouples the identity of the input from the result, which may be
    a scalar, a Series, or a full DataFrame depending on the task.

    Parameters
    ----------
    id : Id
        Identifier inherited from the input row (str, int, tuple, etc.).
    task_name : str
        Name of the task that produced this result.
    data : any
        Primary result as returned by PHREEQC selected output.
        Typically a ``pd.DataFrame`` with one row per simulation step.
    metadata : dict, optional
        Supplementary values computed from the result after the run.
    """

    id: Id
    task_name: str
    data: Any
    metadata: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _selected_output_to_df(phreeqc: PhreeqcBackend) -> pd.DataFrame:
    """Convert PHREEQC selected output array to a DataFrame.

    Parameters
    ----------
    phreeqc : PhreeqcBackend
        Backend instance after a successful ``run`` call.

    Returns
    -------
    pd.DataFrame
        First row of the array used as column headers; subsequent rows
        as data.
    """
    arr = phreeqc.get_selected_output_array()
    return pd.DataFrame(arr[1:], columns=arr[0])


# ---------------------------------------------------------------------------
# BaseTask
# ---------------------------------------------------------------------------

@dataclass
class BaseTask(ABC):
    """Abstract base for all PHREEQC tasks.

    Holds the run template and task name, implements the common ``run()``
    execution flow, and delegates input construction to subclasses via
    ``get_phreeqc_input()``.

    Parameters
    ----------
    task_name : str
        Human-readable identifier propagated to ``PhreeqcResult``.
    run_template : PhreeqcTemplate
        Full PHREEQC input block with named placeholders.
    """

    task_name: str
    run_template: PhreeqcTemplate

    @property
    def extra_keys(self) -> set[str]:
        """Placeholders in ``run_template`` not filled by composition templates.

        These must be supplied as ``**kwargs`` when calling ``run``.

        Returns
        -------
        set of str
        """
        return self.run_template.keys() - self.composition_keys()

    @abstractmethod
    def composition_keys(self) -> set[str]:
        """Placeholder keys in ``run_template`` handled by this task's
        composition templates.

        Returns
        -------
        set of str
        """
        ...

    @abstractmethod
    def get_phreeqc_input(self, *args, **kwargs) -> str:
        """Build the PHREEQC input string without executing it.

        Returns
        -------
        str
            Complete PHREEQC input string ready to execute.
        """
        ...

    def run(
        self,
        phreeqc: PhreeqcBackend,
        id_: Optional[Any] = None,
        *args,
        **kwargs,
    ) -> PhreeqcResult:
        """Execute the task and return a typed result.

        Calls ``get_phreeqc_input``, runs the backend, and wraps the
        selected output in a ``PhreeqcResult``.

        Parameters
        ----------
        phreeqc : PhreeqcBackend
            Backend instance with a loaded database.
        id_ : any, optional
            Identifier propagated to the result.
        *args, **kwargs
            Forwarded to ``get_phreeqc_input``.

        Returns
        -------
        PhreeqcResult
            ``data`` is the selected output as a ``pd.DataFrame``.

        Raises
        ------
        RuntimeError
            If PHREEQC fails to execute the input (raised by the backend).
        """
        phreeqc_input = self.get_phreeqc_input(*args, **kwargs)
        phreeqc.run(phreeqc_input)
        return PhreeqcResult(
            id=id_,
            task_name=self.task_name,
            data=_selected_output_to_df(phreeqc),
        )

    @staticmethod
    def fill_template(
        template: Union[str, "PhreeqcTemplate"],
        ignore_extra: bool = True,
        **kwargs,
    ) -> str:
        """Fill a template with the provided values, accepting str or PhreeqcTemplate.

        Convenience helper that normalizes both inputs to ``PhreeqcTemplate``
        semantics: raw strings are wrapped on the fly, so the behavior with
        respect to missing keys, extra keys, and ``ignore_extra`` matches
        ``PhreeqcTemplate.fill`` regardless of input type.

        Parameters
        ----------
        template : str or PhreeqcTemplate
            Template to fill. A raw ``str`` is wrapped in a ``PhreeqcTemplate``
            before filling, so both inputs behave identically.
        ignore_extra : bool, default True
            If True, extra ``kwargs`` not required by the template are silently
            ignored. If False, raises ``ValueError`` on any extra key.
        **kwargs
            Values for each placeholder in the template.

        Returns
        -------
        str
            The formatted output.

        Raises
        ------
        KeyError
            If any placeholder required by the template is absent from
            ``kwargs``.
        ValueError
            If extra keys are passed and ``ignore_extra`` is False.

        Examples
        --------
        >>> BaseTask.fill_template("Na {Na}", Na=100)
        'Na 100'
        >>> BaseTask.fill_template(PhreeqcTemplate("Na {Na}"), Na=100, Cl=200)
        'Na 100'
        >>> BaseTask.fill_template("Na {Na}", ignore_extra=False, Na=100, Cl=200)
        Traceback (most recent call last):
            ...
        ValueError: Unrecognized keys: ['Cl']
        """
        if isinstance(template, str):
            template = PhreeqcTemplate(template)
        return template.fill(ignore_extra=ignore_extra, **kwargs)
# ---------------------------------------------------------------------------
# SolutionTask — single composition
# ---------------------------------------------------------------------------

@dataclass
class SolutionTask(BaseTask):
    """Single-composition PHREEQC task.

    One composition dict fills one named placeholder in ``run_template``.
    The composition template is optional — when ``None``, the run template
    is filled entirely via ``**kwargs``.

    Validation on construction:

    - If ``composition_template`` is provided, ``composition_key`` must
      appear as a placeholder in ``run_template``.
    - If ``composition_template`` is ``None``, ``composition_key`` must
      NOT appear in ``run_template``.

    Parameters
    ----------
    task_name : str
        Human-readable identifier propagated to ``PhreeqcResult``.
    run_template : PhreeqcTemplate
        Full PHREEQC input block.
    composition_template : PhreeqcTemplate, optional
        Template filled with composition values and injected as
        ``composition_key`` into ``run_template``.
    composition_key : str, default ``"composition_str"``
        Placeholder name in ``run_template`` that receives the filled
        composition string.

    Examples
    --------
    >>> task = SolutionTask(
    ...     task_name="density",
    ...     run_template=DEFAULT_SOLUTION_RUN_TEMPLATE,
    ...     composition_template=DEFAULT_COMPOSITION_TEMPLATE,
    ... )
    >>> result = task.run(phreeqc=backend, id_="PW04", composition=sample)
    """

    composition_template: Optional[PhreeqcTemplate] = None
    composition_key: str = "composition_str"

    def __post_init__(self):
        """Verify that run template and composition template are consistent.

        If the run template requires a composition, a composition template
        must be present, and vice versa.
        """
        has_comp = self.composition_template is not None
        has_key = self.composition_key in self.run_template.keys()
        if has_comp and not has_key:
            raise ValueError(
                f"[{self.task_name}] composition_template provided but "
                f"'{self.composition_key}' not found in run_template."
            )
        elif not has_comp and has_key:
            raise ValueError(
                f"[{self.task_name}] run_template expects '{self.composition_key}' "
                f"but no composition_template was provided."
            )

    def composition_keys(self) -> set[str]:
        return {self.composition_key} if self.composition_template is not None else set()

    def get_phreeqc_input(
        self,
        composition: Optional[dict[str, Any]] = None,
        **kwargs,
    ) -> str:
        """Build the PHREEQC input string without executing it.

        Parameters
        ----------
        composition : dict, optional
            Composition values keyed by template placeholder name.
            Required when ``composition_template`` is set.
        **kwargs
            Extra values for any remaining ``run_template`` placeholders.

        Returns
        -------
        str
            Complete PHREEQC input string.

        Raises
        ------
        ValueError
            If ``composition_template`` is set but no composition is supplied.
        KeyError
            If required template placeholders are missing.
        """
        fill_dict = dict(kwargs)
        if self.composition_template is not None:
            if composition is None:
                raise ValueError(
                    f"[{self.task_name}] composition_template provided but no "
                    f"composition supplied."
                )
            fill_dict[self.composition_key] = self.fill_template(self.composition_template, **composition)
        return self.fill_template(self.run_template, **fill_dict)

    def run(
        self,
        phreeqc: PhreeqcBackend,
        id_: Optional[Any] = None,
        composition: Optional[dict[str, Any]] = None,
        **kwargs,
    ) -> PhreeqcResult:
        """Execute the task for one sample.

        Parameters
        ----------
        phreeqc : PhreeqcBackend
            Backend instance with a loaded database.
        id_ : any, optional
            Sample identifier propagated to the result.
        composition : dict, optional
            Composition values. Required when ``composition_template``
            is set.
        **kwargs
            Extra values for any remaining ``run_template`` placeholders.

        Returns
        -------
        PhreeqcResult
            ``data`` is the selected output as a ``pd.DataFrame``.
        """
        return super().run(phreeqc, id_, composition, **kwargs)


# ---------------------------------------------------------------------------
# MultiSolutionTask — multiple compositions
# ---------------------------------------------------------------------------

@dataclass
class MultiSolutionTask(BaseTask):
    """Multi-composition PHREEQC task for MIX and multi-solution blocks.

    Multiple named composition dicts each fill a named placeholder in
    ``run_template``, enabling ``MIX``, reaction transport, or any
    PHREEQC block requiring more than one ``SOLUTION``.

    Validation on construction:

    - Every key in ``composition_templates`` must appear as a placeholder
      in ``run_template``.

    Parameters
    ----------
    task_name : str
        Human-readable identifier propagated to ``PhreeqcResult``.
    run_template : PhreeqcTemplate
        Full PHREEQC input block with one placeholder per solution
        (e.g. ``{solution_1}``, ``{solution_2}``), plus any extra
        placeholders filled via ``**kwargs``.
    composition_templates : dict of str to PhreeqcTemplate
        Mapping of placeholder key → composition template.

    Examples
    --------
    >>> task = MultiSolutionTask(
    ...     task_name="mixing",
    ...     run_template=MIX_TEMPLATE,
    ...     composition_templates={
    ...         "solution_1": DEFAULT_COMPOSITION_TEMPLATE,
    ...         "solution_2": DEFAULT_COMPOSITION_TEMPLATE,
    ...     },
    ... )
    >>> result = task.run(
    ...     phreeqc=backend,
    ...     id_="mix_01",
    ...     compositions={"solution_1": brine_a, "solution_2": meteoric_water},
    ...     fraction_1=0.7,
    ...     fraction_2=0.3,
    ... )
    """

    composition_templates: dict[str, PhreeqcTemplate] = field(default_factory=dict)

    def __post_init__(self):
        missing = set(self.composition_templates) - self.run_template.keys()
        if missing:
            raise ValueError(
                f"[{self.task_name}] composition keys not found in run_template: "
                f"{sorted(missing)}"
            )

    def composition_keys(self) -> set[str]:
        return set(self.composition_templates)

    def get_phreeqc_input(
        self,
        compositions: dict[str, dict[str, Any]],
        **kwargs,
    ) -> str:
        """Build the PHREEQC input string without executing it.

        Parameters
        ----------
        compositions : dict of str to dict
            Mapping of placeholder key → composition dict. Must contain
            one entry per key in ``composition_templates``.
        **kwargs
            Extra values for any remaining ``run_template`` placeholders
            (e.g. mixing fractions).

        Returns
        -------
        str
            Complete PHREEQC input string.

        Raises
        ------
        ValueError
            If a required composition key is absent from ``compositions``.
        KeyError
            If required template placeholders are missing.
        """
        fill_dict = dict(kwargs)
        for key, template in self.composition_templates.items():
            composition = compositions.get(key)
            if composition is None:
                raise ValueError(
                    f"[{self.task_name}] missing composition for key '{key}'."
                )
            fill_dict[key] = self.fill_template(template, **composition)
        return self.fill_template(self.run_template, **fill_dict)

    def run(
        self,
        phreeqc: PhreeqcBackend,
        compositions: dict[str, dict[str, Any]],
        id_: Optional[Any] = None,
        **kwargs,
    ) -> PhreeqcResult:
        """Execute the task with multiple compositions.

        Parameters
        ----------
        phreeqc : PhreeqcBackend
            Backend instance with a loaded database.
        compositions : dict of str to dict
            Mapping of placeholder key → composition dict.
        id_ : any, optional
            Identifier propagated to the result.
        **kwargs
            Extra values for any remaining ``run_template`` placeholders.

        Returns
        -------
        PhreeqcResult
            ``data`` is the selected output as a ``pd.DataFrame``.
        """
        return super().run(phreeqc, id_, compositions, **kwargs)