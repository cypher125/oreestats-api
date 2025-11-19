"""
Celery configuration for OreeStats
"""
import os
from celery import Celery
from celery.schedules import crontab

# Set default Django settings module
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'OreeStats.settings')

app = Celery('OreeStats')

# Load config from Django settings with CELERY namespace
app.config_from_object('django.conf:settings', namespace='CELERY')

# Auto-discover tasks in all installed apps
app.autodiscover_tasks()

# Periodic task schedule
app.conf.beat_schedule = {
    'process-email-queue-every-minute': {
        'task': 'email_service.tasks.process_email_queue',
        'schedule': 60.0,  # Every 60 seconds
    },
    'check-for-replies-every-15-minutes': {
        'task': 'email_service.tasks.check_for_replies',
        'schedule': 900.0,  # Every 15 minutes
    },
    'reset-daily-limits-at-midnight': {
        'task': 'email_service.tasks.reset_daily_limits',
        'schedule': crontab(hour=0, minute=0),  # Daily at midnight UTC
    },
    'cleanup-expired-pixels-daily': {
        'task': 'email_service.tasks.cleanup_expired_pixels',
        'schedule': crontab(hour=2, minute=0),  # Daily at 2 AM UTC
    },
}

@app.task(bind=True)
def debug_task(self):
    """Debug task to test Celery is working"""
    print(f'Request: {self.request!r}')
