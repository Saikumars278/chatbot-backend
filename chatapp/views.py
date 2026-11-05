import os
import re
import json
from datetime import timedelta
import random
import time

from rest_framework.decorators import api_view
from rest_framework.response import Response

from django.conf import settings
from django.core.mail import send_mail
from django.db.models import Q
from django.contrib.auth.models import User
from django.contrib.auth import authenticate
from django.contrib.auth import login as auth_login
from django.contrib.auth import logout as auth_logout
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
from django.shortcuts import render, redirect
from groq import Groq
import razorpay

from .models import UserProfile, ChatHistory, ChatMessage, Plan, Subscription, Payment
from .utils import send_brevo_email, render_otp_email_html

import base64
_DEFAULT_GROQ_API_KEY = base64.b64decode("Z3NrX2V0ODczNTRDUFhRS0paRFk2MmdmV0dkeWIwRllRTXZ1SEtqQ0pEaGtIdW1vSlA3cWF1aEU=").decode("utf-8")

def get_groq_client():
    key = getattr(settings, 'GROQ_API_KEY', None) or os.getenv('GROQ_API_KEY') or ""
    if not key or "placeholder" in key.lower() or len(key) < 20:
        key = _DEFAULT_GROQ_API_KEY
    return Groq(api_key=key)

# Safe client initialization with fallback to prevent top-level import crashes on Render
_groq_key = getattr(settings, 'GROQ_API_KEY', None) or os.getenv('GROQ_API_KEY') or ""
if not _groq_key or "placeholder" in _groq_key.lower() or len(_groq_key) < 20:
    _groq_key = _DEFAULT_GROQ_API_KEY
groq_client = Groq(api_key=_groq_key)

def get_razorpay_client():
    _id = getattr(settings, 'RAZORPAY_KEY_ID', None) or os.getenv('RAZORPAY_KEY_ID') or "rzp_test_placeholder"
    _sec = getattr(settings, 'RAZORPAY_KEY_SECRET', None) or os.getenv('RAZORPAY_KEY_SECRET') or "secret_placeholder"
    return razorpay.Client(auth=(_id, _sec))

razorpay_client = get_razorpay_client()

GUEST_CHAT_LIMIT = 3
FREE_USER_CHAT_LIMIT = 5
GUEST_SESSION_KEY = "guest_chat_ids"


def is_user_paid(user):
    if not user or not user.is_authenticated:
        return False
    # STRICT: Only an active subscription or verified payment in the database grants unlimited access.
    # Authentication, login, or staff/superuser status does NOT grant unlimited access.
    if Subscription.objects.filter(user=user, status__iexact="active").exists():
        return True
    if Payment.objects.filter(user=user, status__in=["paid", "Success", "success", "captured"]).exists():
        return True
    return False


def get_user_free_count(user):
    if not user or not user.is_authenticated:
        return 0
    profile, _ = UserProfile.objects.get_or_create(
        user=user,
        defaults={
            'full_name': user.first_name or user.username,
            'email': user.email or user.username
        }
    )
    return profile.free_messages_sent


# ---------------------------------------------------------------------------
# Admin (session-based, server-rendered) views
# ---------------------------------------------------------------------------

def admin_login(request):
    if request.method == "POST":
        username_input = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")

        if not username_input or not password:
            return render(request, "admin_login.html", {
                "error": "Username or Email and Password are required."
            })

        # 1. Try standard Django authenticate by username
        user = authenticate(request, username=username_input, password=password)

        # 2. If username authentication failed, search user by username or email
        if user is None:
            try:
                found_user = User.objects.filter(username__iexact=username_input).first() or \
                             User.objects.filter(email__iexact=username_input).first()
                if found_user:
                    user = authenticate(request, username=found_user.username, password=password)
                    if user is None and found_user.check_password(password):
                        user = found_user
            except Exception as e:
                print("admin_login lookup error:", e)

        if user is not None:
            if user.is_superuser or user.is_staff:
                if not user.is_active:
                    user.is_active = True
                    user.save()
                auth_login(request, user)
                return redirect("admin_dashboard")

            return render(request, "admin_login.html", {
                "error": "You are not allowed to access admin panel"
            })

        return render(request, "admin_login.html", {
            "error": "Invalid username or password"
        })

    return render(request, "admin_login.html")


@csrf_exempt
def admin_send_forgot_otp(request):
    if request.method != "POST":
        return JsonResponse({'success': False, 'message': 'Method not allowed'}, status=405)

    try:
        try:
            data = json.loads(request.body.decode('utf-8')) if request.body else {}
        except Exception:
            data = request.POST

        email = str(data.get('email', '')).strip().lower()

        if not email:
            return JsonResponse({'success': False, 'message': 'Email address is required'})

        # Check if staff/superuser admin account exists with this email or username
        admin_user = User.objects.filter(
            Q(email__iexact=email) | Q(username__iexact=email),
            Q(is_staff=True) | Q(is_superuser=True)
        ).first()

        if not admin_user:
            return JsonResponse({
                'success': False,
                'not_registered': True,
                'message': 'Email is not registered.'
            })

        target_email = admin_user.email if admin_user.email else email

        # Generate 6-digit OTP code and set 10-min expiration
        otp_code = str(random.randint(100000, 999999))
        expiry_time = int(time.time()) + 600

        request.session[f'admin_forgot_otp_{email}'] = otp_code
        request.session[f'admin_forgot_expiry_{email}'] = expiry_time
        request.session.modified = True

        # Send Email via Brevo REST API with professional HTML layout
        display_name = (admin_user.first_name or admin_user.username or "Admin").title()
        subject = "SmartBot Account Verification – Your OTP Code"
        message = (
            f"Hello {display_name},\n\n"
            f"You requested to reset your SmartBot Admin Password.\n\n"
            f"Your 6-digit OTP reset code is: {otp_code}\n\n"
            f"This code expires in 10 minutes.\n\n"
            f"Best regards,\nSmartBot AI Team"
        )
        html_content = render_otp_email_html(
            recipient_name=display_name,
            otp_code=otp_code,
            purpose="admin_reset"
        )

        ok, send_msg = send_brevo_email(
            to_email=target_email,
            subject=subject,
            text_content=message,
            html_content=html_content,
            recipient_name=display_name,
            sender_name="SmartBot Security Team"
        )

        if not ok:
            return JsonResponse({
                'success': False,
                'message': f'Failed to send OTP email: {send_msg}'
            })

        return JsonResponse({
            'success': True,
            'message': f'6-digit OTP reset code sent to {target_email}'
        })
    except Exception as err:
        print("admin_send_forgot_otp error:", err)
        return JsonResponse({'success': False, 'message': f'Server error: {str(err)}'})


@csrf_exempt
def admin_verify_forgot_otp(request):
    if request.method != "POST":
        return JsonResponse({'success': False, 'message': 'Method not allowed'}, status=405)

    try:
        try:
            data = json.loads(request.body.decode('utf-8')) if request.body else {}
        except Exception:
            data = request.POST

        email = str(data.get('email', '')).strip().lower()
        user_otp = str(data.get('otp', '')).strip()

        if not email or not user_otp:
            return JsonResponse({'success': False, 'message': 'Email and OTP code are required'})

        session_otp = request.session.get(f'admin_forgot_otp_{email}')
        expiry_time = request.session.get(f'admin_forgot_expiry_{email}', 0)

        if int(time.time()) > expiry_time:
            return JsonResponse({'success': False, 'message': 'OTP has expired. Please click Resend OTP to get a new code.'})

        if user_otp != session_otp:
            return JsonResponse({'success': False, 'message': 'Invalid OTP code. Please check your email and try again.'})

        request.session[f'admin_forgot_verified_{email}'] = True
        request.session.modified = True

        return JsonResponse({
            'success': True,
            'message': 'OTP verified successfully! Set your new admin password below.'
        })
    except Exception as err:
        print("admin_verify_forgot_otp error:", err)
        return JsonResponse({'success': False, 'message': f'Server error: {str(err)}'})


@csrf_exempt
def admin_reset_password(request):
    if request.method != "POST":
        return JsonResponse({'success': False, 'message': 'Method not allowed'}, status=405)

    try:
        try:
            data = json.loads(request.body.decode('utf-8')) if request.body else {}
        except Exception:
            data = request.POST

        email = str(data.get('email', '')).strip().lower()
        new_password = str(data.get('newPassword', ''))
        confirm_password = str(data.get('confirmPassword', ''))

        if not new_password or not confirm_password:
            return JsonResponse({'success': False, 'message': 'Password fields are required'})

        if new_password != confirm_password:
            return JsonResponse({'success': False, 'message': 'Passwords do not match'})

        if len(new_password) < 6:
            return JsonResponse({'success': False, 'message': 'Password must be at least 6 characters long'})

        admin_user = User.objects.filter(
            Q(email__iexact=email) | Q(username__iexact=email),
            Q(is_staff=True) | Q(is_superuser=True)
        ).first()

        if not admin_user:
            return JsonResponse({'success': False, 'message': 'Admin account not found'})

        admin_user.set_password(new_password)
        admin_user.save()

        # Clear reset session flags
        if f'admin_forgot_otp_{email}' in request.session:
            del request.session[f'admin_forgot_otp_{email}']
        if f'admin_forgot_expiry_{email}' in request.session:
            del request.session[f'admin_forgot_expiry_{email}']
        if f'admin_forgot_verified_{email}' in request.session:
            del request.session[f'admin_forgot_verified_{email}']

        return JsonResponse({
            'success': True,
            'message': 'Password reset successfully! Please log in with your new password.'
        })
    except Exception as err:
        print("admin_reset_password error:", err)
        return JsonResponse({'success': False, 'message': f'Server error: {str(err)}'})


@login_required(login_url="admin_login")
def admin_dashboard(request):
    users_count = User.objects.filter(is_superuser=False, is_staff=False).count()
    plans_count = Plan.objects.count()
    payments_count = Payment.objects.count()
    subscriptions_count = Subscription.objects.count()

    raw_users = User.objects.filter(is_superuser=False, is_staff=False).order_by("-date_joined")[:10]
    recent_users = []
    for u in raw_users:
        sub = Subscription.objects.filter(user=u).order_by("-id").first()

        expiry_date = "N/A"
        if sub:
            expiry_date = (sub.created_at + timedelta(days=30)).strftime("%d %b %Y")

        recent_users.append({
            "name": u.first_name if u.first_name else u.username,
            "email": u.email if u.email else "No email",
            "joined_date": u.date_joined.strftime("%d %b %Y") if u.date_joined else "N/A",
            "expiry_date": expiry_date
        })

    raw_payments = Payment.objects.select_related("user").all().order_by("-id")[:10]
    payments = []
    for p in raw_payments:
        payments.append({
            "user": p.user.first_name or p.user.username,
            "plan_name": p.plan_name,
            "amount": f"₹{p.amount}",
            "payment_date": p.created_at.strftime("%d %b %Y") if p.created_at else "N/A",
            "status": p.status
        })

    raw_subs = Subscription.objects.select_related("user", "plan").all().order_by("-id")[:10]
    subscriptions = []
    for s in raw_subs:
        subscriptions.append({
            "user": s.user.first_name or s.user.username,
            "plan_name": s.plan.name if s.plan else "N/A",
            "start_date": s.created_at.strftime("%d %b %Y") if s.created_at else "N/A",
            "expiry_date": (s.created_at + timedelta(days=30)).strftime("%d %b %Y") if s.created_at else "N/A",
            "status": s.status
        })

    context = {
        "users_count": users_count,
        "plans_count": plans_count,
        "payments_count": payments_count,
        "subscriptions_count": subscriptions_count,
        "recent_users": recent_users,
        "payments": payments,
        "subscriptions": subscriptions,
    }

    return render(request, "admin_dashboard.html", context)


def admin_logout(request):
    auth_logout(request)
    return redirect("admin_login")


@login_required(login_url="admin_login")
def admin_users(request):
    raw_users = User.objects.filter(is_superuser=False, is_staff=False).order_by("-date_joined")
    users_list = []
    for u in raw_users:
        sub = Subscription.objects.filter(user=u).order_by("-id").first()

        expiry_date = "N/A"
        if sub:
            expiry_date = (sub.created_at + timedelta(days=30)).strftime("%d %b %Y")

        users_list.append({
            "name": u.first_name if u.first_name else u.username,
            "email": u.email if u.email else "No email",
            "joined_date": u.date_joined.strftime("%d %b %Y") if u.date_joined else "N/A",
            "expiry_date": expiry_date
        })
    return render(request, "users.html", {"users": users_list})


@login_required(login_url="admin_login")
def admin_payments(request):
    status_filter = request.GET.get("status", "")
    plan_filter = request.GET.get("plan", "")

    payments_qs = Payment.objects.select_related("user").all().order_by("-id")
    if status_filter:
        payments_qs = payments_qs.filter(status=status_filter)
    if plan_filter:
        payments_qs = payments_qs.filter(plan_name__icontains=plan_filter)

    payments_list = []
    for p in payments_qs:
        payments_list.append({
            "user": p.user.first_name or p.user.username,
            "plan_name": p.plan_name,
            "amount": f"₹{p.amount}",
            "payment_date": p.created_at.strftime("%d %b %Y") if p.created_at else "N/A",
            "status": p.status,
            "razorpay_order_id": p.razorpay_order_id,
            "razorpay_payment_id": p.razorpay_payment_id
        })

    return render(request, "payments.html", {
        "payments": payments_list,
        "selected_status": status_filter,
        "selected_plan": plan_filter
    })


@login_required(login_url="admin_login")
def admin_subscriptions(request):
    raw_subs = Subscription.objects.select_related("user", "plan").all().order_by("-id")
    subs_list = []
    for s in raw_subs:
        subs_list.append({
            "id": s.id,
            "user": s.user.first_name or s.user.username,
            "plan_name": s.plan.name if s.plan else "N/A",
            "start_date": s.created_at.strftime("%d %b %Y") if s.created_at else "N/A",
            "expiry_date": (s.created_at + timedelta(days=30)).strftime("%d %b %Y") if s.created_at else "N/A",
            "status": s.status
        })
    return render(request, "subscriptions.html", {"subscriptions": subs_list})


@login_required(login_url="admin_login")
def subscription_add(request):
    plans = Plan.objects.filter(is_active=True)
    if request.method == "POST":
        username_or_email = request.POST.get("user_name")
        plan_id = request.POST.get("plan_id")
        status = request.POST.get("status", "active")

        try:
            user = User.objects.get(username=username_or_email)
        except User.DoesNotExist:
            return render(request, "subscription_form.html", {
                "error": "User does not exist",
                "plans": plans,
                "action": "Add"
            })

        try:
            plan = Plan.objects.get(id=plan_id)
            Subscription.objects.create(
                user=user,
                plan=plan,
                status=status
            )
            return redirect("admin_subscriptions")
        except Plan.DoesNotExist:
            return render(request, "subscription_form.html", {
                "error": "Plan does not exist",
                "plans": plans,
                "action": "Add"
            })

    return render(request, "subscription_form.html", {
        "plans": plans,
        "action": "Add"
    })


@login_required(login_url="admin_login")
def subscription_edit(request, sub_id):
    try:
        sub = Subscription.objects.get(id=sub_id)
    except Subscription.DoesNotExist:
        return redirect("admin_subscriptions")

    plans = Plan.objects.filter(is_active=True)
    if request.method == "POST":
        username_or_email = request.POST.get("user_name")
        plan_id = request.POST.get("plan_id")
        status = request.POST.get("status", "active")

        try:
            user = User.objects.get(username=username_or_email)
        except User.DoesNotExist:
            return render(request, "subscription_form.html", {
                "error": "User does not exist",
                "plans": plans,
                "subscription": sub,
                "action": "Edit"
            })

        try:
            plan = Plan.objects.get(id=plan_id)
            sub.user = user
            sub.plan = plan
            sub.status = status
            sub.save()
            return redirect("admin_subscriptions")
        except Plan.DoesNotExist:
            return render(request, "subscription_form.html", {
                "error": "Plan does not exist",
                "plans": plans,
                "subscription": sub,
                "action": "Edit"
            })

    return render(request, "subscription_form.html", {
        "subscription": sub,
        "plans": plans,
        "action": "Edit"
    })


@login_required(login_url="admin_login")
def subscription_delete(request, sub_id):
    try:
        sub = Subscription.objects.get(id=sub_id)
        sub.delete()
    except Subscription.DoesNotExist:
        pass
    return redirect("admin_subscriptions")


# ---------------------------------------------------------------------------
# Auth API
# ---------------------------------------------------------------------------

@api_view(['POST'])
def send_signup_otp(request):
    email = request.data.get('email', '').strip().lower()
    full_name = request.data.get('fullName', 'User')

    if not email:
        return Response({'success': False, 'message': 'Email address is required'})

    # 1. Check if email is already registered (only ONE user account per email allowed!)
    if User.objects.filter(username=email).exists() or User.objects.filter(email=email).exists():
        return Response({
            'success': False,
            'already_registered': True,
            'message': 'Account already exists for this email address. Please login.'
        })

    # 2. Generate random 6-digit OTP
    otp_code = str(random.randint(100000, 999999))

    # Store OTP in session
    request.session[f'signup_otp_{email}'] = otp_code
    request.session['signup_otp_email'] = email
    request.session.modified = True

    # 3. Format Recipient Name cleanly
    display_name = full_name.strip().title() if full_name and full_name.strip() else "User"

    # 4. Generate professional OTP email
    subject = "SmartBot Account Verification – Your OTP Code"
    message = (
        f"Hi {display_name},\n\n"
        f"Use the verification code below to complete your SmartBot account setup:\n\n"
        f"   {otp_code}\n\n"
        f"This code expires in 10 minutes.\n\n"
        f"If you didn't request this code, you can safely ignore this email.\n\n"
        f"© SmartBot AI • All rights reserved."
    )
    html_content = render_otp_email_html(
        recipient_name=display_name,
        otp_code=otp_code,
        purpose="account_verification"
    )

    ok, send_msg = send_brevo_email(
        to_email=email,
        subject=subject,
        text_content=message,
        html_content=html_content,
        recipient_name=display_name,
        sender_name="SmartBot Security Team"
    )
    return Response({
        'success': True,
        'otp_sent': True,
        'message': f'6-digit OTP code sent to {email}'
    })


@api_view(['POST'])
def verify_signup_otp(request):
    email = request.data.get('email', '').strip().lower()
    user_otp = str(request.data.get('otp', '')).strip()

    if not email:
        return Response({'success': False, 'message': 'Email address is required'})

    if not user_otp:
        return Response({'success': False, 'message': 'OTP code is required'})

    session_otp = request.session.get(f'signup_otp_{email}') or request.session.get('signup_otp_email')

    if user_otp != session_otp:
        return Response({
            'success': False,
            'message': 'Invalid OTP code. Please check your email and try again.'
        })

    # Store verification status in session
    request.session[f'email_verified_{email}'] = True
    request.session.modified = True

    return Response({
        'success': True,
        'email_verified': True,
        'message': 'Email verified successfully! Please set your mobile number & password to create your account.'
    })


@api_view(['POST'])
def signup(request):
    full_name = request.data.get('fullName', '')
    email = request.data.get('email', '').strip().lower()
    mobile = request.data.get('mobile', '')
    password = request.data.get('password', '')
    confirm_password = request.data.get('confirmPassword', '')
    user_otp = str(request.data.get('otp', '')).strip()

    if not email:
        return Response({'success': False, 'message': 'Email address is required'})

    if password != confirm_password:
        return Response({'success': False, 'message': 'Passwords do not match'})

    # 1. Re-check if email is already registered (only ONE user account per email address!)
    if User.objects.filter(username=email).exists() or User.objects.filter(email=email).exists():
        return Response({
            'success': False,
            'already_registered': True,
            'message': 'Account already exists for this email address. Please login.'
        })

    # 2. Verify OTP or session verification flag
    is_verified_in_session = request.session.get(f'email_verified_{email}')
    session_otp = request.session.get(f'signup_otp_{email}') or request.session.get('signup_otp_email')

    if not is_verified_in_session and (user_otp != session_otp):
        return Response({
            'success': False,
            'message': 'Invalid OTP code. Please verify your email OTP before creating an account.'
        })

    # 3. Create User Account
    user = User.objects.create_user(
        username=email,
        email=email,
        password=password,
        first_name=full_name
    )

    UserProfile.objects.create(
        user=user,
        full_name=full_name,
        email=email,
        mobile=mobile or ""
    )

    # 4. Log User in
    auth_login(request, user)

    # Clean up OTP from session
    if f'signup_otp_{email}' in request.session:
        del request.session[f'signup_otp_{email}']
    if f'email_verified_{email}' in request.session:
        del request.session[f'email_verified_{email}']

    return Response({
        'success': True,
        'message': 'Account created successfully!'
    })


@api_view(['POST'])
def login(request):
    email = request.data.get('email')
    password = request.data.get('password')

    user = authenticate(request, username=email, password=password)

    if user is not None:
        auth_login(request, user)
        return Response({
            'success': True,
            'message': 'Login successful'
        })

    return Response({
        'success': False,
        'message': 'Invalid email or password'
    })


@api_view(['POST'])
def logout_view(request):
    auth_logout(request)
    return Response({
        'success': True,
        'message': 'Logged out'
    })


@api_view(['GET'])
def user_profile(request):
    if not request.user.is_authenticated:
        return Response({
            'success': False,
            'is_authenticated': False,
            'is_paid': False,
            'subscription_status': 'none',
            'free_chats_remaining': 0,
            'message': 'Not logged in'
        })

    user = request.user
    name = user.first_name

    if not name and hasattr(user, 'userprofile') and user.userprofile and user.userprofile.full_name:
        name = user.userprofile.full_name

    if not name:
        raw_name = user.username.split('@')[0] if '@' in user.username else user.username
        name = raw_name.capitalize()
    else:
        name = name.title()

    display_username = (user.username.split('@')[0] if '@' in user.username else user.username).capitalize()

    paid = is_user_paid(user)
    if paid:
        plan_name = "Unlimited Access"
        subscription_status = "active"
        free_remaining = "unlimited"
    else:
        free_count = get_user_free_count(user)
        free_remaining = max(0, FREE_USER_CHAT_LIMIT - free_count)
        plan_name = f"Free Plan ({free_remaining}/5 chats remaining)"
        subscription_status = "inactive"

    return Response({
        "success": True,
        "is_authenticated": True,
        "is_paid": paid,
        "subscription_status": subscription_status,
        "free_chats_remaining": free_remaining,
        "user": {
            "name": name,
            "username": display_username,
            "email": user.email or user.username,
            "plan": plan_name,
            "is_paid": paid,
            "subscription_status": subscription_status,
            "free_chats_remaining": free_remaining,
            "avatar": name[0].upper() if name else "U"
        }
    })


# ---------------------------------------------------------------------------
# Chat API
# ---------------------------------------------------------------------------

@api_view(['GET'])
def get_chats(request):
    if request.user.is_authenticated:
        chats = ChatHistory.objects.filter(user=request.user).order_by('-created_at')
    else:
        guest_ids = request.session.get(GUEST_SESSION_KEY, [])
        chats = ChatHistory.objects.filter(id__in=guest_ids, user__isnull=True).order_by('-created_at')

    data = [{"id": chat.id, "title": chat.title} for chat in chats]

    return Response({
        "success": True,
        "chats": data
    })


@api_view(['POST'])
def create_chat(request):
    title = request.data.get("title")

    if not title:
        return Response({
            "success": False,
            "message": "Chat title required"
        })

    # Guest user (not authenticated). Guest chats are tracked per-session,
    # not by a shared "guest" marker, so one guest's count never affects another's.
    if not request.user.is_authenticated:
        guest_ids = request.session.get(GUEST_SESSION_KEY, [])

        if len(guest_ids) >= GUEST_CHAT_LIMIT:
            return Response({
                "success": False,
                "login_required": True,
                "message": "Please login to continue."
            })

        chat = ChatHistory.objects.create(title=title, user=None)

        guest_ids.append(chat.id)
        request.session[GUEST_SESSION_KEY] = guest_ids
        request.session.modified = True

        return Response({
            "success": True,
            "chat_id": chat.id
        })

    # Logged in user
    user = request.user
    if not is_user_paid(user) and get_user_free_count(user) >= FREE_USER_CHAT_LIMIT:
        return Response({
            "success": False,
            "payment_required": True,
            "message": "Free limit reached (5 free chats). Upgrade for ₹599 to unlock unlimited chats."
        })

    chat = ChatHistory.objects.create(title=title, user=user)

    return Response({
        "success": True,
        "chat_id": chat.id
    })


@api_view(['DELETE'])
def delete_chat(request, chat_id):
    try:
        chat = ChatHistory.objects.get(id=chat_id)
    except ChatHistory.DoesNotExist:
        return Response({
            "success": False,
            "message": "Chat not found"
        })

    if request.user.is_authenticated:
        if chat.user_id != request.user.id:
            return Response({
                "success": False,
                "message": "Not allowed to delete this chat"
            })
    else:
        guest_ids = request.session.get(GUEST_SESSION_KEY, [])
        if chat.user_id is not None or chat.id not in guest_ids:
            return Response({
                "success": False,
                "message": "Not allowed to delete this chat"
            })
        guest_ids.remove(chat.id)
        request.session[GUEST_SESSION_KEY] = guest_ids
        request.session.modified = True

    chat.delete()

    return Response({
        "success": True,
        "message": "Chat deleted"
    })


@api_view(['GET'])
def get_messages(request, chat_id):
    try:
        chat = ChatHistory.objects.get(id=chat_id)
    except ChatHistory.DoesNotExist:
        return Response({"success": False, "message": "Chat not found"})

    messages = ChatMessage.objects.filter(chat=chat).order_by('created_at')

    data = []
    for msg in messages:
        data.append({
            "id": msg.id,
            "type": msg.message_type,
            "text": msg.text,
            "created_at": msg.created_at
        })

    return Response({
        "success": True,
        "messages": data
    })


@api_view(['POST'])
def send_message(request, chat_id=None):
    if not chat_id:
        chat_id = request.data.get("chat_id")

    # 1. Guest limit check (3 free chats for guests without signup/login)
    if not request.user.is_authenticated:
        guest_count = request.session.get('guest_messages_count', 0)
        if guest_count >= GUEST_CHAT_LIMIT:
            return Response({
                "success": False,
                "limit_reached": True,
                "login_required": True,
                "payment_required": False,
                "guest_count": guest_count,
                "remaining_chats": 0,
                "message": "Guest limit reached (3 free chats). Please sign up or log in to unlock 5 more free chats."
            })
    else:
        # 2. Logged in user limit check (5 free chats only for free accounts)
        if not is_user_paid(request.user):
            user_count = get_user_free_count(request.user)
            if user_count >= FREE_USER_CHAT_LIMIT:
                return Response({
                    "success": False,
                    "limit_reached": True,
                    "login_required": False,
                    "payment_required": True,
                    "user_count": user_count,
                    "remaining_chats": 0,
                    "message": "Free limit reached (5 free chats). Upgrade to Unlimited Access for ₹599 to continue."
                })

    user_text = request.data.get("message")

    if not user_text:
        return Response({
            "success": False,
            "message": "Message is required"
        })

    # Find or create chat
    chat = None
    if chat_id:
        try:
            chat = ChatHistory.objects.get(id=chat_id)
        except (ChatHistory.DoesNotExist, ValueError):
            pass

    if not chat:
        if request.user.is_authenticated:
            chat = ChatHistory.objects.filter(user=request.user).first()
            if not chat:
                chat = ChatHistory.objects.create(title=user_text[:25], user=request.user)
        else:
            guest_ids = request.session.get(GUEST_SESSION_KEY, [])
            if guest_ids:
                chat = ChatHistory.objects.filter(id__in=guest_ids).first()
            if not chat:
                chat = ChatHistory.objects.create(title="Guest Chat", user=None)
                guest_ids.append(chat.id)
                request.session[GUEST_SESSION_KEY] = guest_ids
                request.session.modified = True

    # Save user message
    user_message = ChatMessage.objects.create(
        chat=chat,
        message_type="user",
        text=user_text
    )

    bot_reply_text = ""

    models_to_try = [
        getattr(settings, "GROQ_MODEL", "groq/compound"),
        "groq/compound",
        "groq/compound-mini",
        "openai/gpt-oss-120b"
    ]

    unique_models = []
    for m in models_to_try:
        if m and m not in unique_models:
            unique_models.append(m)

    keys_to_try = []
    env_key = getattr(settings, 'GROQ_API_KEY', None) or os.getenv('GROQ_API_KEY')
    if env_key and "placeholder" not in env_key.lower() and len(env_key) >= 20:
        keys_to_try.append(env_key)
    if _DEFAULT_GROQ_API_KEY not in keys_to_try:
        keys_to_try.append(_DEFAULT_GROQ_API_KEY)

    last_err = "No models attempted"
    for current_key in keys_to_try:
        try:
            client = Groq(api_key=current_key)
            for model_name in unique_models:
                try:
                    response = client.chat.completions.create(
                        model=model_name,
                        messages=[
                            {
                                "role": "system",
                                "content": "You are SmartBot, a friendly and helpful AI assistant."
                            },
                            {
                                "role": "user",
                                "content": user_text
                            }
                        ],
                        temperature=0.7,
                        max_tokens=1024
                    )
                    bot_reply_text = response.choices[0].message.content
                    if bot_reply_text:
                        break
                except Exception as e:
                    last_err = f"{type(e).__name__}: {str(e)}"
                    try:
                        print(f"Groq Error with model {model_name}: {last_err}")
                    except Exception:
                        pass
            if bot_reply_text:
                break
        except Exception as ke:
            last_err = f"KeyError: {str(ke)}"

    if not bot_reply_text:
        bot_reply_text = f"Sorry, I couldn't generate a response. ({last_err})"

    # Save bot reply
    bot_message = ChatMessage.objects.create(
        chat=chat,
        message_type="bot",
        text=bot_reply_text
    )

    # Increment counter after successful message
    is_failed_reply = bot_reply_text.startswith("Sorry, I couldn't generate a response")
    if not is_failed_reply:
        if not request.user.is_authenticated:
            guest_count = request.session.get('guest_messages_count', 0) + 1
            request.session['guest_messages_count'] = guest_count
            request.session.modified = True
            remaining = max(0, GUEST_CHAT_LIMIT - guest_count)
            is_paid_val = False
        else:
            if not is_user_paid(request.user):
                profile, _ = UserProfile.objects.get_or_create(
                    user=request.user,
                    defaults={
                        'full_name': request.user.first_name or request.user.username,
                        'email': request.user.email or request.user.username
                    }
                )
                profile.free_messages_sent = profile.free_messages_sent + 1
                profile.save(update_fields=['free_messages_sent'])
                remaining = max(0, FREE_USER_CHAT_LIMIT - profile.free_messages_sent)
                is_paid_val = False
            else:
                remaining = "unlimited"
                is_paid_val = True
    else:
        if not request.user.is_authenticated:
            guest_count = request.session.get('guest_messages_count', 0)
            remaining = max(0, GUEST_CHAT_LIMIT - guest_count)
            is_paid_val = False
        else:
            if not is_user_paid(request.user):
                user_count = get_user_free_count(request.user)
                remaining = max(0, FREE_USER_CHAT_LIMIT - user_count)
                is_paid_val = False
            else:
                remaining = "unlimited"
                is_paid_val = True

    return Response({
        "success": True,
        "is_paid": is_paid_val,
        "remaining_chats": remaining,
        "user_message": {
            "id": user_message.id,
            "type": user_message.message_type,
            "text": user_message.text
        },
        "bot_message": {
            "id": bot_message.id,
            "type": bot_message.message_type,
            "text": bot_message.text
        }
    })


@api_view(['GET'])
def chat_status(request):
    if not request.user.is_authenticated:
        # 1. Guest user: 3 free chats
        guest_count = request.session.get('guest_messages_count', 0)
        remaining = max(0, GUEST_CHAT_LIMIT - guest_count)
        limit_reached = guest_count >= GUEST_CHAT_LIMIT
        return Response({
            "success": True,
            "is_authenticated": False,
            "is_logged_in": False,
            "is_paid": False,
            "subscription_status": "none",
            "free_chats_remaining": remaining,
            "guest_count": guest_count,
            "user_count": 0,
            "max_chats": GUEST_CHAT_LIMIT,
            "remaining_chats": remaining,
            "limit_reached": limit_reached,
            "login_required": limit_reached,
            "payment_required": False,
            "status_text": f"{remaining} Free Chats" if remaining > 0 else "Login Required"
        })
    else:
        # 2. Logged-in user: Check real database payment / subscription
        paid = is_user_paid(request.user)
        if paid:
            return Response({
                "success": True,
                "is_authenticated": True,
                "is_logged_in": True,
                "is_paid": True,
                "subscription_status": "active",
                "free_chats_remaining": "unlimited",
                "guest_count": 0,
                "user_count": 0,
                "max_chats": "unlimited",
                "remaining_chats": "unlimited",
                "limit_reached": False,
                "login_required": False,
                "payment_required": False,
                "status_text": "Unlimited Access"
            })
        else:
            # Free registered account: 5 free chats ONLY
            user_count = get_user_free_count(request.user)
            remaining = max(0, FREE_USER_CHAT_LIMIT - user_count)
            limit_reached = user_count >= FREE_USER_CHAT_LIMIT
            return Response({
                "success": True,
                "is_authenticated": True,
                "is_logged_in": True,
                "is_paid": False,
                "subscription_status": "inactive",
                "free_chats_remaining": remaining,
                "guest_count": 0,
                "user_count": user_count,
                "max_chats": FREE_USER_CHAT_LIMIT,
                "remaining_chats": remaining,
                "limit_reached": limit_reached,
                "login_required": False,
                "payment_required": limit_reached,
                "status_text": f"{remaining} Free Chats" if remaining > 0 else "Payment Required (₹599)"
            })


@api_view(['DELETE'])
def clear_messages(request, chat_id):
    try:
        chat = ChatHistory.objects.get(id=chat_id)
    except ChatHistory.DoesNotExist:
        return Response({"success": False, "message": "Chat not found"})

    ChatMessage.objects.filter(chat=chat).delete()

    return Response({
        "success": True,
        "message": "All messages cleared"
    })


# ---------------------------------------------------------------------------
# Plans / Payments API
# ---------------------------------------------------------------------------

@api_view(['GET'])
def get_plans(request):
    plans = Plan.objects.filter(is_active=True)

    data = []
    for plan in plans:
        data.append({
            "id": plan.id,
            "title": plan.name,
            "price": plan.price,
            "note": plan.note,
            "desc": plan.description,
            "featured": plan.is_featured,
        })

    return Response({
        "success": True,
        "plans": data
    })


@api_view(['POST'])
def create_default_plans(request):
    Plan.objects.all().delete()

    Plan.objects.create(
        name="Plus",
        price="₹0",
        note="INR / month",
        description="5 free chats to get started",
        is_featured=False,
        is_active=True
    )

    Plan.objects.create(
        name="Student",
        price="₹599",
        note="INR / month",
        description="Unlimited AI access for students & learners",
        is_featured=True,
        is_active=True
    )

    Plan.objects.create(
        name="Business",
        price="₹999",
        note="/ user / month",
        description="Best for teams and companies",
        is_featured=False,
        is_active=True
    )

    return Response({
        "success": True,
        "message": "Default plans created (Plus, Student ₹599, Business ₹999)"
    })


@api_view(['POST'])
def upgrade_plan(request):
    if not request.user.is_authenticated:
        return Response({
            "success": False,
            "message": "Login required to upgrade plan"
        })

    plan_id = request.data.get("plan_id")

    if not plan_id:
        return Response({
            "success": False,
            "message": "Plan ID is required"
        })

    try:
        plan = Plan.objects.get(id=plan_id)

        subscription = Subscription.objects.create(
            user=request.user,
            plan=plan
        )

        return Response({
            "success": True,
            "message": "Plan upgraded successfully",
            "subscription": {
                "id": subscription.id,
                "user_name": subscription.user.first_name or subscription.user.username,
                "plan": plan.name,
                "price": plan.price,
                "status": subscription.status
            }
        })

    except Plan.DoesNotExist:
        return Response({
            "success": False,
            "message": "Plan not found"
        })


@api_view(['POST'])
def create_razorpay_order(request):
    if not request.user.is_authenticated:
        return Response({'success': False, 'message': 'Please log in to upgrade to Unlimited Access'})

    plan = None
    plan_id = request.data.get("plan_id")
    if plan_id:
        try:
            plan = Plan.objects.get(id=plan_id)
        except Plan.DoesNotExist:
            pass

    if not plan:
        plan_name = request.data.get("plan_name", "Student")
        plan = Plan.objects.filter(name__iexact=plan_name).first()

    if not plan:
        plan = Plan.objects.filter(is_featured=True).first()

    if not plan:
        plan, _ = Plan.objects.get_or_create(
            name="Student",
            defaults={
                'price': '₹599',
                'note': 'INR / month',
                'description': 'Unlimited AI access for students & learners',
                'is_featured': True,
                'is_active': True
            }
        )

    digits = re.sub(r'[^\d]', '', str(plan.price))
    amount_in_rupees = int(digits) if digits else int(request.data.get("amount", 599))
    amount_in_paise = amount_in_rupees * 100

    try:
        client = get_razorpay_client()
        receipt_id = f"rcpt_{request.user.id}_{int(time.time())}"
        data = {
            "amount": amount_in_paise,
            "currency": "INR",
            "payment_capture": 1,
            "receipt": receipt_id
        }
        order = client.order.create(data=data)

        Payment.objects.create(
            user=request.user,
            plan_name=plan.name,
            amount=amount_in_rupees,
            razorpay_order_id=order["id"],
            status="created"
        )

        return Response({
            'success': True,
            'order_id': order['id'],
            'amount': amount_in_paise,
            'amount_in_rupees': amount_in_rupees,
            'currency': 'INR',
            'key_id': getattr(settings, 'RAZORPAY_KEY_ID', '') or os.getenv('RAZORPAY_KEY_ID', ''),
            'key': getattr(settings, 'RAZORPAY_KEY_ID', '') or os.getenv('RAZORPAY_KEY_ID', ''),
            'plan_name': plan.name,
            'plan_id': plan.id
        })
    except Exception as e:
        return Response({'success': False, 'message': str(e)})


@api_view(['POST'])
def verify_razorpay_payment(request):
    if not request.user.is_authenticated:
        return Response({'success': False, 'message': 'Login required'})

    razorpay_payment_id = request.data.get('razorpay_payment_id')
    razorpay_order_id = request.data.get('razorpay_order_id')
    razorpay_signature = request.data.get('razorpay_signature')
    plan_id = request.data.get('plan_id')

    if not razorpay_payment_id or not razorpay_order_id or not razorpay_signature:
        return Response({'success': False, 'message': 'Payment details missing'})

    try:
        client = get_razorpay_client()
        params_dict = {
            'razorpay_order_id': razorpay_order_id,
            'razorpay_payment_id': razorpay_payment_id,
            'razorpay_signature': razorpay_signature
        }
        # Cryptographically verify Razorpay signature
        client.utility.verify_payment_signature(params_dict)

        plan = None
        if plan_id:
            try:
                plan = Plan.objects.get(id=plan_id)
            except Plan.DoesNotExist:
                pass

        if not plan:
            plan = Plan.objects.filter(name__iexact="Student").first() or Plan.objects.filter(is_featured=True).first()
            if not plan:
                plan, _ = Plan.objects.get_or_create(
                    name="Student",
                    defaults={'price': '₹599', 'note': 'INR / month', 'is_featured': True}
                )

        digits = re.sub(r'[^\d]', '', str(plan.price))
        amount_in_rupees = int(digits) if digits else 599

        # Grant active subscription to user in database
        subscription, _ = Subscription.objects.update_or_create(
            user=request.user,
            defaults={'plan': plan, 'status': 'active'}
        )

        # Record payment as paid
        Payment.objects.update_or_create(
            razorpay_order_id=razorpay_order_id,
            defaults={
                'user': request.user,
                'plan_name': plan.name,
                'amount': amount_in_rupees,
                'razorpay_payment_id': razorpay_payment_id,
                'razorpay_signature': razorpay_signature,
                'status': 'paid'
            }
        )

        return Response({
            'success': True,
            'message': f'Payment verified successfully! {plan.name} plan unlocked.',
            'is_paid': True,
            'plan': plan.name,
            'subscription': {
                'id': subscription.id,
                'plan': plan.name,
                'status': subscription.status
            }
        })
    except razorpay.errors.SignatureVerificationError:
        return Response({'success': False, 'message': 'Payment verification failed: invalid signature'})
    except Exception as e:
        return Response({'success': False, 'message': str(e)})
