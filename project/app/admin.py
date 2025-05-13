from django.contrib import admin
from django.utils.html import format_html
from .models import Bill, Profile, ReminderSettings, BillActivity

@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'phone_number', 'get_profile_picture')
    search_fields = ('user__username', 'user__email', 'phone_number')
    
    def get_profile_picture(self, obj):
        if obj.profile_picture:
            return format_html('<img src="{}" width="50" height="50" style="border-radius: 50%;" />', obj.profile_picture.url)
        return "No Picture"
    get_profile_picture.short_description = 'Profile Picture'

@admin.register(Bill)
class BillAdmin(admin.ModelAdmin):
    list_display = ('title', 'user', 'amount', 'due_date', 'category', 'payment_status', 'is_overdue')
    list_filter = ('payment_status', 'category', 'due_date')
    search_fields = ('title', 'description', 'user__username', 'user__email')
    date_hierarchy = 'due_date'
    
    def is_overdue(self, obj):
        if obj.payment_status == 'overdue':
            return format_html('<span style="color: red;">Overdue</span>')
        return format_html('<span style="color: green;">Not Overdue</span>')
    is_overdue.short_description = 'Status'

@admin.register(ReminderSettings)
class ReminderSettingsAdmin(admin.ModelAdmin):
    list_display = ('user', 'email_reminders', 'push_notifications', 'default_reminder_days')
    list_filter = ('email_reminders', 'push_notifications')
    search_fields = ('user__username', 'user__email')

@admin.register(BillActivity)
class BillActivityAdmin(admin.ModelAdmin):
    list_display = ('bill', 'type', 'message', 'timestamp')
    list_filter = ('type', 'timestamp')
    search_fields = ('bill__title', 'message', 'bill__user__username')
    date_hierarchy = 'timestamp'
    readonly_fields = ('timestamp',)
