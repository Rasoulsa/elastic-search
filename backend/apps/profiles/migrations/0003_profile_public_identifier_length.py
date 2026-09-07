from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("profiles", "0002_profile_import_contract")]

    operations = [
        migrations.AlterField(
            model_name="profile",
            name="public_identifier",
            field=models.CharField(max_length=600, unique=True),
        ),
    ]
