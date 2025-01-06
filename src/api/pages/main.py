from litestar import get
from litestar.contrib.htmx.request import HTMXRequest
from litestar.contrib.htmx.response import HTMXTemplate
from litestar.response import Template


@get(path="/")
async def get_main_page(
    request: HTMXRequest,
) -> Template:
    context = {}

    return HTMXTemplate(
        template_name="pages/main.html",
        context=context,
    )
