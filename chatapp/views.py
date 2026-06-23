from datetime import timedelta

from rest_framework.decorators import api_view
from rest_framework.response import Response

from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.auth import authenticate
from django.contrib.auth import login as auth_login
from django.contrib.auth import logout as auth_logout
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from groq import Groq
import razorpay

from .models import UserProfile, ChatHistory, ChatMessage, Plan, Subscription, Payment

groq_client = Groq(api_key=settings.GROQ_API_KEY)
razorpay_client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))

GUEST_CHAT_LIMIT = 5
FREE_USER_CHAT_LIMIT = 10
GUEST_SESSION_KEY = "guest_chat_ids"


# ---------------------------------------------------------------------------
# Admin (session-based, server-rendered) views
# ---------------------------------------------------------------------------

def admin_login(request):
    if request.method == "POST":
        username = request.POST.get("username")
        password = request.POST.get("password")

        user = authenticate(request, username=username, password=password)

        if user is not None:
            if user.is_superuser or user.is_staff:
                auth_login(request, user)
                return redirect("admin_dashboard")

            return render(request, "admin_login.html", {
                "error": "You are not allowed to access admin panel"
            })

        return render(request, "admin_login.html", {
            "error": "Invalid username or password"
        })

    return render(request, "admin_login.html")


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
def signup(request):
    full_name = request.data.get('fullName')
    email = request.data.get('email')
    mobile = request.data.get('mobile')
    password = request.data.get('password')
    confirm_password = request.data.get('confirmPassword')

    if password != confirm_password:
        return Response({'success': False, 'message': 'Passwords do not match'})

    if User.objects.filter(username=email).exists():
        return Response({'success': False, 'message': 'Email already exists'})

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

    return Response({
        'success': True,
        'message': 'Signup successful'
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
        return Response({'success': False, 'message': 'Not logged in'})

    user = request.user
    plan_name = "Free Plan"
    sub = Subscription.objects.filter(user=user, status="active").order_by("-id").first()
    if sub and sub.plan:
        plan_name = sub.plan.name

    name = user.first_name or user.username
    return Response({
        "success": True,
        "user": {
            "name": name,
            "email": user.email,
            "plan": plan_name,
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
    total_chats = ChatHistory.objects.filter(user=user).count()

    if total_chats >= FREE_USER_CHAT_LIMIT:
        subscription = Subscription.objects.filter(
            user=user,
            status="active"
        ).exists()

        if not subscription:
            return Response({
                "success": False,
                "payment_required": True,
                "message": "Free limit reached. Upgrade your plan."
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

    # Access limit check
    if not request.user.is_authenticated:
        guest_count = request.session.get('guest_messages_count', 0)
        if guest_count >= 2:
            return Response({
                "success": False,
                "limit_reached": True,
                "login_required": True,
                "message": "Guest limit reached. Please log in."
            })
    else:
        is_paid = Subscription.objects.filter(user=request.user, status="active").exists()
        if not is_paid:
            profile, _ = UserProfile.objects.get_or_create(user=request.user, defaults={'email': request.user.email or f"{request.user.username}@example.com"})
            if profile.free_messages_sent >= 5:
                return Response({
                    "success": False,
                    "limit_reached": True,
                    "payment_required": True,
                    "message": "Free limit reached. Upgrade your plan."
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

    # Increment limits
    if not request.user.is_authenticated:
        guest_count = request.session.get('guest_messages_count', 0)
        request.session['guest_messages_count'] = guest_count + 1
        request.session.modified = True
    else:
        is_paid = Subscription.objects.filter(user=request.user, status="active").exists()
        if not is_paid:
            profile, _ = UserProfile.objects.get_or_create(user=request.user, defaults={'email': request.user.email or f"{request.user.username}@example.com"})
            profile.free_messages_sent += 1
            profile.save()

    bot_reply_text = ""

    try:
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
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

    except Exception as e:
        print("Groq Error:", str(e))
        bot_reply_text = "Sorry, I couldn't generate a response."

    # Save bot reply
    bot_message = ChatMessage.objects.create(
        chat=chat,
        message_type="bot",
        text=bot_reply_text
    )

    return Response({
        "success": True,
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
        guest_count = request.session.get('guest_messages_count', 0)
        remaining = max(0, 2 - guest_count)
        return Response({
            "success": True,
            "is_logged_in": False,
            "is_paid": False,
            "guest_count": guest_count,
            "remaining_chats": remaining,
            "limit_reached": guest_count >= 2,
            "status_text": f"{remaining} remaining free chats" if remaining > 0 else "Login required"
        })
    else:
        user = request.user
        is_paid = Subscription.objects.filter(user=user, status="active").exists()
        if is_paid:
            return Response({
                "success": True,
                "is_logged_in": True,
                "is_paid": True,
                "remaining_chats": "unlimited",
                "limit_reached": False,
                "status_text": "Unlimited Access"
            })
        else:
            profile, _ = UserProfile.objects.get_or_create(user=user, defaults={'email': user.email or f"{user.username}@example.com"})
            user_count = profile.free_messages_sent
            remaining = max(0, 5 - user_count)
            return Response({
                "success": True,
                "is_logged_in": True,
                "is_paid": False,
                "remaining_chats": remaining,
                "limit_reached": user_count >= 5,
                "status_text": f"{remaining} remaining free chats" if remaining > 0 else "Upgrade required"
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
        description="More access to advanced intelligence",
        is_featured=False
    )

    Plan.objects.create(
        name="Business",
        price="₹1,800",
        note="/ user / month",
        description="Best for teams and companies",
        is_featured=True
    )

    Plan.objects.create(
        name="Pro",
        price="₹10,699",
        note="INR / month",
        description="Maximize your productivity",
        is_featured=False
    )

    return Response({
        "success": True,
        "message": "Default plans created"
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
        return Response({
            "success": False,
            "message": "Login required to make a payment"
        })

    plan_name = request.data.get("plan_name")
    amount = request.data.get("amount")

    if not plan_name or not amount:
        return Response({
            "success": False,
            "message": "Plan name and amount required"
        })

    amount_in_paise = int(amount) * 100

    client = razorpay.Client(
        auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET)
    )

    order_data = {
        "amount": amount_in_paise,
        "currency": "INR",
        "payment_capture": 1
    }

    razorpay_order = client.order.create(data=order_data)

    payment = Payment.objects.create(
        user=request.user,
        plan_name=plan_name,
        amount=amount,
        razorpay_order_id=razorpay_order["id"],
        status="created"
    )

    return Response({
        "success": True,
        "key": settings.RAZORPAY_KEY_ID,
        "order_id": razorpay_order["id"],
        "amount": amount_in_paise,
        "currency": "INR",
        "payment_db_id": payment.id
    })


@api_view(['POST'])
def verify_razorpay_payment(request):
    razorpay_order_id = request.data.get("razorpay_order_id")
    razorpay_payment_id = request.data.get("razorpay_payment_id")
    razorpay_signature = request.data.get("razorpay_signature")

    client = razorpay.Client(
        auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET)
    )

    params_dict = {
        "razorpay_order_id": razorpay_order_id,
        "razorpay_payment_id": razorpay_payment_id,
        "razorpay_signature": razorpay_signature
    }

    try:
        client.utility.verify_payment_signature(params_dict)

        payment = Payment.objects.get(razorpay_order_id=razorpay_order_id)
        payment.razorpay_payment_id = razorpay_payment_id
        payment.razorpay_signature = razorpay_signature
        payment.status = "paid"
        payment.save()

        return Response({
            "success": True,
            "message": "Payment verified successfully"
        })

    except Exception:
        return Response({
            "success": False,
            "message": "Payment verification failed"
        })
@api_view(['POST'])
def create_razorpay_order(request):
    if not request.user.is_authenticated:
        return Response({'success': False, 'message': 'Login required'})

    plan_id = request.data.get('plan_id')
    if not plan_id:
        return Response({'success': False, 'message': 'Plan ID is required'})

    try:
        import re
        plan = Plan.objects.get(id=plan_id)
        # Extract only digits and decimal points from the price string
        price_str = re.sub(r'[^\d.]', '', plan.price)
        amount_in_paise = int(float(price_str) * 100)

        data = {
            "amount": amount_in_paise,
            "currency": "INR",
            "receipt": f"receipt_plan_{plan.id}_{request.user.id}"
        }
        payment = razorpay_client.order.create(data=data)

        return Response({
            'success': True,
            'order_id': payment['id'],
            'amount': payment['amount'],
            'currency': payment['currency'],
            'key_id': settings.RAZORPAY_KEY_ID
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

    try:
        params_dict = {
            'razorpay_order_id': razorpay_order_id,
            'razorpay_payment_id': razorpay_payment_id,
            'razorpay_signature': razorpay_signature
        }
        razorpay_client.utility.verify_payment_signature(params_dict)

        plan = Plan.objects.get(id=plan_id)
        subscription = Subscription.objects.create(
            user=request.user,
            plan=plan
        )
        Payment.objects.create(
            user=request.user,
            subscription=subscription,
            amount=plan.price,
            status='Success',
            transaction_id=razorpay_payment_id
        )

        return Response({
            'success': True,
            'message': 'Payment successful, plan upgraded',
            'subscription': {
                'id': subscription.id,
                'plan': plan.name,
            }
        })
    except razorpay.errors.SignatureVerificationError:
        return Response({'success': False, 'message': 'Payment verification failed'})
    except Exception as e:
        return Response({'success': False, 'message': str(e)})
