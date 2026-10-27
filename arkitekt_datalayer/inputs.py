from strawberry.experimental import pydantic

from arkitekt_datalayer import base_models
from arkitekt_datalayer.scalars import ByteCount


@pydantic.input(model=base_models.RequestMediaUploadInput, all_fields=True)
class RequestMediaUploadInput:
    """
    Docstring for RequestMediaUploadInput
    """

    file_size: ByteCount


@pydantic.input(model=base_models.FinishMediaUploadInput, all_fields=True)
class FinishMediaUploadInput:
    """
    Docstring for FinishMediaUploadInput
    """


@pydantic.input(model=base_models.RequestMediaAccessInput, all_fields=True)
class RequestMediaAccessInput:
    """
    Docstring for RequestMediaAccessInput
    """


@pydantic.input(model=base_models.RequestGeneralMediaAccessInput, all_fields=True)
class RequestGeneralMediaAccessInput:
    """
    Docstring for RequestGeneralMediaAccessInput
    """


@pydantic.input(model=base_models.RequestBigFileUploadInput, all_fields=True)
class RequestBigFileUploadInput:
    """
    Docstring for RequestMediaUploadInput
    """

    file_size: ByteCount


@pydantic.input(model=base_models.FinishBigFileUploadInput, all_fields=True)
class FinishBigFileUploadInput:
    """
    Docstring for FinishMediaUploadInput
    """


@pydantic.input(model=base_models.RequestBigFileAccessInput, all_fields=True)
class RequestBigFileAccessInput:
    """
    Docstring for RequestBigFileAccessInput
    """


@pydantic.input(model=base_models.RequestZarrUploadInput, all_fields=True)
class RequestZarrUploadInput:
    """
    Docstring for RequestZarrUploadInput
    """


@pydantic.input(model=base_models.FinishZarrUploadInput, all_fields=True)
class FinishZarrUploadInput:
    """
    Docstring for FinishZarrUploadInput
    """


@pydantic.input(model=base_models.RefreshUploadInput, all_fields=True)
class RefreshUploadInput:
    """Reissue upload credentials for a store whose upload is still in flight, to the same key."""


@pydantic.input(model=base_models.RequestZarrAccessInput, all_fields=True)
class RequestZarrAccessInput:
    """
    Docstring for RequestZarrAccessInput
    """


@pydantic.input(model=base_models.RequestGeneralZarrAccessInput, all_fields=True)
class RequestGeneralZarrAccessInput:
    """
    Docstring for RequestGeneralZarrAccessInput
    """


@pydantic.input(model=base_models.FinishSparseUploadInput, all_fields=True)
class FinishSparseUploadInput:
    """
    Docstring for FinishSparseUploadInput
    """


@pydantic.input(model=base_models.RequestSparseAccessInput, all_fields=True)
class RequestSparseAccessInput:
    """
    Docstring for RequestSparseAccessInput
    """


@pydantic.input(model=base_models.RequestGeneralSparseAccessInput, all_fields=True)
class RequestGeneralSparseAccessInput:
    """
    Docstring for RequestGeneralSparseAccessInput
    """


@pydantic.input(model=base_models.FinishFabriksUploadInput, all_fields=True)
class FinishFabriksUploadInput:
    """
    Docstring for FinishFabriksUploadInput
    """


@pydantic.input(model=base_models.RequestFabriksAccessInput, all_fields=True)
class RequestFabriksAccessInput:
    """
    Docstring for RequestFabriksAccessInput
    """


@pydantic.input(model=base_models.RequestGeneralFabriksAccessInput, all_fields=True)
class RequestGeneralFabriksAccessInput:
    """
    Docstring for RequestGeneralFabriksAccessInput
    """


@pydantic.input(model=base_models.FinishKonnektionUploadInput, all_fields=True)
class FinishKonnektionUploadInput:
    """
    Docstring for FinishKonnektionUploadInput
    """


@pydantic.input(model=base_models.RequestKonnektionAccessInput, all_fields=True)
class RequestKonnektionAccessInput:
    """
    Docstring for RequestKonnektionAccessInput
    """


@pydantic.input(model=base_models.RequestGeneralKonnektionAccessInput, all_fields=True)
class RequestGeneralKonnektionAccessInput:
    """
    Docstring for RequestGeneralKonnektionAccessInput
    """


@pydantic.input(model=base_models.RequestGeneralParquetAccessInput, all_fields=True)
class RequestGeneralParquetAccessInput:
    """
    Docstring for RequestGeneralParquetAccessInput
    """


@pydantic.input(model=base_models.RequestParquetUploadInput, all_fields=True)
class RequestParquetUploadInput:
    """
    Docstring for RequestParquetUploadInput
    """


@pydantic.input(model=base_models.FinishParquetUploadInput, all_fields=True)
class FinishParquetUploadInput:
    """
    Docstring for FinishParquetUploadInput
    """


@pydantic.input(model=base_models.RequestParquetAccessInput, all_fields=True)
class RequestParquetAccessInput:
    """
    Docstring for RequestParquetAccessInput
    """


@pydantic.input(model=base_models.RequestKulisseUploadInput, all_fields=True)
class RequestKulisseUploadInput:
    """Request an upload grant for a kulisse model: one self-contained GLB."""

    file_size: ByteCount


@pydantic.input(model=base_models.FinishKulisseUploadInput, all_fields=True)
class FinishKulisseUploadInput:
    """Finish a kulisse upload: the model is read and checked."""


@pydantic.input(model=base_models.RequestKulisseAccessInput, all_fields=True)
class RequestKulisseAccessInput:
    """Request read credentials for a kulisse model."""


@pydantic.input(model=base_models.RequestGeneralKulisseAccessInput, all_fields=True)
class RequestGeneralKulisseAccessInput:
    """Request read credentials for the organization's kulisse models."""
