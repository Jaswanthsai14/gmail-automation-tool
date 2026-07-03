from celery import Celery
from auth import service

import base64
from email.mime.text import MIMEText

celery = Celery(
    "gmail_agent",
    broker="redis://localhost:6379/0",
    backend="redis://localhost:6379/0"
)

@celery.task
def reply_gmail_task(sender, reply_text, subject, thread_id):
    
    message = MIMEText(reply_text)

    message["To"] = sender
    message["Subject"] = f"Re: {subject}"

    raw = base64.urlsafe_b64encode(
        message.as_bytes()
    ).decode()

    body = {
        "raw": raw,
        "threadId": thread_id
    }

    service.users().messages().send(
        userId="me",
        body=body
    ).execute()

    return f"Reply sent successfully to {sender}"
@celery.task
def send_gmail_task(sender, reply_text, subject):
    message = MIMEText(reply_text)

    message["To"] = sender
    message["Subject"] = f"Re: {subject}"

    raw = base64.urlsafe_b64encode(
        message.as_bytes()
    ).decode()

    body = {
        "raw": raw,
        
    }

    service.users().messages().send(
        userId="me",
        body=body
    ).execute()

   