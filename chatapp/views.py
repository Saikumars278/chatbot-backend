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
    users_count = User.objects.count()
    chats_count = ChatHistory.objects.count()
    messages_count = ChatMessage.objects.count()
    plans_count = Plan.objects.count()
    payments_count = Payment.objects.count()
    subscriptions_count = Subscription.objects.count()

    recent_users = User.objects.all().order_by("-date_joined")[:10]
    payments = Payment.objects.all().order_by("-id")[:10]
    subscriptions = Subscription.objects.all().order_by("-id")[:10]

    context = {
        "users_count": users_count,
        "chats_count": chats_count,
        "messages_count": messages_count,
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

    bot_reply_text = "Thanks for your message. I am processing your request."

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