import os
import boto3
import time
import smtplib
import logging
from datetime import datetime
from email.message import EmailMessage
import requests

def configure_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.StreamHandler()]
    )

_params = None

def get_params():
    logging.info("Getting parameters")
    global _params
    if _params is None:
        if os.environ.get("PARAM_PREFIX"):
            logging.info("Getting parameters from SSM")
            ssm = boto3.client("ssm")
            prefix = os.environ["PARAM_PREFIX"]
            names = [f"{prefix}/nasa-api-key", f"{prefix}/gmail-password",
                    f"{prefix}/email-from", f"{prefix}/email-to"]
            response = ssm.get_parameters(Names=names, WithDecryption=True)
            _params = {
                p["Name"].split("/")[-1]: p["Value"]
                for p in response["Parameters"]
            }
        else:
            logging.info("Getting parameters from .env")
            from dotenv import load_dotenv
            load_dotenv()
            _params = {
                "nasa-api-key": os.environ["NASA_API_KEY"],
                "gmail-password": os.environ["GMAIL_PASSWORD"],
                "email-from": os.environ["EMAIL_FROM"],
                "email-to": os.environ["EMAIL_TO"]
            }
    
    missing = [name for name, value in _params.items() if not value]
    if missing:
        raise ValueError(f"Missing required env values: {', '.join(missing)}")
    
    logging.info("All parameters have been retrieved")
    
    return _params

def get_api_response(url, max_retries=5):
    logging.info("Getting api key")
    params = get_params()
    nasa_api_key = params["nasa-api-key"]
    if nasa_api_key is not None:
        logging.info("API_KEY has been retrieved")
        params = {"api_key": nasa_api_key}
    else:
        logging.error("API_KEY has not been retrieved")
        raise Exception("API_KEY has not been retrieved")

    for attempt in range(max_retries):
        logging.info(f"Running api request. Attempt: {attempt+1}")
        response = requests.get(url, params=params)
        status_code = response.status_code
        
        if status_code in (429, 500, 502, 503, 504):
            retry_after = response.headers.get("Retry-After")
            wait = int(retry_after) if retry_after else 2 ** attempt
            logging.info(f"{status_code} error: Retrying in {wait}s. Attempt {attempt+1}/{max_retries}")
            time.sleep(wait)
            continue
        
        response.raise_for_status()
        logging.info(f"Status Code: {response.status_code}")
        return response
        
    error_msg = f"Unable to access api after max retries: {max_retries}"
    logging.error(error_msg)
    raise Exception(error_msg)

def get_img(data):
    logging.info("Getting image")
    url = data["url"]
    img_response = requests.get(url)
    img_response.raise_for_status()
    logging.info("Image received")
    return img_response.content

def send_email(data, img_bytes):
    title, date, explanation = data["title"], data["date"], data["explanation"]
    formatted_date = datetime.strptime(date, "%Y-%m-%d").strftime("%d %B %Y")
    cid = "nasa_image"

    params = get_params()
    gmail_password = params["gmail-password"]
    email_from = params["email-from"]
    email_to = params["email-to"]
    
    msg = EmailMessage()
    msg["Subject"] = f"{formatted_date}: {title}"
    msg["From"] = email_from
    msg["To"] = email_to
    
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
    
    msg.add_alternative(html_body, subtype="html")
    
    html_part = msg.get_payload()[-1]
    html_part.add_related(img_bytes, maintype="image", subtype="jpeg", cid=f"<{cid}>")

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        logging.info("Sending email")
        server.login(email_from, gmail_password)
        server.send_message(msg)
        logging.info("Email sent")