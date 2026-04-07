"""Email Utility Module for ATMS"""
import os
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart


logger = logging.getLogger(__name__)


def send_email(to, subject, body_html):
    """
    Send an email via SMTP.

    Args:
        to (str): Recipient email address
        subject (str): Email subject
        body_html (str): HTML email body

    Returns:
        bool: True on success, False on failure or if not configured
    """
    # Check if SMTP is configured
    smtp_host = os.getenv("SMTP_HOST")
    smtp_port = os.getenv("SMTP_PORT")
    smtp_user = os.getenv("SMTP_USER")
    smtp_password = os.getenv("SMTP_PASSWORD")
    smtp_from = os.getenv("SMTP_FROM")

    if not all([smtp_host, smtp_port, smtp_user, smtp_password, smtp_from]):
        logger.info("Email not configured, skipping")
        return False

    try:
        # Create message
        message = MIMEMultipart("alternative")
        message["Subject"] = subject
        message["From"] = smtp_from
        message["To"] = to

        # Attach HTML body
        html_part = MIMEText(body_html, "html")
        message.attach(html_part)

        # Send email
        with smtplib.SMTP(smtp_host, int(smtp_port)) as server:
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.sendmail(smtp_from, to, message.as_string())

        logger.info(f"Email sent successfully to {to}")
        return True

    except Exception as e:
        logger.error(f"Failed to send email to {to}: {str(e)}")
        return False


def send_notification_email(user_email, title, message):
    """
    Send a notification email with ATMS branding.

    Args:
        user_email (str): Recipient email address
        title (str): Notification title (used as email subject)
        message (str): Notification message (used as email body)

    Returns:
        bool: True on success, False on failure
    """
    html_body = f"""
    <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; background-color: #f5f5f5; }}
                .container {{ max-width: 600px; margin: 0 auto; background-color: #ffffff; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
                .header {{ border-bottom: 3px solid #007bff; padding-bottom: 15px; margin-bottom: 20px; }}
                .logo {{ font-size: 24px; font-weight: bold; color: #007bff; }}
                .content {{ margin: 20px 0; line-height: 1.6; color: #333333; }}
                .title {{ font-size: 18px; font-weight: bold; color: #333333; margin-bottom: 10px; }}
                .message {{ color: #555555; }}
                .footer {{ border-top: 1px solid #eeeeee; padding-top: 15px; margin-top: 20px; font-size: 12px; color: #999999; text-align: center; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <div class="logo">ATMS</div>
                </div>
                <div class="content">
                    <div class="title">{title}</div>
                    <div class="message">{message}</div>
                </div>
                <div class="footer">
                    <p>This is an automated notification from ATMS. Please do not reply to this email.</p>
                </div>
            </div>
        </body>
    </html>
    """

    return send_email(user_email, title, html_body)
