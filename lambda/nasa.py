from helper_functions import configure_logging, get_params, get_api_response, get_img_url, get_img, send_email

# Defines the Nasa API URL  
URL = "https://api.nasa.gov/planetary/apod"

def lambda_handler(event, context):

    # Sets up the logger and defines parameters
    configure_logging()
    params = get_params()

    # Fetches today's NASA APOD data
    # APOD = Astronomy Picture of the Day
    nasa_data = get_api_response(URL, params["nasa-api-key"]).json()

    img_bytes, subtype = get_img(get_img_url(nasa_data))

    # Emails the title, photo and description
    send_email(nasa_data, img_bytes, subtype, params)

    return {"status": "sent", "date": nasa_data.get("date")}

if __name__ =="__main__":
    lambda_handler({},{})
