from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [('library', '0001_initial')]
    operations = [
        migrations.AddField(model_name='category', name='source_path', field=models.CharField(max_length=300, unique=True, null=True, blank=True)),
        migrations.AddField(model_name='category', name='is_active', field=models.BooleanField(default=True, verbose_name='启用类别')),
        migrations.AddField(model_name='document', name='coverage', field=models.CharField(max_length=12, default='main', choices=[('main','主险'),('rider','附加险')], verbose_name='主险 / 附加险')),
        migrations.AlterField(model_name='document', name='kind', field=models.CharField(max_length=20, default='other', choices=[('clause','条款'),('rate','费率表'),('other','其他资料')], verbose_name='资料类型')),
    ]
