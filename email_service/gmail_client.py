"""
Gmail API Client Wrapper
Handles OAuth2 authentication and email sending via Gmail API
"""
import base64
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from django.conf import settings
from django.utils import timezone
import logging

logger = logging.getLogger(__name__)


class GmailClient:
    """
    Wrapper for Gmail API operations
    Handles OAuth2, sending emails, and monitoring for replies
    """
    
    SCOPES = [
        'https://www.googleapis.com/auth/gmail.send',
        'https://www.googleapis.com/auth/gmail.readonly',
        'https://www.googleapis.com/auth/gmail.modify'
    ]
    
    def __init__(self, access_token, refresh_token, token_expiry, client_id=None):
        """
        Initialize Gmail client with OAuth2 credentials
        
        Args:
            access_token: OAuth2 access token
            refresh_token: OAuth2 refresh token
            token_expiry: Token expiration datetime
            client_id: Optional client ID for logging
        """
        self.client_id = client_id
        self.credentials = Credentials(
            token=access_token,
            refresh_token=refresh_token,
            token_uri='https://oauth2.googleapis.com/token',
            client_id=settings.GOOGLE_CLIENT_ID,
            client_secret=settings.GOOGLE_CLIENT_SECRET,
            scopes=self.SCOPES
        )
        
        # Check if token needs refresh
        if self.credentials.expired and self.credentials.refresh_token:
            try:
                self.credentials.refresh(Request())
                logger.info(f"Token refreshed for client {client_id}")
            except Exception as e:
                logger.error(f"Failed to refresh token for client {client_id}: {e}")
                raise
        
        self.service = build('gmail', 'v1', credentials=self.credentials)
    
    def get_updated_credentials(self):
        """
        Get updated credentials after potential refresh
        Returns dict with access_token, refresh_token, and token_expiry
        """
        return {
            'access_token': self.credentials.token,
            'refresh_token': self.credentials.refresh_token,
            'token_expiry': self.credentials.expiry
        }
    
    def send_email(self, to_email, subject, body_html, tracking_pixel_url=None, 
                   tracked_links=None, from_name=None):
        """
        Send email via Gmail API with optional tracking
        
        Args:
            to_email: Recipient email address
            subject: Email subject line
            body_html: HTML body content
            tracking_pixel_url: URL for 1x1 tracking pixel (optional)
            tracked_links: Dict mapping original URLs to tracking URLs (optional)
            from_name: Custom from name (optional)
        
        Returns:
            Gmail message ID if successful, None otherwise
        """
        try:
            # Create MIME message
            message = MIMEMultipart('alternative')
            message['To'] = to_email
            message['Subject'] = subject
            
            if from_name:
                message['From'] = from_name
            
            # Replace links with tracking URLs
            if tracked_links:
                for original_url, tracking_url in tracked_links.items():
                    body_html = body_html.replace(original_url, tracking_url)
            
            # Add tracking pixel to body
            if tracking_pixel_url:
                pixel_html = f'<img src="{tracking_pixel_url}" width="1" height="1" style="display:none;" alt="" />'
                body_html += pixel_html
            
            # Attach HTML body
            html_part = MIMEText(body_html, 'html')
            message.attach(html_part)
            
            # Encode message
            raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode('utf-8')
            
            # Send via Gmail API
            send_result = self.service.users().messages().send(
                userId='me',
                body={'raw': raw_message}
            ).execute()
            
            message_id = send_result.get('id')
            thread_id = send_result.get('threadId')
            
            logger.info(f"Email sent successfully. Message ID: {message_id}")
            
            return {
                'message_id': message_id,
                'thread_id': thread_id,
                'success': True
            }
            
        except HttpError as error:
            logger.error(f'Gmail API error sending email: {error}')
            return {
                'success': False,
                'error': str(error),
                'error_code': error.resp.status if hasattr(error, 'resp') else None
            }
        except Exception as error:
            logger.error(f'Unexpected error sending email: {error}')
            return {
                'success': False,
                'error': str(error)
            }
    
    def get_message(self, message_id, format='full'):
        """
        Retrieve a message by ID
        
        Args:
            message_id: Gmail message ID
            format: Message format ('full', 'minimal', 'raw', 'metadata')
        
        Returns:
            Message object or None
        """
        try:
            message = self.service.users().messages().get(
                userId='me',
                id=message_id,
                format=format
            ).execute()
            return message
        except HttpError as error:
            logger.error(f'Error retrieving message {message_id}: {error}')
            return None
    
    def list_history(self, start_history_id, max_results=100):
        """
        List history changes (for reply detection)
        
        Args:
            start_history_id: History ID to start from
            max_results: Maximum number of results to return
        
        Returns:
            List of history records
        """
        try:
            history = self.service.users().history().list(
                userId='me',
                startHistoryId=start_history_id,
                maxResults=max_results,
                historyTypes=['messageAdded']
            ).execute()
            
            return history.get('history', [])
        except HttpError as error:
            # historyId not found error is common and expected
            if error.resp.status == 404:
                logger.debug(f'History ID {start_history_id} not found (expected for new accounts)')
                return []
            logger.error(f'Error listing history: {error}')
            return []
    
    def get_profile(self):
        """
        Get the user's Gmail profile
        
        Returns:
            Profile object with email address and historyId
        """
        try:
            profile = self.service.users().getProfile(userId='me').execute()
            return profile
        except HttpError as error:
            logger.error(f'Error getting profile: {error}')
            return None
    
    def watch_mailbox(self, topic_name):
        """
        Set up push notifications for mailbox changes
        Requires Google Cloud Pub/Sub topic
        
        Args:
            topic_name: Full Pub/Sub topic name (projects/{project}/topics/{topic})
        
        Returns:
            Watch response with historyId and expiration
        """
        try:
            request = {
                'labelIds': ['INBOX'],
                'topicName': topic_name
            }
            result = self.service.users().watch(
                userId='me',
                body=request
            ).execute()
            
            logger.info(f"Mailbox watch set up successfully. Expires: {result.get('expiration')}")
            return result
        except HttpError as error:
            logger.error(f'Error setting up mailbox watch: {error}')
            return None
    
    def check_for_replies(self, thread_id):
        """
        Check if a thread has received replies
        
        Args:
            thread_id: Gmail thread ID
        
        Returns:
            List of reply messages (excluding our sent messages)
        """
        try:
            thread = self.service.users().threads().get(
                userId='me',
                id=thread_id
            ).execute()
            
            messages = thread.get('messages', [])
            
            # Get our email address
            profile = self.get_profile()
            our_email = profile.get('emailAddress') if profile else None
            
            # Filter for replies (messages not from us)
            replies = []
            for msg in messages:
                headers = msg.get('payload', {}).get('headers', [])
                from_header = next((h['value'] for h in headers if h['name'].lower() == 'from'), '')
                
                # Check if message is not from us
                if our_email and our_email.lower() not in from_header.lower():
                    replies.append(msg)
            
            return replies
            
        except HttpError as error:
            logger.error(f'Error checking for replies in thread {thread_id}: {error}')
            return []
    
    def get_message_snippet(self, message_id):
        """
        Get a short snippet of a message (useful for reply preview)
        
        Args:
            message_id: Gmail message ID
        
        Returns:
            Message snippet text
        """
        try:
            message = self.service.users().messages().get(
                userId='me',
                id=message_id,
                format='minimal'
            ).execute()
            
            return message.get('snippet', '')
        except HttpError as error:
            logger.error(f'Error getting message snippet: {error}')
            return ''


class GmailClientFactory:
    """
    Factory class to create GmailClient instances from database tokens
    """
    
    @staticmethod
    def from_gmail_token(gmail_token):
        """
        Create GmailClient from GmailToken model instance
        
        Args:
            gmail_token: GmailToken model instance
        
        Returns:
            GmailClient instance
        """
        return GmailClient(
            access_token=gmail_token.access_token,
            refresh_token=gmail_token.refresh_token,
            token_expiry=gmail_token.token_expiry,
            client_id=str(gmail_token.client_id)
        )
    
    @staticmethod
    def from_client_id(client_id):
        """
        Create GmailClient from client_id by fetching token from database
        
        Args:
            client_id: UUID of the client
        
        Returns:
            GmailClient instance or None if token not found
        """
        from .models import GmailToken
        
        try:
            gmail_token = GmailToken.objects.get(
                client_id=client_id,
                status='active'
            )
            
            client = GmailClientFactory.from_gmail_token(gmail_token)
            
            # Update last_used_at
            gmail_token.last_used_at = timezone.now()
            
            # Update token if it was refreshed
            updated_creds = client.get_updated_credentials()
            if updated_creds['access_token'] != gmail_token.access_token:
                gmail_token.access_token = updated_creds['access_token']
                gmail_token.token_expiry = updated_creds['token_expiry']
            
            gmail_token.save()
            
            return client
            
        except GmailToken.DoesNotExist:
            logger.error(f'No active Gmail token found for client {client_id}')
            return None
        except Exception as e:
            logger.error(f'Error creating Gmail client for client {client_id}: {e}')
            return None


# Utility functions

def parse_email_headers(message):
    """
    Parse email headers from Gmail message
    
    Args:
        message: Gmail message object
    
    Returns:
        Dict with common headers (from, to, subject, date)
    """
    headers = message.get('payload', {}).get('headers', [])
    
    header_dict = {}
    for header in headers:
        name = header['name'].lower()
        if name in ['from', 'to', 'subject', 'date', 'message-id']:
            header_dict[name] = header['value']
    
    return header_dict


def get_email_body(message):
    """
    Extract email body from Gmail message
    
    Args:
        message: Gmail message object
    
    Returns:
        Email body as text
    """
    try:
        payload = message.get('payload', {})
        
        # Check for multipart message
        if 'parts' in payload:
            for part in payload['parts']:
                if part['mimeType'] == 'text/plain':
                    data = part['body'].get('data', '')
                    return base64.urlsafe_b64decode(data).decode('utf-8')
                elif part['mimeType'] == 'text/html':
                    data = part['body'].get('data', '')
                    return base64.urlsafe_b64decode(data).decode('utf-8')
        else:
            # Simple message
            data = payload.get('body', {}).get('data', '')
            if data:
                return base64.urlsafe_b64decode(data).decode('utf-8')
        
        return message.get('snippet', '')
        
    except Exception as e:
        logger.error(f'Error extracting email body: {e}')
        return message.get('snippet', '')
