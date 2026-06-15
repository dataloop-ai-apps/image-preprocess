"""Shared ETL error recording helper.

Kept in its own module so it can be imported by both ``main`` (ServiceRunner)
and the extractor modules (``metadata_extractor``, ``thumbnail``) without
creating a circular import.
"""


def record_etl_error(item, stage: str, error: str, failed: bool = False) -> list:
    """Append an error to ``system.etl.errors`` and optionally set the failed flag.

    Returns the etl_errors list so callers can keep using the same reference.
    """
    system = item.metadata.setdefault('system', {})
    etl = system.setdefault('etl', {})
    etl_errors = etl.setdefault('errors', [])
    etl_errors.append({'stage': stage, 'error': error})
    if failed:
        etl['failed'] = True
        system.setdefault('imageEtl', {})['etl'] = {
            'failed': True,
            'errors': etl_errors,
        }
    return etl_errors
