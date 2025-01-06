from litestar import get
from litestar.contrib.htmx.request import HTMXRequest
from litestar.contrib.htmx.response import HTMXTemplate
from litestar.response import Template


@get(path="/posts")
async def get_posts_page(
    request: HTMXRequest,
) -> Template:
    context = {}

    return HTMXTemplate(
        template_name="pages/posts.html",
        context=context,
    )


@get(path="/posts/{post_slug:str}")
async def get_post(
    request: HTMXRequest,
    post_slug: str,
) -> Template:
    return HTMXTemplate(
        template_name=f"posts/{post_slug}.html",
    )
