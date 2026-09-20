"""Category visibility and directory classification shared by import and views."""
from pathlib import PurePosixPath
from .models import Category

def active_category_ids():
    categories = {c.pk: c for c in Category.objects.all()}
    result = []
    for category in categories.values():
        current, seen, enabled = category, set(), True
        while current:
            if current.pk in seen or not current.is_active:
                enabled = False
                break
            seen.add(current.pk)
            current = categories.get(current.parent_id)
        if enabled:
            result.append(category.pk)
    return result

def classify_document(source_path, title, legacy_kind='other'):
    parts = PurePosixPath(source_path or '').parts
    is_rider = legacy_kind == 'rider' or '附加' in title or any('附加险' in p for p in parts[:-1])
    coverage = 'rider' if is_rider else 'main'
    if legacy_kind == 'rate' or '费率' in title:
        kind = 'rate'
    elif legacy_kind in ('main', 'rider', 'clause') or '条款' in title:
        kind = 'clause'
    else:
        kind = 'other'
    return coverage, kind

def visible_documents(user, queryset):
    if user.is_superuser:
        return queryset
    return queryset.filter(category_id__in=active_category_ids())
