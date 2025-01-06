from datetime import datetime

from litestar import get
from litestar.contrib.htmx.request import HTMXRequest
from litestar.contrib.htmx.response import HTMXTemplate
from litestar.response import Template, Response


@get(path="/current_year")
async def get_current_year(
    request: HTMXRequest,
) -> Template | Response:
    if not request.htmx:
        return Response(status_code=400, content={"error": "Only httpx requests are allowed."})

    context = {"year": datetime.now().year}
    return HTMXTemplate(
        template_name="partial/year.html",
        context=context,
    )
