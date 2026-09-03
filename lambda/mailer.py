import html
import logging
import os
import smtplib
from datetime import datetime
from email.message import EmailMessage
from typing import Any

# Define the colours and styles used by the email
THEME = {
    "bg": "#0a0a0a",
    "card": "#161616",
    "heading": "#f5f5f5",
    "body_text": "#c4c4c4",
    "muted": "#8a8a8a",
    "link": "#d4d4d4",
    "border": "#2a2a2a",
    "sans": "Helvetica,Arial,sans-serif",
    "serif": "Georgia,'Times New Roman',serif",
}
# CID = Content ID
CID = "nasa_image"
LINK_STYLE = f"color:{THEME['link']}; text-decoration:none;"

def build_media_html(
    img_bytes: bytes | None,
    subtype: str | None,
    safe_title: str,
    is_video: bool,
    safe_url: str,
    copyright_holder: str,
) -> str:
    """Build the media section of the HTML email body."""

    # If a usable image is available, embed it inline in the email using a CID so the
    # HTML can render it without attaching a separate file; otherwise, fall back to a
    # direct link for videos or the original NASA page.
    img_style = "display:block; width:100%; height:auto; border-radius:4px;"
    p_style = f"font-family:{THEME['sans']}; font-size:14px;"

    if img_bytes and subtype:
        media_html = f'<img src="cid:{CID}" alt="{safe_title}" style="{img_style}">'
        if is_video:
            media_html += (
                f'<p style="margin:12px 0 0 0; {p_style}">'
                f'<a href="{safe_url}" style="{LINK_STYLE}">&#9654; Watch the video</a></p>'
            )
    else:
        label = "Watch the video" if is_video else "View on NASA"
        media_html = (
            f'<p style="margin:0; {p_style}">'
            f'<a href="{safe_url}" style="{LINK_STYLE}">{label}</a></p>'
        )

    # Add the copyright holder to the email if there is one
    if copyright_holder:
        credit_style = f"font-family:{THEME['sans']}; font-size:12px; color:{THEME['muted']};"
        media_html += (
            f'<p style="margin:8px 0 0 0; {credit_style}">'
            f'{html.escape(copyright_holder)}</p>'
        )

    return media_html

def render_html_body(
    safe_title: str,
    formatted_date: str,
    media_html: str,
    explanation: str,
    safe_url: str,
    link_style: str,
) -> str:
    """Render the full HTML email body for the APOD message."""

    html_body = f"""\
    <html>
    <body style="margin:0; padding:0; background-color:{THEME['bg']};">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
            style="background-color:{THEME['bg']}; padding:24px 12px;">
        <tr>
            <td align="center">
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
                    style="max-width:600px; background-color:{THEME['card']}; border-radius:8px;
                    overflow:hidden; border:1px solid {THEME['border']};">
                <tr>
                <td style="padding:28px 28px 8px 28px;">
                    <p style="margin:0 0 6px 0; font-family:{THEME['sans']};
                            font-size:12px; letter-spacing:1.5px; text-transform:uppercase;
                            color:{THEME['muted']};">
                    Astronomy Picture of the Day
                    </p>
                    <h1 style="margin:0 0 4px 0; font-family:{THEME['serif']};
                            font-size:26px; line-height:1.25; color:{THEME['heading']};
                            font-weight:normal;">
                    {safe_title}
                    </h1>
                    <p style="margin:0; font-family:{THEME['sans']};
                            font-size:13px; color:{THEME['muted']};">
                    {formatted_date}
                    </p>
                </td>
                </tr>
                <tr>
                <td style="padding:20px 28px;">
                    {media_html}
                </td>
                </tr>
                <tr>
                <td style="padding:0 28px 28px 28px;">
                    <p style="margin:0; font-family:{THEME['serif']};
                            font-size:16px; line-height:1.65; color:{THEME['body_text']};">
                    {html.escape(explanation)}
                    </p>
                    <p style="margin:24px 0 0 0; font-family:{THEME['sans']};
                            font-size:13px;">
                    <a href="{safe_url}" style="{link_style}">
                        View on NASA &rarr;
                    </a>
                    </p>
                </td>
                </tr>
            </table>
            </td>
        </tr>
        </table>
    </body>
    </html>
    """
    return html_body

def create_msg(
    nasa_data: dict[str, Any],
    img_bytes: bytes | None,
    subtype: str | None,
    params: dict[str, str],
) -> EmailMessage:
    """Build the email message for the APOD content and optional inline image."""

    # Extract and format info from nasa_data
    title, explanation, source_url = nasa_data["title"], nasa_data["explanation"], nasa_data["url"]
    formatted_date = datetime.strptime(nasa_data["date"], "%Y-%m-%d").strftime("%d %B %Y")
    copyright_holder = " ".join((nasa_data.get("copyright") or "").split())
    is_video = nasa_data.get("media_type") == "video"

    # Drop oversized images rather than failing at the SMTP layer
    max_attachment_bytes = 18 * 1024 * 1024
    if img_bytes and len(img_bytes) > max_attachment_bytes:
        logging.warning("Image too large to attach (%d bytes), linking instead", len(img_bytes))
        img_bytes, subtype = None, None

    safe_url = html.escape(source_url, quote=True)
    safe_title = html.escape(title, quote=True)

    # Define and format the data needed for the email
    msg = EmailMessage()
    env_name = os.environ.get("ENV_NAME", "Local")
    subject_prefix = "" if env_name == "Prod" else f"[{env_name}] "
    msg["Subject"] = f"{subject_prefix}{formatted_date}: {title}"
    msg["From"] = params["email-from"]
    msg["To"] = params["email-to"]

    # Plain-text part first, for clients that won't render HTML
    copyright_text = f"\n\n{copyright_holder}" if copyright_holder else ""
    msg.set_content(f"{title}{copyright_text}\n\n{source_url}\n\nExplanation\n\n{explanation}")

    link_style = f"color:{THEME['link']}; text-decoration:none;"
    media_html = build_media_html(img_bytes, subtype, safe_title, is_video, safe_url,
                                    copyright_holder)
    html_body = render_html_body(safe_title, formatted_date, media_html,
                                explanation, safe_url, link_style)
    msg.add_alternative(html_body, subtype="html")

    # Add the HTML body and attach the image inline using its CID
    if img_bytes and subtype:
        html_part = msg.get_payload()[-1]
        html_part.add_related(img_bytes, maintype="image", subtype=subtype, cid=f"<{CID}>")

    return msg

def send_email(msg: EmailMessage, params: dict[str, str]) -> None:
    """Send an already composed email through the configured Gmail SMTP server."""

    # Connect securely to Gmail, authenticate, and send the email
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as server:
        logging.info("Sending email")
        server.login(params["email-from"], params["gmail-password"])
        server.send_message(msg)
        logging.info("Email sent")
