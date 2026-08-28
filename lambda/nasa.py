from helper_functions import configure_logging, get_api_response, get_img, send_email

def lambda_handler(event, context):

    # Sets up the logger
    configure_logging()

    # Defines the Nasa API URL
    url = "https://api.nasa.gov/planetary/apod"

    # Fetches today's NASA APOD data
    # APOD = Astronomy Picture of the Day
    nasa_data = get_api_response(url).json()

    # Emails the title, photo and description
    send_email(nasa_data, get_img(nasa_data))