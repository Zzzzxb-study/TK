import hashlib
from django.core.management.base import BaseCommand, CommandError
from library.models import Blob, Document
from library.storage import blob_path


class Command(BaseCommand):
    help = '逐一校验服务器文件是否存在且内容与数据库指纹一致。'

    def handle(self, *args, **options):
        errors = []
        for blob in Blob.objects.iterator():
            path = blob_path(blob)
            if not path.is_file():
                errors.append(f'缺失 blob={blob.pk}')
                continue
            with path.open('rb') as file:
                sha = hashlib.file_digest(file, 'sha256').hexdigest()
            if sha != blob.sha256 or path.stat().st_size != blob.size:
                errors.append(f'校验失败 blob={blob.pk}')
        if errors:
            raise CommandError('\n'.join(errors))
        self.stdout.write(f'PASS: {Blob.objects.count()} 个存储文件，{Document.objects.count()} 条资料记录，内容校验全部通过。')
