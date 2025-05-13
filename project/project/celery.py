import os
from celery import Celery
from celery.schedules import crontab

# Set the default Django settings module for the 'celery' program.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'project.settings')

# Create the Celery app
app = Celery('project')

# Using a string here means the worker doesn't have to serialize
# the configuration object to child processes.
app.config_from_object('django.conf:settings', namespace='CELERY')

# Load task modules from all registered Django app configs.
app.autodiscover_tasks()

# Configure Celery Beat schedule
app.conf.beat_schedule = {
    'send-daily-bill-reminders': {
        'task': 'app.tasks.send_bill_reminders',
        'schedule': crontab(hour=9, minute=0),  # Run daily at 9 AM
    },
    'send-weekly-bill-summary': {
        'task': 'app.tasks.send_weekly_bill_summary',
        'schedule': crontab(day_of_week='monday', hour=8, minute=0),  # Run every Monday at 8 AM
    },
} 