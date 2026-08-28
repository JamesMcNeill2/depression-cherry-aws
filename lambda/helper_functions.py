import os
import boto3
import time
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

@lru_cache(maxsize=1)
def get_params():
    """Load and cache required parameters from SSM or the local environment.
    The result is cached for the lifetime of the process.

    Returns:
        dict: NASA API and email configuration values.

    Raises:
        ValueError: If a required parameter is missing.
    """
    logging.info("Getting parameters")

    if os.environ.get("PARAM_PREFIX"):
        logging.info("Getting parameters from SSM")
        ssm = boto3.client("ssm")
        # Queries AWS Parameter Store for parameters
        prefix = os.environ["PARAM_PREFIX"]
        names = [f"{prefix}/nasa-api-key", f"{prefix}/gmail-password",
                f"{prefix}/email-from", f"{prefix}/email-to"]
        response = ssm.get_parameters(Names=names, WithDecryption=True)
        # Caches returned parameters
        params = {
            p["Name"].split("/")[-1]: p["Value"]
            for p in response["Parameters"]
        }
    else:
        logging.info("Getting parameters from .env")
        # Queries anc caches .env for parameters
        from dotenv import load_dotenv
        load_dotenv()
        params = {
            "nasa-api-key": os.environ["NASA_API_KEY"],
            "gmail-password": os.environ["GMAIL_PASSWORD"],
            "email-from": os.environ["EMAIL_FROM"],
            "email-to": os.environ["EMAIL_TO"]
        }

    # Checks for missing parameters
    # Raises an error iif one or more are
    missing = [name for name, value in params.items() if not value]
    if missing:
        raise ValueError(f"Missing required env values: {', '.join(missing)}")
    
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
        
        response.raise_for_status()
        logging.info(f"Status Code: {response.status_code}")
        return response

    # Return error if API isn't reachable after max_retries
    error_msg = f"Unable to access api after max retries: {max_retries}"
    logging.error(error_msg)
    raise Exception(error_msg)

def get_img(data):
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