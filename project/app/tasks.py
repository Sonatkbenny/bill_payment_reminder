from celery import shared_task
from django.core.mail import send_mail
from django.conf import settings
from django.utils import timezone
from datetime import timedelta
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from .models import Bill, ReminderSettings, BillActivity
import logging

logger = logging.getLogger(__name__)

@shared_task
def test_email_send(user_email):
    """
    Test function to send an email and verify it works
    """
    subject = 'Test Email from Bill Payment System'
    message = 'This is a test email to verify the email system is working.'
    
    try:
        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user_email],
            fail_silently=False,
        )
        print(f"Test email sent successfully to {user_email}")
        return True
    except Exception as e:
        print(f"Failed to send test email: {str(e)}")
        return False

@shared_task
def send_bill_reminders():
    """
    Send email reminders for upcoming bills based on user preferences.
    This task should be run daily via Celery beat.
    """
    today = timezone.now().date()
    
    # Get all pending bills
    pending_bills = Bill.objects.filter(
        payment_status='pending',
        due_date__gte=today - timedelta(days=30)  # Include bills due in the last 30 days (overdue)
    ).select_related('user', 'user__profile')

    for bill in pending_bills:
        # Get user's reminder settings
        reminder_settings, _ = ReminderSettings.objects.get_or_create(user=bill.user)
        
        if not reminder_settings.email_reminders:
            continue

        days_until_due = (bill.due_date - today).days
        
        # Check if we should send a reminder based on user's default reminder days
        should_send_reminder = False
        
        # Always send reminder for overdue bills (once per day)
        if days_until_due < 0:
            # Only send if we haven't sent a reminder today
            if not bill.last_reminder_sent or bill.last_reminder_sent.date() < today:
                should_send_reminder = True
        # Send reminder on due date
        elif days_until_due == 0:
            should_send_reminder = True
        # Send reminder 1 day before
        elif days_until_due == 1:
            should_send_reminder = True
        # Send reminder based on user's default reminder days
        elif days_until_due == reminder_settings.default_reminder_days:
            should_send_reminder = True
        # Send reminder 3 days before if not already sent
        elif days_until_due == 3 and (not bill.last_reminder_sent or bill.last_reminder_sent.date() < today - timedelta(days=1)):
            should_send_reminder = True
        # Send reminder 7 days before if not already sent
        elif days_until_due == 7 and (not bill.last_reminder_sent or bill.last_reminder_sent.date() < today - timedelta(days=4)):
            should_send_reminder = True

        if should_send_reminder:
            # Prepare email content
            context = {
                'bill': bill,
                'days_until_due': days_until_due,
                'user': bill.user,
                'site_name': 'Bill Payment System',
                'site_url': settings.SITE_URL if hasattr(settings, 'SITE_URL') else 'http://127.0.0.1:7777',
            }

            # Render HTML email template
            html_content = render_to_string('app/email/bill_reminder.html', context)
            plain_text = strip_tags(html_content)

            # Prepare email subject based on due status
            if days_until_due < 0:
                subject = f'URGENT: Overdue Bill Payment Required - {bill.title}'
            elif days_until_due == 0:
                subject = f'Bill Payment Due Today - {bill.title}'
            elif days_until_due <= 3:
                subject = f'Bill Payment Due Soon - {bill.title} due in {days_until_due} days'
            else:
                subject = f'Bill Payment Reminder: {bill.title} due in {days_until_due} days'

            try:
                # Send email
                send_mail(
                    subject=subject,
                    message=plain_text,
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[bill.user.email],
                    html_message=html_content,
                    fail_silently=False,
                )

                # Update bill reminder status
                bill.reminder_sent = True
                bill.last_reminder_sent = timezone.now()
                bill.save()

                # Create activity record
                BillActivity.objects.create(
                    bill=bill,
                    type='reminder',
                    message=f'Email reminder sent for bill due in {days_until_due} days'
                )

            except Exception as e:
                print(f"Failed to send email for bill {bill.id}: {str(e)}")
                # Create activity record for failed reminder
                BillActivity.objects.create(
                    bill=bill,
                    type='reminder',
                    message=f'Failed to send email reminder: {str(e)}'
                )

@shared_task
def send_weekly_bill_summary():
    """
    Send a weekly summary of all bills to users who have email reminders enabled.
    This task should be run weekly via Celery beat.
    """
    today = timezone.now().date()
    week_ago = today - timedelta(days=7)
    week_ahead = today + timedelta(days=7)
    
    # Get all users with email reminders enabled
    users_with_reminders = ReminderSettings.objects.filter(email_reminders=True).select_related('user')
    
    for reminder_setting in users_with_reminders:
        user = reminder_setting.user
        
        # Get user's bills
        overdue_bills = Bill.objects.filter(
            user=user,
            payment_status='pending',
            due_date__lt=today
        ).order_by('due_date')
        
        due_this_week = Bill.objects.filter(
            user=user,
            payment_status='pending',
            due_date__gte=today,
            due_date__lte=week_ahead
        ).order_by('due_date')
        
        # Only send if there are bills to report
        if overdue_bills.exists() or due_this_week.exists():
            context = {
                'user': user,
                'overdue_bills': overdue_bills,
                'due_this_week': due_this_week,
                'site_name': 'Bill Payment System',
                'site_url': settings.SITE_URL if hasattr(settings, 'SITE_URL') else 'http://127.0.0.1:7777',
            }
            
            # Render HTML email template
            html_content = render_to_string('app/email/weekly_summary.html', context)
            plain_text = strip_tags(html_content)
            
            subject = f'Weekly Bill Summary - {today.strftime("%B %d, %Y")}'
            
            try:
                # Send email
                send_mail(
                    subject=subject,
                    message=plain_text,
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[user.email],
                    html_message=html_content,
                    fail_silently=False,
                )
                
                # Create activity record
                BillActivity.objects.create(
                    bill=None,  # No specific bill for weekly summary
                    type='summary',
                    message=f'Weekly bill summary email sent'
                )
                
            except Exception as e:
                print(f"Failed to send weekly summary to user {user.id}: {str(e)}") 

@shared_task
def send_payment_confirmation(bill_id):
    """
    Send a payment confirmation email when a bill is marked as paid
    """
    try:
        bill = Bill.objects.get(id=bill_id)
        user = bill.user
        
        # Check if user has email reminders enabled
        reminder_settings = ReminderSettings.objects.filter(user=user).first()
        if not reminder_settings or not reminder_settings.email_reminders:
            return
        
        # Prepare email content
        context = {
            'bill': bill,
            'user': user,
            'payment_date': bill.paid_date,
            'site_name': 'Bill Payment System',
            'site_url': settings.SITE_URL if hasattr(settings, 'SITE_URL') else 'http://127.0.0.1:7777',
        }
        
        # Render HTML email template
        html_content = render_to_string('app/email/payment_confirmation.html', context)
        plain_text = strip_tags(html_content)
        
        subject = f'Payment Confirmation - {bill.title}'
        
        # Send email
        send_mail(
            subject=subject,
            message=plain_text,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            html_message=html_content,
            fail_silently=False,
        )
        
        # Create activity record
        BillActivity.objects.create(
            bill=bill,
            type='payment',
            message=f'Payment confirmation email sent'
        )
        
    except Exception as e:
        logger.error(f"Failed to send payment confirmation email: {str(e)}")
        if bill:
            BillActivity.objects.create(
                bill=bill,
                type='payment',
                message=f'Failed to send payment confirmation email: {str(e)}'
            ) 