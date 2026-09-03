import logging
import os
from functools import lru_cache

import boto3
from errors import raise_error


def configure_logging() -> None:
    """Configure logging for both Lambda and local execution."""

    root = logging.getLogger()

    if root.handlers:
        # Set the logging for lambda
        root.setLevel(logging.INFO)
        for handler in root.handlers:
            handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    else:
        # Set the logging for local execution
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(message)s",
            handlers=[logging.StreamHandler()]
        )

@lru_cache(maxsize=1)
def get_params() -> dict[str, str]:
    """Retrieve and cache AWS SSM parameters for NASA API and email configuration.

    Fetches configuration values from AWS Parameter Store and caches the result
    for the lifetime of the process to minimize API calls.

    Returns:
        dict: Configuration dictionary with keys: nasa-api-key, gmail-password,
            email-from, email-to.

    Raises:
        ValueError: If any required SSM parameter is missing or inaccessible.
    """
    logging.info("Getting parameters from SSM")
    ssm = boto3.client("ssm")
    # Queries AWS Parameter Store for parameters
    prefix = os.environ.get("PARAM_PREFIX", "/depression-cherry/shared")
    param_names = ("nasa-api-key", "gmail-password", "email-from", "email-to")
    response = ssm.get_parameters(
        Names=[f"{prefix}/{name}" for name in param_names],
        WithDecryption=True
    )

    # Throw an error if one of the parameters hasn't been returned
    if response["InvalidParameters"]:
        error_msg = f"Missing SSM Parameters: {', '.join(response['InvalidParameters'])}"
        raise_error(ValueError, error_msg)

    # Put the parameters into a variable
    params = {
        p["Name"].split("/")[-1]: p["Value"]
        for p in response["Parameters"]
    }

    logging.info("All parameters have been retrieved")

    return params
