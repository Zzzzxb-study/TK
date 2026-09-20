import hashlib
import json
from datetime import timedelta
from functools import wraps
from pathlib import Path
from django.contrib import messages
from django.contrib.auth import login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q, F, Sum, Count
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.crypto import salted_hmac
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST
from .forms import LoginForm, UploadForm, UserCreateForm, UserEditForm
from .models import Audit, Blob, Category, Document, LoginThrottle, Product, User
from .storage import blob_path, save_blob
from .catalog import active_category_ids, visible_documents


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapped(request, *args, **kwargs):
        if not request.user.is_superuser:
            raise PermissionDenied
        return view(request, *args, **kwargs)
    return wrapped


def audit(user, action, target, detail=''):
    Audit.objects.create(actor=user, action=action, target=str(target)[:400], detail=detail)


@never_cache
def sign_in(request):
    if request.user.is_authenticated:
        return redirect('library')
    form = LoginForm(request, data=request.POST or None)
    if request.method == 'POST':
        now = timezone.now()
        raw_keys = ['user:' + request.POST.get('username', '').casefold()[:150],
                    'ip:' + request.META.get('REMOTE_ADDR', '')]
        keys = [salted_hmac('login', v, algorithm='sha256').hexdigest() for v in raw_keys]
        blocked = False
        for key, limit in zip(keys, [8, 40]):
            with transaction.atomic():
                throttle, _ = LoginThrottle.objects.select_for_update().get_or_create(key=key, defaults={'window_start': now})
                if throttle.window_start < now - timedelta(minutes=15):
                    throttle.failures, throttle.window_start = 0, now
                    throttle.save()
                if throttle.failures >= limit:
                    blocked = True
        if blocked:
            form = LoginForm(request, data={'username': '', 'password': ''})
            form.is_valid()
            form.add_error(None, '尝试次数过多，请在 15 分钟后重试。')
        elif form.is_valid():
            login(request, form.get_user())
            LoginThrottle.objects.filter(key=keys[0]).delete()
            audit(request.user, '登录', request.user.username)
            return redirect('library')
        else:
            LoginThrottle.objects.filter(key__in=keys).update(failures=F('failures') + 1)
    return render(request, 'login.html', {'form': form})


@require_POST
@login_required
def sign_out(request):
    logout(request)
    return redirect('login')


@login_required
@never_cache
def password(request):
    form = PasswordChangeForm(request.user, request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = form.save()
        user.must_change_password = False
        user.save(update_fields=['must_change_password'])
        update_session_auth_hash(request, user)
        audit(user, '修改密码', user.username)
        messages.success(request, '密码已更新。')
        return redirect('library')
    return render(request, 'form.html', {'form': form, 'title': '修改密码',
        'subtitle': '首次登录必须修改初始密码。密码至少 12 位。' if request.user.must_change_password else '更新你的登录密码。', 'submit': '保存密码'})


@login_required
@never_cache
def library(request):
    from collections import Counter
    enabled = set(active_category_ids())
    all_categories = list(Category.objects.all())
    categories = [c for c in all_categories if request.user.is_superuser or c.pk in enabled]
    category_map = {c.pk: c for c in categories}
    base = visible_documents(request.user, Document.objects.filter(deleted_at__isnull=True))
    totals = Counter(base.values_list('product_id', flat=True))
    all_products = list(Product.objects.filter(category_id__in=category_map).select_related('category').order_by('name'))
    for product in all_products:
        product.document_count = totals[product.pk]
    category_id, product_id = request.GET.get('category', ''), request.GET.get('product', '')
    active_category = get_object_or_404(Category.objects.filter(pk__in=category_map), pk=category_id) if category_id.isdigit() else None
    active_product = None
    if product_id.isdigit():
        active_product = get_object_or_404(Product.objects.filter(category_id__in=category_map).select_related('category'), pk=product_id)
        if active_category and not (active_product.category_id == active_category.pk or active_product.category.full_path.startswith(active_category.full_path + '/')):
            raise Http404
        active_category = active_product.category
    ancestors = []
    current = active_category
    while current:
        ancestors.insert(0, current)
        current = category_map.get(current.parent_id)
    ancestor_ids = {c.pk for c in ancestors}
    nodes = {c.pk: {'category': c, 'children': [], 'products': [], 'expanded': c.pk in ancestor_ids, 'enabled': c.pk in enabled} for c in categories}
    roots = []
    for c in categories:
        if c.parent_id in nodes:
            nodes[c.parent_id]['children'].append(nodes[c.pk])
        else:
            roots.append(nodes[c.pk])
    for product in all_products:
        nodes[product.category_id]['products'].append(product)
    scope_ids = set(category_map)
    if active_category:
        scope_ids = {c.pk for c in categories if c.pk == active_category.pk or c.full_path.startswith(active_category.full_path + '/')}
    docs = base.filter(category_id__in=scope_ids)
    if active_product:
        docs = docs.filter(product=active_product)
    if request.GET.get('unassigned') == '1':
        docs = docs.filter(product__isnull=True)
    coverage_counts = dict(docs.values('coverage').annotate(count=Count('pk')).values_list('coverage', 'count'))
    q = request.GET.get('q', '').strip()[:200]
    if q:
        docs = docs.filter(Q(title__icontains=q) | Q(original_name__icontains=q) | Q(product__name__icontains=q)
                           | Q(product__code__icontains=q) | Q(version__icontains=q) | Q(category__full_path__icontains=q))
    coverage = request.GET.get('coverage', '')
    if coverage in dict(Document.COVERAGES):
        docs = docs.filter(coverage=coverage)
    kind = request.GET.get('kind', '')
    if kind in dict(Document.KINDS):
        docs = docs.filter(kind=kind)
    extension = request.GET.get('extension', '')
    if extension in ['.doc', '.docx', '.pdf']:
        docs = docs.filter(extension=extension)
    if request.GET.get('review') == '1':
        docs = docs.filter(needs_review=True)
    show_documents = bool(active_product or q or kind or coverage or extension or request.GET.get('review') or request.GET.get('unassigned'))
    page = Paginator(docs.select_related('category', 'product', 'blob'), 25).get_page(request.GET.get('page'))
    params = request.GET.copy()
    params.pop('page', None)
    children = [c for c in categories if c.parent_id == (active_category.pk if active_category else None)]
    products = [p for p in all_products if active_category and p.category_id == active_category.pk]
    return render(request, 'library.html', {
        'page': page, 'tree': roots, 'total': base.count(), 'product_count': len(all_products),
        'review_count': base.filter(needs_review=True).count(), 'kinds': Document.KINDS,
        'query': q, 'kind': kind, 'coverage': coverage, 'extension': extension,
        'active_category': active_category, 'active_product': active_product, 'breadcrumbs': ancestors,
        'params': params.urlencode(), 'show_documents': show_documents, 'folder_categories': children,
        'folder_products': products, 'main_count': coverage_counts.get('main', 0), 'rider_count': coverage_counts.get('rider', 0),
        'category_disabled': bool(active_category and active_category.pk not in enabled),
        'unassigned_count': base.filter(category_id__in=scope_ids, product__isnull=True).count(),
    })


@login_required
@never_cache
def detail(request, pk):
    doc = get_object_or_404(visible_documents(request.user, Document.objects.select_related('category', 'product', 'blob', 'uploaded_by')), pk=pk, deleted_at__isnull=True)
    return render(request, 'detail.html', {'doc': doc})


@login_required
@permission_required('library.upload_document', raise_exception=True)
def upload(request):
    initial = {key: request.GET.get(key) for key in ('category', 'product', 'coverage') if request.GET.get(key)}
    form = UploadForm(request.POST or None, request.FILES or None, initial=initial)
    if request.method == 'POST' and form.is_valid():
        try:
            blob = save_blob(form.cleaned_data['file'])
            with transaction.atomic():
                list(Category.objects.select_for_update().values_list('pk', flat=True))
                if form.cleaned_data['category'].pk not in active_category_ids():
                    raise ValidationError('产品类别已停用，不能上传。')
                doc = form.save(commit=False)
                doc.blob = blob
                doc.uploaded_by = request.user
                doc.original_name = Path(form.cleaned_data['file'].name).name
                doc.extension = Path(doc.original_name).suffix.lower()
                if form.cleaned_data['product_name']:
                    raw = json.dumps([doc.category_id, form.cleaned_data['product_name'], form.cleaned_data['product_code'], doc.version], ensure_ascii=False)
                    doc.product, _ = Product.objects.get_or_create(source_key=hashlib.sha256(raw.encode()).hexdigest(), defaults={
                        'category': doc.category, 'name': form.cleaned_data['product_name'], 'code': form.cleaned_data['product_code'], 'version': doc.version})
                doc.save()
                audit(request.user, '上传资料', doc.title, f'document_id={doc.pk}')
            messages.success(request, '资料已上传并保存在服务器。')
            return redirect('detail', pk=doc.pk)
        except ValidationError as exc:
            form.add_error('file', exc)
    return render(request, 'form.html', {'form': form, 'title': '上传资料', 'subtitle': '支持 DOC、DOCX、PDF，单个文件最大 20 MB。', 'submit': '上传并保存'})


@login_required
@permission_required('library.download_document', raise_exception=True)
@never_cache
def download(request, pk):
    doc = get_object_or_404(visible_documents(request.user, Document.objects.select_related('blob')), pk=pk, deleted_at__isnull=True)
    try:
        stream = blob_path(doc.blob).open('rb')
    except FileNotFoundError:
        raise Http404('文件缺失，请联系管理员')
    audit(request.user, '下载资料', doc.title, f'document_id={doc.pk}; 已授权并开始传输，不代表客户端完成保存')
    response = FileResponse(stream, as_attachment=True, filename=doc.original_name, content_type='application/octet-stream')
    response['X-Content-Type-Options'] = 'nosniff'
    return response


@login_required
@permission_required('library.remove_document', raise_exception=True)
def remove(request, pk):
    doc = get_object_or_404(visible_documents(request.user, Document.objects.all()), pk=pk, deleted_at__isnull=True)
    if request.method == 'POST':
        with transaction.atomic():
            changed = Document.objects.filter(pk=pk, deleted_at__isnull=True).update(deleted_at=timezone.now(), deleted_by=request.user)
            if changed:
                audit(request.user, '删除资料', doc.title, f'document_id={pk}')
        messages.success(request, '资料已移入回收站，下载入口已关闭。')
        return redirect('library')
    return render(request, 'confirm.html', {'title': '删除资料', 'description': f'将“{doc.title}”移入回收站？管理员可以恢复。', 'submit': '确认删除'})


@admin_required
def trash(request):
    docs = Document.objects.filter(deleted_at__isnull=False).select_related('deleted_by').order_by('-deleted_at')
    return render(request, 'trash.html', {'page': Paginator(docs, 30).get_page(request.GET.get('page'))})


@admin_required
@require_POST
def restore(request, pk):
    with transaction.atomic():
        doc = get_object_or_404(Document.objects.select_for_update(), pk=pk, deleted_at__isnull=False)
        doc.deleted_at = doc.deleted_by = None
        doc.save(update_fields=['deleted_at', 'deleted_by'])
        audit(request.user, '恢复资料', doc.title, f'document_id={pk}')
    messages.success(request, '资料已恢复。')
    return redirect('trash')


def set_permissions(user, codes):
    user.user_permissions.set(Permission.objects.filter(content_type__app_label='library', content_type__model='document', codename__in=codes))


@admin_required
def users(request):
    return render(request, 'users.html', {'users': User.objects.prefetch_related('user_permissions').order_by('-is_superuser', 'username')})


@admin_required
def create_user(request):
    form = UserCreateForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            user = User.objects.create_user(username=form.cleaned_data['username'], display_name=form.cleaned_data['display_name'], password=form.cleaned_data['password'])
            set_permissions(user, form.cleaned_data['permissions'])
            audit(request.user, '创建工号', user.username, ','.join(form.cleaned_data['permissions']))
        messages.success(request, '工号已创建，请将初始密码交给使用人；首次登录必须修改。')
        return redirect('users')
    return render(request, 'form.html', {'form': form, 'title': '创建工号', 'subtitle': '分别勾选上传、下载、删除权限；默认不授予操作权限。', 'submit': '创建账户'})


@admin_required
def edit_user(request, pk):
    user = get_object_or_404(User, pk=pk, is_superuser=False)
    form = UserEditForm(request.POST or None, user=user, initial={'display_name': user.display_name, 'is_active': user.is_active,
                         'permissions': list(user.user_permissions.values_list('codename', flat=True))})
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            user.display_name = form.cleaned_data['display_name']
            was_active = user.is_active
            user.is_active = form.cleaned_data['is_active']
            if form.cleaned_data['password']:
                user.set_password(form.cleaned_data['password'])
                user.must_change_password = True
            user.save()
            set_permissions(user, form.cleaned_data['permissions'])
            if was_active and not user.is_active:
                from django.contrib.sessions.models import Session
                for session in Session.objects.filter(expire_date__gt=timezone.now()).iterator():
                    if str(session.get_decoded().get('_auth_user_id')) == str(user.pk):
                        session.delete()
            audit(request.user, '更新工号', user.username, json.dumps({'active': user.is_active, 'permissions': form.cleaned_data['permissions'], 'password_reset': bool(form.cleaned_data['password'])}))
        messages.success(request, '账户及权限已更新。')
        return redirect('users')
    return render(request, 'form.html', {'form': form, 'title': f'管理工号 · {user.username}', 'subtitle': '取消启用会立即使现有登录失效。', 'submit': '保存设置'})


@admin_required
def audit_log(request):
    return render(request, 'audit.html', {'page': Paginator(Audit.objects.select_related('actor'), 40).get_page(request.GET.get('page'))})


@admin_required
def edit_metadata(request, pk):
    from .forms import MetadataForm
    doc = get_object_or_404(visible_documents(request.user, Document.objects.all()), pk=pk, deleted_at__isnull=True)
    form = MetadataForm(request.POST or None, instance=doc)
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            form.save()
            audit(request.user, '修订资料信息', doc.title, f'document_id={doc.pk}')
        messages.success(request, '资料信息已更新，原文件内容不变。')
        return redirect('detail', pk=doc.pk)
    return render(request, 'form.html', {'form': form, 'title': '核对资料信息', 'subtitle': '核对原文件后修订名称、资料类型和版本；确认后取消待核对标记。', 'submit': '保存资料信息'})



@admin_required
@never_cache
def categories(request):
    enabled = set(active_category_ids())
    rows = list(Category.objects.annotate(product_count=Count('product', distinct=True), document_count=Count('document', distinct=True)))
    for category in rows:
        category.effective_active = category.pk in enabled
    return render(request, 'categories.html', {'categories': rows})

@admin_required
@transaction.atomic
def category_edit(request, pk=None):
    from .forms import CategoryForm
    if request.method == 'POST':
        # Serialize hierarchy edits so two renames cannot corrupt descendant paths.
        list(Category.objects.select_for_update().values_list('pk', flat=True))
    instance = get_object_or_404(Category, pk=pk) if pk is not None else None
    old_path = instance.full_path if instance else ''
    form = CategoryForm(request.POST or None, instance=instance)
    if request.method == 'POST' and form.is_valid():
        category = form.save()
        audit(request.user, '编辑产品类别' if pk else '新增产品类别', category.full_path,
              json.dumps({'old_path': old_path, 'is_active': category.is_active}, ensure_ascii=False))
        messages.success(request, '产品类别已保存。停用上级时，下属类别暂停使用；历史资料保留。')
        return redirect('categories')
    return render(request, 'form.html', {'form': form, 'title': '编辑产品类别' if pk else '新增产品类别',
        'subtitle': '按资料存放结构维护类别；名称或上级变更不会改变原文件及来源路径。', 'submit': '保存类别',
        'back_url': '/categories/', 'back_label': '返回类别管理'})

@admin_required
@transaction.atomic
def category_toggle(request, pk):
    category = get_object_or_404(Category.objects.select_for_update(), pk=pk)
    if request.method == 'POST':
        action = request.POST.get('action')
        if action not in ('enable', 'disable'):
            raise PermissionDenied
        category.is_active = action == 'enable'
        category.save(update_fields=['is_active'])
        audit(request.user, '启用产品类别' if category.is_active else '停用产品类别', category.full_path)
        messages.success(request, '类别状态已更新。子类别仍受上级启停状态约束。')
        return redirect('categories')
    action = 'disable' if category.is_active else 'enable'
    text = '停用后，普通工号无法浏览或下载本类别及下属类别的资料，并停止新上传；管理员可查阅历史资料，文件不会删除。' if category.is_active else '启用后恢复使用；若上级仍停用，本类别仍暂停使用。'
    return render(request, 'confirm.html', {'title': ('停用' if category.is_active else '启用') + '产品类别',
        'description': category.full_path + '：' + text, 'submit': '确认停用' if category.is_active else '确认启用',
        'action': action, 'cancel_url': '/categories/'})
