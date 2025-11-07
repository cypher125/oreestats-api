"""
Django REST Framework serializers for email tracking
"""
from rest_framework import serializers
from .models import (
    EmailEvent,
    EmailTrackingPixel,
    EmailClickTracking,
    GmailToken,
    EmailSendQueue
)


class EmailEventSerializer(serializers.ModelSerializer):
    """Serializer for email events"""
    
    class Meta:
        model = EmailEvent
        fields = [
            'id', 'lead_id', 'client_id', 'event_type',
            'message_id', 'thread_id', 'sequence_number',
            'email_subject', 'url', 'user_agent', 'ip_address',
            'device_type', 'reply_content', 'reply_snippet',
            'created_at', 'metadata'
        ]
        read_only_fields = ['id', 'created_at']


class EmailTrackingPixelSerializer(serializers.ModelSerializer):
    """Serializer for tracking pixels"""
    
    class Meta:
        model = EmailTrackingPixel
        fields = [
            'id', 'lead_id', 'message_id', 'pixel_id',
            'opened', 'open_count', 'first_opened_at',
            'last_opened_at', 'created_at', 'expires_at'
        ]
        read_only_fields = ['id', 'created_at', 'first_opened_at', 'last_opened_at']


class EmailClickTrackingSerializer(serializers.ModelSerializer):
    """Serializer for click tracking"""
    
    class Meta:
        model = EmailClickTracking
        fields = [
            'id', 'lead_id', 'message_id', 'click_id',
            'destination_url', 'click_count', 'first_clicked_at',
            'last_clicked_at', 'created_at'
        ]
        read_only_fields = ['id', 'created_at', 'first_clicked_at', 'last_clicked_at']


class GmailTokenSerializer(serializers.ModelSerializer):
    """Serializer for Gmail tokens - EXCLUDES sensitive fields by default"""
    
    class Meta:
        model = GmailToken
        fields = [
            'id', 'client_id', 'email_address', 'gmail_user_id',
            'token_expiry', 'scopes', 'status', 'last_history_id',
            'created_at', 'updated_at', 'last_used_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']
        # Exclude sensitive fields (access_token, refresh_token)


class GmailTokenDetailSerializer(serializers.ModelSerializer):
    """Serializer for Gmail tokens including sensitive fields (internal use only)"""
    
    class Meta:
        model = GmailToken
        fields = '__all__'
        read_only_fields = ['id', 'created_at', 'updated_at']


class EmailSendQueueSerializer(serializers.ModelSerializer):
    """Serializer for email send queue"""
    
    class Meta:
        model = EmailSendQueue
        fields = [
            'id', 'lead_id', 'client_id', 'recipient_email',
            'email_subject', 'email_body', 'email_cta',
            'sequence_number', 'send_delay_days', 'scheduled_for',
            'status', 'attempts', 'max_attempts', 'last_error',
            'failed_at', 'message_id', 'sent_at', 'sent_from_email',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'sent_at', 'failed_at']


class EmailSendRequestSerializer(serializers.Serializer):
    """Serializer for email send request from n8n"""
    lead_id = serializers.UUIDField(required=True)
    client_id = serializers.UUIDField(required=True)  # Required for mailbox rotation
    recipient_email = serializers.EmailField(required=True)  # Email address to send to
    email_subject = serializers.CharField(required=True, max_length=255)
    email_body = serializers.CharField(required=True)
    email_cta = serializers.CharField(required=False, allow_blank=True)
    sequence_number = serializers.IntegerField(required=True, min_value=1, max_value=4)
    send_delay_days = serializers.IntegerField(required=False, default=0, min_value=0)
    scheduled_for = serializers.DateTimeField(required=False, allow_null=True)
    
    def validate_sequence_number(self, value):
        """Validate sequence number is between 1-4"""
        if value < 1 or value > 4:
            raise serializers.ValidationError("Sequence number must be between 1 and 4")
        return value


class EmailStatusResponseSerializer(serializers.Serializer):
    """Serializer for email status response"""
    lead_id = serializers.UUIDField()
    emails_sent = serializers.IntegerField()
    emails_opened = serializers.IntegerField()
    emails_clicked = serializers.IntegerField()
    emails_replied = serializers.IntegerField()
    emails_bounced = serializers.IntegerField()
    last_engagement_type = serializers.CharField(allow_null=True)
    last_engagement_at = serializers.DateTimeField(allow_null=True)
    current_sequence_step = serializers.IntegerField()
    sequence_status = serializers.CharField()
    
    # Recent events
    recent_events = EmailEventSerializer(many=True, read_only=True)


class TrackingPixelResponseSerializer(serializers.Serializer):
    """Serializer for tracking pixel response (minimal)"""
    success = serializers.BooleanField()
    message = serializers.CharField(required=False)


class TrackingClickResponseSerializer(serializers.Serializer):
    """Serializer for tracking click response"""
    success = serializers.BooleanField()
    redirect_url = serializers.URLField()
    message = serializers.CharField(required=False)


# ============================================
# CLIENT DASHBOARD SERIALIZERS
# ============================================

class ClientLoginSerializer(serializers.Serializer):
    """Serializer for client login request"""
    email = serializers.EmailField(required=True)
    password = serializers.CharField(required=True, write_only=True)


class ClientLoginResponseSerializer(serializers.Serializer):
    """Serializer for client login response"""
    success = serializers.BooleanField()
    token = serializers.CharField()
    client = serializers.DictField()


class ClientStatsSerializer(serializers.Serializer):
    """Serializer for client campaign statistics"""
    client_id = serializers.UUIDField()
    all_time = serializers.DictField()
    last_7_days = serializers.DictField()
    last_30_days = serializers.DictField()


class ClientCampaignSerializer(serializers.Serializer):
    """Serializer for campaign performance by sequence"""
    sequence_number = serializers.IntegerField()
    emails_sent = serializers.IntegerField()
    opens = serializers.IntegerField()
    open_rate = serializers.FloatField()
    clicks = serializers.IntegerField()
    click_rate = serializers.FloatField()
    replies = serializers.IntegerField()
    reply_rate = serializers.FloatField()
    last_sent = serializers.DateTimeField(allow_null=True)


class ClientReplySerializer(serializers.Serializer):
    """Serializer for email replies"""
    id = serializers.UUIDField()
    lead_id = serializers.UUIDField()
    message_id = serializers.CharField()
    reply_content = serializers.CharField()
    reply_snippet = serializers.CharField()
    created_at = serializers.DateTimeField()
    email_subject = serializers.CharField()


class ClientTimelineSerializer(serializers.Serializer):
    """Serializer for daily email timeline data"""
    date = serializers.DateField()
    emails_sent = serializers.IntegerField()
    opens = serializers.IntegerField()
    clicks = serializers.IntegerField()
    replies = serializers.IntegerField()


class ClientMailboxSerializer(serializers.Serializer):
    """Serializer for connected mailboxes status"""
    email_address = serializers.EmailField()
    status = serializers.CharField()
    daily_send_count = serializers.IntegerField()
    daily_send_limit = serializers.IntegerField()
    remaining = serializers.IntegerField()
    last_used_at = serializers.DateTimeField(allow_null=True)


class ChangePasswordSerializer(serializers.Serializer):
    """Serializer for password change request"""
    current_password = serializers.CharField(required=True, write_only=True)
    new_password = serializers.CharField(required=True, write_only=True, min_length=8)


class UpdateClientSettingsSerializer(serializers.Serializer):
    """Serializer for updating client settings"""
    campaign_status = serializers.ChoiceField(
        choices=['active', 'paused'],
        required=False
    )
