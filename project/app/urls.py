from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    path('', views.index, name='index'),
    path('login/', views.CustomLoginView.as_view(), name='login'),
    path('logout/', auth_views.LogoutView.as_view(next_page='login'), name='logout'),
    path('register/', views.register, name='register'),
    path('profile/', views.profile, name='profile'),
    path('profile/delete_picture/', views.delete_profile_picture, name='delete_profile_picture'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('bills/', views.bill_list, name='bill_list'),
    path('bills/create/', views.bill_create, name='bill_create'),
    path('bills/<int:pk>/', views.bill_detail, name='bill_detail'),
    path('bills/<int:pk>/update/', views.bill_update, name='bill_update'),
    path('bills/<int:pk>/delete/', views.bill_delete, name='bill_delete'),
    path('bills/<int:pk>/mark-paid/', views.mark_bill_paid, name='mark_bill_paid'),
    path('calendar/', views.calendar_view, name='calendar'),
    
    # Password Change URLs
    path('password_change/', auth_views.PasswordChangeView.as_view(template_name='app/password_change.html'), name='password_change'),
    path('password_change/done/', auth_views.PasswordChangeDoneView.as_view(template_name='app/password_change_done.html'), name='password_change_done'),
    
    # Password Reset URLs
    path('password_reset/', views.CustomPasswordResetView.as_view(), name='password_reset'),
    path('password_reset/done/', views.CustomPasswordResetDoneView.as_view(), name='password_reset_done'),
    path('password_reset/verify-otp/<uidb64>/<token>/', views.VerifyOTPView.as_view(), name='verify_otp'),
    path('password_reset/confirm/<uidb64>/<token>/', views.CustomPasswordResetConfirmView.as_view(), name='password_reset_confirm'),
    path('password_reset/complete/', views.CustomPasswordResetCompleteView.as_view(), name='password_reset_complete'),
    path('settings/reminder/', views.update_reminder_settings, name='update_reminder_settings'),
    path('reminder-settings/', views.reminder_settings, name='reminder_settings'),
    path('reminder-settings/update/', views.update_reminder_settings, name='update_reminder_settings'),
    path('test-email/', views.test_email, name='test_email'),
    
    # Notification URLs
    path('notifications/', views.notification_history, name='notification_history'),
    path('bill/<int:bill_id>/send-reminder/', views.send_manual_reminder, name='send_manual_reminder'),
    path('bill/<int:bill_id>/pay/', views.initiate_payment, name='initiate_payment'),
    path('bill/<int:bill_id>/process-payment/', views.process_payment, name='process_payment'),
    path('bill/<int:bill_id>/download-receipt/', views.download_receipt, name='download_receipt'),
    
    # Admin URLs
    path('admin-portal/', views.admin_login, name='admin_login'),
    path('admin-portal/dashboard/', views.admin_dashboard, name='admin_dashboard'),
    path('admin-portal/users/', views.admin_user_list, name='admin_user_list'),
    path('admin-portal/users/<int:user_id>/', views.admin_user_detail, name='admin_user_detail'),
    path('admin-portal/bills/', views.admin_bill_list, name='admin_bill_list'),
    path('admin-portal/bills/<int:bill_id>/', views.admin_bill_detail, name='admin_bill_detail'),
    path('admin-portal/payments/', views.admin_payment_list, name='admin_payment_list'),
    path('admin-portal/payments/<int:payment_id>/', views.admin_payment_detail, name='admin_payment_detail'),
    path('admin-portal/users/<int:user_id>/toggle-status/', views.admin_toggle_user_status, name='admin_toggle_user_status'),
] 