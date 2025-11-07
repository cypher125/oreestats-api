"""
URL routing for email_service app
"""
from django.urls import path
from . import views

app_name = 'email_service'

urlpatterns = [
    # Email sending endpoints
    path('email/send', views.send_email, name='send_email'),
    path('email/status/<uuid:lead_id>', views.email_status, name='email_status'),
    
    # Tracking endpoints
    path('track/open/<str:pixel_id>.png', views.track_open, name='track_open'),
    path('track/click/<str:click_id>', views.track_click, name='track_click'),
    path('track/reply', views.track_reply, name='track_reply'),
    
    # OAuth endpoints
    path('oauth/initiate/<uuid:client_id>', views.oauth_initiate, name='oauth_initiate'),
    path('oauth/callback', views.oauth_callback, name='oauth_callback'),
    
    # Utility endpoints
    path('health', views.health_check, name='health_check'),
    
    # Client Dashboard endpoints
    path('client/login', views.client_login, name='client_login'),
    path('client/logout', views.client_logout, name='client_logout'),
    path('client/stats', views.get_client_stats, name='client_stats'),
    path('client/campaigns', views.get_client_campaigns, name='client_campaigns'),
    path('client/replies', views.get_client_replies, name='client_replies'),
    path('client/timeline', views.get_client_timeline, name='client_timeline'),
    path('client/mailboxes', views.get_client_mailboxes, name='client_mailboxes'),
    path('client/change-password', views.change_client_password, name='change_password'),
    path('client/settings', views.update_client_settings, name='client_settings'),
]
