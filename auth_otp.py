"""Email OTP helper. Configure SMTP; OTPs are short-lived and stored hashed by caller."""
import os, smtplib
from email.message import EmailMessage

def send_email_otp(recipient: str, code: str) -> None:
    host=os.getenv('SMTP_HOST'); port=int(os.getenv('SMTP_PORT','587'))
    username=os.getenv('SMTP_USERNAME'); password=os.getenv('SMTP_PASSWORD')
    sender=os.getenv('SMTP_FROM')
    if not all([host, username, password, sender]):
        raise RuntimeError('Email OTP is unavailable: configure SMTP_HOST, SMTP_USERNAME, SMTP_PASSWORD and SMTP_FROM.')
    msg=EmailMessage(); msg['Subject']='Your MediRefill sign-in code'; msg['From']=sender; msg['To']=recipient
    msg.set_content(f'Your MediRefill verification code is {code}. It expires in 5 minutes. Do not share this code.')
    with smtplib.SMTP(host,port,timeout=15) as server:
        server.starttls(); server.login(username,password); server.send_message(msg)
