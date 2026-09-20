from django import forms
from django.contrib.auth import password_validation
from django.contrib.auth.forms import AuthenticationForm
from django.core.validators import RegexValidator
from .models import Category, Document, User, Product
from .catalog import active_category_ids
from .storage import validate_document


PERMISSIONS = [('upload_document', '上传资料'), ('download_document', '下载资料'), ('remove_document', '删除资料')]


class LoginForm(AuthenticationForm):
    username = forms.CharField(label='工号 / 管理员账号', max_length=150)
    password = forms.CharField(label='密码', widget=forms.PasswordInput)
    error_messages = {'invalid_login': '工号或密码错误，或账户已被停用。', 'inactive': '账户已被停用。'}


class UploadForm(forms.ModelForm):
    product = forms.ModelChoiceField(label='选择已有产品', queryset=Product.objects.none(), required=False, empty_label='请选择；新产品请填写下方名称')
    product_name = forms.CharField(label='新产品名称', max_length=300, required=False, help_text='仅新增产品时填写；与“已有产品”二选一。')
    product_code = forms.CharField(label='新产品代码', max_length=80, required=False)
    file = forms.FileField(label='Word / PDF 文件', validators=[validate_document],
                           widget=forms.ClearableFileInput(attrs={'accept': '.doc,.docx,.pdf'}))

    class Meta:
        model = Document
        fields = ['title', 'category', 'product', 'product_name', 'product_code', 'coverage', 'kind', 'version', 'file']
        labels = {'category': '产品类别'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        ids = active_category_ids()
        self.fields['category'].queryset = Category.objects.filter(pk__in=ids)
        self.fields['product'].queryset = Product.objects.filter(category_id__in=ids).select_related('category').order_by('category__full_path', 'name')
        self.fields['product'].label_from_instance = lambda p: f'{p.category.full_path} / {p.name}'

    def clean(self):
        data = super().clean()
        product, name = data.get('product'), data.get('product_name')
        if not product and not name:
            self.add_error('product_name', '请选择已有产品，或填写新产品名称。')
        if product and (name or data.get('product_code')):
            self.add_error('product_name', '已选择产品，无需再填写新产品名称或代码。')
        if product and data.get('category') and product.category_id != data['category'].pk:
            self.add_error('product', '所选产品不属于该产品类别。')
        return data


class UserCreateForm(forms.Form):
    username = forms.CharField(label='工号', max_length=150, validators=[RegexValidator(r'^[A-Za-z0-9_-]+$', '工号仅支持字母、数字、下划线和连字符。')])
    display_name = forms.CharField(label='姓名', max_length=80)
    password = forms.CharField(label='初始密码', widget=forms.PasswordInput, help_text='至少 12 位，不能为纯数字或常见密码。')
    permissions = forms.MultipleChoiceField(label='操作权限', choices=PERMISSIONS, required=False, widget=forms.CheckboxSelectMultiple)

    def clean_username(self):
        username = self.cleaned_data['username']
        if User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError('该工号已存在。')
        return username

    def clean(self):
        data = super().clean()
        if data.get('password'):
            password_validation.validate_password(data['password'], User(username=data.get('username', '')))
        return data


class UserEditForm(forms.Form):
    display_name = forms.CharField(label='姓名', max_length=80)
    is_active = forms.BooleanField(label='启用账户', required=False)
    permissions = forms.MultipleChoiceField(label='操作权限', choices=PERMISSIONS, required=False, widget=forms.CheckboxSelectMultiple)
    password = forms.CharField(label='重置为新初始密码', required=False, widget=forms.PasswordInput, help_text='留空则不修改；重置后要求用户重新登录并修改密码。')

    def __init__(self, *args, user, **kwargs):
        self.target_user = user
        super().__init__(*args, **kwargs)

    def clean_password(self):
        value = self.cleaned_data['password']
        if value:
            password_validation.validate_password(value, self.target_user)
        return value


class MetadataForm(forms.ModelForm):
    class Meta:
        model = Document
        fields = ['title', 'coverage', 'kind', 'version', 'needs_review']
        labels = {'needs_review': '仍需核对名称或类型'}



class CategoryForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = ['name', 'parent', 'is_active']
        labels = {'name': '产品类别名称', 'parent': '上级类别'}
        help_texts = {'parent': '留空为一级类别；例如财产保险下可设置家庭财产保险。',
                      'is_active': '停用后普通工号无法查看、下载，下属类别也暂停使用；历史文件保留。'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        qs = Category.objects.all()
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk).exclude(full_path__startswith=self.instance.full_path + '/')
        self.fields['parent'].queryset = qs
        self.fields['parent'].empty_label = '一级类别'

    def clean_name(self):
        name = self.cleaned_data['name'].strip()
        if name in ('.', '..') or any(c in name for c in '/\\'):
            raise forms.ValidationError('类别名称不能包含路径分隔符，也不能为 . 或 ..。')
        return name

    def clean(self):
        data = super().clean()
        if not data.get('name'):
            return data
        parent = data.get('parent')
        target = (parent.full_path + '/' if parent else '') + data['name']
        old = self.instance.full_path if self.instance.pk else None
        descendants = list(Category.objects.filter(full_path__startswith=old + '/')) if old else []
        changed_ids = {c.pk for c in descendants} | {self.instance.pk}
        occupied = {v.casefold() for v in Category.objects.exclude(pk__in=[i for i in changed_ids if i]).values_list('full_path', flat=True)}
        new_paths = [target] + [target + c.full_path[len(old):] for c in descendants]
        if any(len(path) > 300 for path in new_paths):
            self.add_error('name', '类别层级过长，请缩短名称或选择更上层目录。')
        if any(path.casefold() in occupied for path in new_paths):
            self.add_error('name', '同一上级下已有同名类别（包括已停用类别）。')
        self.target_path = target
        self.descendants = descendants
        self.old_path = old
        return data

    def save(self, commit=True):
        category = super().save(commit=False)
        category.full_path = self.target_path
        if commit:
            category.save()
            for child in self.descendants:
                child.full_path = self.target_path + child.full_path[len(self.old_path):]
                child.save(update_fields=['full_path'])
        return category
