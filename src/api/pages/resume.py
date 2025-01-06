from litestar import get
from litestar.contrib.htmx.request import HTMXRequest
from litestar.contrib.htmx.response import HTMXTemplate
from litestar.response import Template


@get(path="/resume")
async def get_resume_page(
    request: HTMXRequest,
) -> Template:
    context = {}
    context['projects'] = [
        {
            'title': 'Django TinyMCE4 Plus',
            'link': 'https://github.com/danfimov/django-tinymce4-plus',
            'description': 'Библиотека для интеграции TinyMCE 4 виджета в Django админку. Работает со всеми версиями Django.',
            'creation_reason': 'Написал, когда нужно было перевозить проект с Django 1.11 на Django 4+ с сохранением работы привычных виджетов.',
            'technologies': ['Django', 'TinyMCE']
        },
        {
            'title': 'Yandex Tracker Client',
            'link': 'https://github.com/danfimov/ya_tracker_client',
            'description': 'Обертка над API Яндекс Трекера для удобной работы с задачами и проектами из Python кода.',
            'creation_reason': 'Написал, когда нужно было вытащить сводную информацию о работе нашей команды по спринтам.',
            'technologies': ['Aiohttp', 'Pydantic'],
        }
    ]

    context['certificates'] = [
        {
            'title': 'Cloud Services Engineer',
            'organization': 'Yandex Practicum',
            'date': 'Apr 2022',
            'link': 'https://www.linkedin.com/in/danfimov/details/certifications/1635548567790/single-media-viewer/?profileId=ACoAACKJl8gB9DsVLqkybPexfhqQR-hkmJKON4Y',
            'technologies': ['Cloud Infrastructure', 'Docker'],
        },
        {
            'title': 'Specialization - Interface development: layout and JavaScript',
            'organization': 'Coursera',
            'date': 'Aug 2020',
            'link': 'https://www.coursera.org/account/accomplishments/specialization/8FQB235KM4ME',
            'technologies': ['JavaScript', 'HTML', 'CSS'],
        }
    ]

    context['education'] = [
        {
            'title': 'Школа бэкенд разработки',
            'organization': 'Yandex',
            'date_start': 'Oct 2021',
            'date_end': 'Dec 2021',
        },
        {
            'title': 'Неоконченное высшее по специальности "Прикладная математика и информатика"',
            'organization': 'NaRFU',
            'date_start': 'Sep 2018',
            'date_end': 'May 2022',
        }
    ]

    return HTMXTemplate(
        template_name="pages/resume.html",
        context=context,
    )
