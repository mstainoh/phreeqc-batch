"""PHREEQC task definitions and result types for lithium brine geochemistry.

Provides a generic task class that handles the full flow from composition
dict to PHREEQC result: composition template filling, run template filling,
execution, and output parsing.
"""
from __future__ import annotations

import logging
import numpy as np
import pandas as pd
from dataclasses import dataclass, field, fields
from typing import Any, Generic, TypeVar, Optional

from .backend import PhreeqcBackend
from .composition import BaseComposition

from .templates import PhreeqcTemplate

logger = logging.getLogger(__name__)

Id = TypeVar("Id")


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------

@dataclass
class PhreeqcResult(Generic[Id]):
    """Output container for a single PHREEQC task execution.

    Decouples the identity of the input sample from the result, which
    may be a scalar, a Series, or a full DataFrame depending on usage.

    Parameters
    ----------
    id : Id
        Identifier inherited from the input row (str, int, tuple, etc.).
    task_name : str
        Name of the task that produced this result.
    data : float or pd.Series or pd.DataFrame
        Primary result as returned by PHREEQC selected output.
    metadata : dict, optional
        Supplementary values (e.g. ``hcl_consumed``, ``density``).
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
    phreeqc : phreeqc_mod.IPhreeqc
        Instance after a successful ``run_string`` call.

    Returns
    -------
    pd.DataFrame
        First row of the array used as column headers.
    """
    arr = phreeqc.get_selected_output_array()
    return pd.DataFrame(arr[1:], columns=arr[0])


# ---------------------------------------------------------------------------
# Task
# ---------------------------------------------------------------------------

@dataclass
class PhreeqcTask:
    """Generic PHREEQC task: composition → template → run → result.

    Handles the full flow from a composition dict to a PHREEQC result
    DataFrame. The composition template is optional — when ``None`` the
    run template is filled directly with ``**kwargs``.

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
        Full PHREEQC input block. Contains ``{composition_key}`` when
        a ``composition_template`` is provided, plus any extra
        placeholders filled via ``**kwargs`` in ``run``.
    composition_template : PhreeqcTemplate, optional
        Template filled with composition values to produce the string
        injected as ``composition_key`` into ``run_template``.
    composition_key : str, default "composition_str"
        Name of the placeholder in ``run_template`` that receives the
        filled composition string.

    Examples
    --------
    Density task:

    >>> task = PhreeqcTask(
    ...     task_name="density",
    ...     run_template=DEFAULT_SOLUTION_RUN_TEMPLATE,
    ...     composition_template=DEFAULT_COMPOSITION_TEMPLATE,
    ... )
    >>> result = task.run(composition, id_="PW04", phreeqc=ph)

    Acidification task with extra params:

    >>> task = PhreeqcTask(
    ...     task_name="acidification",
    ...     run_template=DEFAULT_ACIDIFICATION_RUN_TEMPLATE,
    ...     composition_template=DEFAULT_COMPOSITION_TEMPLATE,
    ... )
    >>> result = task.run(composition, id_="PW04", phreeqc=ph,
    ...                   hcl_conc=0.32, hcl_dens=1.16)

    Direct template without composition:

    >>> task = PhreeqcTask(
    ...     task_name="custom",
    ...     run_template=my_template,
    ... )
    >>> result = task.run({}, id_="test", phreeqc=ph, param1=1.0)
    """

    task_name: str
    run_template: PhreeqcTemplate
    composition_template: Optional[PhreeqcTemplate] = None
    composition_key: str = "composition_str"

    def __post_init__(self):
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

    @property
    def requires_composition(self) -> bool:
        return self.composition_template is not None

    @property
    def extra_keys(self) -> set[str]:
        """Placeholders in ``run_template`` beyond ``composition_key``.

        These must be supplied as ``**kwargs`` when calling ``run``.

        Returns
        -------
        set of str
        """
        return self.run_template.keys() - {self.composition_key}

    def get_phreeqc_input(self, 
            composition: Optional[dict[str, Any] | BaseComposition] = None,
            **kwargs,) -> str:
        """Execute the task for one sample.

        Fills the composition template (if present), then fills the run
        template with the composition string and any extra ``kwargs``,

        Parameters
        ----------
        composition : dict of str to float, optional
            PHREEQC-keyed composition dict. Ignored when
            ``composition_template`` is ``None``.
        **kwargs
            Extra values for ``run_template`` placeholders beyond
            ``composition_key`` (e.g. ``hcl_conc``, ``hcl_dens``).

        Returns
        -------
        str
            phreeqc input string.

        Raises
        ------
        KeyError
            If composition or kwargs are missing keys required by
            the respective templates.
        """
        fill_dict = dict(kwargs)
        if self.composition_template is not None:
            if composition is None:
                raise ValueError(
                    f"[{self.task_name}] composition_template provided but no "
                    f"composition dict supplied."
                )
            fill_dict[self.composition_key] = self.composition_template.fill(**composition)

        phreeqc_input = self.run_template.fill(**fill_dict)
        return phreeqc_input

    def run(
        self,
        phreeqc: PhreeqcBackend,
        id_: Optional[Any] = None,
        composition: Optional[dict[str, Any] | BaseComposition] = None,
        **kwargs,
    ) -> PhreeqcResult:
        """Execute the task for one sample.

        Fills the composition template (if present), then fills the run
        template with the composition string and any extra ``kwargs``,
        executes PHREEQC, and returns the selected output as a DataFrame.

        Both ``PhreeqcTemplate.fill`` calls validate their keys
        internally — missing keys raise ``KeyError``.

        Parameters
        ----------
        phreeqc : PhreeqpyBackend
            Loaded IPhreeqc instance.
        id_ : any, optional
            Sample identifier propagated to the result.
        composition : dict of str to float, optional
            PHREEQC-keyed composition dict. Ignored when
            ``composition_template`` is ``None``.
        **kwargs
            Extra values for ``run_template`` placeholders beyond
            ``composition_key`` (e.g. ``hcl_conc``, ``hcl_dens``).

        Returns
        -------
        PhreeqcResult
            ``data`` is the selected output as a DataFrame.

        Raises
        ------
        KeyError
            If composition or kwargs are missing keys required by
            the respective templates.
        """
        phreeqc_input = self.get_phreeqc_input(composition, **kwargs)
        phreeqc.run(phreeqc_input)  # error handling encapsulado en el backend
        return PhreeqcResult(
            id=id_,
            task_name=self.task_name,
            data=_selected_output_to_df(phreeqc),
        )