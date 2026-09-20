from django.contrib.auth.models import AbstractUser
from django.conf import settings
from django.db import models


class User(AbstractUser):
    display_name = models.CharField('姓名', max_length=80)
    must_change_password = models.BooleanField(default=True)

    def __str__(self):
        return f'{self.username} · {self.display_name or self.username}'


class Category(models.Model):
    name = models.CharField(max_length=120)
    parent = models.ForeignKey('self', null=True, blank=True, on_delete=models.PROTECT, related_name='children')
    full_path = models.CharField(max_length=300, unique=True)
    source_path = models.CharField(max_length=300, unique=True, null=True, blank=True)
    is_active = models.BooleanField('启用类别', default=True)

    class Meta:
        ordering = ['full_path']

    def __str__(self):
        return self.full_path


class Product(models.Model):
    category = models.ForeignKey(Category, on_delete=models.PROTECT)
    name = models.CharField(max_length=300)
    code = models.CharField(max_length=80, blank=True)
    version = models.CharField(max_length=80, blank=True)
    source_key = models.CharField(max_length=64, unique=True)

    def __str__(self):
        return self.name


class Blob(models.Model):
    sha256 = models.CharField(max_length=64, unique=True)
    storage_name = models.CharField(max_length=100, unique=True)
    size = models.PositiveBigIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)


class Document(models.Model):
    KINDS = [('clause', '条款'), ('rate', '费率表'), ('other', '其他资料')]
    COVERAGES = [('main', '主险'), ('rider', '附加险')]
    coverage = models.CharField('主险 / 附加险', max_length=12, choices=COVERAGES, default='main')
    title = models.CharField('资料名称', max_length=300)
    category = models.ForeignKey(Category, on_delete=models.PROTECT)
    product = models.ForeignKey(Product, null=True, blank=True, on_delete=models.PROTECT)
    kind = models.CharField('资料类型', max_length=20, choices=KINDS, default='other')
    version = models.CharField('版本', max_length=80, blank=True)
    blob = models.ForeignKey(Blob, on_delete=models.PROTECT)
    original_name = models.CharField(max_length=300)
    extension = models.CharField(max_length=8)
    source_path = models.TextField(null=True, blank=True, unique=True)
    needs_review = models.BooleanField(default=False)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='uploads')
    uploaded_at = models.DateTimeField(auto_now_add=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='deletions')

    class Meta:
        ordering = ['-uploaded_at', '-pk']
        permissions = [('upload_document', '可上传资料'), ('download_document', '可下载资料'),
                       ('remove_document', '可删除资料')]
        indexes = [models.Index(fields=['deleted_at', 'category']), models.Index(fields=['kind'])]


class Audit(models.Model):
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    action = models.CharField(max_length=40)
    target = models.CharField(max_length=400)
    detail = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-pk']


class LoginThrottle(models.Model):
    key = models.CharField(max_length=64, unique=True)
    failures = models.PositiveIntegerField(default=0)
    window_start = models.DateTimeField()
