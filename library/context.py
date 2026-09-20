def capabilities(request):
    u = request.user
    return {'can_upload': u.has_perm('library.upload_document'),
            'can_download': u.has_perm('library.download_document'),
            'can_delete': u.has_perm('library.remove_document')}
