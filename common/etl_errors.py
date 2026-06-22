"""Shared helpers for the image-preprocess and tiff-preprocess service runners.

Kept in a top-level ``common`` package so both services can import them without
duplication:

- :func:`record_etl_error` - append ETL errors to ``system.etl.errors``.
- :func:`active_logger` - prefer the Dataloop-injected logger when present.
- :func:`report_progress` - push a Dataloop progress update, never raising.
"""

import logging

_fallback_logger = logging.getLogger("common")


def record_etl_error(item, stage: str, error: str, failed: bool = False,
                     **extra) -> list:
    """Append an error to ``system.etl.errors`` and optionally set the failed flag.

    Extra keyword args are merged into the error dict (e.g. ``traceback=...``).
    Returns the etl_errors list so callers can keep using the same reference.
    """
    system = item.metadata.setdefault('system', {})
    etl = system.setdefault('etl', {})
    etl_errors = etl.setdefault('errors', [])
    entry = {'stage': stage, 'error': error}
    entry.update(extra)
    etl_errors.append(entry)
    if failed:
        etl['failed'] = True
        system.setdefault('imageEtl', {})['etl'] = {
            'failed': True,
            'errors': etl_errors,
        }
    return etl_errors


def active_logger(progress=None, context=None, default=None):
    """Return the Dataloop-injected logger when available, else ``default``.

    Dataloop injects a ``progress`` object (with a ``.logger``) and a
    ``context`` (also exposing ``.logger``) into service functions. Using them
    keeps stage logs correlated with the execution; callers pass their module
    logger as ``default`` so we fall back to it when running outside the
    platform (e.g. tests).
    """
    for source in (progress, context):
        candidate = getattr(source, "logger", None)
        if candidate is not None:
            return candidate
    return default if default is not None else _fallback_logger


def report_progress(progress, message=None, percent=None, logger=None):
    """Push a Dataloop progress update; never raises if progress is absent/odd."""
    if progress is None:
        return
    try:
        progress.update(message=message, progress=percent)
    except Exception:
        (logger or _fallback_logger).debug("progress.update failed", exc_info=True)
