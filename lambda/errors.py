import logging
from typing import NoReturn


def raise_error(error_type: type[Exception], error_msg: str) -> NoReturn:
    """Log an error message and raise it as the given exception type.

    Args:
        error_type: Exception class to raise (e.g. ``ValueError``).
        error_msg: Error message to log and attach to the exception.

    Raises:
        error_type: Always.
    """
    logging.error(error_msg)
    raise error_type(error_msg)
