from rest_framework.decorators import api_view
from rest_framework.response import Response

from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.auth import authenticate
from django.contrib.auth import login as auth_login
from django.contrib.auth import logout as auth_logout
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect

import razorpay

from .models import ChatHistory, ChatMessage, Plan, Subscription, Payment


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
    from datetime import timedelta
    for u in raw_users:
        sub = Subscription.objects.filter(user_name=u.username).order_by("-id").first()
        if not sub and u.first_name:
            sub = Subscription.objects.filter(user_name=u.first_name).order_by("-id").first()
        
        expiry_date = "N/A"
        if sub:
            expiry_date = (sub.created_at + timedelta(days=30)).strftime("%d %b %Y")
        
        recent_users.append({
            "name": u.first_name if u.first_name else u.username,
            "email": u.email if u.email else "No email",
            "joined_date": u.date_joined.strftime("%d %b %Y") if u.date_joined else "N/A",
            "expiry_date": expiry_date
        })

    raw_payments = Payment.objects.all().order_by("-id")[:10]
    payments = []
    for p in raw_payments:
        # Since Payment doesn't link directly to User, try to find a user/subscription or default to Dhanush/Guest
        user_display = "Guest"
        # If there's an active subscription with same plan name around that time, or we can check first user
        first_user = User.objects.first()
        if first_user:
            user_display = first_user.first_name or first_user.username
        
        payments.append({
            "user": user_display,
            "plan_name": p.plan_name,
            "amount": f"₹{p.amount}",
            "payment_date": p.created_at.strftime("%d %b %Y") if p.created_at else "N/A",
            "status": p.status
        })

    raw_subs = Subscription.objects.all().order_by("-id")[:10]
    subscriptions = []
    for s in raw_subs:
        subscriptions.append({
            "user": s.user_name,
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

    user.save()

    return Response({
        'success': True,
        'message': 'Signup successful'
    })


@api_view(['POST'])
def login(request):
    email = request.data.get('email')
    password = request.data.get('password')

    user = authenticate(username=email, password=password)

    if user is not None:
        return Response({
            'success': True,
            'message': 'Login successful'
        })

    return Response({
        'success': False,
        'message': 'Invalid email or password'
    })


@api_view(['GET'])
def get_chats(request):
    chats = ChatHistory.objects.all().order_by('-created_at')

    data = []
    for chat in chats:
        data.append({
            "id": chat.id,
            "title": chat.title
        })

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
            "message": "Chat title is required"
        })

    chat = ChatHistory.objects.create(title=title)

    return Response({
        "success": True,
        "message": "Chat created",
        "chat": {
            "id": chat.id,
            "title": chat.title
        }
    })


@api_view(['DELETE'])
def delete_chat(request, chat_id):
    try:
        chat = ChatHistory.objects.get(id=chat_id)
        chat.delete()

        return Response({
            "success": True,
            "message": "Chat deleted"
        })

    except ChatHistory.DoesNotExist:
        return Response({
            "success": False,
            "message": "Chat not found"
        })


@api_view(['GET'])
def user_profile(request):
    return Response({
        "success": True,
        "user": {
            "name": "Dhanush",
            "plan": "Free Plan",
            "avatar": "D"
        }
    })

@api_view(['GET'])
def get_messages(request):
    messages = ChatMessage.objects.all().order_by('created_at')

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
def send_message(request):
    import requests as http_requests

    user_text = request.data.get("message")

    if not user_text:
        return Response({
            "success": False,
            "message": "Message is required"
        })

    user_message = ChatMessage.objects.create(
        message_type="user",
        text=user_text
    )

    # ── Google Gemini API (Free Tier) ──────────────────────────────────
    # Get a FREE key at: https://aistudio.google.com/app/apikey
    GEMINI_API_KEY = getattr(settings, 'GEMINI_API_KEY', '')

    bot_reply_text = ""

    if GEMINI_API_KEY:
        try:
            gemini_url = (
                f"https://generativelanguage.googleapis.com/v1beta/models/"
                f"gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
            )
            payload = {
                "system_instruction": {
                    "parts": [{"text": "You are SmartBot, a friendly and helpful AI assistant."}]
                },
                "contents": [
                    {"parts": [{"text": user_text}]}
                ],
                "generationConfig": {
                    "maxOutputTokens": 1024,
                    "temperature": 0.7,
                }
            }
            resp = http_requests.post(gemini_url, json=payload, timeout=30)
            result = resp.json()
            if resp.status_code == 200:
                bot_reply_text = (
                    result.get("candidates", [{}])[0]
                    .get("content", {})
                    .get("parts", [{}])[0]
                    .get("text", "")
                    .strip()
                )
            else:
                err = result.get("error", {}).get("message", "Gemini API error")
                print("Gemini Error:", err)
        except Exception as e:
            print("Gemini Request Exception:", str(e))

    # ── Smart keyword fallback if no API key or empty response ──────────
    if not bot_reply_text:
        text_lower = user_text.lower()
        if any(w in text_lower for w in ["hello", "hi", "hey", "greet"]):
            bot_reply_text = "Hello! I'm SmartBot 👋 How can I assist you today?"
        elif any(w in text_lower for w in ["how are you", "how r you"]):
            bot_reply_text = "I'm doing great, thanks for asking! How can I help you?"
        elif any(w in text_lower for w in ["price", "plan", "subscription", "cost", "upgrade"]):
            bot_reply_text = "We offer 3 plans: **Plus** (Free), **Business** (₹1,800/mo), and **Pro** (₹10,699/mo). You can upgrade from the Upgrade button in the top bar."
        elif any(w in text_lower for w in ["what can you do", "help", "feature"]):
            bot_reply_text = "I can answer questions, help with your workflow, explain plans, and assist with general queries. Just ask me anything!"
        elif any(w in text_lower for w in ["bye", "goodbye", "see you", "exit"]):
            bot_reply_text = "Goodbye! Feel free to come back anytime. 👋"
        elif any(w in text_lower for w in ["thank", "thanks"]):
            bot_reply_text = "You're welcome! Is there anything else I can help with?"
        elif any(w in text_lower for w in ["who are you", "what are you", "your name"]):
            bot_reply_text = "I'm SmartBot, an AI assistant built to help you with your questions and tasks!"
        elif "?" in user_text:
            bot_reply_text = f"That's a great question! To get full AI-powered answers, add a free Gemini API key to your settings at https://aistudio.google.com/app/apikey"
        else:
            bot_reply_text = f"I received your message: \"{user_text}\". To enable full AI responses, please add a free Gemini API key in your Django settings (GEMINI_API_KEY)."

    bot_message = ChatMessage.objects.create(
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


@api_view(['DELETE'])
def clear_messages(request):
    ChatMessage.objects.all().delete()

    return Response({
        "success": True,
        "message": "All messages cleared"
    })


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
    plan_id = request.data.get("plan_id")
    user_name = request.data.get("user_name", "Dhanush")

    if not plan_id:
        return Response({
            "success": False,
            "message": "Plan ID is required"
        })

    try:
        plan = Plan.objects.get(id=plan_id)

        subscription = Subscription.objects.create(
            user_name=user_name,
            plan=plan
        )

        return Response({
            "success": True,
            "message": "Plan upgraded successfully",
            "subscription": {
                "id": subscription.id,
                "user_name": subscription.user_name,
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


@login_required(login_url="admin_login")
def admin_users(request):
    raw_users = User.objects.filter(is_superuser=False, is_staff=False).order_by("-date_joined")
    users_list = []
    from datetime import timedelta
    for u in raw_users:
        sub = Subscription.objects.filter(user_name=u.username).order_by("-id").first()
        if not sub and u.first_name:
            sub = Subscription.objects.filter(user_name=u.first_name).order_by("-id").first()
        
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
    
    payments_qs = Payment.objects.all().order_by("-id")
    if status_filter:
        payments_qs = payments_qs.filter(status=status_filter)
    if plan_filter:
        payments_qs = payments_qs.filter(plan_name__icontains=plan_filter)
        
    payments_list = []
    first_user = User.objects.first()
    user_display = first_user.first_name or first_user.username if first_user else "Guest"
    for p in payments_qs:
        payments_list.append({
            "user": user_display,
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
    raw_subs = Subscription.objects.all().order_by("-id")
    subs_list = []
    from datetime import timedelta
    for s in raw_subs:
        subs_list.append({
            "id": s.id,
            "user": s.user_name,
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
        user_name = request.POST.get("user_name")
        plan_id = request.POST.get("plan_id")
        status = request.POST.get("status", "active")
        
        try:
            plan = Plan.objects.get(id=plan_id)
            Subscription.objects.create(
                user_name=user_name,
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
        user_name = request.POST.get("user_name")
        plan_id = request.POST.get("plan_id")
        status = request.POST.get("status", "active")
        
        try:
            plan = Plan.objects.get(id=plan_id)
            sub.user_name = user_name
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