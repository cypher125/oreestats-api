"""
Celery tasks for email service
Background tasks for sending emails, checking replies, etc.
"""
from celery import shared_task
from django.utils import timezone
from django.conf import settings
import logging

from .models import EmailSendQueue, GmailToken, EmailTrackingPixel, EmailEvent
from .gmail_client import GmailClientFactory
from .tracking import EmailTracker
from .utils import get_aisdr_connection

logger = logging.getLogger(__name__)


@shared_task
def process_email_queue():
    """
    Process emails in the send queue that are ready to be sent
    Runs every minute via Celery Beat
    """
    logger.info("Processing email send queue...")
    
    # Get emails ready to send
    ready_emails = EmailSendQueue.objects.filter(
        status='PENDING',
        scheduled_for__lte=timezone.now()
    ).order_by('scheduled_for')[:100]  # Batch of 100
    
    sent_count = 0
    failed_count = 0
    
    for email in ready_emails:
        try:
            # Check if client has reached daily limit
            if not check_client_daily_limit(email.client_id):
                logger.warning(f"Client {email.client_id} has reached daily email limit")
                continue
            
            # Update status to SENDING
            email.status = 'SENDING'
            email.save()
            
            # Get assigned mailbox for this lead (sticky assignment)
            # Same lead always uses same mailbox (Ben's requirement)
            from .utils import get_or_assign_mailbox_for_lead
            gmail_token = get_or_assign_mailbox_for_lead(email.lead_id, email.client_id)
            
            if not gmail_token:
                raise Exception(f"No active mailbox available for client {email.client_id}")
            
            # Create Gmail client from the assigned token
            gmail_client = GmailClientFactory.from_gmail_token(gmail_token)
            
            if not gmail_client:
                raise Exception(f"Failed to create Gmail client for token {gmail_token.email_address}")
            
            # Generate temporary message ID for tracking
            import uuid
            temp_message_id = str(uuid.uuid4())
            
            # Add tracking to email body
            html_with_tracking = EmailTracker.add_tracking_to_email(
                email.email_body,
                email.lead_id,
                temp_message_id,
                email.client_id
            )
            
            # Send email via Gmail
            result = gmail_client.send_email(
                to_email=email.recipient_email,  # Email passed from n8n (AISDR database)
                subject=email.email_subject,
                body_html=html_with_tracking
            )
            
            if result.get('success'):
                # Update email record
                email.status = 'SENT'
                email.message_id = result['message_id']
                email.sent_at = timezone.now()
                email.sent_from_email = gmail_token.email_address  # Track which mailbox sent this
                email.save()
                
                # Log SENT event
                EmailEvent.objects.create(
                    lead_id=email.lead_id,
                    client_id=email.client_id,
                    event_type='SENT',
                    message_id=result['message_id'],
                    thread_id=result.get('thread_id'),
                    sequence_number=email.sequence_number,
                    email_subject=email.email_subject
                )
                
                # Update lead metrics
                update_lead_sent_metrics(email.lead_id)
                
                # Increment client daily counter
                increment_client_daily_counter(email.client_id)
                
                sent_count += 1
                logger.info(f"Email sent successfully: {email.id}")
                
            else:
                raise Exception(result.get('error', 'Unknown error'))
            
        except Exception as e:
            email.attempts += 1
            email.last_error = str(e)
            
            if email.attempts >= email.max_attempts:
                email.status = 'FAILED'
                email.failed_at = timezone.now()
                logger.error(f"Email {email.id} failed after {email.attempts} attempts: {e}")
            else:
                email.status = 'PENDING'
                # Reschedule for 5 minutes later
                email.scheduled_for = timezone.now() + timezone.timedelta(minutes=5)
                logger.warning(f"Email {email.id} failed (attempt {email.attempts}), will retry: {e}")
            
            email.save()
            failed_count += 1
    
    logger.info(f"Email queue processed: {sent_count} sent, {failed_count} failed")
    return {'sent': sent_count, 'failed': failed_count}


@shared_task
def check_for_replies():
    """
    Check for replies to sent emails
    Runs every 15 minutes via Celery Beat
    """
    logger.info("Checking for email replies...")
    
    # Get all active Gmail tokens
    tokens = GmailToken.objects.filter(status='active')
    
    replies_found = 0
    
    for token in tokens:
        try:
            gmail_client = GmailClientFactory.from_gmail_token(token)
            
            if not gmail_client:
                continue
            
            # Get current history ID
            profile = gmail_client.get_profile()
            if not profile:
                continue
            
            current_history_id = profile.get('historyId')
            
            # Check for new messages since last check
            if token.last_history_id:
                history = gmail_client.list_history(token.last_history_id)
                
                for history_record in history:
                    messages_added = history_record.get('messagesAdded', [])
                    
                    for msg_added in messages_added:
                        message_id = msg_added['message']['id']
                        
                        # Get full message
                        message = gmail_client.get_message(message_id)
                        
                        if message:
                            # Check if this is a reply to one of our sent emails
                            process_potential_reply(message, token.client_id, gmail_client)
                            replies_found += 1
            
            # Update last_history_id
            token.last_history_id = current_history_id
            token.save()
            
        except Exception as e:
            logger.error(f"Error checking replies for client {token.client_id}: {e}")
    
    logger.info(f"Reply check complete: {replies_found} potential replies found")
    return {'replies_found': replies_found}


@shared_task
def reset_daily_limits():
    """
    Reset daily email counters for all clients
    Runs daily at midnight UTC via Celery Beat
    """
    logger.info("Resetting daily email limits...")
    
    with get_aisdr_connection().cursor() as cursor:
        cursor.execute("""
            UPDATE clients
            SET emails_sent_today = 0,
                last_reset_date = CURRENT_DATE
            WHERE last_reset_date < CURRENT_DATE
        """)
        
        reset_count = cursor.rowcount
    
    logger.info(f"Reset daily limits for {reset_count} clients")
    return {'reset_count': reset_count}


@shared_task
def cleanup_expired_pixels():
    """
    Delete expired tracking pixels
    Runs daily at 2 AM UTC via Celery Beat
    """
    logger.info("Cleaning up expired tracking pixels...")
    
    # Delete pixels older than 30 days
    cutoff_date = timezone.now() - timezone.timedelta(days=30)
    
    deleted_count, _ = EmailTrackingPixel.objects.filter(
        created_at__lt=cutoff_date
    ).delete()
    
    logger.info(f"Deleted {deleted_count} expired tracking pixels")
    return {'deleted_count': deleted_count}


@shared_task
def send_single_email(email_queue_id):
    """
    Send a single email immediately (for testing or manual triggering)
    
    Args:
        email_queue_id: UUID of EmailSendQueue record
    """
    try:
        email = EmailSendQueue.objects.get(id=email_queue_id)
        
        if email.status != 'PENDING':
            return {'error': f'Email status is {email.status}, not PENDING'}
        
        # Process just this email
        email.scheduled_for = timezone.now()
        email.save()
        
        # Trigger processing
        process_email_queue.delay()
        
        return {'success': True, 'email_id': str(email_queue_id)}
        
    except EmailSendQueue.DoesNotExist:
        return {'error': 'Email not found'}


# Helper functions

def check_client_daily_limit(client_id):
    """
    Check if client has reached their daily sending limit
    
    Args:
        client_id: UUID of client
    
    Returns:
        Boolean
    """
    with get_aisdr_connection().cursor() as cursor:
        cursor.execute("""
            SELECT 
                gmail_daily_limit,
                emails_sent_today,
                last_reset_date
            FROM clients
            WHERE id = %s
        """, [str(client_id)])
        
        row = cursor.fetchone()
        
        if not row:
            return False
        
        daily_limit, sent_today, last_reset = row
        
        # Reset if new day
        from datetime import date
        if last_reset < date.today():
            cursor.execute("""
                UPDATE clients
                SET emails_sent_today = 0,
                    last_reset_date = CURRENT_DATE
                WHERE id = %s
            """, [str(client_id)])
            return True
        
        # Check limit
        return sent_today < daily_limit


def increment_client_daily_counter(client_id):
    """
    Increment the client's daily email counter
    
    Args:
        client_id: UUID of client
    """
    with get_aisdr_connection().cursor() as cursor:
        cursor.execute("""
            UPDATE clients
            SET emails_sent_today = emails_sent_today + 1
            WHERE id = %s
        """, [str(client_id)])


def get_lead_email(lead_id):
    """
    Get lead's email address from database
    
    Args:
        lead_id: UUID of lead
    
    Returns:
        Email address string
    """
    with get_aisdr_connection().cursor() as cursor:
        cursor.execute("""
            SELECT email
            FROM leads
            WHERE id = %s
        """, [str(lead_id)])
        
        row = cursor.fetchone()
        return row[0] if row else None


def update_lead_sent_metrics(lead_id):
    """
    Update lead's sent email metrics
    
    Args:
        lead_id: UUID of lead
    """
    with get_aisdr_connection().cursor() as cursor:
        cursor.execute("""
            UPDATE leads
            SET emails_sent = emails_sent + 1,
                last_engagement_type = 'SENT',
                last_engagement_at = %s
            WHERE id = %s
        """, [timezone.now(), str(lead_id)])


def process_potential_reply(message, client_id, gmail_client):
    """
    Process a potential reply message
    
    Args:
        message: Gmail message object
        client_id: UUID of client
        gmail_client: GmailClient instance
    """
    try:
        from .gmail_client import parse_email_headers, get_email_body
        
        # Parse headers
        headers = parse_email_headers(message)
        thread_id = message.get('threadId')
        message_id = message.get('id')
        
        # Check if this thread contains any of our sent emails
        with get_aisdr_connection().cursor() as cursor:
            cursor.execute("""
                SELECT DISTINCT lead_id, message_id
                FROM email_events
                WHERE client_id = %s
                AND thread_id = %s
                AND event_type = 'SENT'
                LIMIT 1
            """, [str(client_id), thread_id])
            
            row = cursor.fetchone()
            
            if row:
                lead_id, original_message_id = row
                
                # Get email body
                body = get_email_body(message)
                snippet = message.get('snippet', '')
                
                # Create reply event
                EmailEvent.objects.create(
                    lead_id=lead_id,
                    client_id=client_id,
                    event_type='REPLY',
                    message_id=message_id,
                    thread_id=thread_id,
                    reply_content=body,
                    reply_snippet=snippet[:200]
                )
                
                # Update lead metrics
                cursor.execute("""
                    UPDATE leads
                    SET emails_replied = emails_replied + 1,
                        first_replied_at = COALESCE(first_replied_at, %s),
                        last_engagement_type = 'REPLY',
                        last_engagement_at = %s,
                        sequence_status = 'REPLIED'
                    WHERE id = %s
                """, [timezone.now(), timezone.now(), str(lead_id)])
                
                logger.info(f"Logged reply for lead {lead_id}")
                
    except Exception as e:
        logger.error(f"Error processing potential reply: {e}")
