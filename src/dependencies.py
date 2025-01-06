from pathlib import Path

from litestar import Litestar
from litestar.config.compression import CompressionConfig
from litestar.contrib.jinja import JinjaTemplateEngine
from litestar.plugins.htmx import HTMXPlugin
from litestar.static_files import StaticFilesConfig
from litestar.template.config import TemplateConfig

from src.api.pages.main import get_main_page
from src.api.pages.resume import get_resume_page
from src.api.pages.posts import get_posts_page, get_post
from src.api.utils import get_current_year


def get_application() -> Litestar:
    app = Litestar(
        route_handlers=[
            get_main_page,
            get_resume_page,
            get_current_year,
            get_posts_page,
            get_post,
        ],
        debug=True,
        plugins=[HTMXPlugin()],
        template_config=TemplateConfig(
            directory=Path("src/templates"),
            engine=JinjaTemplateEngine,
        ),
        static_files_config=[
            StaticFilesConfig(
                directories=[
                    Path("src/static"),
                ],
                path="static",
            ),
        ],
        compression_config=CompressionConfig(backend="gzip"),
    )
    return app
