from fastapi_mail import ConnectionConfig, FastMail, MessageSchema, MessageType
from app.core.config import settings 

conf = ConnectionConfig(
    MAIL_USERNAME = settings.MAIL_USERNAME,
    MAIL_PASSWORD = settings.MAIL_PASSWORD,
    MAIL_FROM = settings.MAIL_FROM,
    MAIL_PORT = settings.MAIL_PORT,
    MAIL_SERVER = settings.MAIL_SERVER,
    MAIL_STARTTLS = settings.MAIL_STARTTLS,
    MAIL_SSL_TLS = settings.MAIL_SSL_TLS,
    USE_CREDENTIALS = True,
    VALIDATE_CERTS = True,
    MAIL_FROM_NAME = settings.MAIL_FROM_NAME
)

async def send_otp_email(email_to: str, otp: str):
    html = f"""
    <div style="font-family: Arial, sans-serif; padding: 20px;">
        <h2 style="color: #F05A5E;">FamilySide Password Reset</h2>
        <p>Your 6-digit verification code is:</p>
        <div style="font-size: 32px; font-weight: bold; letter-spacing: 5px; color: #333;">{otp}</div>
        <p>This code will expire in 15 minutes.</p>
        <p>If you didn't request this, please ignore this email.</p>
    </div>
    """
    message = MessageSchema(
        subject="FamilySide Password Reset Code",
        recipients=[email_to],
        body=html,
        subtype=MessageType.html
    )
    fm = FastMail(conf)
    await fm.send_message(message)

async def send_signup_otp_email(email_to: str, otp: str):
    html = f"""
    <div style="font-family: Arial, sans-serif; padding: 20px;">
        <h2 style="color: #F05A5E;">Welcome to FamilySide!</h2>
        <p>Your email verification code is:</p>
        <div style="font-size: 32px; font-weight: bold; letter-spacing: 5px; color: #333;">{otp}</div>
        <p>This code will expire in 15 minutes.</p>
    </div>
    """
    message = MessageSchema(
        subject="FamilySide Email Verification",
        recipients=[email_to],
        body=html,
        subtype=MessageType.html
    )
    fm = FastMail(conf)
    await fm.send_message(message)

async def send_support_alert_to_admin(user_email: str, problem: str):
    html = f"""
    <h3>New Support Request Received</h3>
    <p><b>From:</b> {user_email}</p>
    <p><b>Issue:</b> {problem}</p>
    <hr>
    <p>Please log in to the Admin Dashboard to reply to this user.</p>
    """
    message = MessageSchema(
        subject=f"URGENT: Support Request from {user_email}",
        recipients=[settings.MAIL_USERNAME], # Sends the alert to YOUR email
        body=html,
        subtype=MessageType.html
    )
    fm = FastMail(conf)
    await fm.send_message(message)