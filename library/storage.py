import hashlib
import uuid
import zipfile
from pathlib import Path
import olefile
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.storage import FileSystemStorage
from .models import Blob


def validate_document(file):
    suffix = Path(file.name).suffix.lower()
    if suffix not in {'.pdf', '.doc', '.docx'}:
        raise ValidationError('仅支持 PDF、DOC、DOCX 文件。')
    if not file.size or file.size > settings.MAX_UPLOAD_BYTES:
        raise ValidationError('文件不能为空，单个文件最大 20 MB。')
    file.seek(0)
    signature = file.read(8)
    file.seek(0)
    try:
        if suffix == '.pdf':
            if not signature.startswith(b'%PDF-'):
                raise ValueError()
        elif suffix == '.docx':
            with zipfile.ZipFile(file) as z:
                names = set(z.namelist())
                if not {'[Content_Types].xml', 'word/document.xml'} <= names:
                    raise ValueError()
                if len(names) > 10000 or sum(i.file_size for i in z.infolist()) > 100 * 1024 * 1024:
                    raise ValueError()
                if 'word/vbaProject.bin' in names:
                    raise ValueError()
                if z.testzip() is not None:
                    raise ValueError()
        else:
            with olefile.OleFileIO(file) as ole:
                if not ole.exists('WordDocument'):
                    raise ValueError()
    except (ValueError, OSError, zipfile.BadZipFile, RuntimeError, EOFError):
        raise ValidationError('文件内容与格式不符、已损坏，或包含不支持的内容。')
    finally:
        file.seek(0)
    return file


def save_blob(file):
    digest = hashlib.sha256()
    for chunk in file.chunks():
        digest.update(chunk)
    sha = digest.hexdigest()
    existing = Blob.objects.filter(sha256=sha).first()
    if existing:
        if not blob_path(existing).is_file():
            raise ValidationError('服务器文件缺失，请联系管理员核查存储。')
        return existing
    file.seek(0)
    storage = FileSystemStorage(location=settings.PRIVATE_STORAGE_ROOT)
    name = storage.save(f'{sha[:2]}/{uuid.uuid4().hex}', file)
    try:
        blob, created = Blob.objects.get_or_create(sha256=sha, defaults={'storage_name': name, 'size': file.size})
    except Exception:
        storage.delete(name)
        raise
    if not created:
        storage.delete(name)
    return blob


def blob_path(blob):
    root = settings.PRIVATE_STORAGE_ROOT.resolve()
    target = (root / blob.storage_name).resolve()
    if not target.is_relative_to(root):
        raise ValidationError('非法文件路径。')
    return target
