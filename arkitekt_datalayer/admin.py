from django.contrib import admin

from arkitekt_datalayer import models

admin.site.register(models.DatalayerStore)
admin.site.register(models.MediaStore)
admin.site.register(models.BigFileStore)
admin.site.register(models.ZarrStore)
admin.site.register(models.ParquetStore)
admin.site.register(models.FabriksStore)
admin.site.register(models.KonnektionStore)
admin.site.register(models.SparseStore)
admin.site.register(models.KulisseStore)
