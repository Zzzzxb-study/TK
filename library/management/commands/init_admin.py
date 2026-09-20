import getpass
import os
import secrets
from pathlib import Path
from django.contrib.auth.password_validation import validate_password
from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
from library.models import Category, User

CATEGORIES = ['保证保险', '财产保险', '船舶保险', '工程保险', '货运保险', '健康保险', '其他保险', '特殊保险', '意外保险', '责任保险']


class Command(BaseCommand):
    help = '首次创建管理员；已存在时不改动密码。'

    def add_arguments(self, parser):
        parser.add_argument('--username', default='admin')
        parser.add_argument('--local-credential-file', action='store_true', help='本地开发时生成随机密码并保存到私有 data 目录')

    def handle(self, *args, **options):
        for name in CATEGORIES:
            if not Category.objects.filter(source_path=name).exists():
                category, _ = Category.objects.get_or_create(full_path=name, defaults={'name': name, 'source_path': name})
                if category.source_path is None:
                    category.source_path = name
                    category.save(update_fields=['source_path'])
        if User.objects.filter(is_superuser=True).exists():
            self.stdout.write('管理员已存在，未修改任何密码。')
            return
        username = options['username']
        if User.objects.filter(username__iexact=username).exists():
            raise CommandError('同名工号已存在，不能升级或覆盖。')
        if options['local_credential_file']:
            if settings.PRODUCTION:
                raise CommandError('生产环境请通过交互输入或 ADMIN_INITIAL_PASSWORD 设置密码。')
            password = secrets.token_urlsafe(18)
        else:
            password = os.getenv('ADMIN_INITIAL_PASSWORD') or getpass.getpass('管理员初始密码（至少12位）: ')
        user = User(username=username, display_name='管理员', is_staff=True, is_superuser=True)
        validate_password(password, user)
        user.set_password(password)
        user.save()
        if options['local_credential_file']:
            target = settings.DATA_DIR / 'initial-admin.txt'
            target.write_text(f'本地条款库初始登录信息\n地址：http://127.0.0.1:8000\n账号：{username}\n初始密码：{password}\n首次登录必须修改密码。修改后请删除此文件。\n', encoding='utf-8')
            self.stdout.write(f'初始登录信息已写入 {target}；未在日志输出密码。')
        self.stdout.write('管理员初始化完成，首次登录必须修改密码。')
