"""Who a resolver acts for: the organization and user authentikate put on the request."""

from typing import cast

from authentikate.models import User
from kante.types import Info


def caller(info: Info) -> tuple[int, User]:
    """The organization id and user a datalayer resolver acts for.

    The request carries kante's protocol types; authentikate fills them with its models, and the
    datalayer records the user as a store's creator, so it is narrowed here once.
    """
    request = info.context.request
    return request.organization.id, cast(User, request.user)
