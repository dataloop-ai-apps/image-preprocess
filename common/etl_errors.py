"""Shared ETL error recording helper.

Kept in a top-level ``common`` package so it can be imported by both the
image-preprocess and tiff-preprocess services without duplication.
"""


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
