"""Batch execution of PHREEQC tasks over DataFrames.

Provides ``PhreeqcBatchRunner`` for applying a ``PhreeqcTask`` row by row
on a DataFrame, collecting ``PhreeqcResult`` objects, and utility functions
for creating PHREEQC instances and post-processing results.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional, Union

import pandas as pd

from .backend import PhreeqcBackend

from .composition import BaseComposition

from .tasks import PhreeqcTask, PhreeqcResult

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
@dataclass
class PhreeqcBatchRunner:
    """Apply a ``PhreeqcTask`` row by row over a DataFrame.

    The runner handles iteration, composition extraction, instance
    management, and error logging. The DataFrame is expected to arrive
    clean — no renaming or filtering is done here.

    Parameters
    ----------
    task : PhreeqcTask
        Task to execute on each row.
    composition_cols : list of str. Optional
        Columns mapped to composition fields. Passed directly
        to ``task.run`` as a dict. If None, will take all dataframe columns
    id_col : str, optional. Default None
        Column in the DataFrame used as the sample identifier. if None, will use df.index
    kwargs : dict, optional
        Extra keyword arguments forwarded to every ``task.run`` call
        (e.g. ``hcl_conc``, ``hcl_dens``).

    Examples
    --------
    >>> runner = PhreeqcBatchRunner(
    ...     task=density_task,
    ...     id_col="id",
    ...     composition_cols=["Na", "Cl", "pH", "temp", "density"],
    ... )
    >>> results = runner.run(df)
    """

    task: PhreeqcTask
    composition_cols: Optional[list[str]] = None
    id_col: Optional[str] = None
    extra_keys: dict[str, Any] = field(default_factory=dict)

    def get_phreeqc_input(self, composition, **kwargs) -> str:
        """
        wrapper for self.task.get_phreeqc_input
        """
        return self.task.get_phreeqc_input(composition, **kwargs)

    def get_composition_dict(self, data: pd.DataFrame) -> dict[Any, dict[str, Any]]:
        """
        """
        out = dict()
        for (ix, row) in data.iterrows():
            id_ = row[self.id_col] if self.id_col else ix
            composition = {col: row[col] for col in self.composition_cols or data.columns}
            out[id_] = composition
        return out

    def run(self, data: Union[pd.DataFrame, dict[Any, Union[dict[str, Any], BaseComposition]]],
            phreeqc: PhreeqcBackend) -> list[PhreeqcResult]:
        """Execute the task on every row of the DataFrame.

        Creates a PHREEQC instance if none was injected. Logs progress
        at ``DEBUG`` level and errors at ``ERROR`` level. A failed row
        does not stop the batch — it is logged and skipped.

        Parameters
        ----------
        data : pd.DataFrame
            Input DataFrame with ``id_col`` and all ``composition_cols``.
        phreeqc : phreeqc_mod.IPhreeqc
            Loaded IPhreeqc instance.

        Returns
        -------
        list of PhreeqcResult
            One result per successfully processed row.
        """
        n = len(data)
        results = []

        if isinstance(data, pd.DataFrame):
            composition_dict = self.get_composition_dict(data)
        else:
            composition_dict = data

        for i, (id_, composition) in enumerate(composition_dict.items()):
            try:
                result = self.task.run(
                    composition=composition, id_=id_, phreeqc=phreeqc, **self.extra_keys
                )
                results.append(result)
            except Exception:
                logger.error(
                    "[%s] row %d/%d (id=%s) failed", self.task.task_name, i + 1, n, id_,
                    exc_info=True,
                )
                continue

            logger.debug(
                "[%s] row %d/%d (id=%s) done", self.task.task_name, i + 1, n, id_,
            )

        logger.info(
            "[%s] batch complete: %d/%d rows succeeded",
            self.task.task_name, len(results), n,
        )
        return results


# ---------------------------------------------------------------------------
# Result post-processing utilities
# ---------------------------------------------------------------------------

def results_to_scalar_df(
    results: list[PhreeqcResult],
    id_col: str = "id",
    scalar_key: str | None = None,
) -> pd.DataFrame:
    """Flatten scalar results into a DataFrame.

    Parameters
    ----------
    results : list of PhreeqcResult
        Results from a batch run.
    id_col : str, default "id"
        Column name for the sample identifier.
    scalar_key : str, optional
        If ``None``, uses ``result.data`` directly as the value.
        If a string, extracts ``result.metadata[scalar_key]``.

    Returns
    -------
    pd.DataFrame
        One row per result with columns ``[id_col, value_col]``.
    """
    rows = []
    for r in results:
        value = r.metadata[scalar_key] if scalar_key else r.data
        value_col = scalar_key or r.task_name
        rows.append({id_col: r.id, value_col: value})
    return pd.DataFrame(rows)


def results_to_curve_dict(
    results: list[PhreeqcResult],
) -> dict[Any, pd.DataFrame]:
    """Collect DataFrame results into a dict keyed by sample id.

    Parameters
    ----------
    results : list of PhreeqcResult
        Results where ``data`` is a DataFrame (e.g. acidification curves).

    Returns
    -------
    dict
        ``{id: DataFrame}`` mapping.
    """
    return {r.id: r.data for r in results}