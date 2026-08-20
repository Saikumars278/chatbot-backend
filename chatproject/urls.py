from django.contrib import admin
from django.urls import path
from chatapp.views import signup, login, get_chats, create_chat, delete_chat, user_profile, get_messages, send_message, clear_messages, get_plans, create_default_plans, upgrade_plan, chat_status, logout_view
from django.urls import path
from chatapp import views

urlpatterns = [
    
    path('admin/', admin.site.urls),
    path("", views.admin_login, name="admin_login"),
    path("admin-dashboard/", views.admin_dashboard, name="admin_dashboard"),
    path("admin-logout/", views.admin_logout, name="admin_logout"),
    path("admin-users/", views.admin_users, name="admin_users"),
    path("admin-payments/", views.admin_payments, name="admin_payments"),
    path("admin-subscriptions/", views.admin_subscriptions, name="admin_subscriptions"),
    path("admin-subscriptions/add/", views.subscription_add, name="subscription_add"),
    path("admin-subscriptions/edit/<int:sub_id>/", views.subscription_edit, name="subscription_edit"),
    path("admin-subscriptions/delete/<int:sub_id>/", views.subscription_delete, name="subscription_delete"),


    path('api/signup/', signup, name='signup'),
    path('api/send-signup-otp/', views.send_signup_otp, name='send_signup_otp'),
    path('api/verify-signup-otp/', views.verify_signup_otp, name='verify_signup_otp'),
    path('api/login/', login, name='login'),
    path('api/logout/', logout_view, name='logout'),
    path('api/chats/', get_chats, name='get_chats'),
    path('api/chats/create/', create_chat, name='create_chat'),
    path('api/chats/delete/<int:chat_id>/', delete_chat, name='delete_chat'),
    path('api/user/profile/', user_profile, name='user_profile'),
    path('api/user-profile/', user_profile, name='user_profile_alt'),
    path('api/chat-status/', chat_status, name='chat_status'),
    path('api/messages/', get_messages, name='get_messages'),
    path('api/messages/send/', send_message, name='send_message'),
    path('api/messages/send/<int:chat_id>/', send_message, name='send_message_with_id'),
    path('api/messages/clear/', clear_messages, name='clear_messages'),
    path('api/plans/', get_plans, name='get_plans'),
    path('api/plans/create-default/', create_default_plans, name='create_default_plans'),
    path('api/upgrade-plan/', upgrade_plan, name='upgrade_plan'),
    path('api/create-razorpay-order/', views.create_razorpay_order, name='create_razorpay_order'),
    path('api/verify-razorpay-payment/', views.verify_razorpay_payment, name='verify_razorpay_payment'),
]