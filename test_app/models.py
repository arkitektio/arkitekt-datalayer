from django.db import models

from arkitekt_datalayer.models import BigFileStore, MediaStore, ZarrStore


class Document(models.Model):
    """A data row holding one big file, like bank's statement import."""

    store = models.ForeignKey(BigFileStore, on_delete=models.CASCADE, related_name="documents")


class Image(models.Model):
    """A data row holding a zarr and a thumbnail, like mikro's array dataset."""

    data = models.ForeignKey(ZarrStore, on_delete=models.CASCADE, related_name="images")
    thumbnail = models.ForeignKey(MediaStore, on_delete=models.SET_NULL, null=True, blank=True, related_name="images")
