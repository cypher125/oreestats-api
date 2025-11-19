"""
Django models for email tracking and management
Corresponds to tables created in DATABASE_SCHEMA_GMAIL.sql
"""
from django.db import models
import uuid
from django.utils import timezone


class EmailEvent(models.Model):
    """
    Tracks all email events (sent, opened, clicked, replied, bounced)
    Table: email_events
    """
    EVENT_TYPES = [
        ('SENT', 'Sent'),
        ('OPEN', 'Open'),
        ('CLICK', 'Click'),
        ('REPLY', 'Reply'),
        ('BOUNCE', 'Bounce')
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    lead_id = models.UUIDField(db_index=True)
    client_id = models.UUIDField(db_index=True)
    
    event_type = models.CharField(max_length=10, choices=EVENT_TYPES, db_index=True)
    
    # Gmail identifiers
    message_id = models.CharField(max_length=255, db_index=True)
    thread_id = models.CharField(max_length=255, blank=True, null=True)
    
    # Email info
    sequence_number = models.IntegerField(null=True, blank=True)
    email_subject = models.TextField(blank=True)
    
    # Tracking data (for OPEN and CLICK events)
    url = models.TextField(blank=True, null=True)  # Destination URL for clicks
    user_agent = models.TextField(blank=True, null=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    device_type = models.CharField(max_length=50, blank=True)
    
    # Reply data (for REPLY events)
    reply_content = models.TextField(blank=True, null=True)
    reply_snippet = models.TextField(blank=True, null=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    
    # Additional metadata
    metadata = models.JSONField(default=dict, blank=True)
    
    class Meta:
        db_table = 'email_events'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['lead_id', 'event_type']),
            models.Index(fields=['message_id', 'created_at'])
        ]
    
    def __str__(self):
        return f"{self.event_type} - {self.message_id} - {self.created_at}"


class EmailTrackingPixel(models.Model):
    """
    Maps unique pixel IDs to emails for open tracking
    Table: email_tracking_pixels
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    lead_id = models.UUIDField(db_index=True)
    message_id = models.CharField(max_length=255)
    
    pixel_id = models.CharField(max_length=100, unique=True, db_index=True)
    
    opened = models.BooleanField(default=False)
    open_count = models.IntegerField(default=0)
    first_opened_at = models.DateTimeField(null=True, blank=True)
    last_opened_at = models.DateTimeField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        db_table = 'email_tracking_pixels'
    
    def __str__(self):
        return f"Pixel {self.pixel_id} - Opened: {self.opened}"


class EmailClickTracking(models.Model):
    """
    Maps unique click IDs to destination URLs
    Table: email_click_tracking
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    lead_id = models.UUIDField(db_index=True)
    message_id = models.CharField(max_length=255)
    
    click_id = models.CharField(max_length=100, unique=True, db_index=True)
    destination_url = models.TextField()
    
    click_count = models.IntegerField(default=0)
    first_clicked_at = models.DateTimeField(null=True, blank=True)
    last_clicked_at = models.DateTimeField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'email_click_tracking'
    
    def __str__(self):
        return f"Click {self.click_id} - {self.destination_url[:50]}"


class GmailToken(models.Model):
    """
    Stores OAuth2 credentials for each client's Gmail account
    Table: gmail_tokens
    NOTE: In production, access_token and refresh_token should be encrypted
    """
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('expired', 'Expired'),
        ('revoked', 'Revoked')
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    client_id = models.UUIDField(db_index=True)  # REMOVED unique=True to allow multiple mailboxes per client
    
    email_address = models.EmailField()
    gmail_user_id = models.CharField(max_length=255, blank=True)
    
    # OAuth2 credentials (should be encrypted in production)
    access_token = models.TextField()
    refresh_token = models.TextField()
    token_expiry = models.DateTimeField()
    
    scopes = models.JSONField(default=list, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    
    # For reply detection
    last_history_id = models.CharField(max_length=100, blank=True)
    
    # Multi-mailbox rotation support
    send_priority = models.IntegerField(default=1, help_text="Priority order for mailbox rotation")
    daily_send_count = models.IntegerField(default=0, help_text="Emails sent today from this mailbox")
    daily_send_limit = models.IntegerField(default=400, help_text="Gmail daily sending limit per mailbox")
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_used_at = models.DateTimeField(null=True, blank=True, help_text="Last time this mailbox was used to send")
    
    class Meta:
        db_table = 'gmail_tokens'
        # Ensure same email can't be added twice for same client
        constraints = [
            models.UniqueConstraint(
                fields=['client_id', 'email_address'],
                name='unique_client_email_combo'
            )
        ]
    
    def __str__(self):
        return f"{self.email_address} ({self.client_id}) - {self.status}"


class EmailSendQueue(models.Model):
    """
    Queue for emails to be sent (supports scheduling & retry logic)
    Table: email_send_queue
    """
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('SENDING', 'Sending'),
        ('SENT', 'Sent'),
        ('FAILED', 'Failed'),
        ('CANCELLED', 'Cancelled')
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    lead_id = models.UUIDField(db_index=True)
    client_id = models.UUIDField(db_index=True)
    
    # Recipient info (from external AISDR database)
    recipient_email = models.EmailField(
        help_text="Email address to send to (from AISDR database)",
        default='unknown@placeholder.com'  # Temporary default for migration
    )
    
    # Email content
    email_subject = models.TextField()
    email_body = models.TextField()
    email_cta = models.TextField(blank=True)
    
    # Sequence info
    sequence_number = models.IntegerField()
    send_delay_days = models.IntegerField(default=0)
    
    # Scheduling
    scheduled_for = models.DateTimeField(db_index=True)
    
    # Status tracking
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING', db_index=True)
    attempts = models.IntegerField(default=0)
    max_attempts = models.IntegerField(default=3)
    
    # Error tracking
    last_error = models.TextField(blank=True, null=True)
    failed_at = models.DateTimeField(null=True, blank=True)
    
    # Result after sending
    message_id = models.CharField(max_length=255, blank=True, null=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    sent_from_email = models.EmailField(blank=True, null=True, help_text="Which mailbox was used to send this email")
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'email_send_queue'
        ordering = ['scheduled_for']
        indexes = [
            models.Index(fields=['status', 'scheduled_for']),
        ]
    
    def __str__(self):
        return f"Email {self.id} - {self.status} - {self.scheduled_for}"


class LeadMailboxAssignment(models.Model):
    """
    Sticky assignment of leads to mailboxes.
    Ensures same lead always gets emails from same mailbox (Ben's requirement).
    Table: lead_mailbox_assignments
    """
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('inactive', 'Inactive'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    lead_id = models.UUIDField(db_index=True, help_text="Lead ID from AISDR database")
    client_id = models.UUIDField(db_index=True, help_text="Client ID from AISDR database")
    assigned_email = models.EmailField(help_text="Which mailbox is assigned to this lead")
    
    assigned_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(auto_now=True)
    email_count = models.IntegerField(default=0, help_text="Number of emails sent to this lead")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'lead_mailbox_assignments'
        unique_together = [['lead_id', 'client_id']]
        indexes = [
            models.Index(fields=['lead_id']),
            models.Index(fields=['client_id']),
            models.Index(fields=['assigned_email']),
            models.Index(fields=['status']),
        ]
    
    def __str__(self):
        return f"Lead {self.lead_id} → {self.assigned_email} ({self.email_count} emails)"


# Note: These models reference the 'leads' and 'clients' tables which exist
# in the main AISDR database. We don't need to define them here as they're
# already managed by n8n workflows and the existing PostgreSQL schema.
#
# For client dashboard authentication, the 'clients' table should have:
# - email VARCHAR(255) UNIQUE
# - password_hash VARCHAR(255)
# - last_login TIMESTAMP
# - dashboard_enabled BOOLEAN DEFAULT true
#
# Run this SQL in AISDR database:
# ALTER TABLE clients 
# ADD COLUMN IF NOT EXISTS email VARCHAR(255) UNIQUE,
# ADD COLUMN IF NOT EXISTS password_hash VARCHAR(255),
# ADD COLUMN IF NOT EXISTS last_login TIMESTAMP,
# ADD COLUMN IF NOT EXISTS dashboard_enabled BOOLEAN DEFAULT true;
# CREATE INDEX IF NOT EXISTS idx_clients_email ON clients(email);
