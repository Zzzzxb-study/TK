from django.db import migrations
from pathlib import PurePosixPath

def forwards(apps, schema_editor):
    Category = apps.get_model('library', 'Category')
    Document = apps.get_model('library', 'Document')
    for category in Category.objects.all():
        category.source_path = category.full_path
        category.save(update_fields=['source_path'])
    for doc in Document.objects.all().iterator():
        parts = PurePosixPath(doc.source_path or '').parts
        rider = doc.kind == 'rider' or '附加' in doc.title or any('附加险' in p for p in parts[:-1])
        doc.coverage = 'rider' if rider else 'main'
        if doc.kind in ('main', 'rider'):
            doc.kind = 'clause'
        doc.save(update_fields=['coverage', 'kind'])

def backwards(apps, schema_editor):
    Document = apps.get_model('library', 'Document')
    for doc in Document.objects.filter(kind='clause').iterator():
        doc.kind = doc.coverage
        doc.save(update_fields=['kind'])

class Migration(migrations.Migration):
    dependencies = [('library', '0002_category_structure')]
    operations = [migrations.RunPython(forwards, backwards)]
