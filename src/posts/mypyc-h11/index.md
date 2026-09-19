Rewriting parts of a Python library in Rust with PyO3 is a perfectly normal way to speed it up these days. But what if you're not ready to learn a whole new language just for potential optimizations? If you still want the speedup and don't want to leave the cozy world of Python, there is mypyc.

> TL;DR: I'll show how to speed up [h11](https://github.com/python-hyper/h11) (a small HTTP/1.1 library with 710k dependents on GitHub) by roughly a factor of two by compiling it with mypyc. Along the way I'll walk through the interesting errors I hit while adapting the codebase to mypyc, and how I fixed them.

## The basics first

You've heard of mypy (maybe even used it), but what is mypyc? mypyc is an ahead-of-time compiler that turns Python code annotated with type hints into CPython C extensions. In plain words: mypyc takes your Python code and, relying on the type annotations, compiles it ahead of time into `.so` or `.pyd` files (depending on the platform). That file holds a CPython C extension. You import it like any other module, but inside it isn't interpreted on the fly: native code runs right away, and that's where the speedup comes from.

Type annotations in the source are needed to:
- pick more efficient representations (for example, "unboxed" integers). Roughly speaking, instead of a `PyObject` for an integer you use a plain `int32_t` at the C level;
- do **early binding** (resolve function calls and attribute access at compile time);
- minimize dynamic checks and namespace lookups. That is, no need to walk the whole chain: look into `__dict__`, then into the classes (MRO), then take descriptors, `__getattribute__` and `__getattr__` into account. Instead, the compiler can remember in advance which struct fields to access.

Also, at the boundary between compiled and regular Python code, mypyc inserts explicit type checks that raise `TypeError` if the passed types don't match.

## Fixing the library's type annotations

To try compiling the codebase with mypyc, we first need to fix all the errors in type annotations that mypy reports. Install mypy, put the config into `pyproject.toml`, and we can start:

```toml
[tool.mypy]
strict = true
warn_unused_configs = true
warn_unused_ignores = true
show_error_codes = true
```

Let's see how bad things are in h11:

```bash
> mypy h11
...
Found 13 errors in 3 files (checked 11 source files)
```

Not that bad: a few redundant `type: ignore` comments and a few type mismatches. Keep in mind that the library isn't young and supports old Python versions, all the way back to 3.8. To avoid going overboard with backward compatibility, we'll take the latest mypy version at the time of writing (2.3.1) and fix the annotations as if we only had to support Python 3.10+ (all releases that aren't EOL).

Basically, we'll go through three stages:
- Satisfy mypy and get the code to the point where it reports no errors in strict mode
- Make mypyc compile everything successfully
- Make the compiled code work correctly at runtime (imports and tests pass)

### `bytes` vs `bytearray` in the readers chain

Let's go through the errors mypy returns one by one. `ReceiveBuffer.maybe_extract_lines()` and `maybe_extract_at_most()` return
`bytearray` (this is done to avoid copying the data one more time). Meanwhile `_obsolete_line_fold`, `_decode_header_lines`, `validate()` and the `Data()` constructor were annotated as accepting `bytes`. Hence the mismatch that mypy reports:

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

To fix this, it's enough to widen the signatures of `_obsolete_line_fold`, `_decode_header_lines`, `validate()` and the `Data()` constructor to `bytes | bytearray` instead of plain `bytes`. In general, we go through every place where a byte string flows from `ReceiveBuffer` straight into an API declared for pure `bytes`. For this I introduced a helper type and threaded it through the code like this:

```python
# _util.py
ByteLike = Union[bytes, bytearray]

def validate(regex, data: ByteLike, ...) -> Dict[str, bytes]: ...
```

A similar problem affects `method`/`target`/`http_version`/`reason` in the `Request`/`_ResponseBase` constructors: they're annotated as `bytes`, but judging by the tests they can also accept `bytearray`. We'll replace those too.

After these changes and removing the unneeded `type: ignore` comments, mypy is clean. Does that mean mypyc can already build the code? Unfortunately, not yet. Running `mypyc h11 --exclude 'h11/tests/'` produces a bunch of errors. Let's figure out what needs fixing and how.

### Fixing the Sentinel metaclass

In [`h11/_util.py`](https://github.com/python-hyper/h11/blob/62c5068c971579d61fa1b55373390e12f25fd856/h11/_util.py#L107) there is this class:

```python
class Sentinel(type):
    def __new__(cls, name, bases, namespace, **kwds):
        assert bases == (Sentinel,)
        v = super().__new__(cls, name, bases, namespace, **kwds)
        v.__class__ = v  # so that `type(sentinel) is sentinel` works
        return v

    def __repr__(self):
        return self.__name__

class IDLE(Sentinel, metaclass=Sentinel):
    pass
```

This is a metaclass used to create unique named constants (sentinel values), such as the protocol states `CLIENT`, `SERVER`, `IDLE`, `DONE`, `NEED_DATA`, `PAUSED` and so on.

mypyc trips over it because it can't compile custom metaclasses:

```bash
h11/_util.py:112: error: Inheriting from most builtin types is unimplemented
note: Potential workaround: @mypy_extensions.mypyc_attr(native_class=False)
```

The `v.__class__ = v` trick, which gives every sentinel the special property `type(IDLE) is IDLE`, simply can't be expressed in a compiled class. There are two ways around this:

- Follow the hint from mypyc itself and put the `@mypyc_attr(native_class=False)` decorator on the class, then carry on. It tells the compiler "don't try to turn this class into a native C extension, leave it as a regular interpreted Python class". The downsides: we get a runtime dependency on `mypy_extensions`, and this part of the code won't get any of the speed benefits of compilation.
- Rewrite `Sentinel` as an empty class and inherit from it directly with `class IDLE(Sentinel)`, giving up the nice `__repr__` and `type(sentinel) is sentinel`. I think that's acceptable for the purposes of this article (if I were sending a real PR to the library, I'd have to think about it some more).

We fixed the class and rewrote one test that relied on `__repr__`, so it looks like we're done. After this, mypyc will actually build your code, and `.so` files will appear in the project. Does that mean everything works without errors? Sadly, not yet...

### Event(ABC) + hand-written slots on dataclasses

If you try to run the simplest script after compilation, you'll get an error:

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

The cause is a combination of two things: `Event` inherits from `abc.ABC`, while `Request`/`Response`/... are frozen `@dataclass(init=False, frozen=True)` classes with a hand-written `__slots__ = (...)` in the class body. In regular Python this works perfectly well. But when compiled, mypyc creates "native" classes (C extensions, `PyTypeObject`) whose slots are already baked into the layout, and combining that with the ABC metaclass at class creation time raises an `AttributeError` during module initialization.

To fix it, it's enough to detach `Event` from `ABC` and stop declaring slots by hand:

```python
# before
class Event(ABC):
    __slots__ = ()

@dataclass(init=False, frozen=True)
class Request(Event):
    __slots__ = ("method", "headers", "target", "http_version")
    ...

# after
class Event:
    pass

@dataclass(init=False, frozen=True, slots=True)
class Request(Event):
    ...
```

After this you can also safely drop the `super().__init__()` call from `Request`/`Response`, because it would break even plain Python code.

The error then changes to:

```bash
Traceback (most recent call last):
  File "<frozen runpy>", line 198, in _run_module_as_main
  File "<frozen runpy>", line 88, in _run_code
  File "/home/danfimov/Documents/projects/h11-mypyc/a.py", line 1, in <module>
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

This one is even easier to fix: replace `from ._events import *` with an explicit import:

```python
from ._events import (
    ConnectionClosed, Data, EndOfMessage, Event,
    InformationalResponse, Request, Response,
)
```

After that, our naive check script works:

```
> uv run python -m test_script
<class 'h11._events.Event'>
```

Sadly, a fair share of the tests now fail with `TypeError`:

```
FAILED h11/tests/test_against_stdlib_http.py::test_h11_as_client - TypeError: bytes object expected; got bytearray
FAILED h11/tests/test_connection.py::test__body_framing - TypeError: bytes object expected; got None
FAILED h11/tests/test_connection.py::test_Connection_basics_and_content_length - TypeError: bytes object expected; got bytearray
FAILED h11/tests/test_connection.py::test_chunked - TypeError: bytes object expected; got bytearray
FAILED h11/tests/test_connection.py::test_chunk_boundaries - TypeError: bytes object expected; got bytearray
FAILED h11/tests/test_connection.py::test_client_talking_to_http10_server - TypeError: bytes object expected; got bytearray
...
23 failed, 55 passed in 0.30s
```

### Maybe Any isn't so bad?

As I mentioned earlier, mypyc inserts explicit type checks that raise `TypeError` when the passed types don't match. That's exactly what's happening in the tests.

Let's look at one of the tests:

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

As we can see, it fails simply on passing a plain `bytearray` as the `data` argument. The problem is that the type of `Data.data` is declared as `bytes`, which causes a `TypeError` in compiled code.

According to the docs, `Data.data` is not only `bytes` but also "any object your data-writing code knows how to handle and for which `len()` returns the number of bytes" — this is official support for `sendfile()`-style placeholders. We could widen it to `bytes | bytearray`, but, generally speaking, by design it should be able to accept `Any` (one of the tests even checks that). So we change the annotation here and in every place where this field is read (see the `send_data` method), compile, and the test passes.

The same story goes for `_ResponseBase.status_code`. The constructor of this class explicitly checks `isinstance(status_code, int)` and raises `LocalProtocolError("status code must be integer")` otherwise, so the API deliberately provides a friendly error for a wrong type. With the parameter annotated as `status_code: int`, mypyc itself raises `TypeError` before execution reaches that check: the human-readable message from the library never fires, and one of the tests fails. We'll have to widen this one to `Any` as well.

### Cleaning up unnecessary None

One of the tests fails like this:

```bash
>   reason = b"" if matches["reason"] is None else matches["reason"]
E   TypeError: bytes object expected; got None
```

In ABNF, `status_line` allows `reason` and `http_version` to be absent (some servers send `HTTP/1.0 200\r\n` without a reason phrase). In that case `match.groupdict()` puts `None` into the unmatched named group. The function is declared as
`def validate(...) -> Dict[str, bytes]`, which is essentially a lie, because the dictionary could contain `None`. At runtime mypyc checks that all values of the returned dictionary really are `bytes`, and fails right on `return match.groupdict()`. We can fix this by dropping the unmatched groups before returning:

```python
def validate(regex, data: ByteLike, msg="malformed data", *format_args) -> Dict[str, bytes]:
    match = regex.fullmatch(data)
    if not match:
        ...
        raise LocalProtocolError(msg)
    return {name: value for name, value in match.groupdict().items() if value is not None}
```

and on the calling side, read the optional fields through `.get(name, default)` instead of `matches[name] is None`:

```python
http_version = matches.get("http_version", b"1.1")
reason = matches.get("reason", b"")
```

### Removing cast

The tests in `test_connection.py` already contained `type: ignore` comments, which hint that something is off:

```python
assert _body_framing(None, req()) == ("content-length", (0,))  # type: ignore
```

`Connection._request_method` is an `Optional[bytes]`: until a `Request` arrives (for example, when the server replies `408 Request Timeout` before it has read anything) there is no method yet. In h11 the calling code hid this behind `cast(bytes, self._request_method)`, basically saying "trust me, it won't be `None` here". In compiled code `cast()` does nothing at runtime (it's purely a hint for mypy), while `_body_framing` is declared as taking `bytes`, so it fails with `TypeError` in a real 408 scenario. The fix is to explicitly accept `Optional[bytes]`:

```python
def _body_framing(request_method: Optional[bytes], event: Union[Request, Response]):
    ...
```

`None` correctly fails both comparisons (`== b"HEAD"`, `== b"GET"`) inside the function, so nothing else in the code needs to change, just the signature and removing `cast()`.

After that, all the tests finally pass.

## Measuring the performance gain

Now it's time to measure how much compilation gives us. For this we can build a small toy benchmark: parsing a GET request with a realistic set of browser headers, including a long cookie, plus sending a 1000-byte response.

| Version                            | Median, req/sec | Relative to baseline |
| ---------------------------------- | --------------- | -------------------- |
| `h11`, before changes              | 36 414          | -                    |
| `h11`, after changes, pure Python  | 37 409          | +2%                  |
| `h11`, after changes and compiled  | 58 983          | **+62%**             |

So the version with our changes didn't get slower (+2% is within the noise of the benchmark). But compilation gave a decent boost. No, it's not the clickbait 2x, but it's still quite noticeable.

I think we can wrap up here with an interim conclusion: compilation gives a real gain, but it requires careful typing and an understanding of how mypyc-compiled code behaves. As a proof of concept, I forked the h11 repository and published a Python package so I can play with optimizations even more:
- [the fork's code](https://github.com/danfimov/h11) (you can easily check the diff against the upstream code there)
- [h11-mypyc package on PyPI](https://pypi.org/project/h11-mypyc/)

In fact, a 2x gain can be reached with additional code optimizations and a careful look at cProfile/memray output. So if the article gets a good response, I'm planning to write a second part dedicated to exactly that.
