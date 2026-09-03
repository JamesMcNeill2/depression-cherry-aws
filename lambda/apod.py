"""NASA APOD API access and image retrieval.

Fetches entries from api.nasa.gov, retrying transient failures with exponential
backoff. Handles both image and video entries; on video days the API returns
an embed URL, so the thumbnail is used instead, where one is available.
"""
import logging
import time
from typing import Any

import requests
from errors import raise_error


def retry_delay(response: requests.Response | None, attempt: int) -> int:
    """Calculate the delay time for retrying an API request.

    Args:
        response: The HTTP response object or None if request failed.
        attempt: The current attempt number (0-indexed).

    Returns:
        int: The number of seconds to wait before retrying, based on the
            Retry-After header if present, otherwise exponential backoff.
    """
    if response is not None:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                return max(0, int(retry_after))
            except ValueError:
                # Retry-After may be an HTTP-date rather than seconds
                pass
    return 2 ** attempt

def build_api_params(api_key: str) -> dict[str, str]:
    """Build the query parameters for the APOD endpoint.

    ``thumbs=true`` adds a ``thumbnail_url`` field on video days.
    """
    return {"api_key": api_key, "thumbs": "true"}


    Args:
        url: The API endpoint URL to query.
        api_key: The API key for authentication.
        max_retries: Maximum number of retry attempts. Defaults to 5.

    Returns:
        requests.Response: The HTTP response object on successful request.

    Raises:
        ValueError: If max_retries is less than 1.
        RuntimeError: If the API request fails after all retry attempts.
    """
    # Error out if supplied max_retries is less than 1
    if max_retries < 1:
        raise_error(ValueError, f"max_retries must be at least 1, got: {max_retries}")

    params = {"api_key": api_key, "thumbs": "true"}
    last_attempt = max_retries - 1

    # Query the NASA API for up to max_retries amount of times
    for attempt in range(max_retries):
        logging.info("Running api request. Attempt: %d/%d", attempt + 1, max_retries)

        try:
            # Call the api and retrieve status code
            response = requests.get(url, params=params, timeout=10)
            status_code = response.status_code
        # Handle no response received
        except requests.RequestException as exc:
            response, reason = None, f"Failed request ({exc})"
        else:
            # Only retry if returned status code is 429 or 5xx
            if status_code in (429, 500, 502, 503, 504):
                reason = f"{status_code} response"
            else:
                # Non-retryable (401, 404) errors raised here
                response.raise_for_status()
                # Return response if it has been received
                logging.info("Status Code: %d", status_code)
                return response

        # Raise error if api call hasn't worked by the last attempt
        if attempt == last_attempt:
            error_msg = f"NASA API: {reason} after {max_retries}/{max_retries} attempts"
            raise_error(RuntimeError, error_msg)

        # Define delay time (exponential backoff)
        # and log reason for failure
        wait = retry_delay(response, attempt)
        logging.warning("NASA API: %s. Retrying in %ds", reason, wait)
        time.sleep(wait)

def get_img_url(nasa_data: dict[str, Any]) -> str | None:
    """Return the image or thumbnail URL for a NASA media item.

    Args:
        nasa_data: NASA API response payload. It should include a ``media_type``
            field and either an ``url`` for images or a ``thumbnail_url`` for
            videos.

    Returns:
        str | None: The relevant image URL when one is present; otherwise,
        ``None``.
    """
    # If the media_type is image, return the image's source url
    media_type = nasa_data.get("media_type")
    if media_type == "image":
        logging.info("APOD is an image")
        return nasa_data.get("url")

    # If the media_type is video, return thumbnail image's url
    if media_type == "video":
        logging.info("APOD is a video")
        return nasa_data.get("thumbnail_url")

    # If the media_type is other, return None
    return None

def detect_subtype(content: bytes, content_type: str) -> str | None:
    """Determine the image subtype from the HTTP content type or file signature.

    Args:
        content: Raw image bytes to inspect when the content type is missing or
            ambiguous.
        content_type: HTTP content-type header value, such as ``image/jpeg``.

    Returns:
        str | None: The normalized subtype name (for example ``jpeg``, ``png``,
        or ``gif``) when it can be identified, otherwise ``None``.
    """
    logging.info("Determining content type")

    # Format content_type
    # Eg. image/jpeg -> maintype = image, subtype = jpeg
    maintype, _, subtype = content_type.partition("/")
    subtype = subtype.split(";")[0].strip().lower()

    # Return the subtype if it is jpeg, png or gif
    if maintype == "image" and subtype in {"jpeg", "png", "gif"}:
        logging.info("Determined content type: %s", subtype)
        return subtype

    # Defines the bytes each type of file starts with
    magic = (
        (b"\xff\xd8\xff", "jpeg"),
        (b"\x89PNG\r\n\x1a\n", "png"),
        (b"GIF87a", "gif"),
        (b"GIF89a", "gif")
    )

    # Backup for missing content_type
    # Uses the starting bytes for each file to define file type
    for signature, name in magic:
        if content.startswith(signature):
            logging.info("Determined content type: %s", name)
            return name

    logging.info("Determined content type: None")
    return None

def get_img(url: str | None) -> tuple[bytes | None, str | None]:
    """Download the image identified by a NASA API response.

    Args:
        url: URL of the image to download.

    Returns:
        tuple: Downloaded image content (bytes) and subtype (str),
        or (None, None) when no usable image exists.
    """
    # Check if a url has been passed in
    if not url:
        logging.info("No image url")
        return None, None

    logging.info("Getting image")
    img_response = requests.get(url, timeout=30)
    img_response.raise_for_status()

    # Verify the payload is a supported image type before attempting to embed it.
    # Some NASA responses may be HTML, JSON, or a non-image binary payload even
    # when the URL resolves successfully, so we reject anything we can't identify.
    subtype = detect_subtype(img_response.content, img_response.headers.get("Content-Type", ""))
    if subtype is None:
        logging.warning("Unrecognised image type at %s", url)
        return None, None

    logging.info("Image received (%s, %d bytes)", subtype, len(img_response.content))
    return img_response.content, subtype
