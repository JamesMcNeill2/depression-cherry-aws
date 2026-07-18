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
    global _params
    if _params is None:
        if os.environ.get("PARAM_PREFIX"):
            ssm = boto3.client("ssm")
            response = ssm.get_parameters_by_path(
                Path=os.environ["PARAM_PREFIX"],
                WithDecryption=True
            )
            _params = {
                p["Name"].split("/")[-1]: p["Value"]
                for p in response["Parameters"]
            }
        else:
            from dotenv import load_dotenv
            load_dotenv()
            print(os.getenv("EMAIL_FROM"))
            _params = {
                "nasa-api-key": os.environ["NASA_API_KEY"],
                "gmail-password": os.environ["GMAIL_PASSWORD"],
                "email-from": os.environ["EMAIL_FROM"],
                "email-to": os.environ["EMAIL_TO"]
            }
    return _params

def get_api_response(url, max_retries=5):
    logging.info("Getting api key")
    api_key = os.getenv("NASA_API_KEY")
    if api_key is not None:
        logging.info("API_KEY has been retrieved")
        params = {"api_key": api_key}
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

def get_env_values():
    env_values = {
        "EMAIL_FROM": os.getenv("EMAIL_FROM"),
        "EMAIL_TO": os.getenv("EMAIL_TO"),
        "EMAIL_PASSWORD": os.getenv("GMAIL_PASSWORD")
    }
    
    missing = [name for name, value in env_values.items() if not value]
    if missing:
        raise ValueError(f"Missing required env values: {', '.join(missing)}")

    logging.info("All email env values retrieved")
    return env_values["EMAIL_FROM"], env_values["EMAIL_TO"], env_values["EMAIL_PASSWORD"]

def send_email(data, img_bytes):
    title, date, explanation = data["title"], data["date"], data["explanation"]
    formatted_date = datetime.strptime(date, "%Y-%m-%d").strftime("%d %B %Y")
    cid = "nasa_image"
    
    email_from, email_to, password = get_env_values()
    
    msg = EmailMessage()
    msg["Subject"] = f"{formatted_date}: {title}"
    msg["From"] = email_from
    msg["To"] = email_to
    # msg.set_content(explanation)
    # msg.add_attachment(img_bytes, maintype="image", subtype="jpeg", filename="nasa_img.jpg")
    
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
        server.login(email_from, password)
        server.send_message(msg)
        logging.info("Email sent")