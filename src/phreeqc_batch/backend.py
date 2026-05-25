"""PHREEQC backend abstraction.

Decouples the task execution layer from any specific PHREEQC Python binding.
Defines the ``PhreeqcBackend`` Protocol that all backends must satisfy, plus
the default ``PhreeqpyBackend`` implementation wrapping ``phreeqpy``.

To implement a custom backend, subclass or duck-type ``PhreeqcBackend``::

    class MyBackend:
        def run(self, input: str) -> None:
            ...
        def get_selected_output_array(self) -> list:
            ...

Any object satisfying the Protocol can be passed to ``BaseTask.run`` subclasses
and runners ``.run`` method in place of the default backend.
"""
from __future__ import annotations

from pathlib import Path
from typing import Protocol, Union, runtime_checkable

import phreeqpy.iphreeqc.phreeqc_dll as phreeqc_mod


@runtime_checkable
class PhreeqcBackend(Protocol):
    """Protocol defining the interface any PHREEQC backend must satisfy.

    Implementations are responsible for executing a PHREEQC input string
    and exposing the selected output array. Error handling and any
    binding-specific details are encapsulated within the implementation.

    This Protocol is ``runtime_checkable``, so ``isinstance(obj, PhreeqcBackend)``
    works at runtime for duck-type validation.
    """

    def run(self, input: str) -> None:
        """Execute a PHREEQC input block.

        Parameters
        ----------
        input : str
            A complete, valid PHREEQC input string.

        Raises
        ------
        RuntimeError
            If PHREEQC fails to execute the input. Implementations should
            include the error detail and a truncated copy of the input in
            the exception message to aid debugging.
        """
        ...

    def get_selected_output_array(self) -> list:
        """Return the selected output from the last ``run`` call.

        Returns
        -------
        list
            Nested list where the first row contains column headers and
            subsequent rows contain output values, as produced by the
            PHREEQC ``SELECTED_OUTPUT`` block.
        """
        ...


class PhreeqpyBackend:
    """PHREEQC backend wrapping the ``phreeqpy`` IPhreeqc instance.

    Adapts ``phreeqpy.iphreeqc.phreeqc_dll.IPhreeqc`` to the
    ``PhreeqcBackend`` Protocol. Encapsulates phreeqpy-specific error
    reporting via ``get_error_string()``, so the calling layer remains
    backend-agnostic.

    Parameters
    ----------
    phreeqc : phreeqc_mod.IPhreeqc
        A loaded IPhreeqc instance (database already loaded).

    Examples
    --------
    >>> import phreeqpy.iphreeqc.phreeqc_dll as phreeqc_mod
    >>> raw = phreeqc_mod.IPhreeqc()
    >>> raw.load_database("pitzer.dat")
    >>> backend = PhreeqpyBackend(raw)
    >>> backend.run("SOLUTION 1\\npH 7\\nEND")
    """

    def __init__(self, phreeqc: phreeqc_mod.IPhreeqc) -> None:
        self._phreeqc = phreeqc

    @property
    def phreeqc(self):
        return self._phreeqc

    def run(self, input: str) -> None:
        """Execute a PHREEQC input block via phreeqpy.

        Calls ``run_string`` on the underlying IPhreeqc instance.
        On failure, retrieves the phreeqpy error string and raises a
        ``RuntimeError`` with both the original exception and the
        PHREEQC error detail.

        Parameters
        ----------
        input : str
            A complete, valid PHREEQC input string.

        Raises
        ------
        RuntimeError
            If ``run_string`` raises, wrapping the original exception
            and including the phreeqpy error string and the first 500
            characters of the input for debugging.
        """
        try:
            self._phreeqc.run_string(input)
        except Exception as e:
            error_str = ""
            try:
                error_str = self._phreeqc.get_error_string() or ""
            except Exception:
                pass
            raise RuntimeError(
                f"PHREEQC failed:\n{e}\n"
                f"--- error string ---\n{error_str}\n"
                f"--- input (first 500 chars) ---\n{input[:500]}"
            ) from e

    def get_selected_output_array(self) -> list:
        """Return the selected output from the last ``run`` call.

        Delegates to ``phreeqpy``'s ``get_selected_output_array()``.

        Returns
        -------
        list
            Nested list where the first row contains column headers and
            subsequent rows contain output values.
        """
        return self._phreeqc.get_selected_output_array()

    @staticmethod
    def create_from_database(db_path: Union[str,Path]) -> PhreeqpyBackend:
        """Create a ``PhreeqpyBackend`` with a loaded PHREEQC database.

        Convenience factory that instantiates a raw IPhreeqc object, loads
        the given database file, and wraps it in a ``PhreeqpyBackend``.

        Parameters
        ----------
        db_path : Path
            Path to a valid PHREEQC database file (e.g. ``pitzer.dat``).

        Returns
        -------
        PhreeqpyBackend
            Ready-to-use backend instance.

        Raises
        ------
        FileNotFoundError
            If ``db_path`` does not exist or is not a file.
        RuntimeError
            If IPhreeqc fails to load the database (e.g. malformed file,
            wrong encoding, or unsupported database format). Includes the
            IPhreeqc error string when available.

        Examples
        --------
        >>> backend = PhreeqpyBackend.create_from_database(Path("databases/pitzer.dat"))
        >>> backend.run("SOLUTION 1\\npH 7\\nEND")
        """
        db_path = Path(db_path)
        if not db_path.is_file():
            raise FileNotFoundError(
                f"PHREEQC database not found at: {db_path}"
            )

        phreeqc = phreeqc_mod.IPhreeqc()
        try:
            phreeqc.load_database(str(db_path))
        except Exception as e:
            error_str = ""
            try:
                error_str = phreeqc.get_error_string() or ""
            except Exception:
                pass
            raise RuntimeError(
                f"Failed to load PHREEQC database from {db_path}:\n{e}\n"
                f"--- error string ---\n{error_str}"
            ) from e

        return PhreeqpyBackend(phreeqc)