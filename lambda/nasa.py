"""Lambda entry point for the daily NASA APOD email."""

from apod import build_api_params, get_api_response, get_img, get_img_url
from config import configure_logging, get_params
from mailer import create_msg, send_email

# Defines the Nasa API URL
# APOD = Astronomy Picture of the Day
APOD_URL = "https://api.nasa.gov/planetary/apod"

def lambda_handler(event, context):

    # Sets up the logger and defines parameters
    configure_logging()
    params = get_params()

    # Fetches today's NASA APOD data
    api_params = build_api_params(params["nasa-api-key"])
    nasa_data = get_api_response(APOD_URL, api_params).json()

    img_bytes, subtype = get_img(get_img_url(nasa_data))

    # Emails the title, photo and description
    msg = create_msg(nasa_data, img_bytes, subtype, params)
    send_email(msg, params)

    return {"status": "sent", "date": nasa_data.get("date")}

if __name__ == "__main__":
    lambda_handler({}, {})
