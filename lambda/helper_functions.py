"""Utility helpers for the NASA image email workflow.

This module centralizes configuration lookup, NASA API access, image validation,
and email delivery. In AWS, values are loaded from AWS Systems Manager Parameter
Store under the shared project namespace (currently "/depression-cherry/shared");
this code does not read local `.env` files at runtime.

Expected SSM parameter names:
- `nasa-api-key`
- `gmail-password`
- `email-from`
- `email-to`

The functions in this module handle retrying transient NASA API failures,
checking that downloaded media is a supported image type before embedding it,
and sending a formatted HTML email through Gmail SMTP with an inline image when
available.
"""

import boto3
import time
import html
import smtplib
import logging
from datetime import datetime
from email.message import EmailMessage
import requests
from functools import lru_cache

def configure_logging():
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

def raise_error(error_type, error_msg):
    """Log an error message and raise it as the given exception type.

    Args:
        error_type: Exception class to raise (e.g. ``ValueError``).
        message: Error message to log and attach to the exception.

    Raises:
        error_type: Always.
    """
    logging.error(error_msg)
    raise error_type(error_msg)

@lru_cache(maxsize=1)
def get_params():
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
    param_names = ("nasa-api-key", "gmail-password", "email-from", "email-to")
    response = ssm.get_parameters(
        Names=[f"/depression-cherry/shared/{name}" for name in param_names],
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

def retry_delay(response, attempt):
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

def get_api_response(url, api_key, max_retries=5):
    # Error out if supplied max_retries is less than 1
    if max_retries < 1:
        raise_error(ValueError, f"max_retries must be at least 1, got: {max_retries}")

    params = {"api_key": api_key, "thumbs": "true"}
    last_attempt = max_retries - 1

    # Query the NASA API for up to max_retries amount of times
    for attempt in range(max_retries):
        logging.info(f"Running api request. Attempt: {attempt+1}/{max_retries}")

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
                logging.info(f"Status Code: {status_code}")
                return response

        # Raise error if api call hasn't worked by the last attempt
        if attempt == last_attempt:
            raise_error(RuntimeError, f"NASA API: {reason} after {max_retries}/{max_retries} attempts")

        # Define delay time (exponential backoff)
        # and log reason for failure
        wait = retry_delay(response, attempt)
        logging.warning(f"NASA API: {reason}. Retrying in {wait}s")
        time.sleep(wait)

    error_msg = f"No API request attempted (max_retries={max_retries})"
    raise_error(RuntimeError, error_msg)
    
def get_img_url(nasa_data):
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
        return nasa_data.get("url")

    # If the media_type is video, return thumbnail image's url
    if media_type == "video":
        return nasa_data.get("thumbnail_url")

    # If the media_type is other, return None
    return None

def detect_subtype(content, content_type):
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
        logging.info(f"Determined content type: {subtype}")
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
            logging.info(f"Determined content type: {name}")
            return name

    logging.info("Determined content type: None")
    return None

def get_img(url):
    """Download the image identified by a NASA API response.

    Args:
        data: Response data containing the image ``url``.

    Returns:
        bytes: Downloaded image content.
    """
    # Check if a url has been passed in
    if url is None:
        return None, None

    logging.info("Getting image")
    img_response = requests.get(url, timeout=30)
    img_response.raise_for_status()

    # Verify the payload is a supported image type before attempting to embed it.
    # Some NASA responses may be HTML, JSON, or a non-image binary payload even
    # when the URL resolves successfully, so we reject anything we can't identify.
    subtype = detect_subtype(img_response.content, img_response.headers.get("Content-Type", ""))
    if subtype is None:
        logging.warning(f"Unrecognised image type at {url}")
        return None, None

    logging.info("Image received (%s, %d bytes)", subtype, len(img_response.content))
    return img_response.content, subtype

def send_email(nasa_data, img_bytes, subtype, params):
    """Send a NASA image and explanation through Gmail SMTP.

    Args:
        nasa_data: Dictionary with NASA image metadata, including ``title``, ``date``,
            and ``explanation``.
        img_bytes: Raw image bytes to embed inline in the email HTML body.
        subtype: Image subtype (e.g., 'png', 'jpeg').
        params: Configuration dictionary containing Gmail and recipient values,
            including ``gmail-password``, ``email-from``, and ``email-to``.
    """
    # Extract and format info from nasa_data
    title, explanation, source_url = nasa_data["title"], nasa_data["explanation"], nasa_data["url"]
    formatted_date = datetime.strptime(nasa_data["date"], "%Y-%m-%d").strftime("%d %B %Y")
    is_video = nasa_data.get("media_type") == "video"

    # Drop oversized images rather than failing at the SMTP layer
    max_attachment_bytes = 18 * 1024 * 1024
    if img_bytes and len(img_bytes) > max_attachment_bytes:
        logging.warning("Image too large to attach (%d bytes), linking instead", len(img_bytes))
        img_bytes, subtype = None, None

    # CID = Content ID
    cid = "nasa_image"
    safe_url = html.escape(source_url, quote=True)

    # If a usable image is available, embed it inline in the email using a CID so the
    # HTML can render it without attaching a separate file; otherwise, fall back to a
    # direct link for videos or the original NASA page.
    if img_bytes and subtype:
        media_html = f'<img src="cid:{cid}" style="max-width:100%; height:auto;">'
        if is_video:
            media_html += f'<p><a href="{safe_url}">Watch the video</a></p>'
    else:
        label = "Watch the video" if is_video else "View on NASA"
        media_html = f'<p><a href="{safe_url}">{label}</a></p>'

    # Define and format the data needed for the email
    msg = EmailMessage()
    msg["Subject"] = f"{formatted_date}: {title}"
    msg["From"] = params["email-from"]
    msg["To"] = params["email-to"]

    # Plain-text part first, for clients that won't render HTML
    msg.set_content(f"{title}\n\n{source_url}\n\nExplanation\n\n{explanation}")

    # Define the HTML body of the email
    html_body = f"""
      <html>
        <body>
          <h2>{html.escape(title)}</h2>
          {media_html}
          <h2>Explanation</h2>
          <p>{html.escape(explanation)}</p>
        </body>
      </html>
    """
    msg.add_alternative(html_body, subtype="html")
    
    # Add the HTML body and attach the image inline using its CID
    if img_bytes and subtype:
        html_part = msg.get_payload()[-1]
        html_part.add_related(img_bytes, maintype="image", subtype=subtype, cid=f"<{cid}>")

    # Connect securely to Gmail, authenticate, and send the email
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as server:
        logging.info("Sending email")
        server.login(params["email-from"], params["gmail-password"])
        server.send_message(msg)
        logging.info("Email sent")