from helper_functions import configure_logging, get_params, get_api_response, get_img, send_email

def lambda_handler(event, context):

    configure_logging()

    url = "https://api.nasa.gov/planetary/apod"
    nasa_data = get_api_response(url).json()
    send_email(nasa_data, get_img(nasa_data))