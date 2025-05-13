from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q
from django.utils import timezone
from django.contrib.auth import login as auth_login, authenticate
from django.contrib.auth.views import LoginView, PasswordResetView, PasswordResetDoneView, PasswordResetConfirmView, PasswordResetCompleteView
from django.urls import reverse_lazy
from django.core.mail import send_mail
from django.conf import settings
from django.contrib.auth.models import User
from .models import Bill, Profile, ReminderSettings, BillActivity, Payment
from .forms import BillForm, UserRegistrationForm, ProfileForm, UserUpdateForm, CustomPasswordResetForm, CustomSetPasswordForm, ReminderSettingsForm, AdminLoginForm
from datetime import datetime, timedelta
import random
import string
import os
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_POST
from .tasks import test_email_send, send_bill_reminders, send_payment_confirmation
from django.core.paginator import Paginator
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.contrib.auth.tokens import default_token_generator
from django.urls import reverse
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.utils.encoding import force_str, force_bytes
from django.views import View
import uuid
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from io import BytesIO
from django.contrib.auth import authenticate
from django.contrib.admin.views.decorators import staff_member_required
import razorpay
import logging

logger = logging.getLogger(__name__)

class CustomLoginView(LoginView):
    template_name = 'app/login.html'
    redirect_authenticated_user = True

    def form_valid(self, form):
        # Get the user
        user = form.get_user()
        
        # Log the user in
        auth_login(self.request, user)
        
        # Redirect staff users to admin dashboard
        if user.is_staff:
            messages.success(self.request, f'Welcome to admin panel, {user.username}!')
            return redirect('admin_dashboard')
        
        # Regular users go to the user dashboard
        messages.success(self.request, f'Welcome back, {user.get_full_name() or user.username}!')
        return redirect(self.get_success_url())

def generate_otp():
    return ''.join(random.choices(string.digits, k=6))

class CustomPasswordResetView(PasswordResetView):
    template_name = 'app/password_reset.html'
    email_template_name = 'app/email/password_reset_email.html'
    success_url = reverse_lazy('password_reset_done')
    
    def form_valid(self, form):
        email = form.cleaned_data['email']
        try:
            user = User.objects.get(email=email)
            # Generate OTP
            otp = ''.join(random.choices(string.digits, k=6))
            user.profile.reset_otp = otp
            user.profile.reset_otp_created_at = timezone.now()
            user.profile.save()
            
            # Generate password reset token
            token = default_token_generator.make_token(user)
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            
            # Send email with OTP
            context = {
                'user': user,
                'otp': otp,
                'site_name': 'Bill Payment Reminder',
                'site_url': self.request.build_absolute_uri('/'),
                'reset_url': self.request.build_absolute_uri(
                    reverse_lazy('verify_otp', kwargs={'uidb64': uid, 'token': token})
                ),
            }
            
            html_message = render_to_string(self.email_template_name, context)
            send_mail(
                subject='Password Reset OTP - Bill Payment Reminder',
                message=f'Your OTP is: {otp}',
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[email],
                html_message=html_message,
            )
            
            messages.success(self.request, 'Password reset OTP has been sent to your email.')
            # Redirect to OTP verification page instead of password_reset_done
            return redirect('verify_otp', uidb64=uid, token=token)
        except User.DoesNotExist:
            messages.error(self.request, 'No user found with this email address.')
            return self.form_invalid(form)

class CustomPasswordResetDoneView(PasswordResetDoneView):
    template_name = 'app/password_reset_done.html'

class CustomPasswordResetConfirmView(PasswordResetConfirmView):
    form_class = CustomSetPasswordForm
    template_name = 'app/password_reset_confirm.html'
    success_url = reverse_lazy('password_reset_complete')

class CustomPasswordResetCompleteView(PasswordResetCompleteView):
    template_name = 'app/password_reset_complete.html'

@login_required
def profile(request):
    if request.method == 'POST':
        user_form = UserUpdateForm(request.POST, instance=request.user)
        profile_form = ProfileForm(request.POST, request.FILES, instance=request.user.profile)
        if user_form.is_valid() and profile_form.is_valid():
            user_form.save()
            profile_form.save()
            messages.success(request, 'Your profile has been updated!')
            return redirect('profile')
    else:
        user_form = UserUpdateForm(instance=request.user)
        profile_form = ProfileForm(instance=request.user.profile)
    
    # Get bill counts
    total_bills = request.user.bill_set.count()
    pending_bills = request.user.bill_set.filter(payment_status='pending').count()
    paid_bills = request.user.bill_set.filter(payment_status='paid').count()
    
    context = {
        'user_form': user_form,
        'profile_form': profile_form,
        'total_bills': total_bills,
        'pending_bills': pending_bills,
        'paid_bills': paid_bills,
    }
    return render(request, 'app/profile.html', context)

@login_required
def index(request):
    # Get current user's bills
    bills = Bill.objects.filter(user=request.user)
    today = timezone.now().date()  # Convert to date object
    
    # Calculate statistics
    total_bills = bills.count()
    pending_bills = bills.filter(payment_status='pending', due_date__gte=today).count()
    overdue_bills = bills.filter(payment_status='pending', due_date__lt=today).count()
    paid_bills = bills.filter(
        payment_status='paid',
        paid_date__isnull=False,
        paid_date__month=today.month,
        paid_date__year=today.year
    ).count()
    
    # Get upcoming bills (due in next 30 days)
    upcoming_bills = bills.filter(
        payment_status='pending',
        due_date__gte=today,
        due_date__lte=today + timedelta(days=30)
    ).order_by('due_date')[:5]

    # Add is_overdue and is_due_soon flags to upcoming bills
    for bill in upcoming_bills:
        bill.is_overdue = bill.due_date < today
        bill.is_due_soon = (bill.due_date - today).days <= 3

    # Get recent activities
    recent_activities = BillActivity.objects.filter(
        bill__user=request.user
    ).order_by('-timestamp')[:5]

    context = {
        'total_bills': total_bills,
        'pending_bills': pending_bills,
        'overdue_bills': overdue_bills,
        'paid_bills': paid_bills,
        'upcoming_bills': upcoming_bills,
        'recent_activities': recent_activities,
    }
    
    return render(request, 'app/index.html', context)

def register(request):
    if request.method == 'POST':
        form = UserRegistrationForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Registration successful! Please login to continue.')
            return redirect('login')
    else:
        form = UserRegistrationForm()
    return render(request, 'app/register.html', {'form': form})

@login_required
def dashboard(request):
    today = timezone.now().date()
    upcoming_bills = Bill.objects.filter(
        user=request.user,
        due_date__gte=today,
        payment_status='pending'
    ).order_by('due_date')[:5]
    
    overdue_bills = Bill.objects.filter(
        user=request.user,
        payment_status='overdue'
    ).order_by('due_date')
    
    paid_bills = Bill.objects.filter(
        user=request.user,
        payment_status='paid'
    ).order_by('-updated_at')[:5]
    
    context = {
        'upcoming_bills': upcoming_bills,
        'overdue_bills': overdue_bills,
        'paid_bills': paid_bills,
    }
    return render(request, 'app/dashboard.html', context)

@login_required
def bill_list(request):
    # Get base queryset for user's bills
    bills = Bill.objects.filter(user=request.user)
    
    # Get filter parameters from request
    category = request.GET.get('category')
    status = request.GET.get('status')
    search = request.GET.get('search')
    sort_by = request.GET.get('sort_by', 'due_date')

    # Apply filters
    if category:
        bills = bills.filter(category=category)
    if status:
        bills = bills.filter(payment_status=status)
    if search:
        bills = bills.filter(title__icontains=search)

    # Apply sorting
    if sort_by == 'amount':
        bills = bills.order_by('amount')
    elif sort_by == 'created_at':
        bills = bills.order_by('-created_at')
    else:  # default to due_date
        bills = bills.order_by('due_date')

    # Get choices for dropdowns
    categories = Bill.CATEGORY_CHOICES
    statuses = Bill.PAYMENT_STATUS_CHOICES

    # Add is_overdue and is_due_soon flags
    today = timezone.now().date()
    for bill in bills:
        bill.is_overdue = bill.due_date < today
        bill.is_due_soon = (bill.due_date - today).days <= 3

    context = {
        'bills': bills,
        'categories': categories,
        'statuses': statuses,
        'current_category': category,
        'current_status': status,
        'current_search': search,
        'current_sort': sort_by,
    }
    
    return render(request, 'app/bill_list.html', context)

@login_required
def bill_create(request):
    if request.method == 'POST':
        form = BillForm(request.POST)
        if form.is_valid():
            bill = form.save(commit=False)
            bill.user = request.user
            bill.save()
            messages.success(request, 'Bill created successfully!')
            return redirect('bill_list')
    else:
        form = BillForm()
    return render(request, 'app/bill_form.html', {'form': form, 'title': 'Create Bill'})

@login_required
def bill_update(request, pk):
    bill = get_object_or_404(Bill, pk=pk, user=request.user)
    if request.method == 'POST':
        form = BillForm(request.POST, instance=bill)
        if form.is_valid():
            form.save()
            messages.success(request, 'Bill updated successfully!')
            return redirect('bill_list')
    else:
        form = BillForm(instance=bill)
    return render(request, 'app/bill_form.html', {'form': form, 'title': 'Update Bill'})

@login_required
def bill_delete(request, pk):
    bill = get_object_or_404(Bill, pk=pk, user=request.user)
    if request.method == 'POST':
        bill.delete()
        messages.success(request, 'Bill deleted successfully!')
        return redirect('bill_list')
    return render(request, 'app/bill_confirm_delete.html', {'bill': bill})

@login_required
def bill_detail(request, pk):
    bill = get_object_or_404(Bill, pk=pk, user=request.user)
    successful_payments = bill.payments.filter(payment_status='success')
    
    context = {
        'bill': bill,
        'successful_payments': successful_payments,
    }
    return render(request, 'app/bill_detail.html', context)

@login_required
def calendar_view(request):
    bills = Bill.objects.filter(user=request.user)
    return render(request, 'app/calendar.html', {'bills': bills})

@login_required
def delete_profile_picture(request):
    if request.method == 'POST':
        profile = request.user.profile
        if profile.profile_picture:
            # Delete the file from storage
            if os.path.isfile(profile.profile_picture.path):
                os.remove(profile.profile_picture.path)
            # Clear the profile picture field
            profile.profile_picture = None
            profile.save()
            messages.success(request, 'Profile picture deleted successfully!')
        return redirect('profile')
    return redirect('profile')

@login_required
@require_POST
def update_reminder_settings(request):
    reminder_settings, created = ReminderSettings.objects.get_or_create(user=request.user)
    
    # Update email reminders setting
    reminder_settings.email_reminders = request.POST.get('email_reminders') == 'on'
    
    # Update push notifications setting
    reminder_settings.push_notifications = request.POST.get('push_notifications') == 'on'
    
    # Update default reminder days
    try:
        reminder_settings.default_reminder_days = int(request.POST.get('default_reminder_days', 3))
    except ValueError:
        reminder_settings.default_reminder_days = 3
    
    reminder_settings.save()
    
    messages.success(request, 'Reminder settings updated successfully!')
    return redirect('index')

@login_required
def mark_bill_paid(request, pk=None, bill_id=None):
    # Handle both parameter names for backward compatibility
    bill_pk = pk or bill_id
    bill = get_object_or_404(Bill, pk=bill_pk, user=request.user)
    if request.method == 'POST':
        bill.payment_status = 'paid'
        bill.paid_date = timezone.now()
        # Set reminder_sent to True to prevent further reminders
        bill.reminder_sent = True
        bill.last_reminder_sent = timezone.now()
        bill.save()
        
        # Create a payment record
        payment = Payment.objects.create(
            bill=bill,
            user=request.user,
            amount=bill.amount,
            payment_method='other',  # Default payment method for manual marking
            transaction_id=str(uuid.uuid4()),
            payment_status='success',
            payment_date=bill.paid_date
        )
        
        # Create activity record
        BillActivity.objects.create(
            bill=bill,
            type='payment',
            message=f"Bill marked as paid by {request.user.get_full_name() or request.user.username}"
        )
        
        # Send payment confirmation email
        send_payment_confirmation.delay(bill.id)
        
        messages.success(request, f'Bill "{bill.title}" has been marked as paid.')
        return redirect('bill_detail', pk=bill.pk)
    return redirect('bill_detail', pk=bill.pk)

@login_required
def reminder_settings(request):
    reminder_settings, created = ReminderSettings.objects.get_or_create(user=request.user)
    if request.method == 'POST':
        form = ReminderSettingsForm(request.POST, instance=reminder_settings)
        if form.is_valid():
            form.save()
            messages.success(request, 'Reminder settings updated successfully!')
            return redirect('index')
    else:
        form = ReminderSettingsForm(instance=reminder_settings)
    
    return render(request, 'app/reminder_settings.html', {'form': form})

@login_required
def test_email(request):
    """
    View to test email sending with enhanced template
    """
    if request.method == 'POST':
        user_email = request.user.email
        
        # Create a sample bill for testing
        sample_bill = Bill.objects.filter(user=request.user).first()
        
        if sample_bill:
            # Prepare email content with sample bill
            context = {
                'bill': sample_bill,
                'days_until_due': (sample_bill.due_date - timezone.now().date()).days,
                'user': request.user,
                'site_name': 'Bill Payment System',
                'site_url': getattr(settings, 'SITE_URL', 'http://127.0.0.1:7777'),
            }
            
            # Render HTML email template
            html_content = render_to_string('app/email/bill_reminder.html', context)
            plain_text = strip_tags(html_content)
            
            subject = 'Test Email from Bill Payment System'
            
            try:
                # Send email
                send_mail(
                    subject=subject,
                    message=plain_text,
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[user_email],
                    html_message=html_content,
                    fail_silently=False,
                )
                
                # Create activity record
                BillActivity.objects.create(
                    bill=sample_bill,
                    type='reminder',
                    message=f'Test email sent successfully'
                )
                
                messages.success(request, f'Test email sent successfully to {user_email}')
            except Exception as e:
                messages.error(request, f'Failed to send test email: {str(e)}')
        else:
            # If no bills exist, send a simple test email
            if test_email_send(user_email):
                messages.success(request, f'Test email sent successfully to {user_email}')
            else:
                messages.error(request, 'Failed to send test email. Check console for details.')
                
        return redirect('profile')
    return redirect('profile')

@login_required
def notification_history(request):
    """
    View to display email notification history
    """
    # Get user's notification activities
    activities = BillActivity.objects.filter(
        Q(bill__user=request.user) | Q(bill__isnull=True, type='summary')
    ).order_by('-timestamp')
    
    # Paginate the results
    paginator = Paginator(activities, 10)  # Show 10 activities per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'activities': page_obj,
        'is_paginated': paginator.num_pages > 1,
    }
    
    return render(request, 'app/notification_history.html', context)

@login_required
def send_manual_reminder(request, bill_id):
    """
    View to manually send a reminder for a specific bill
    """
    bill = get_object_or_404(Bill, id=bill_id, user=request.user)
    
    # Don't send reminders for paid bills
    if bill.payment_status == 'paid':
        messages.warning(request, f'Cannot send reminder for paid bill "{bill.title}".')
        return redirect('bill_detail', bill_id)
    
    # Prepare email content
    context = {
        'bill': bill,
        'days_until_due': (bill.due_date - timezone.now().date()).days,
        'user': request.user,
        'site_name': 'Bill Payment System',
        'site_url': getattr(settings, 'SITE_URL', 'http://127.0.0.1:7777'),
    }
    
    # Render HTML email template
    html_content = render_to_string('app/email/bill_reminder.html', context)
    plain_text = strip_tags(html_content)
    
    # Prepare email subject based on due status
    days_until_due = (bill.due_date - timezone.now().date()).days
    if days_until_due < 0:
        subject = f'URGENT: Overdue Bill Payment Required - {bill.title}'
    elif days_until_due == 0:
        subject = f'Bill Payment Due Today - {bill.title}'
    else:
        subject = f'Bill Payment Reminder: {bill.title} due in {days_until_due} days'
    
    try:
        # Send email
        send_mail(
            subject=subject,
            message=plain_text,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[request.user.email],
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
            message=f'Manual reminder sent for bill due in {days_until_due} days'
        )
        
        messages.success(request, f'Reminder sent successfully for {bill.title}')
    except Exception as e:
        messages.error(request, f'Failed to send reminder: {str(e)}')
    
    return redirect('bill_detail', pk=bill_id)

class VerifyOTPView(View):
    template_name = 'app/verify_otp.html'
    
    def get(self, request, uidb64, token):
        # Check if the token is valid
        try:
            uid = force_str(urlsafe_base64_decode(uidb64))
            user = User.objects.get(pk=uid)
        except (TypeError, ValueError, OverflowError, User.DoesNotExist):
            user = None
            
        if user is None or not default_token_generator.check_token(user, token):
            messages.error(request, 'Password reset link is invalid or has expired.')
            return redirect('password_reset')
            
        return render(request, self.template_name, {'uidb64': uidb64, 'token': token})
    
    def post(self, request, uidb64, token):
        otp = request.POST.get('otp')
        
        try:
            uid = force_str(urlsafe_base64_decode(uidb64))
            user = User.objects.get(pk=uid)
        except (TypeError, ValueError, OverflowError, User.DoesNotExist):
            user = None
            
        if user is None or not default_token_generator.check_token(user, token):
            messages.error(request, 'Password reset link is invalid or has expired.')
            return redirect('password_reset')
        
        if not otp:
            messages.error(request, 'Please enter the OTP sent to your email.')
            return render(request, self.template_name, {'uidb64': uidb64, 'token': token})
            
        # Get the user's profile
        try:
            profile = Profile.objects.get(user=user)
        except Profile.DoesNotExist:
            messages.error(request, 'User profile not found.')
            return redirect('password_reset')
            
        if not profile.reset_otp or profile.reset_otp != otp:
            messages.error(request, 'Invalid OTP. Please try again.')
            return render(request, self.template_name, {'uidb64': uidb64, 'token': token})
        
        # Check if OTP is expired (10 minutes)
        if profile.reset_otp_created_at and (timezone.now() - profile.reset_otp_created_at).total_seconds() > 600:
            messages.error(request, 'OTP has expired. Please request a new one.')
            return render(request, self.template_name, {'uidb64': uidb64, 'token': token})
        
        # Clear the OTP after successful verification
        profile.reset_otp = None
        profile.reset_otp_created_at = None
        profile.save()
        
        # Redirect to password reset confirm page
        return redirect('password_reset_confirm', uidb64=uidb64, token=token)

@login_required
def initiate_payment(request, bill_id):
    bill = get_object_or_404(Bill, id=bill_id, user=request.user)
    
    try:
        # Initialize Razorpay client with proper error handling
        try:
            client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))
            client.set_app_details({"title": "Bill Payment System"})
            
            # Verify authentication
            client.payment.all()  # This will fail if auth is incorrect
            
        except razorpay.errors.SignatureVerificationError as e:
            messages.error(request, 'Invalid Razorpay credentials. Please contact support.')
            return redirect('bill_detail', bill_id)
        except Exception as e:
            messages.error(request, f'Error connecting to Razorpay: {str(e)}')
            return redirect('bill_detail', bill_id)
        
        # Clean up any existing pending payments
        Payment.objects.filter(bill=bill, payment_status='pending').delete()
        
        # Create Razorpay order
        order_amount = int(bill.amount * 100)  # Convert to paise
        order_currency = settings.RAZORPAY_CURRENCY
        order_receipt = f'bill_{bill.id}'
        
        order_data = {
            'amount': order_amount,
            'currency': order_currency,
            'receipt': order_receipt,
            'payment_capture': 1  # Auto capture payment
        }
        
        order = client.order.create(data=order_data)
        
        # Create payment record
        payment = Payment.objects.create(
            bill=bill,
            user=request.user,
            amount=bill.amount,
            payment_method='razorpay',
            transaction_id=str(uuid.uuid4()),
            razorpay_order_id=order['id']
        )
        
        # Prepare context for template
        context = {
            'bill': bill,
            'razorpay_order_id': order['id'],
            'razorpay_merchant_key': settings.RAZORPAY_KEY_ID,
            'razorpay_amount': order_amount,
            'razorpay_currency': order_currency,
            'callback_url': request.build_absolute_uri(reverse('process_payment', args=[bill_id])),
            'razorpay_email': request.user.email,
            'razorpay_contact': request.user.profile.phone_number or '',
            'test_mode': getattr(settings, 'RAZORPAY_TEST_MODE', False)
        }
        
        return render(request, 'app/payment.html', context)
        
    except Exception as e:
        messages.error(request, f'Error initiating payment: {str(e)}')
        return redirect('bill_detail', bill_id)

@login_required
def process_payment(request, bill_id):
    if request.method != 'POST':
        return redirect('bill_detail', bill_id)

    bill = get_object_or_404(Bill, id=bill_id, user=request.user)
    
    try:
        # Get payment details from POST data
        payment_id = request.POST.get('razorpay_payment_id', '')
        order_id = request.POST.get('razorpay_order_id', '')
        signature = request.POST.get('razorpay_signature', '')
        
        # Initialize Razorpay client
        client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))
        
        # Verify payment signature
        params_dict = {
            'razorpay_payment_id': payment_id,
            'razorpay_order_id': order_id,
            'razorpay_signature': signature
        }
        
        try:
            client.utility.verify_payment_signature(params_dict)
        except Exception as e:
            messages.error(request, 'Payment verification failed. Please contact support.')
            return redirect('bill_detail', bill_id)
        
        # Update payment record
        payment = Payment.objects.get(bill=bill, razorpay_order_id=order_id)
        payment.razorpay_payment_id = payment_id
        payment.razorpay_signature = signature
        payment.payment_status = 'success'
        payment.payment_date = timezone.now()
        payment.save()
        
        # Clean up any pending payments
        Payment.objects.filter(bill=bill, payment_status='pending').exclude(id=payment.id).delete()

        # Update bill status
        bill.payment_status = 'paid'
        bill.paid_date = timezone.now()
        bill.save()

        # Create activity record
        BillActivity.objects.create(
            bill=bill,
            type='payment',
            message=f'Payment of ₹{bill.amount} processed successfully via Razorpay'
        )

        # Send payment confirmation email synchronously
        try:
            # Prepare email context
            context = {
                'user': bill.user,
                'bill': bill,
                'payment': payment,
                'site_name': 'Bill Payment System',
                'site_url': settings.SITE_URL if hasattr(settings, 'SITE_URL') else request.build_absolute_uri('/'),
            }
            # Render HTML email template
            html_content = render_to_string('app/email/payment_success.html', context)
            plain_text = strip_tags(html_content)
            # Send email
            send_mail(
                subject=f'Payment Successful - {bill.title}',
                message=plain_text,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[bill.user.email],
                html_message=html_content,
                fail_silently=True,
            )
            # Log email sent
            BillActivity.objects.create(
                bill=bill,
                type='payment_confirmation',
                message=f'Payment confirmation email sent for ₹{payment.amount}'
            )
        except Exception as e:
            # Log email error but don't stop the payment process
            logger.error(f"Failed to send payment confirmation email: {str(e)}")
        
        # Show success message with user's name and bill details
        success_message = f'Thank you {request.user.get_full_name() or request.user.username}! Your payment of ₹{bill.amount} for {bill.title} has been processed successfully.'
        messages.success(request, success_message)
        return redirect('bill_detail', bill_id)
        
    except Exception as e:
        logger.error(f"Error processing payment: {str(e)}")
        messages.error(request, f'Error processing payment. Please try again or contact support.')
        return redirect('bill_detail', bill_id)

@login_required
def download_receipt(request, bill_id):
    bill = get_object_or_404(Bill, id=bill_id, user=request.user)
    
    if bill.payment_status != 'paid':
        messages.error(request, 'Receipt is only available for paid bills.')
        return redirect('bill_detail', pk=bill.id)
    
    # Get the payment details
    payment = bill.payments.filter(payment_status='success').first()
    if not payment:
        messages.error(request, 'Payment details not found.')
        return redirect('bill_detail', pk=bill.id)
    
    # Create a file-like buffer to receive PDF data
    buffer = BytesIO()
    
    # Create the PDF object using ReportLab
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=72,
        leftMargin=72,
        topMargin=72,
        bottomMargin=72
    )
    
    # Container for the 'Flowable' objects
    elements = []
    
    # Get styles
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=24,
        spaceAfter=30,
        alignment=1  # Center alignment
    )
    
    # Add the receipt title
    elements.append(Paragraph('Payment Receipt', title_style))
    elements.append(Spacer(1, 20))
    
    # Create the receipt data
    data = [
        ['Bill Title:', bill.title],
        ['Payment Date:', payment.payment_date.strftime('%B %d, %Y %H:%M')],
        ['Amount Paid:', f'₹{payment.amount}'],
        ['Payment Method:', payment.get_payment_method_display()],
        ['Reference Number:', payment.transaction_id],
        ['Category:', bill.get_category_display()],
        ['Paid By:', request.user.get_full_name() or request.user.username],
    ]
    
    # Create table style
    table_style = TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.lightgrey),
        ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 12),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
        ('TOPPADDING', (0, 0), (-1, -1), 12),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
    ])
    
    # Create the table and apply the style
    receipt_table = Table(data, colWidths=[4*cm, 12*cm])
    receipt_table.setStyle(table_style)
    
    # Add the table to the elements
    elements.append(receipt_table)
    elements.append(Spacer(1, 30))
    
    # Add footer
    footer_style = ParagraphStyle(
        'Footer',
        parent=styles['Normal'],
        fontSize=10,
        textColor=colors.gray,
        alignment=1  # Center alignment
    )
    elements.append(Paragraph('This is an electronically generated receipt.', footer_style))
    elements.append(Paragraph(f'Generated on: {timezone.now().strftime("%B %d, %Y %H:%M")}', footer_style))
    
    # Build the PDF
    doc.build(elements)
    
    # Get the value of the BytesIO buffer and write it to the response
    pdf = buffer.getvalue()
    buffer.close()
    
    # Create the HTTP response with PDF content
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="receipt_{bill.id}.pdf"'
    response.write(pdf)
    
    return response

def admin_login(request):
    # Redirect users to main login page
    return redirect('login')
    
@staff_member_required(login_url='login')
def admin_dashboard(request):
    # Count statistics
    total_users = User.objects.count()
    total_bills = Bill.objects.count()
    total_payments = Payment.objects.count()
    
    # Recent users
    recent_users = User.objects.order_by('-date_joined')[:5]
    
    # Recent bills
    recent_bills = Bill.objects.order_by('-created_at')[:5]
    
    # Recent payments
    recent_payments = Payment.objects.order_by('-payment_date')[:5]
    
    context = {
        'total_users': total_users,
        'total_bills': total_bills,
        'total_payments': total_payments,
        'recent_users': recent_users,
        'recent_bills': recent_bills,
        'recent_payments': recent_payments,
    }
    
    return render(request, 'app/admin/dashboard.html', context)

@staff_member_required(login_url='login')
def admin_user_list(request):
    users = User.objects.all().order_by('-date_joined')
    
    # Simple search functionality
    search_query = request.GET.get('search', '')
    if search_query:
        users = users.filter(
            Q(username__icontains=search_query) | 
            Q(email__icontains=search_query) |
            Q(first_name__icontains=search_query) |
            Q(last_name__icontains=search_query)
        )
    
    # Pagination
    paginator = Paginator(users, 10)  # Show 10 users per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    return render(request, 'app/admin/user_list.html', {'page_obj': page_obj, 'search_query': search_query})

@staff_member_required(login_url='login')
def admin_user_detail(request, user_id):
    user = get_object_or_404(User, id=user_id)
    user_bills = Bill.objects.filter(user=user).order_by('-created_at')
    user_payments = Payment.objects.filter(user=user).order_by('-payment_date')
    
    context = {
        'user': user,
        'user_bills': user_bills,
        'user_payments': user_payments,
    }
    
    return render(request, 'app/admin/user_detail.html', context)

@staff_member_required(login_url='login')
def admin_bill_list(request):
    bills = Bill.objects.all().order_by('-created_at')
    
    # Filtering
    status_filter = request.GET.get('status', '')
    if status_filter:
        bills = bills.filter(payment_status=status_filter)
    
    # Search
    search_query = request.GET.get('search', '')
    if search_query:
        bills = bills.filter(
            Q(title__icontains=search_query) | 
            Q(description__icontains=search_query) |
            Q(user__username__icontains=search_query)
        )
    
    # Pagination
    paginator = Paginator(bills, 10)  # Show 10 bills per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'page_obj': page_obj,
        'status_filter': status_filter,
        'search_query': search_query,
        'statuses': Bill.PAYMENT_STATUS_CHOICES,
    }
    
    return render(request, 'app/admin/bill_list.html', context)

@staff_member_required(login_url='login')
def admin_bill_detail(request, bill_id):
    bill = get_object_or_404(Bill, id=bill_id)
    payments = Payment.objects.filter(bill=bill).order_by('-payment_date')
    activities = BillActivity.objects.filter(bill=bill).order_by('-timestamp')
    
    context = {
        'bill': bill,
        'payments': payments,
        'activities': activities,
    }
    
    return render(request, 'app/admin/bill_detail.html', context)

@staff_member_required(login_url='login')
def admin_payment_list(request):
    payments = Payment.objects.all().order_by('-payment_date')
    
    # Filtering
    method_filter = request.GET.get('method', '')
    if method_filter:
        payments = payments.filter(payment_method=method_filter)
    
    # Search
    search_query = request.GET.get('search', '')
    if search_query:
        payments = payments.filter(
            Q(bill__title__icontains=search_query) | 
            Q(user__username__icontains=search_query) |
            Q(transaction_id__icontains=search_query)
        )
    
    # Pagination
    paginator = Paginator(payments, 10)  # Show 10 payments per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'page_obj': page_obj,
        'method_filter': method_filter,
        'search_query': search_query,
        'methods': Payment.PAYMENT_METHOD_CHOICES,
    }
    
    return render(request, 'app/admin/payment_list.html', context)

@staff_member_required(login_url='login')
def admin_payment_detail(request, payment_id):
    payment = get_object_or_404(Payment, id=payment_id)
    
    context = {
        'payment': payment,
    }
    
    return render(request, 'app/admin/payment_detail.html', context)

@staff_member_required(login_url='login')
def admin_toggle_user_status(request, user_id):
    if request.method == 'POST':
        user = get_object_or_404(User, id=user_id)
        
        # Don't allow blocking superusers
        if user.is_superuser:
            messages.error(request, "Superuser accounts cannot be blocked.")
            return redirect('admin_user_detail', user_id=user_id)
        
        action = request.POST.get('action', '')
        
        if action == 'block':
            user.is_active = False
            user.save()
            messages.success(request, f"User '{user.username}' has been blocked successfully.")
        elif action == 'unblock':
            user.is_active = True
            user.save()
            messages.success(request, f"User '{user.username}' has been unblocked successfully.")
        
        return redirect('admin_user_detail', user_id=user_id)
    
    # If not POST, redirect back to detail page
    return redirect('admin_user_detail', user_id=user_id)
