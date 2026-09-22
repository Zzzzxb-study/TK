import hashlib
import io
import json
import tempfile
import zipfile
from pathlib import Path
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from .models import Blob, Category, Document, User
from .storage import blob_path

PASSWORD = 'Testing-Str0ng-Password!'
PDF = b'%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF'

def pdf(name='example.pdf'):
    return SimpleUploadedFile(name, PDF, content_type='application/pdf')

class LibraryTests(TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.override = override_settings(PRIVATE_STORAGE_ROOT=Path(self.temp.name) / 'files')
        self.override.enable()
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.override.disable)
        self.admin = User.objects.create_superuser('admin', password=PASSWORD, must_change_password=False)
        self.reader = User.objects.create_user('00001', password=PASSWORD, display_name='测试用户', must_change_password=False)
        self.category = Category.objects.create(name='责任保险', full_path='责任保险', source_path='责任保险')
        self.client.force_login(self.admin)
        response = self.client.post('/upload/', {'title': '测试条款', 'category': self.category.pk, 'kind': 'clause', 'coverage': 'main', 'product_name': '测试产品', 'file': pdf()})
        self.assertEqual(response.status_code, 302)
        self.doc = Document.objects.get()

    def grant(self, *codes):
        self.reader.user_permissions.set(Permission.objects.filter(content_type__app_label='library', codename__in=codes))
        self.client.force_login(self.reader)

    def test_anonymous_and_private_files(self):
        self.client.logout()
        for url in ['/', f'/documents/{self.doc.pk}/download/', '/users/', '/upload/']:
            self.assertEqual(self.client.get(url).status_code, 302)
        for prefix in ['/media/', '/data/files/']:
            self.assertEqual(self.client.get(prefix + self.doc.blob.storage_name).status_code, 404)

    def test_default_user_permissions(self):
        self.client.force_login(self.reader)
        self.assertEqual(self.client.get('/').status_code, 200)
        for method, url in [('get', '/upload/'), ('get', f'/documents/{self.doc.pk}/download/'), ('post', f'/documents/{self.doc.pk}/delete/'), ('get', '/users/'), ('get', '/audit/'), ('get', '/trash/'), ('post', '/users/new/')]:
            self.assertEqual(getattr(self.client, method)(url).status_code, 403, url)

    def test_batch_upload_and_pdf_preview(self):
        self.grant('download_document', 'upload_document')
        response = self.client.post('/upload/', {
            'title': '', 'category': self.category.pk, 'product': self.doc.product_id,
            'coverage': 'main', 'kind': 'clause', 'file': [pdf('第一份.pdf'), pdf('第二份.pdf')],
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Document.objects.count(), 3)
        self.assertEqual(set(Document.objects.exclude(pk=self.doc.pk).values_list('title', flat=True)), {'第一份', '第二份'})
        preview = self.client.get(f'/documents/{self.doc.pk}/preview/')
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(preview['Content-Type'], 'application/pdf')
        b''.join(preview.streaming_content)
        preview.close()
        self.assertTrue(preview['Content-Disposition'].startswith('inline;'))
    def test_download_only_and_content_hash(self):
        self.grant('download_document')
        response = self.client.get(f'/documents/{self.doc.pk}/download/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(hashlib.sha256(b''.join(response.streaming_content)).hexdigest(), self.doc.blob.sha256)
        self.assertIn('attachment;', response['Content-Disposition'])
        self.assertIn('no-store', response['Cache-Control'])
        self.assertEqual(self.client.post('/upload/').status_code, 403)
        self.assertEqual(self.client.post(f'/documents/{self.doc.pk}/delete/').status_code, 403)

    def test_upload_only_and_shared_blob(self):
        self.grant('upload_document')
        response = self.client.post('/upload/', {'title': '另一产品', 'category': self.category.pk, 'kind': 'clause', 'coverage': 'rider', 'product_name': '测试产品', 'file': pdf()})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Document.objects.count(), 2)
        self.assertEqual(Blob.objects.count(), 1)
        self.assertEqual(self.client.get(f'/documents/{self.doc.pk}/download/').status_code, 403)
        self.assertEqual(self.client.post(f'/documents/{self.doc.pk}/delete/').status_code, 403)

    def test_delete_only_and_restore(self):
        self.grant('remove_document')
        self.assertEqual(self.client.get('/upload/').status_code, 403)
        self.assertEqual(self.client.get(f'/documents/{self.doc.pk}/download/').status_code, 403)
        self.assertEqual(self.client.get(f'/documents/{self.doc.pk}/delete/').status_code, 200)
        self.doc.refresh_from_db()
        self.assertIsNone(self.doc.deleted_at)
        self.assertEqual(self.client.post(f'/documents/{self.doc.pk}/delete/').status_code, 302)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(f'/documents/{self.doc.pk}/download/').status_code, 404)
        self.assertTrue(blob_path(self.doc.blob).exists())
        self.assertEqual(self.client.get(f'/trash/{self.doc.pk}/restore/').status_code, 405)
        self.assertEqual(self.client.post(f'/trash/{self.doc.pk}/restore/').status_code, 302)
        self.assertEqual(self.client.get(f'/documents/{self.doc.pk}/').status_code, 200)

    def test_reject_disguised_and_empty_files(self):
        files = [SimpleUploadedFile('bad.pdf', b'not pdf'), SimpleUploadedFile('bad.docx', b'PK123'), SimpleUploadedFile('bad.doc', PDF), SimpleUploadedFile('bad.exe', PDF), SimpleUploadedFile('empty.pdf', b'')]
        for file in files:
            response = self.client.post('/upload/', {'title': '无效', 'category': self.category.pk, 'kind': 'clause', 'coverage': 'main', 'product_name': '测试产品', 'file': file})
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.context['form'].errors)
        self.assertEqual(Document.objects.count(), 1)

    def test_docx(self):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as archive:
            archive.writestr('[Content_Types].xml', '<Types/>')
            archive.writestr('word/document.xml', '<document/>')
        response = self.client.post('/upload/', {'title': 'Word', 'category': self.category.pk, 'kind': 'clause', 'coverage': 'main', 'product_name': '测试产品', 'file': SimpleUploadedFile('word.docx', stream.getvalue())})
        self.assertEqual(response.status_code, 302)

    @override_settings(MAX_UPLOAD_BYTES=10)
    def test_size_limit(self):
        response = self.client.post('/upload/', {'title': '大文件', 'category': self.category.pk, 'kind': 'clause', 'coverage': 'main', 'product_name': '测试产品', 'file': pdf()})
        self.assertContains(response, '单个文件最大')
        self.assertEqual(Document.objects.count(), 1)

    def test_csrf(self):
        browser = Client(enforce_csrf_checks=True)
        browser.force_login(self.admin)
        for url in ['/upload/', f'/documents/{self.doc.pk}/delete/', '/users/new/', '/logout/']:
            self.assertEqual(browser.post(url).status_code, 403)

    def test_first_login_password_change(self):
        self.reader.must_change_password = True
        self.reader.save()
        self.client.force_login(self.reader)
        self.assertRedirects(self.client.get('/'), '/password/', fetch_redirect_response=False)
        self.assertRedirects(self.client.get(f'/documents/{self.doc.pk}/download/'), '/password/', fetch_redirect_response=False)
        response = self.client.post('/password/', {'old_password': PASSWORD, 'new_password1': 'New-Str0ng-Password!2026', 'new_password2': 'New-Str0ng-Password!2026'})
        self.assertEqual(response.status_code, 302)
        self.reader.refresh_from_db()
        self.assertFalse(self.reader.must_change_password)
        self.assertTrue(self.reader.check_password('New-Str0ng-Password!2026'))
        self.assertEqual(self.client.get('/').status_code, 200)

    def test_create_employee_and_password_reset(self):
        response = self.client.post('/users/new/', {'username': '00123', 'display_name': '张三', 'password': PASSWORD, 'permissions': ['download_document']})
        self.assertEqual(response.status_code, 302)
        employee = User.objects.get(username='00123')
        self.assertTrue(employee.must_change_password)
        self.assertTrue(employee.has_perm('library.download_document'))
        self.assertFalse(employee.has_perm('library.upload_document'))
        self.assertNotEqual(employee.password, PASSWORD)
        browser = Client()
        browser.force_login(self.reader)
        self.assertEqual(browser.get('/').status_code, 200)
        self.client.post(f'/users/{self.reader.pk}/', {'display_name': '新名字', 'is_active': 'on', 'password': 'Reset-Str0ng-Password!2026'})
        self.assertEqual(browser.get('/').status_code, 302)

    def test_disable_invalidates_session_after_reenable(self):
        browser = Client()
        browser.force_login(self.reader)
        self.client.post(f'/users/{self.reader.pk}/', {'display_name': '测试用户'})
        self.assertEqual(browser.get('/').status_code, 302)
        self.client.post(f'/users/{self.reader.pk}/', {'display_name': '测试用户', 'is_active': 'on'})
        self.assertEqual(browser.get('/').status_code, 302)

    def test_revoke_permission(self):
        self.grant('download_document')
        self.reader.user_permissions.clear()
        self.assertEqual(self.client.get(f'/documents/{self.doc.pk}/download/').status_code, 403)

    def test_login_throttle(self):
        self.client.logout()
        for _ in range(8):
            response = self.client.post('/login/', {'username': '00001', 'password': 'wrong'})
            self.assertEqual(response.status_code, 200)
        self.assertContains(self.client.post('/login/', {'username': '00001', 'password': PASSWORD}), '尝试次数过多')
        self.assertEqual(self.client.get('/register/').status_code, 404)

    def test_pages(self):
        for url in ['/', '/?q=测试&kind=clause&extension=.pdf', f'/?category={self.category.pk}', '/upload/', '/users/', '/users/new/', f'/users/{self.reader.pk}/', '/trash/', '/audit/', '/password/', f'/documents/{self.doc.pk}/']:
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_import_idempotent_shared_associations(self):
        root = Path(self.temp.name) / 'source'
        for product in ['04-040I产品（2026）', '04-040J产品（2026）']:
            directory = root / '责任保险' / product / '附加险'
            directory.mkdir(parents=True)
            (directory / '12345.pdf').write_bytes(PDF)
        output = io.StringIO()
        report = str(Path(self.temp.name) / 'report.json')
        call_command('import_documents', str(root), apply=True, report=report, stdout=output)
        self.assertEqual(Document.objects.filter(source_path__isnull=False).count(), 2)
        self.assertEqual(Blob.objects.count(), 1)
        self.assertEqual(Document.objects.filter(needs_review=True).count(), 2)
        call_command('import_documents', str(root), apply=True, report=report, stdout=output)
        self.assertEqual(Document.objects.count(), 3)
        self.assertEqual(json.loads(Path(report).read_text(encoding='utf-8'))['unchanged'], 2)
        call_command('verify_storage', stdout=output)

    def test_admin_init_never_resets(self):
        before = self.admin.password
        call_command('init_admin', stdout=io.StringIO())
        self.admin.refresh_from_db()
        self.assertEqual(before, self.admin.password)


    def test_metadata_edit_admin_only(self):
        self.client.force_login(self.reader)
        self.assertEqual(self.client.get(f'/documents/{self.doc.pk}/edit/').status_code, 403)
        self.client.force_login(self.admin)
        original_sha = self.doc.blob.sha256
        self.assertEqual(self.client.post(f'/documents/{self.doc.pk}/edit/', {'title': '已核对标题', 'kind': 'clause', 'coverage': 'rider', 'product_name': '测试产品', 'version': '2026'}).status_code, 302)
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.title, '已核对标题')
        self.assertEqual(self.doc.blob.sha256, original_sha)

    def test_import_normalizes_actual_pdf_not_html(self):
        from django.core.management.base import CommandError
        root = Path(self.temp.name) / 'source'
        folder = root / '责任保险' / '测试产品'
        folder.mkdir(parents=True)
        (folder / '条款.docx').write_bytes(PDF)
        (folder / '网页.doc').write_bytes(b'<html>not a Word binary</html>')
        report = Path(self.temp.name) / 'report.json'
        with self.assertRaises(CommandError):
            call_command('import_documents', str(root), apply=True, normalize_pdf_names=True, report=str(report), stdout=io.StringIO())
        doc = Document.objects.get(source_path__endswith='条款.docx')
        self.assertEqual(doc.original_name, '条款.pdf')
        self.assertEqual(doc.extension, '.pdf')
        self.assertEqual(doc.blob.sha256, hashlib.sha256(PDF).hexdigest())
        self.assertEqual(len(json.loads(report.read_text(encoding='utf-8'))['errors']), 1)


    def test_category_admin_create_edit_and_duplicate(self):
        response = self.client.post('/categories/new/', {'name': '新类别', 'is_active': 'on'})
        self.assertEqual(response.status_code, 302)
        category = Category.objects.get(name='新类别')
        self.assertIsNone(category.source_path)
        self.assertEqual(self.client.post('/categories/new/', {'name': '新类别', 'is_active': 'on'}).status_code, 200)
        self.assertEqual(Category.objects.filter(name='新类别').count(), 1)
        self.assertEqual(self.client.post(f'/categories/{category.pk}/edit/', {'name': '修改后的类别', 'is_active': 'on'}).status_code, 302)
        category.refresh_from_db()
        self.assertEqual(category.full_path, '修改后的类别')
        self.client.force_login(self.reader)
        for url in ['/categories/', '/categories/new/', f'/categories/{category.pk}/edit/', f'/categories/{category.pk}/status/']:
            self.assertEqual(self.client.get(url).status_code, 403)
            self.assertEqual(self.client.post(url).status_code, 403)

    def test_category_rename_descendants_and_source_mapping(self):
        child = Category.objects.create(name='子类别', parent=self.category, full_path='责任保险/子类别', source_path='责任保险/子类别')
        self.client.post(f'/categories/{self.category.pk}/edit/', {'name': '责任险产品', 'is_active': 'on'})
        self.category.refresh_from_db()
        child.refresh_from_db()
        self.doc.refresh_from_db()
        self.assertEqual(child.full_path, '责任险产品/子类别')
        self.assertEqual(child.source_path, '责任保险/子类别')
        self.assertEqual(self.category.source_path, '责任保险')
        self.assertEqual(self.doc.category_id, self.category.pk)
        self.assertTrue(blob_path(self.doc.blob).exists())
        # Initialization uses immutable source mapping; it must not recreate the renamed root.
        call_command('init_admin', stdout=io.StringIO())
        self.assertEqual(Category.objects.filter(source_path='责任保险').count(), 1)
        self.assertFalse(Category.objects.filter(full_path='责任保险').exists())

    def test_category_cannot_move_under_itself_or_child(self):
        child = Category.objects.create(name='子类', parent=self.category, full_path='责任保险/子类')
        for parent in [self.category.pk, child.pk]:
            response = self.client.post(f'/categories/{self.category.pk}/edit/', {'name': '责任保险', 'parent': parent, 'is_active': 'on'})
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.context['form'].errors)
        self.category.refresh_from_db()
        self.assertIsNone(self.category.parent_id)

    def test_disable_blocks_browse_download_and_upload_preserves_files(self):
        self.grant('download_document', 'upload_document', 'remove_document')
        browser = self.client
        admin = Client()
        admin.force_login(self.admin)
        response = admin.get(f'/categories/{self.category.pk}/status/')
        self.assertEqual(response.status_code, 200)
        self.category.refresh_from_db()
        self.assertTrue(self.category.is_active)
        self.assertEqual(admin.post(f'/categories/{self.category.pk}/status/', {'action': 'disable'}).status_code, 302)
        for url in [f'/?category={self.category.pk}', f'/?product={self.doc.product_id}', f'/documents/{self.doc.pk}/', f'/documents/{self.doc.pk}/download/']:
            self.assertEqual(browser.get(url).status_code, 404, url)
        self.assertEqual(browser.get('/?q=测试').context['page'].paginator.count, 0)
        form = browser.get('/upload/').context['form']
        self.assertFalse(form.fields['category'].queryset.filter(pk=self.category.pk).exists())
        response = browser.post('/upload/', {'title': '禁止上传', 'category': self.category.pk, 'product_name': '新产品', 'coverage': 'main', 'kind': 'clause', 'file': pdf()})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['form'].errors)
        self.assertEqual(Document.objects.count(), 1)
        self.assertTrue(blob_path(self.doc.blob).exists())
        self.assertEqual(admin.get(f'/documents/{self.doc.pk}/').status_code, 200)
        admin.post(f'/categories/{self.category.pk}/status/', {'action': 'enable'})
        self.assertEqual(browser.get(f'/documents/{self.doc.pk}/').status_code, 200)

    def test_parent_disable_and_child_independent_state(self):
        from .catalog import active_category_ids
        child = Category.objects.create(name='子类', parent=self.category, full_path='责任保险/子类')
        self.client.post(f'/categories/{self.category.pk}/status/', {'action': 'disable'})
        self.assertNotIn(child.pk, active_category_ids())
        self.client.post(f'/categories/{child.pk}/status/', {'action': 'disable'})
        self.client.post(f'/categories/{self.category.pk}/status/', {'action': 'enable'})
        self.assertIn(self.category.pk, active_category_ids())
        self.assertNotIn(child.pk, active_category_ids())
        self.client.post(f'/categories/{child.pk}/status/', {'action': 'enable'})
        self.assertIn(child.pk, active_category_ids())

    def test_category_csrf(self):
        browser = Client(enforce_csrf_checks=True)
        browser.force_login(self.admin)
        for url in ['/categories/new/', f'/categories/{self.category.pk}/edit/', f'/categories/{self.category.pk}/status/']:
            self.assertEqual(browser.post(url, {'action': 'disable'}).status_code, 403)

    def test_product_coverage_and_document_kind_filters(self):
        rider = Document.objects.create(title='附加费率', category=self.category, product=self.doc.product, coverage='rider', kind='rate', blob=self.doc.blob, original_name='rider.pdf', extension='.pdf', uploaded_by=self.admin)
        root = self.client.get(f'/?category={self.category.pk}')
        self.assertFalse(root.context['show_documents'])
        self.assertIn(self.doc.product, root.context['folder_products'])
        response = self.client.get(f'/?product={self.doc.product_id}&coverage=rider&kind=rate')
        self.assertEqual([d.pk for d in response.context['page']], [rider.pk])
        self.assertEqual(response.context['main_count'], 1)
        self.assertEqual(response.context['rider_count'], 1)
        self.assertContains(response, '主险')
        self.assertContains(response, '附加险')
        other = Category.objects.create(name='别类', full_path='别类')
        self.assertEqual(self.client.get(f'/?category={other.pk}&product={self.doc.product_id}').status_code, 404)

    def test_existing_product_upload_and_mismatch(self):
        payload = {'title': '已有产品资料', 'category': self.category.pk, 'product': self.doc.product_id, 'coverage': 'rider', 'kind': 'rate', 'file': pdf()}
        self.assertEqual(self.client.post('/upload/', payload).status_code, 302)
        document = Document.objects.get(title='已有产品资料')
        self.assertEqual(document.product_id, self.doc.product_id)
        self.assertEqual(document.coverage, 'rider')
        other = Category.objects.create(name='别类', full_path='别类')
        payload.update(category=other.pk, file=pdf())
        self.assertEqual(self.client.post('/upload/', payload).status_code, 200)
        self.assertEqual(Document.objects.filter(title='已有产品资料').count(), 1)
        self.assertEqual(self.client.post('/upload/', {'title': '未选产品', 'category': self.category.pk, 'coverage': 'main', 'kind': 'clause', 'file': pdf()}).status_code, 200)

    def test_import_after_category_rename_and_rider_rate_classification(self):
        root = Path(self.temp.name) / 'source'
        folder = root / '责任保险' / '04-040I产品（2026）' / '附加险'
        folder.mkdir(parents=True)
        (folder / '附加险费率.pdf').write_bytes(PDF)
        self.client.post(f'/categories/{self.category.pk}/edit/', {'name': '责任险产品', 'is_active': 'on'})
        call_command('import_documents', str(root), apply=True, report=str(Path(self.temp.name)/'report.json'), stdout=io.StringIO())
        document = Document.objects.get(source_path__isnull=False)
        self.assertEqual(document.category_id, self.category.pk)
        self.assertEqual(document.coverage, 'rider')
        self.assertEqual(document.kind, 'rate')
        self.assertEqual(Category.objects.filter(source_path='责任保险').count(), 1)
