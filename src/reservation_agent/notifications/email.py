"""Email notification service."""

import asyncio
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import aiosmtplib

from reservation_agent.core.config import SMTPConfig
from reservation_agent.core.exceptions import EmailDeliveryError
from reservation_agent.utils.logging import get_logger

logger = get_logger(__name__)


class EmailNotifier:
    """Sends email notifications for reservation events."""

    def __init__(self, config: SMTPConfig):
        self.config = config
        self._templates_dir = Path(__file__).parent / "templates"

    async def send_email(
        self,
        subject: str,
        body_text: str,
        body_html: str | None = None,
        to_addresses: list[str] | None = None,
    ) -> bool:
        """Send an email notification.

        Args:
            subject: Email subject line
            body_text: Plain text body
            body_html: Optional HTML body
            to_addresses: Recipients (defaults to config addresses)

        Returns:
            True if sent successfully
        """
        recipients = to_addresses or self.config.to_addresses
        if not recipients:
            logger.warning("no_recipients_configured")
            return False

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = self.config.from_address or self.config.username
        msg["To"] = ", ".join(recipients)

        # Add plain text part
        msg.attach(MIMEText(body_text, "plain"))

        # Add HTML part if provided
        if body_html:
            msg.attach(MIMEText(body_html, "html"))

        try:
            async with aiosmtplib.SMTP(
                hostname=self.config.host,
                port=self.config.port,
                use_tls=False,
                start_tls=True,
            ) as smtp:
                await smtp.login(self.config.username, self.config.password)
                await smtp.send_message(msg)

            logger.info(
                "email_sent",
                subject=subject,
                recipients=recipients,
            )
            return True

        except Exception as e:
            logger.error("email_send_failed", error=str(e))
            raise EmailDeliveryError(f"Failed to send email: {e}")

    async def send_booking_success(
        self,
        restaurant_name: str,
        date: str,
        time: str,
        party_size: int,
        confirmation_number: str | None = None,
    ) -> bool:
        """Send booking success notification."""
        subject = f"🎉 Reservation Confirmed: {restaurant_name}"

        body_text = f"""
Great news! Your reservation has been booked.

Restaurant: {restaurant_name}
Date: {date}
Time: {time}
Party Size: {party_size}
{f'Confirmation #: {confirmation_number}' if confirmation_number else ''}

This reservation was booked automatically by your Reservation Agent.
"""

        body_html = f"""
<!DOCTYPE html>
<html>
<head>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }}
        .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
        .header {{ background: #22c55e; color: white; padding: 20px; border-radius: 8px 8px 0 0; }}
        .content {{ background: #f9fafb; padding: 20px; border-radius: 0 0 8px 8px; }}
        .detail {{ margin: 10px 0; }}
        .label {{ color: #6b7280; font-size: 14px; }}
        .value {{ font-size: 18px; font-weight: 600; }}
        .confirmation {{ background: #fef3c7; padding: 15px; border-radius: 8px; margin-top: 15px; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1 style="margin: 0;">🎉 Reservation Confirmed!</h1>
        </div>
        <div class="content">
            <div class="detail">
                <div class="label">Restaurant</div>
                <div class="value">{restaurant_name}</div>
            </div>
            <div class="detail">
                <div class="label">Date & Time</div>
                <div class="value">{date} at {time}</div>
            </div>
            <div class="detail">
                <div class="label">Party Size</div>
                <div class="value">{party_size} guests</div>
            </div>
            {f'''
            <div class="confirmation">
                <div class="label">Confirmation Number</div>
                <div class="value">{confirmation_number}</div>
            </div>
            ''' if confirmation_number else ''}
            <p style="color: #6b7280; font-size: 12px; margin-top: 20px;">
                This reservation was booked automatically by your Reservation Agent.
            </p>
        </div>
    </div>
</body>
</html>
"""

        return await self.send_email(subject, body_text, body_html)

    async def send_booking_failed(
        self,
        restaurant_name: str,
        date: str,
        party_size: int,
        reason: str,
    ) -> bool:
        """Send booking failure notification."""
        subject = f"❌ Reservation Failed: {restaurant_name}"

        body_text = f"""
Unfortunately, we couldn't book your reservation.

Restaurant: {restaurant_name}
Date: {date}
Party Size: {party_size}

Reason: {reason}

We'll keep monitoring for cancellations.
"""

        body_html = f"""
<!DOCTYPE html>
<html>
<head>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }}
        .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
        .header {{ background: #ef4444; color: white; padding: 20px; border-radius: 8px 8px 0 0; }}
        .content {{ background: #f9fafb; padding: 20px; border-radius: 0 0 8px 8px; }}
        .detail {{ margin: 10px 0; }}
        .label {{ color: #6b7280; font-size: 14px; }}
        .value {{ font-size: 18px; font-weight: 600; }}
        .reason {{ background: #fee2e2; padding: 15px; border-radius: 8px; margin-top: 15px; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1 style="margin: 0;">❌ Reservation Failed</h1>
        </div>
        <div class="content">
            <div class="detail">
                <div class="label">Restaurant</div>
                <div class="value">{restaurant_name}</div>
            </div>
            <div class="detail">
                <div class="label">Date</div>
                <div class="value">{date}</div>
            </div>
            <div class="detail">
                <div class="label">Party Size</div>
                <div class="value">{party_size} guests</div>
            </div>
            <div class="reason">
                <div class="label">Reason</div>
                <div class="value" style="color: #dc2626;">{reason}</div>
            </div>
            <p style="color: #6b7280; font-size: 14px; margin-top: 20px;">
                We'll continue monitoring for cancellations and try again.
            </p>
        </div>
    </div>
</body>
</html>
"""

        return await self.send_email(subject, body_text, body_html)

    async def send_auth_required(self, platform: str) -> bool:
        """Send notification that re-authentication is needed."""
        subject = f"⚠️ Action Required: {platform.title()} Login Needed"

        body_text = f"""
Your {platform.title()} session has expired.

Please run the manual authentication script to log in again:

    python scripts/manual_auth.py --platform {platform}

The agent will resume monitoring once you've logged in.
"""

        body_html = f"""
<!DOCTYPE html>
<html>
<head>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }}
        .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
        .header {{ background: #f59e0b; color: white; padding: 20px; border-radius: 8px 8px 0 0; }}
        .content {{ background: #f9fafb; padding: 20px; border-radius: 0 0 8px 8px; }}
        code {{ background: #1f2937; color: #10b981; padding: 15px; display: block; border-radius: 8px; margin: 15px 0; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1 style="margin: 0;">⚠️ Login Required</h1>
        </div>
        <div class="content">
            <p>Your <strong>{platform.title()}</strong> session has expired.</p>
            <p>Please run the manual authentication script:</p>
            <code>python scripts/manual_auth.py --platform {platform}</code>
            <p style="color: #6b7280; font-size: 14px;">
                The agent will resume monitoring once you've logged in.
            </p>
        </div>
    </div>
</body>
</html>
"""

        return await self.send_email(subject, body_text, body_html)

    async def send_availability_alert(
        self,
        restaurant_name: str,
        date: str,
        available_times: list[str],
    ) -> bool:
        """Send notification about newly available slots."""
        subject = f"🔔 Slots Available: {restaurant_name}"

        times_list = ", ".join(available_times[:5])
        if len(available_times) > 5:
            times_list += f" (+{len(available_times) - 5} more)"

        body_text = f"""
New availability detected!

Restaurant: {restaurant_name}
Date: {date}
Available Times: {times_list}

The agent is attempting to book now.
"""

        return await self.send_email(subject, body_text)
