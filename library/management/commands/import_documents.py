import hashlib
import json
import re
from pathlib import Path
from django.conf import settings
from django.core.files import File
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from library.models import Audit, Category, Document, Product, User
from library.storage import save_blob, validate_document
from library.catalog import classify_document, active_category_ids
from .init_admin import CATEGORIES


def metadata(relative):
    parts = relative.parts
    category_parts = [parts[0]]
    product_index = 1
    if parts[0] == '财产保险' and len(parts) > 3 and parts[1] in ['家庭财产保险', '企业财产保险']:
        category_parts.append(parts[1])
        product_index = 2
    product_name = parts[product_index] if len(parts) > product_index + 1 else ''
    code_match = re.match(r'^(\d{2}-[A-Za-z0-9]+)', product_name)
    code = code_match.group(1) if code_match else ''
    version_match = re.search(r'[（(]((?:19|20)\d{2})(?:版)?[）)]', product_name)
    version = version_match.group(1) if version_match else ''
    filename = parts[-1]
    title = Path(filename).stem
    if '费率' in title:
        kind = 'rate'
    elif '附加' in title or any('附加险' in p for p in parts[:-1]):
        kind = 'rider'
    elif '条款' in title:
        kind = 'main'
    else:
        kind = 'other'
    return category_parts, product_name, code, version, title, kind


class Command(BaseCommand):
    help = '从现有险种目录导入 Word/PDF，保留产品关联；默认预检查，--apply 才写入。'

    def add_arguments(self, parser):
        parser.add_argument('source')
        parser.add_argument('--apply', action='store_true')
        parser.add_argument('--normalize-pdf-names', action='store_true', help='对实际为 PDF 的错后缀文件修正入库名称，原件不变')
        parser.add_argument('--username', default='admin')
        parser.add_argument('--report', default='')

    def handle(self, *args, **options):
        root = Path(options['source']).resolve()
        if not root.is_dir():
            raise CommandError('源目录不存在。')
        actor = User.objects.filter(username=options['username'], is_superuser=True, is_active=True).first()
        if not actor:
            raise CommandError('请先初始化管理员。')
        report = {'source': str(root), 'applied': options['apply'], 'scanned': 0, 'created': 0, 'unchanged': 0, 'valid_new': 0, 'normalized': [], 'errors': []}
        for category_name in CATEGORIES:
            folder = root / category_name
            if not folder.is_dir():
                continue
            for path in sorted(folder.rglob('*')):
                if not path.is_file() or path.suffix.lower() not in {'.doc', '.docx', '.pdf'}:
                    continue
                report['scanned'] += 1
                relative = path.relative_to(root)
                try:
                    if path.is_symlink() or not path.resolve().is_relative_to(root):
                        raise ValueError('不允许导入源目录外的文件或符号链接')
                    existing = Document.objects.select_related('blob').filter(source_path=relative.as_posix()).first()
                    if existing:
                        with path.open('rb') as source_stream:
                            digest = hashlib.file_digest(source_stream, 'sha256').hexdigest()
                        if digest != existing.blob.sha256:
                            raise ValueError('原路径内容已变化，请作为新版本上传，不自动覆盖')
                        report['unchanged'] += 1
                        continue
                    with path.open('rb') as stream:
                        stored_name = path.name
                        if options['normalize_pdf_names'] and stream.read(5) == b'%PDF-' and path.suffix.lower() != '.pdf':
                            stored_name = path.stem + '.pdf'
                            report['normalized'].append({'source': relative.as_posix(), 'download_name': stored_name})
                        stream.seek(0)
                        file = File(stream, name=stored_name)
                        validate_document(file)
                        report['valid_new'] += 1
                        if not options['apply']:
                            continue
                        blob = save_blob(file)
                    category_parts, product_name, code, version, title, kind = metadata(relative)
                    with transaction.atomic():
                        parent = None
                        for index, name in enumerate(category_parts):
                            source_category_path = '/'.join(category_parts[:index+1])
                            current_path = (parent.full_path + '/' if parent else '') + name
                            parent, _ = Category.objects.get_or_create(source_path=source_category_path,
                                defaults={'name': name, 'parent': parent, 'full_path': current_path})
                        if parent.pk not in active_category_ids():
                            raise ValueError('产品类别已停用，不能导入新资料')
                        product = None
                        if product_name:
                            # Import and manual upload share the same product identity algorithm.
                            raw = json.dumps([parent.pk, product_name, code, version], ensure_ascii=False)
                            product, _ = Product.objects.get_or_create(source_key=hashlib.sha256(raw.encode()).hexdigest(), defaults={
                                'category': parent, 'name': product_name, 'code': code, 'version': version})
                        coverage, kind = classify_document(relative.as_posix(), title, kind)
                        Document.objects.create(title=title, category=parent, product=product, coverage=coverage, kind=kind, version=version,
                            blob=blob, original_name=stored_name, extension=Path(stored_name).suffix.lower(), source_path=relative.as_posix(),
                            needs_review=title.isdigit() or kind == 'other', uploaded_by=actor)
                    report['created'] += 1
                except Exception as exc:
                    report['errors'].append({'path': relative.as_posix(), 'error': str(exc)})
                if report['scanned'] % 200 == 0:
                    self.stdout.write(f"已扫描 {report['scanned']}，已导入 {report['created']}")
        report_path = Path(options['report']) if options['report'] else settings.DATA_DIR / 'import-report.json'
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        if options['apply']:
            Audit.objects.create(actor=actor, action='批量导入', target=str(root), detail=json.dumps({k:v for k,v in report.items() if k != 'errors'}, ensure_ascii=False))
        self.stdout.write(json.dumps({**report, 'errors': len(report['errors']), 'report': str(report_path)}, ensure_ascii=False))
        if report['errors']:
            raise CommandError('部分文件未导入，请查看报告；成功部分已保留，修复后可重复执行。')
