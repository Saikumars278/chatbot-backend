
from django.db import models
from django.contrib.auth.models import User


class UserProfile(models.Model):
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE
    )
    full_name = models.CharField(max_length=100)
    email = models.EmailField(unique=True)
    mobile = models.CharField(max_length=15)
    free_messages_sent = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.full_name


class ChatHistory(models.Model):
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        null=True,
        blank=True
    )
    title = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title


class ChatMessage(models.Model):
    MESSAGE_TYPES = (
        ('user', 'User'),
        ('bot', 'Bot'),
    )

    chat = models.ForeignKey(
        ChatHistory,
        on_delete=models.CASCADE,
        related_name='messages',
        null=True,
        blank=True
    )

    message_type = models.CharField(
        max_length=10,
        choices=MESSAGE_TYPES
    )

    text = models.TextField()

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    def __str__(self):
        return f"{self.message_type}: {self.text[:30]}"


class Plan(models.Model):
    name = models.CharField(max_length=100)
    price = models.CharField(max_length=50)
    note = models.CharField(max_length=150)
    description = models.TextField()
    is_featured = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class Subscription(models.Model):
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE
    )

    plan = models.ForeignKey(
        Plan,
        on_delete=models.CASCADE
    )

    status = models.CharField(
        max_length=50,
        default="active"
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    def __str__(self):
        return f"{self.user.username} - {self.plan.name}"


class Payment(models.Model):
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE
    )

    plan_name = models.CharField(max_length=100)
    amount = models.IntegerField()

    razorpay_order_id = models.CharField(
        max_length=255,
        blank=True,
        null=True
    )

    razorpay_payment_id = models.CharField(
        max_length=255,
        blank=True,
        null=True
    )

    razorpay_signature = models.CharField(
        max_length=255,
        blank=True,
        null=True
    )

    status = models.CharField(
        max_length=50,
        default="created"
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    def __str__(self):
        return f"{self.user.username} - {self.plan_name} - {self.status}"

