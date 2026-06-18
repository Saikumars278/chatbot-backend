from django.contrib import admin
from django.urls import path
from chatapp.views import signup, login,get_chats, create_chat, delete_chat, user_profile, get_messages, send_message, clear_messages,get_plans, create_default_plans, upgrade_plan
from django.urls import path
from chatapp import views

urlpatterns = [
    
    path('admin/', admin.site.urls),
    path("", views.admin_login, name="admin_login"),
    path("admin-dashboard/", views.admin_dashboard, name="admin_dashboard"),
    path("admin-logout/", views.admin_logout, name="admin_logout"),


    path('api/signup/', signup, name='signup'),
    path('api/login/', login, name='login'),
    path('api/chats/', get_chats, name='get_chats'),
    path('api/chats/create/', create_chat, name='create_chat'),
    path('api/chats/delete/<int:chat_id>/', delete_chat, name='delete_chat'),
    path('api/user/profile/', user_profile, name='user_profile'),
    path('api/messages/', get_messages, name='get_messages'),
    path('api/messages/send/', send_message, name='send_message'),
    path('api/messages/clear/', clear_messages, name='clear_messages'),
    path('api/plans/', get_plans, name='get_plans'),
    path('api/plans/create-default/', create_default_plans, name='create_default_plans'),
    path('api/upgrade-plan/', upgrade_plan, name='upgrade_plan'),
]