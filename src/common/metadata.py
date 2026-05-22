"""Metadata filtering utilities to prevent internal field leakage."""

# Internal fields that should never be exposed in webhook payloads or external API responses
INTERNAL_FIELDS = {
    "task_id",
    "attempt_id",
    "internal_state",
    "worker_id",
    "execution_id",
    "internal_metadata",
    "run_id",
    "sandbox_id",
    "internal_status",
    "debug_info",
    "traceback",
    "internal_error",
    "system_metadata",
    "_internal",
    "_private",
}


def filter_internal_metadata(
    payload: dict,
    internal_fields: set = None,
) -> dict:
    """
    Remove internal fields from a payload dictionary.
    
    Args:
        payload: The payload dictionary to filter
        internal_fields: Optional custom set of internal fields to filter.
                       Defaults to INTERNAL_FIELDS if not provided.
    
    Returns:
        A new dictionary with internal fields removed.
    
    Example:
        >>> payload = {"task_id": "123", "status": "complete", "result": "ok"}
        >>> filter_internal_metadata(payload)
        {'status': 'complete', 'result': 'ok'}
    """
    if internal_fields is None:
        internal_fields = INTERNAL_FIELDS
    
    if not isinstance(payload, dict):
        return payload
    
    return {
        key: value
        for key, value in payload.items()
        if key not in internal_fields
    }


def filter_payload_recursive(
    payload: any,
    internal_fields: set = None,
) -> any:
    """
    Recursively filter internal fields from payloads, including nested dicts and lists.
    
    Args:
        payload: The payload to filter (dict, list, or other)
        internal_fields: Optional custom set of internal fields to filter.
    
    Returns:
        Filtered payload with the same structure.
    """
    if internal_fields is None:
        internal_fields = INTERNAL_FIELDS
    
    if isinstance(payload, dict):
        filtered = {}
        for key, value in payload.items():
            if key not in internal_fields:
                filtered[key] = filter_payload_recursive(value, internal_fields)
        return filtered
    elif isinstance(payload, list):
        return [filter_payload_recursive(item, internal_fields) for item in payload]
    else:
        return payload


def sanitize_webhook_payload(
    payload: dict,
    additional_internal_fields: set = None,
) -> dict:
    """
    Sanitize a webhook payload by removing all internal fields.
    This is the main function to call before delivering webhook payloads.
    
    Args:
        payload: The webhook payload to sanitize
        additional_internal_fields: Optional additional fields to treat as internal
    
    Returns:
        Sanitized payload safe for webhook delivery
    """
    fields = INTERNAL_FIELDS.copy()
    if additional_internal_fields:
        fields.update(additional_internal_fields)
    
    return filter_payload_recursive(payload, fields)
