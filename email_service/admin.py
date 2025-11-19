from django.contrib import admin
from .models import (
    EmailEvent,
    EmailTrackingPixel,
    EmailClickTracking,
    GmailToken,
    EmailSendQueue
)


@admin.register(EmailEvent)
class EmailEventAdmin(admin.ModelAdmin):
    list_display = ('id', 'event_type', 'lead_id', 'message_id', 'created_at')
    list_filter = ('event_type', 'created_at')
    search_fields = ('lead_id', 'message_id', 'email_subject')
    ordering = ('-created_at',)
    readonly_fields = ('id', 'created_at')


@admin.register(EmailTrackingPixel)
class EmailTrackingPixelAdmin(admin.ModelAdmin):
    list_display = ('pixel_id', 'lead_id', 'opened', 'open_count', 'created_at')
    list_filter = ('opened', 'created_at')
    search_fields = ('pixel_id', 'lead_id', 'message_id')
    readonly_fields = ('id', 'created_at')


@admin.register(EmailClickTracking)
class EmailClickTrackingAdmin(admin.ModelAdmin):
    list_display = ('click_id', 'lead_id', 'click_count', 'destination_url_short', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('click_id', 'lead_id', 'destination_url')
    readonly_fields = ('id', 'created_at')
    
    def destination_url_short(self, obj):
        return obj.destination_url[:50] + '...' if len(obj.destination_url) > 50 else obj.destination_url
    destination_url_short.short_description = 'Destination URL'


@admin.register(GmailToken)
class GmailTokenAdmin(admin.ModelAdmin):
    list_display = ('email_address', 'client_id', 'status', 'token_expiry', 'last_used_at')
    list_filter = ('status', 'created_at')
    search_fields = ('email_address', 'client_id')
    readonly_fields = ('id', 'created_at', 'updated_at')
    
    # Hide sensitive fields in list view
    exclude = ('access_token', 'refresh_token')


@admin.register(EmailSendQueue)
class EmailSendQueueAdmin(admin.ModelAdmin):
    list_display = ('id', 'lead_id', 'status', 'sequence_number', 'scheduled_for', 'attempts')
    list_filter = ('status', 'scheduled_for', 'sequence_number')
    search_fields = ('lead_id', 'client_id', 'email_subject')
    ordering = ('scheduled_for',)
    readonly_fields = ('id', 'created_at', 'updated_at', 'sent_at')
    
    fieldsets = (
        ('Basic Info', {
            'fields': ('id', 'lead_id', 'client_id', 'sequence_number')
        }),
        ('Email Content', {
            'fields': ('email_subject', 'email_body', 'email_cta')
        }),
        ('Scheduling', {
            'fields': ('scheduled_for', 'send_delay_days', 'status')
        }),
        ('Status Tracking', {
            'fields': ('attempts', 'max_attempts', 'last_error', 'failed_at', 'message_id', 'sent_at')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at')
        }),
    )
