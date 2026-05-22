"""Batch execution of PHREEQC tasks.

Provides three batch runners and post-processing utilities:

- ``BaseBatchRunner``: abstract base — handles iteration, error logging,
  and optional parallel execution.
- ``SolutionBatchRunner``: runs a ``SolutionTask`` over a DataFrame or a
  dict of compositions.
- ``MultiSolutionBatchRunner``: runs a ``MultiSolutionTask`` over a list
  of per-job dicts.

Each runner exposes both ``run`` (sequential, shares one backend instance)
and ``run_parallel`` (process-based parallelism, each worker process
creates and caches its own backend).
"""
from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Optional, Union

import pandas as pd

from .backend import PhreeqcBackend
from .tasks import (
    BaseTask,
    MultiSolutionTask,
    PhreeqcResult,
    SolutionTask,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Worker-side helpers for parallel execution
# ---------------------------------------------------------------------------

# Per-process backend cache. Each worker process initializes its own backend
# once on first use and reuses it for all subsequent jobs in that process.
_WORKER_BACKEND: Optional[PhreeqcBackend] = None


def _get_worker_backend(backend_factory: Callable[[], PhreeqcBackend]) -> PhreeqcBackend:
    """Return this process's backend, creating it on first call."""
    global _WORKER_BACKEND
    if _WORKER_BACKEND is None:
        _WORKER_BACKEND = backend_factory()
    return _WORKER_BACKEND


def _run_one_job(
    task: BaseTask,
    backend_factory: Callable[[], PhreeqcBackend],
    id_: Any,
    run_kwargs: dict[str, Any],
    extra_keys: dict[str, Any],
) -> PhreeqcResult:
    """Execute one job in a worker process. Must be picklable."""
    backend = _get_worker_backend(backend_factory)
    return task.run(phreeqc=backend, id_=id_, **run_kwargs, **extra_keys)


# ---------------------------------------------------------------------------
# BaseBatchRunner
# ---------------------------------------------------------------------------

@dataclass
class BaseBatchRunner(ABC):
    """Abstract base for batch runners.

    Provides the iteration loop, error logging, and result collection.
    Subclasses define how input data is converted into per-job arguments
    via ``iter_jobs``.

    Parameters
    ----------
    task : BaseTask
        Task to execute on each job.
    extra_keys : dict, optional
        Keyword arguments forwarded to every ``task.run`` call (e.g.
        constant reaction parameters).
    """

    task: BaseTask
    extra_keys: dict[str, Any] = field(default_factory=dict)

    @abstractmethod
    def iter_jobs(self, data: Any) -> Iterable[tuple[Any, dict[str, Any]]]:
        """Yield ``(id_, run_kwargs)`` pairs from input data.

        Each ``run_kwargs`` is merged with ``self.extra_keys`` and
        passed to ``task.run`` as keyword arguments.

        Parameters
        ----------
        data : any
            Subclass-specific input.

        Yields
        ------
        tuple of (id, dict)
        """
        ...

    def run(self, data: Any, phreeqc: PhreeqcBackend) -> list[PhreeqcResult]:
        """Execute the task over every job and collect results.

        A failed job is logged and skipped — the batch continues.

        Parameters
        ----------
        data : any
            Subclass-specific input.
        phreeqc : PhreeqcBackend
            Loaded backend instance.

        Returns
        -------
        list of PhreeqcResult
        """
        jobs = list(self.iter_jobs(data))
        n = len(jobs)
        results: list[PhreeqcResult] = []

        for i, (id_, run_kwargs) in enumerate(jobs):
            try:
                result = self.task.run(
                    phreeqc=phreeqc,
                    id_=id_,
                    **run_kwargs,
                    **self.extra_keys,
                )
                results.append(result)
                logger.debug(
                    "[%s] %d/%d (id=%s) done",
                    self.task.task_name, i + 1, n, id_,
                )
            except Exception:
                logger.error(
                    "[%s] %d/%d (id=%s) failed",
                    self.task.task_name, i + 1, n, id_,
                    exc_info=True,
                )

        logger.info(
            "[%s] batch complete: %d/%d succeeded",
            self.task.task_name, len(results), n,
        )
        return results

    def run_parallel(
        self,
        data: Any,
        backend_factory: Callable[[], PhreeqcBackend],
        n_workers: Optional[int] = None,
        preserve_order: bool = True,
    ) -> list[PhreeqcResult]:
        """Execute the task in parallel using a process pool.

        Each worker process creates and caches its own backend on first
        use (via ``backend_factory``), then reuses it for all subsequent
        jobs assigned to that worker. This amortizes the backend
        initialization cost (typically ~100ms and ~50MB per process).

        Parallel execution is only worth the overhead for batches of
        roughly 50+ jobs. For smaller batches, prefer ``run``.

        A failed job is logged and skipped — the batch continues.

        Parameters
        ----------
        data : any
            Subclass-specific input (same as ``run``).
        backend_factory : callable
            Zero-argument callable that returns a fresh ``PhreeqcBackend``.
            Each worker process calls it once. Must be picklable —
            module-level functions and ``staticmethod`` work; lambdas
            and closures over local state do not.
        n_workers : int, optional
            Number of worker processes. Defaults to ``os.cpu_count()``.
        preserve_order : bool, default True
            If True, results are returned in the same order as ``iter_jobs``
            yields jobs (matches the sequential ``run``). If False, results
            are returned as workers complete them, which can reveal
            partial progress sooner but produces non-deterministic order.

        Returns
        -------
        list of PhreeqcResult

        Examples
        --------
        >>> from phreeqpy_tools import PhreeqpyBackend
        >>> def make_backend():
        ...     return PhreeqpyBackend.create_from_database(Path("pitzer.dat"))
        >>> results = runner.run_parallel(df, backend_factory=make_backend, n_workers=4)
        """
        jobs = list(self.iter_jobs(data))
        n = len(jobs)
        n_workers = n_workers or os.cpu_count() or 1
        results: list[PhreeqcResult] = []

        logger.info(
            "[%s] parallel batch: %d jobs on %d workers",
            self.task.task_name, n, n_workers,
        )

        with ProcessPoolExecutor(max_workers=n_workers) as executor:
            futures = {
                executor.submit(
                    _run_one_job,
                    self.task,
                    backend_factory,
                    id_,
                    run_kwargs,
                    self.extra_keys,
                ): (i, id_)
                for i, (id_, run_kwargs) in enumerate(jobs)
            }

            if preserve_order:
                # collect into a slot list, then strip None for failures
                slots: list[Optional[PhreeqcResult]] = [None] * n
                for future, (i, id_) in futures.items():
                    try:
                        slots[i] = future.result()
                        logger.debug(
                            "[%s] %d/%d (id=%s) done",
                            self.task.task_name, i + 1, n, id_,
                        )
                    except Exception:
                        logger.error(
                            "[%s] %d/%d (id=%s) failed",
                            self.task.task_name, i + 1, n, id_,
                            exc_info=True,
                        )
                results = [r for r in slots if r is not None]
            else:
                for future in as_completed(futures):
                    i, id_ = futures[future]
                    try:
                        results.append(future.result())
                        logger.debug(
                            "[%s] %d/%d (id=%s) done",
                            self.task.task_name, i + 1, n, id_,
                        )
                    except Exception:
                        logger.error(
                            "[%s] %d/%d (id=%s) failed",
                            self.task.task_name, i + 1, n, id_,
                            exc_info=True,
                        )

        logger.info(
            "[%s] parallel batch complete: %d/%d succeeded",
            self.task.task_name, len(results), n,
        )
        return results


# ---------------------------------------------------------------------------
# SolutionBatchRunner
# ---------------------------------------------------------------------------

@dataclass
class SolutionBatchRunner(BaseBatchRunner):
    """Batch runner for ``SolutionTask`` over a DataFrame or dict.

    The DataFrame case is the common path for processing chemistry tables:
    each row contributes one composition. The dict case is provided for
    pre-built compositions keyed by id.

    Parameters
    ----------
    task : SolutionTask
        Task to execute on each row.
    composition_cols : list of str, optional
        Columns to extract as composition keys. If ``None``, uses the
        task's composition template keys (recommended). Pass an explicit
        list only when the DataFrame has extra columns to ignore that
        are not in the template.
    id_col : str, optional
        Column to use as sample identifier. If ``None``, uses the
        DataFrame index.
    extra_keys : dict, optional
        Keyword arguments forwarded to every ``task.run`` call.

    Examples
    --------
    >>> runner = SolutionBatchRunner(task=density_task, id_col="sample_id")
    >>> results = runner.run(df, phreeqc=backend)
    """

    task: SolutionTask
    composition_cols: Optional[list[str]] = None
    id_col: Optional[str] = None

    def _resolve_composition_cols(self) -> set[str]:
        """Return the set of columns to extract as composition keys."""
        if self.composition_cols is not None:
            return set(self.composition_cols)
        if self.task.composition_template is None:
            return set()
        return self.task.composition_template.keys()

    def iter_jobs(
        self,
        data: Union[pd.DataFrame, dict[Any, dict[str, Any]]],
    ) -> Iterable[tuple[Any, dict[str, Any]]]:
        """Yield ``(id_, {"composition": dict})`` pairs.

        Parameters
        ----------
        data : pd.DataFrame or dict
            DataFrame with composition columns (and optionally ``id_col``),
            or a ``{id: composition_dict}`` mapping.

        Yields
        ------
        tuple of (id, dict)
        """
        if isinstance(data, pd.DataFrame):
            cols = self._resolve_composition_cols()
            for ix, row in data.iterrows():
                id_ = row[self.id_col] if self.id_col else ix
                composition = {c: row[c] for c in cols} if cols else {}
                yield id_, {"composition": composition}
        else:
            for id_, composition in data.items():
                yield id_, {"composition": composition}


# ---------------------------------------------------------------------------
# MultiSolutionBatchRunner
# ---------------------------------------------------------------------------

@dataclass
class MultiSolutionBatchRunner(BaseBatchRunner):
    """Batch runner for ``MultiSolutionTask`` over a list of job dicts.

    Each job is a dict containing:

    - ``id`` (optional): identifier propagated to the result.
    - ``compositions``: dict of placeholder key → composition dict,
      one entry per key in ``task.composition_templates``.
    - any extra keys: forwarded as ``**kwargs`` to ``task.run`` (e.g.
      mixing fractions, reaction amounts).

    Parameters
    ----------
    task : MultiSolutionTask
        Task to execute on each job.
    extra_keys : dict, optional
        Keyword arguments forwarded to every ``task.run`` call (constants
        shared across all jobs).

    Examples
    --------
    >>> jobs = [
    ...     {
    ...         "id": "mix_01",
    ...         "compositions": {"solution_1": brine_a, "solution_2": water},
    ...         "fraction_1": 0.5,
    ...         "fraction_2": 0.5,
    ...     },
    ...     ...
    ... ]
    >>> runner = MultiSolutionBatchRunner(task=mix_task)
    >>> results = runner.run(jobs, phreeqc=backend)
    """

    task: MultiSolutionTask

    def iter_jobs(
        self,
        data: list[dict[str, Any]],
    ) -> Iterable[tuple[Any, dict[str, Any]]]:
        """Yield ``(id_, run_kwargs)`` pairs from a list of job dicts.

        Parameters
        ----------
        data : list of dict
            Each dict must contain ``compositions`` and may contain ``id``
            and additional keyword arguments for ``task.run``.

        Yields
        ------
        tuple of (id, dict)

        Raises
        ------
        ValueError
            If a job is missing the ``compositions`` key.
        """
        for i, job in enumerate(data):
            if "compositions" not in job:
                raise ValueError(
                    f"Job {i} missing required 'compositions' key."
                )
            id_ = job.get("id", i)
            run_kwargs = {k: v for k, v in job.items() if k != "id"}
            yield id_, run_kwargs


# ---------------------------------------------------------------------------
# Result post-processing utilities
# ---------------------------------------------------------------------------

def results_to_scalar_df(
    results: list[PhreeqcResult],
    id_col: str = "id",
    scalar_key: Optional[str] = None,
) -> pd.DataFrame:
    """Flatten scalar results into a DataFrame.

    Parameters
    ----------
    results : list of PhreeqcResult
        Results from a batch run.
    id_col : str, default ``"id"``
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
        Results where ``data`` is a DataFrame (e.g. titration curves).

    Returns
    -------
    dict
        ``{id: DataFrame}`` mapping.
    """
    return {r.id: r.data for r in results}