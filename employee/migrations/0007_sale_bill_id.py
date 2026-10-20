import uuid

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('employee', '0006_sale_amount_paid_sale_farmer_name_sale_farmer_phone_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='sale',
            name='bill_id',
            field=models.UUIDField(db_index=True, default=uuid.uuid4, editable=False),
        ),
    ]