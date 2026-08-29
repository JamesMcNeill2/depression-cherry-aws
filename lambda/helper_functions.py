import boto3
import time
import html
import smtplib
import logging
from datetime import datetime
from email.message import EmailMessage
import requests
from functools import lru_cache

"""Utility helpers for the NASA image email workflow.

This module centralizes configuration lookup, NASA API access, image download,
and Gmail SMTP delivery. When running in AWS, values are loaded from AWS SSM
using the `PARAM_PREFIX` environment variable; otherwise the local `.env` file is
used.

Expected configuration keys:
- `NASA_API_KEY`
- `GMAIL_PASSWORD`
- `EMAIL_FROM`
- `EMAIL_TO`

When deployed to AWS, the same values are expected under the `PARAM_PREFIX`
namespace with names such as `{prefix}/nasa-api-key`.
"""

def configure_logging():
    """Configure the root logger to emit INFO-level console output."""
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
    logging.info("Getting parameters")

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

def get_api_response(url, api_key, max_retries=5):
    """Fetch a NASA API resource, retrying transient HTTP failures.

    Args:
        url: NASA API endpoint to request.
        api_key: NASA API key.
        max_retries: Maximum number of request attempts.

    Returns:
        requests.Response: The successful API response.
    """
    params = {"api_key": api_key, "thumbs": "true"}

    # Query the NASA API for up to max_retries amount of times
    for attempt in range(max_retries):
        logging.info(f"Running api request. Attempt: {attempt+1}")
        response = requests.get(url, params=params)
        status_code = response.status_code

        ## Only retry if returned status code is 429 or 5xx
        if status_code in (429, 500, 502, 503, 504):
            retry_after = response.headers.get("Retry-After")
            wait = int(retry_after) if retry_after else 2 ** attempt
            logging.info(f"{status_code} error: Retrying in {wait}s. Attempt {attempt+1}/{max_retries}")
            time.sleep(wait)
            continue

        # If response has been provided, return it
        response.raise_for_status()
        logging.info(f"Status Code: {response.status_code}")
        return response

    # Return error if API isn't reachable after max_retries
    error_msg = f"Unable to access api after max retries: {max_retries}"
    raise_error(Exception, error_msg)

def get_img_url(nasa_data):
    """Extract the image URL from NASA API response data.

    Args:
        nasa_data: Dictionary containing NASA API response with ``media_type``
            and either ``url`` (for images) or ``thumbnail_url`` (for videos).

    Returns:
        str | None: The image or thumbnail URL if available, otherwise None.
    """
    # If the media_type is image, return the image's source url
    media_type = nasa_data.get("media_type")
    if media_type == "image":
        return nasa_data.get("url")

    # If the media_type is video, return thumbnail image's url
    if media_type == "video":
        return nasa_data("thumbnail_url")

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

    logging.info(f"Determined content type: None")
    return None

def get_img(url):
    """Download the image identified by a NASA API response.

    Args:
        data: Response data containing the image ``url``.

    Returns:
        bytes: Downloaded image content.
    """
    logging.info("Getting image")
    url = data["url"]
    img_response = requests.get(url)
    img_response.raise_for_status()
    logging.info("Image received")
    return img_response.content

def send_email(data, img_bytes, params):
    """Send a NASA image and explanation through Gmail SMTP.

    Args:
        data: Dictionary with NASA image metadata, including ``title``, ``date``,
            and ``explanation``.
        img_bytes: Raw image bytes to embed inline in the email HTML body.
        params: Configuration dictionary containing Gmail and recipient values,
            including ``gmail-password``, ``email-from``, and ``email-to``.
    """
    # Extract and format the data
    title, date, explanation = data["title"], data["date"], data["explanation"]
    formatted_date = datetime.strptime(date, "%Y-%m-%d").strftime("%d %B %Y")

    # CID = Content ID
    cid = "nasa_image"

    # Retrieve the email parameters
    gmail_password = params["gmail-password"]
    email_from = params["email-from"]
    email_to = params["email-to"]

    # Define and format the data needed for the email
    msg = EmailMessage()
    msg["Subject"] = f"{formatted_date}: {title}"
    msg["From"] = email_from
    msg["To"] = email_to

    # Define the HTML body of the email
    html_body = f"""
      <html>
        <body>
        <h2>{title}</h2>
        <img src="cid:{cid}" style="max-width:100%; height:auto;">
        <h2>Explanation</h2>
        <p>{explanation}</p>
      </body>
    </html>
    """
    
    # Add the HTML body and attach the image inline using its CID
    msg.add_alternative(html_body, subtype="html")
    html_part = msg.get_payload()[-1]
    html_part.add_related(img_bytes, maintype="image", subtype="jpeg", cid=f"<{cid}>")


    # Connect securely to Gmail, authenticate, and send the email
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        logging.info("Sending email")
        server.login(email_from, gmail_password)
        server.send_message(msg)
        logging.info("Email sent")