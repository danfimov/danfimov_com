Сейчас вполне нормальной историей является ускорение Python библиотек с помощью переписывания их частей на Rust с использованием [PyO3](https://github.com/pyo3/pyo3). На случай, если ускорения всё-таки хочется, а покидать уютный мир Python - нет, есть [mypyc](https://mypyc.readthedocs.io/en/latest/introduction.html).

> **TLDR**: покажу, как можно ускорить код [h11](https://github.com/python-hyper/h11) (HTTP/1.1 библиотечка со 710k пользователями на GitHub) с помощью компиляции с mypyc примерно в два раза. В процессе покажу, как я чинил разные интересные ошибки, связанные с адаптацией кодовой базы под mypyc.

Код с изменениями, упомянутыми в статье, можно посмотреть в репозитории на GitHub: [danfimov/h11](https://github.com/danfimov/h11).

## Для начала база

Про [mypy](https://mypy.readthedocs.io/en/stable/) слышали примерно все (надеюсь, использовали тоже), а что вообще такое mypyc? Mypyc — это ahead-of-time компилятор, который превращает аннотированный типами Python-код в CPython C-extensions. Если объяснять на пальцах, то mypyc берет ваш Python-код и, опираясь на аннотации типов, компилирует его в файлы `.so` или `.pyd` (в зависимости от платформы). В этих файлах будет лежать C‑extension код, причем вы сможете импортировать его как обычный модуль. Под капотом CPython код уже не будет интерпретироваться на ходу, вместо этого будет исполняться нативный заранее скомпилированный под конкретную платформу код — отсюда и ускорение.

Аннотации типов в исходном Python-коде при этом нужны, чтобы:

- Выбирать более эффективные представления (например, «unboxed» целые числа). Условно, вместо использования `PyObject` для integer использовать сразу `int32_t` на уровне C;
- Делать early binding (разрешать вызовы функций и доступ к атрибутам на этапе компиляции);
- Минимизировать динамические проверки и lookup’и в неймспейсах. То есть не надо проходить цепочку: пройдись по `__dict__`, потом по классам (MRO), потом учти дескрипторы, `__getattribute__`, `__getattr__`. Вместо этого можно заранее запомнить, к каким полям структуры надо обращаться.

Причем на границах вызовов скомпилированного Python кода mypyc вставляет явные проверки типов, которые будут выбрасывать `TypeError` в случае несовпадения переданных типов.

## Чиним типизацию в библиотеке

Чтобы попробовать скомпилировать кодовую базу через mypyc, нужно для начала устранить все ошибки в аннотациях типов, которые подсвечивает mypy. Устанавливаем mypy, кладем конфиг в `pyproject.toml` и можем начинать:

```toml
[tool.mypy]
strict = true
warn_unused_configs = true
warn_unused_ignores = true
show_error_codes = true
```

Оценим масштаб проблемы в h11:

```bash
> mypy h11
...
Found 13 errors in 3 files (checked 11 source files)
```

В целом, не так плохо, пара лишних `# type: ignore` и несколько несовпадений типов. Надо понимать, что библиотечка немолодая, плюс поддерживает старые версии Python вплоть до 3.8. Чтобы совсем не упарываться с back compatibility, возьмем последнюю на данный момент версию mypy (2.3.1) и будем чинить аннотации так, будто нам нужно поддерживать Python 3.10+ (все не EOL релизы).

По сути надо будет пройти три этапа:

- Удовлетворить mypy и довести код до состояния, когда он перестанет в strict режиме выдавать ошибки;
- Сделать так, чтобы mypyc при вызове успешно всё компилировал;
- Добиться корректности работы скомпилированного кода в рантайме (импорты и тесты работают).

### `bytes` vs `bytearray` в цепочке вызовов

Пойдем по ошибкам, которые возвращает mypy. `ReceiveBuffer.maybe_extract_lines()` [метод](https://github.com/python-hyper/h11/blob/62c5068c971579d61fa1b55373390e12f25fd856/h11/_receivebuffer.py#L104) и `maybe_extract_at_most()` [метод](https://github.com/python-hyper/h11/blob/62c5068c971579d61fa1b55373390e12f25fd856/h11/_receivebuffer.py#L77) возвращают
`bytearray` (так сделано, чтобы не копировать данные лишний раз). А `_obsolete_line_fold`, `_decode_header_lines`, `validate()`, конструктор `Data()` были аннотированы как принимающие `bytes`. Отсюда расхождение, о котором сигнализирует mypy:

```bash
h11/_readers.py:53: error: Incompatible types in assignment (expression has type "bytearray", variable has type "bytes | None")  [assignment]
h11/_readers.py:84: error: Argument 2 to "validate" has incompatible type "bytearray"; expected "bytes"  [arg-type]
h11/_readers.py:87: error: Argument 1 to "_decode_header_lines" has incompatible type "list[bytearray]"; expected "Iterable[bytes]"  [arg-type]
h11/_readers.py:104: error: Argument 2 to "validate" has incompatible type "bytearray"; expected "bytes"  [arg-type]
h11/_readers.py:114: error: Argument 1 to "_decode_header_lines" has incompatible type "list[bytearray]"; expected "Iterable[bytes]"  [arg-type]
h11/_readers.py:134: error: Argument "data" to "Data" has incompatible type "bytearray"; expected "bytes"  [arg-type]
h11/_readers.py:161: error: Argument 1 to "_decode_header_lines" has incompatible type "list[bytearray]"; expected "Iterable[bytes]"  [arg-type]
h11/_readers.py:182: error: Argument 2 to "validate" has incompatible type "bytearray"; expected "bytes"  [arg-type]
h11/_readers.py:204: error: Argument "data" to "Data" has incompatible type "bytearray"; expected "bytes"  [arg-type]
h11/_readers.py:218: error: Argument "data" to "Data" has incompatible type "bytearray"; expected "bytes"  [arg-type]
```

Чтобы починить, достаточно расширить сигнатуры в `_obsolete_line_fold`, `_decode_header_lines`, `validate()` и конструкторе `Data()` до `bytes | bytearray` вместо простого `bytes`. В общем проходимся по всем местам, где байтовая строка идёт из `ReceiveBuffer` напрямую в API, объявленный под чистый `bytes`. Для этого я завел вспомогательный тип и везде прорастил его примерно так:

```python
# _util.py
ByteLike = Union[bytes, bytearray]

def validate(regex, data: ByteLike, ...) -> Dict[str, bytes]: ...
```

Также от похожей проблемы страдают `method`/`target`/`http_version`/`reason` (например [тут](https://github.com/python-hyper/h11/blob/62c5068c971579d61fa1b55373390e12f25fd856/h11/_events.py#L77)) в конструкторах `Request`/`_ResponseBase` — там в типах указаны `bytes`, но судя по тестам, они могут принимать и `bytearray`. Заменим.

После этих правок и удаления ненужных `# type: ignore` комментариев mypy чист. Значит ли это, что код уже успешно собирается mypyc? Пока, к сожалению, нет. При попытке вызвать `mypyc h11 --exclude 'h11/tests/'` получается куча ошибок. Разберемся, что и как нужно поправить.

### Чиним метакласс Sentinel

В [h11/_util.py](https://github.com/python-hyper/h11/blob/62c5068c971579d61fa1b55373390e12f25fd856/h11/_util.py#L107) есть вот такой класс:

```python
class Sentinel(type):
    def __new__(cls, name, bases, namespace, **kwds):
        assert bases == (Sentinel,)
        v = super().__new__(cls, name, bases, namespace, **kwds)
        v.__class__ = v  # чтобы удобно было писать type(sentinel) is sentinel
        return v

    def __repr__(self):
        return self.__name__

class IDLE(Sentinel, metaclass=Sentinel):
    pass
```

Это метакласс, который используется для создания уникальных именованных констант (sentinel-значений), таких как состояния протокола `CLIENT`, `SERVER`, `IDLE`, `DONE`, `NEED_DATA`, `PAUSED` и так далее.

mypyc спотыкается на нем, потому что не умеет компилировать пользовательские метаклассы:

```bash
h11/_util.py:112: error: Inheriting from most builtin types is unimplemented
note: Potential workaround: @mypy_extensions.mypyc_attr(native_class=False)
```

Прикол с `v.__class__ = v`, дающий каждому сентинелу возможность делать проверку вроде `type(IDLE) is IDLE`, вообще не выразим в скомпилированном классе. Можно обойти эту проблему двумя способами:

- По совету той же подсказки от mypyc навесить `@mypyc_attr(native_class=False)` декоратор на класс и спокойно жить. Это говорит компилятору «не пытайся сделать из этого класса нативное C-расширение, оставь как обычный интерпретируемый Python-класс». Из минусов: у нас появляется runtime зависимость от `mypy_extensions`, а также эта часть не получит бенефитов скорости скомпилированного кода.
- Переписать Sentinel в пустой класс и использовать его в наследовании напрямую `class IDLE(Sentinel)`, забив на красивый `__repr__` и `type(sentinel) is sentinel`. Думаю, в рамках статьи это приемлемо (если приносить реальный MR в библиотеку, то тут, конечно, еще подумать надо).

Поправили класс, переписали один тест с `__repr__` — как будто починили. После этого даже mypyc реально соберет вам код, и в проекте появятся `.so` файлы. Значит ли это, что всё работает без ошибок? Жаль, но пока нет...

### Event(ABC) + написанные вручную slots на dataclasses

Если попытаться после компиляции вызвать простейший скрипт, то вылезет ошибка:

```python
import h11

print(h11.Event)
```

```bash
> uv run python -m test_script
Traceback (most recent call last):
  File "<frozen runpy>", line 198, in _run_module_as_main
  File "<frozen runpy>", line 88, in _run_code
  File "/home/danfimov/Documents/projects/h11-mypyc/test_script.py", line 1, in <module>
    import h11
  File "h11/__init__.py", line 9, in <module>
    from h11._connection import Connection, NEED_DATA, PAUSED
  File "h11/_connection.py", line 16, in <module>
    from ._events import (
  File "h11/_events.py", line 41, in <module>
    class Request(Event):
AttributeError: type object 'Request' has no attribute '__slots__'
```

Причина в связке двух вещей: `Event` наследуется от `abc.ABC`, `Request`/`Response`/... — замороженные `@dataclass(init=False, frozen=True)` с ручным `__slots__ = (...)` в теле класса. В обычном Python это прекрасно работает. Но в скомпилированном виде mypyc создаёт классы как «нативные» (расширения C, `PyTypeObject`), у которых слоты уже зашиты в layout — и сочетание с ABC-метаклассом на этапе создания класса даёт `AttributeError` при инициализации модуля.

Чтобы это поправить, достаточно отвязать `Event` от `ABC` и перестать задавать слоты вручную:

```python
# было
class Event(ABC):
    __slots__ = ()

@dataclass(init=False, frozen=True)
class Request(Event):
    __slots__ = ("method", "headers", "target", "http_version")
    ...

# стало
class Event:
    pass

@dataclass(init=False, frozen=True, slots=True)
class Request(Event):
    ...
```

Также после этого из `Request`/`Response` можно смело выкидывать вызов `super().__init__()`, потому что он сломает даже обычный Python-код.

После этого ошибка изменится на:

```bash
Traceback (most recent call last):
  File "<frozen runpy>", line 198, in _run_module_as_main
  File "<frozen runpy>", line 88, in _run_code
  File "/home/danfimov/Documents/projects/h11-mypyc/test_script.py", line 1, in <module>
    import h11
  File "h11/__init__.py", line 9, in <module>
    from h11._connection import Connection, NEED_DATA, PAUSED
  File "h11/_connection.py", line 26, in <module>
    from ._readers import READERS, ReadersType
  File "h11/_readers.py", line 25, in <module>
    from ._state import (
  File "h11/_state.py", line 115, in <module>
    from ._events import *
ModuleNotFoundError: No module named '_events'
```

Чинится еще проще — надо заменить `from ._events import *` на более явный:

```python
from ._events import (
    ConnectionClosed, Data, EndOfMessage, Event,
    InformationalResponse, Request, Response,
)
```

После этого наивная проверка со скриптом заработает:

```bash
> uv run python -m test_script
<class 'h11._events.Event'>
```

Жаль, что заметная часть тестов при этом развалится с `TypeError`:

```bash
FAILED h11/tests/test_against_stdlib_http.py::test_h11_as_client - TypeError: bytes object expected; got bytearray
FAILED h11/tests/test_connection.py::test__body_framing - TypeError: bytes object expected; got None
FAILED h11/tests/test_connection.py::test_Connection_basics_and_content_length - TypeError: bytes object expected; got bytearray
FAILED h11/tests/test_connection.py::test_chunked - TypeError: bytes object expected; got bytearray
FAILED h11/tests/test_connection.py::test_chunk_boundaries - TypeError: bytes object expected; got bytearray
FAILED h11/tests/test_connection.py::test_client_talking_to_http10_server - TypeError: bytes object expected; got bytearray
...
23 failed, 55 passed in 0.30s
```

### Может Any не так уж плох?

Как я упоминал ранее, mypyc вставляет явные проверки типов, которые будут выбрасывать `TypeError` в случае несовпадения переданных типов. Это и происходит в тестах.

Разберем на примере одного из тестов:

```python
    def test_normalize_data_events() -> None:
        assert normalize_data_events(
            [
>               Data(data=bytearray(b"1")),
                ^^^^^^^^^^^^^^^^^^^^^^^^^^
                Data(data=b"2"),
                Response(status_code=200, headers=[]),
                Data(data=b"3"),
                Data(data=b"4"),
                EndOfMessage(),
                Data(data=b"5"),
                Data(data=b"6"),
                Data(data=b"7"),
            ]
        ) == [
            Data(data=b"12"),
            Response(status_code=200, headers=[]),
            Data(data=b"34"),
            EndOfMessage(),
            Data(data=b"567"),
        ]

h11/tests/test_helpers.py:8:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _

>   object.__setattr__(self, "data", data)
E   TypeError: bytes object expected; got bytearray

h11/_events.py:293: TypeError
```

Как видим, падает просто на передаче в аргумент `data` обычного `bytearray`. Проблема в том, что тип для `Data.data` указан как `bytes`, что вызывает `TypeError` для скомпилированного кода.

По документации `Data.data` принимает не только `bytes`, но и «любой объект, который ваш код записи данных умеет обрабатывать, и для которого `len()` возвращает число байт» — это официальная поддержка `sendfile()`-заглушек. Можно расширить до `bytes | bytearray`, но, вообще говоря, по логике работы он должен быть способен принимать `Any` (это даже проверяет один из тестов). Меняем аннотацию здесь и во всех местах, где это поле читается (см. метод `send_data`) и компилируем — тест после этого пройдет.

Аналогичная история будет с `_ResponseBase.status_code`. Конструктор этого класса явно проверяет `isinstance(status_code, int)` и кидает `LocalProtocolError("status code must be integer")`, если это не так — то есть в API специально заложена дружелюбная ошибка для неправильного типа. При параметре, аннотированном как `status_code: int`, mypyc сам кидает `TypeError` до того, как выполнение доходит до этой проверки — человекочитаемое сообщение из библиотеки никогда не срабатывает и один из тестов падает. Придется тоже расширить до `Any`.

### Вычищаем лишние None

В одном из тестов есть такое падение:

```bash
>   reason = b"" if matches["reason"] is None else matches["reason"]
E   TypeError: bytes object expected; got None
```

`status_line` в ABNF допускает отсутствие `reason` и `http_version` (некоторые серверы шлют `HTTP/1.0 200\r\n` без фразы). `match.groupdict()` в таком случае кладёт `None` в несовпавшую именованную группу. Функция объявлена как
`def validate(...) -> Dict[str, bytes]`, что по сути неправда, потому что словарь мог содержать `None`. mypyc в рантайме проверяет, что все значения возвращаемого словаря — действительно `bytes`, и падает прямо на `return match.groupdict()`. Можно пофиксить, если начать вычищать несовпавшие группы перед возвратом:

```python
def validate(regex, data: ByteLike, msg="malformed data", *format_args) -> Dict[str, bytes]:
    match = regex.fullmatch(data)
    if not match:
        ...
        raise LocalProtocolError(msg)
    return {name: value for name, value in match.groupdict().items() if value is not None}
```

а на стороне вызывающего кода — читать опциональные поля через `.get(name, default)` вместо `matches[name] is None`:

```python
http_version = matches.get("http_version", b"1.1")
reason = matches.get("reason", b"")
```

### Убираем cast

Тесты в `test_connection.py` уже использовали `type: ignore`, по которым можно понять, что что-то идет не так:

```python
assert _body_framing(None, req()) == ("content-length", (0,))  # type: ignore
```

`Connection._request_method` — это `Optional[bytes]`: до прихода `Request` (например, сервер отвечает `408 Request Timeout` раньше, чем что-либо прочитал) метода ещё нет. В h11 вызывающий код прятал это через `cast(bytes, self._request_method)` — мол, «доверьтесь мне, тут не будет `None`». В скомпилированном виде `cast()` ничего не даёт в рантайме (это чисто mypy-подсказка), а `_body_framing` объявлена как принимающая `bytes` — падает `TypeError` на живом 408-сценарии. В качестве фикса нужно начать явно принимать `Optional[bytes]`:

```python
def _body_framing(request_method: Optional[bytes], event: Union[Request, Response]):
    ...
```

`None` корректно проваливает оба сравнения (`== b"HEAD"`, `== b"GET"`) внутри функции, так что дальше по коду ничего менять не нужно — только сигнатура и снятие `cast()`.

После этого все тесты наконец пройдут.

## Считаем прирост производительности

Самое время посчитать, сколько компиляция дает к производительности. Для этого можно собрать небольшой игрушечный бенчмарк: разбор GET-запроса с реалистичным набором заголовков браузера, включая длинную куку, плюс отправка ответа на 1000 байт.

| Версия                             | Медиана, req/sec | Относительно baseline |
| ---------------------------------- | ---------------- | --------------------- |
| `h11`, до правок                   | 36 414           | -                     |
| `h11`, после правок, чистый Python | 37 409           | +2%                   |
| `h11`, после правок и компиляции   | 58 983           | **+62%**              |

Получилось, что версия после правок не просела по производительности (+2% — это что-то в пределах шума бенчмарка). Но компиляция дала неплохой буст. Да, не кликбейтный x2, но всё еще вполне ощутимый.

Думаю, на этом можно подвести промежуточный итог: компиляция дает реальный профит, но требует аккуратной типизации и знания нюансов работы скомпилированного mypyc кода. В качестве proof-of-concept я форкнул репозиторий h11 и выпустил Python-пакет, чтобы поиграться с оптимизациями еще больше:

- [код форка](https://github.com/danfimov/h11) (там можно легко прикинуть diff с апстрим кодом библиотеки)
- [h11-mypyc пакет на PyPI](https://pypi.org/project/h11-mypyc/)

> На самом деле прироста в два раза можно добиться дополнительными оптимизациями кода и внимательным разбором вывода [Tachyon](https://docs.python.org/3.15/whatsnew/3.15.html#whatsnew315-sampling-profiler)/[Memray](https://github.com/bloomberg/memray). В форке уже применена часть из них. Так что если статья найдет отклик, я планирую написать вторую часть, посвященную конкретно этому аспекту.

Спасибо за прочтение. Надеюсь, статья оказалась полезной для вас. Любые вопросы готов обсудить в комментариях.
