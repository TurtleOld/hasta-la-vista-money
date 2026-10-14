from datetime import timedelta

from django.db import migrations
from django.db.models import F


def backfill_invite_expiry(apps, _schema_editor):
    """Give legacy invites an explicit expiry derived from their creation."""
    FamilyInvite = apps.get_model('users', 'FamilyInvite')
    # The TTL is frozen here on purpose: migrations must not follow
    # ``FAMILY_INVITE_TTL`` if that constant changes later.
    FamilyInvite.objects.filter(expires_at__isnull=True).update(
        expires_at=F('created_at') + timedelta(days=7),
    )


class Migration(migrations.Migration):

    dependencies = [
        (
            'users',
            '0019_remove_bankstatementrow_unique_statement_row_transfer_'
            'and_more',
        ),
    ]

    operations = [
        migrations.RunPython(
            backfill_invite_expiry,
            migrations.RunPython.noop,
        ),
    ]
