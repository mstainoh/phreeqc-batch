"""Batch execution of PHREEQC tasks.

Provides three batch runners organized by axis of variation:

- ``SolutionBatchRunner`` (Pattern A): compositions vary, parameters fixed.
  Input is a DataFrame with one row per composition. Constant parameters
  go in ``extra_keys``. Works only with ``SolutionTask``.

- ``ParamBatchRunner`` (Pattern B): compositions fixed, parameters vary.
  Compositions are passed once to the runner; the input DataFrame holds
  only the varying parameters. Works with both ``SolutionTask`` and
  ``MultiSolutionTask``.

- ``FullBatchRunner`` (Pattern C): everything varies. Input is a list of
  per-job dicts. Works with both ``SolutionTask`` and ``MultiSolutionTask``.

All three inherit from ``BaseBatchRunner``, which handles iteration, error
logging, and optional process-based parallel execution. Each worker process
creates and caches its own backend via a user-supplied factory.

Choosing a runner:

============  =============  =============  ====================
Pattern       Compositions   Parameters     Runner
============  =============  =============  ====================
A             Vary           Fixed          SolutionBatchRunner
B             Fixed          Vary           ParamBatchRunner
C             Vary           Vary           FullBatchRunner
============  =============  =============  ====================
"""
from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Iterator, Optional, Union

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
        Keyword arguments forwarded to every ``task.run`` call. Use this
        for values that are constant across the entire batch (e.g. fixed
        reaction amounts, shared mixing fractions). Per-job values belong
        in the input data.
    """

    task: BaseTask
    extra_keys: dict[str, Any] = field(default_factory=dict)

    @abstractmethod
    def iter_jobs(self, data: Any) -> Iterable[tuple[Any, dict[str, Any]]]:
        """Yield ``(id_, run_kwargs)`` pairs from input data.

        Parameters
        ----------
        data : any
            Subclass-specific input.

        Yields
        ------
        tuple of (id, dict)
        """
        ...

    def run(
        self,
        data: Any,
        phreeqc: PhreeqcBackend,
        stop_on_error: bool = False,
    ) -> list[PhreeqcResult]:
        """Execute the task over every job sequentially and collect results.

        A failed job is logged and skipped unless ``stop_on_error`` is True.

        Parameters
        ----------
        data : any
            Subclass-specific input.
        phreeqc : PhreeqcBackend
            Loaded backend instance shared across all jobs.
        stop_on_error : bool, default False
            If True, re-raises the first exception after logging it,
            aborting the batch. If False, failed jobs are skipped.

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
                if stop_on_error:
                    raise

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
        stop_on_error: bool = False,
    ) -> list[PhreeqcResult]:
        """Execute the task in parallel using a process pool.

        Each worker process creates and caches its own backend on first
        use (via ``backend_factory``), then reuses it for all subsequent
        jobs assigned to that worker. This amortizes the backend
        initialization cost (typically ~100ms and ~50MB per process).

        Parallel execution is only worth the overhead for batches of
        roughly 50+ jobs. For smaller batches, prefer ``run``.

        A failed job is logged and skipped unless ``stop_on_error`` is True.
        Note: when ``stop_on_error=True``, already-submitted futures are not
        cancelled — workers in flight complete normally, but no new jobs are
        submitted and the exception is re-raised after draining results.

        Parameters
        ----------
        data : any
            Subclass-specific input (same as ``run``).
        backend_factory : callable
            Zero-argument callable returning a fresh ``PhreeqcBackend``.
            Each worker process calls it once. Must be picklable —
            module-level functions and ``functools.partial`` work;
            lambdas and closures over local state do not.
        n_workers : int, optional
            Number of worker processes. Defaults to ``os.cpu_count()``.
        preserve_order : bool, default True
            If True, results are returned in the same order as ``iter_jobs``
            yields jobs. If False, results are returned as workers complete
            them (non-deterministic order, useful for progress monitoring).
        stop_on_error : bool, default False
            If True, re-raises the first exception encountered after logging
            it. Already-running workers are not interrupted.

        Returns
        -------
        list of PhreeqcResult

        Examples
        --------
        >>> from functools import partial
        >>> factory = partial(PhreeqpyBackend.create_from_database, Path("pitzer.dat"))
        >>> results = runner.run_parallel(df, backend_factory=factory, n_workers=4)
        """
        from concurrent.futures import as_completed

        jobs = list(self.iter_jobs(data))
        n = len(jobs)
        n_workers = n_workers or os.cpu_count() or 1

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
                        if stop_on_error:
                            raise
                results = [r for r in slots if r is not None]
            else:
                results = []
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
                        if stop_on_error:
                            raise

        logger.info(
            "[%s] parallel batch complete: %d/%d succeeded",
            self.task.task_name, len(results), n,
        )
        return results


# ---------------------------------------------------------------------------
# Pattern A: SolutionBatchRunner — compositions vary, parameters fixed
# ---------------------------------------------------------------------------

@dataclass
class SolutionBatchRunner(BaseBatchRunner):
    """Pattern A: vary compositions, fix parameters.

    Iterates over a DataFrame (or dict) of compositions, applying the same
    ``SolutionTask`` to each row. Any constant per-batch parameters go in
    ``extra_keys``. This is the standard path for processing a chemistry
    table where each row is one sample.

    Restricted to ``SolutionTask``. For multi-solution patterns where all
    compositions vary, use ``FullBatchRunner``.

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
        Keyword arguments forwarded to every ``task.run`` call. Use this
        for values that are constant across the batch.

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
    ) -> Iterator[tuple[Any, dict[str, Any]]]:
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
            for index, row in data.iterrows():
                id_ = row[self.id_col] if self.id_col else index
                composition = {c: row[c] for c in cols} if cols else {}
                yield id_, {"composition": composition}
        else:
            for id_, composition in data.items():
                yield id_, {"composition": composition}


# ---------------------------------------------------------------------------
# Pattern B: ParamBatchRunner — compositions fixed, parameters vary
# ---------------------------------------------------------------------------

@dataclass
class ParamBatchRunner(BaseBatchRunner):
    """Pattern B: fix compositions, vary parameters.

    Compositions are passed once to the runner; the input DataFrame holds
    only the per-job varying parameters (e.g. mixing fractions, target pH).
    The composition payload travels with the runner instance, so in
    parallel execution it is serialized once per worker instead of per job.

    Works with both ``SolutionTask`` and ``MultiSolutionTask``:

    - With ``SolutionTask``: pass a single composition dict via
      ``composition``.
    - With ``MultiSolutionTask``: pass a slot → composition mapping via
      ``compositions``.

    Exactly one of ``composition`` or ``compositions`` must be provided.

    Parameters
    ----------
    task : SolutionTask or MultiSolutionTask
        Task to execute on each parameter row.
    composition : dict, optional
        Single composition dict, used when task is a ``SolutionTask``.
    compositions : dict of str to dict, optional
        Mapping of slot key → composition dict, used when task is a
        ``MultiSolutionTask``. Must cover every key in
        ``task.composition_templates``.
    param_cols : list of str, optional
        DataFrame columns to forward as keyword arguments to ``task.run``.
        If ``None``, all columns except ``id_col`` are forwarded.
    id_col : str, optional
        Column to use as job identifier. If ``None``, uses the DataFrame
        index.
    extra_keys : dict, optional
        Keyword arguments forwarded to every ``task.run`` call.

    Examples
    --------
    Brine mixing with fixed end-members, varying mixing fractions
    (DataFrame input):

    >>> runner = ParamBatchRunner(
    ...     task=mix_task,
    ...     compositions={"solution_1": formation_water, "solution_2": recharge_water},
    ...     param_cols=["f1", "f2"],
    ...     id_col="mix_id",
    ... )
    >>> params_df = pd.DataFrame({
    ...     "mix_id": ["m10", "m50", "m90"],
    ...     "f1": [0.1, 0.5, 0.9],
    ...     "f2": [0.9, 0.5, 0.1],
    ... })
    >>> results = runner.run(params_df, phreeqc=backend)

    Same problem, programmatically built list of dicts:

    >>> jobs = [
    ...     {"id": f"mix_{int(f*100):02d}", "f1": f, "f2": 1 - f}
    ...     for f in [0.1, 0.5, 0.9]
    ... ]
    >>> runner = ParamBatchRunner(
    ...     task=mix_task,
    ...     compositions={"solution_1": formation_water, "solution_2": recharge_water},
    ... )
    >>> results = runner.run(jobs, phreeqc=backend)

    Acidification curve on a single brine, varying target pH:

    >>> runner = ParamBatchRunner(
    ...     task=acid_task,
    ...     composition=brine_sample,
    ...     param_cols=["ph_target"],
    ...     id_col="step",
    ... )
    """

    task: BaseTask = None  # type: ignore[assignment]
    composition: Optional[dict[str, Any]] = None
    compositions: Optional[dict[str, dict[str, Any]]] = None
    param_cols: Optional[list[str]] = None
    id_col: Optional[str] = None

    def __post_init__(self):
        """
        Check input argument consistency
        """
        # check that composition or compositions is provided, only one and not both
        if (self.composition is None) == (self.compositions is None):
            raise ValueError(
                "ParamBatchRunner requires exactly one of "
                "'composition' (for SolutionTask) or "
                "'compositions' (for MultiSolutionTask)."
            )
        
        # check that composition is provided for SolutionTask, compositions for MultisolutionTask
        is_multi = isinstance(self.task, MultiSolutionTask)
        if is_multi and self.composition is not None:
            raise TypeError(
                f"[{self.task.task_name}] MultiSolutionTask requires 'compositions' "
                f"(dict of slot → composition), not 'composition'."
            )
        if not is_multi and self.compositions is not None:
            raise TypeError(
                f"[{self.task.task_name}] SolutionTask requires 'composition' "
                f"(single composition dict), not 'compositions'."
            )

    def _build_run_kwargs(self, params: dict[str, Any]) -> dict[str, Any]:
        """Combine fixed compositions with varying parameters."""
        run_kwargs: dict[str, Any] = dict(params)
        if self.composition is not None:
            run_kwargs["composition"] = self.composition
        else:
            run_kwargs["compositions"] = self.compositions
        return run_kwargs

    def iter_jobs(
        self,
        data: Union[pd.DataFrame, list[dict[str, Any]]],
    ) -> Iterator[tuple[Any, dict[str, Any]]]:
        """Yield ``(id_, run_kwargs)`` pairs from a parameter source.

        Two input shapes are supported:

        - ``pd.DataFrame``: one row per job. Columns named in ``param_cols``
          (or all columns except ``id_col`` if ``param_cols`` is None)
          become keyword arguments to ``task.run``. The id comes from
          ``id_col`` if set, otherwise from the DataFrame index.

        - ``list[dict]``: one dict per job. Each dict's keys (excluding
          ``"id"``) become keyword arguments to ``task.run``. The id
          comes from the ``"id"`` key if present, otherwise from the list
          index. ``param_cols`` and ``id_col`` are ignored in this mode —
          the dicts already define the parameter shape.

        Parameters
        ----------
        data : pd.DataFrame or list of dict
            Per-job parameters.

        Yields
        ------
        tuple of (id, dict)
        """
        if isinstance(data, pd.DataFrame):
            if self.param_cols is not None:
                cols = list(self.param_cols)
            else:
                cols = [c for c in data.columns if c != self.id_col]
            for ix, row in data.iterrows():
                id_ = row[self.id_col] if self.id_col else ix
                params = {c: row[c] for c in cols}
                yield id_, self._build_run_kwargs(params)
        else:
            for i, job in enumerate(data):
                id_ = job.get("id", i)
                params = {k: v for k, v in job.items() if k != "id"}
                yield id_, self._build_run_kwargs(params)


# ---------------------------------------------------------------------------
# Pattern C: FullBatchRunner — everything varies
# ---------------------------------------------------------------------------

@dataclass
class FullBatchRunner(BaseBatchRunner):
    """Pattern C: vary compositions and parameters per job.

    Each job is a fully self-contained dict with its compositions and
    parameters. Use this when no axis of the problem is fixed across jobs
    — for example, screening a set of scenarios where both the brine
    compositions and the mixing parameters change together.

    Works with both ``SolutionTask`` and ``MultiSolutionTask``:

    - With ``SolutionTask``: each job dict has ``composition``.
    - With ``MultiSolutionTask``: each job dict has ``compositions``
      (slot → composition mapping).

    Parameters
    ----------
    task : SolutionTask or MultiSolutionTask
        Task to execute on each job.
    extra_keys : dict, optional
        Keyword arguments forwarded to every ``task.run`` call.

    Examples
    --------
    >>> jobs = [
    ...     {
    ...         "id": "scenario_A",
    ...         "compositions": {"solution_1": brine_a1, "solution_2": water_a},
    ...         "f1": 0.7, "f2": 0.3,
    ...     },
    ...     {
    ...         "id": "scenario_B",
    ...         "compositions": {"solution_1": brine_b1, "solution_2": water_b},
    ...         "f1": 0.4, "f2": 0.6,
    ...     },
    ... ]
    >>> runner = FullBatchRunner(task=mix_task)
    >>> results = runner.run(jobs, phreeqc=backend)
    """

    task: BaseTask = None  # type: ignore[assignment]

    def __post_init__(self):
        if not isinstance(self.task, (SolutionTask, MultiSolutionTask)):
            raise TypeError(
                f"FullBatchRunner requires SolutionTask or MultiSolutionTask, "
                f"got {type(self.task).__name__}."
            )
        self._composition_key = (
            "compositions" if isinstance(self.task, MultiSolutionTask) else "composition"
        )

    def iter_jobs(
        self,
        data: list[dict[str, Any]],
    ) -> Iterable[tuple[Any, dict[str, Any]]]:
        """Yield ``(id_, run_kwargs)`` pairs from a list of job dicts.

        Each job must contain the composition key appropriate to the task
        (``composition`` for ``SolutionTask``, ``compositions`` for
        ``MultiSolutionTask``). Optionally an ``id`` key; otherwise the
        list index is used.

        Parameters
        ----------
        data : list of dict
            Per-job dicts.

        Yields
        ------
        tuple of (id, dict)

        Raises
        ------
        ValueError
            If a job is missing the required composition key.
        """
        key = self._composition_key
        for i, job in enumerate(data):
            if key not in job:
                raise ValueError(
                    f"Job {i} missing required '{key}' key for "
                    f"{type(self.task).__name__}."
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