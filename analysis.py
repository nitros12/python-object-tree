import ast
import inspect
import typing
from importlib import import_module
from itertools import chain
from types import FunctionType
from typing import Callable, List, Optional, Tuple, Type, Union


def escape_xml(s: str):
    replacements = (("<", "&lt;"),
                    (">", "&gt;"),
                    ('"', r'\"'),
                    ("'", r"\'"),
                    ("[", r"\["),
                    ("]", r"\]"))
    for a, b in replacements:
        s = s.replace(a, b)
    return s


class PythonClass:
    def __init__(self, obj: object, name: str, parents: List[Union['PythonClass', str]], methods: List['PythonMethod']):
        self.obj = obj
        self.name = name
        self.parents = parents
        self.attrs = self.build_body(self.obj.__init__)
        self.methods = methods

    @property
    def info(self):
        attrs = escape_xml(r"\l".join(map(str, self.attrs)) + r"\l")
        methods = r"\l".join(map(str, self.methods)) + r"\l"
        return "{" + f"{self.name} | {attrs} | {methods}" + "}"

    def build_body(self, obj) -> List['PythonAttr']:
        try:
            lines, _ = inspect.getsourcelines(obj)
        except TypeError:
            return ()
        indent = len(lines[0]) - len(lines[0].lstrip())
        lines = [line[indent:] for line in lines]
        fn_body = ast.parse("".join(lines)).body[0].body  # the function body we just parsed
        return list(chain.from_iterable(PythonAttr.from_ast(i, self.obj, obj) for i in fn_body if PythonAttr.valid_ast(i)))

    @classmethod
    def from_object(cls, obj: type):

        def predicate(obj):
            if not isinstance(obj, FunctionType):
                return False

            if obj.__name__ == "__init__":
                return True  # allow constructor

            return not obj.__name__.startswith("_")

        return cls(obj, obj.__name__,
                   [c.__qualname__ for c in obj.__bases__],  # get names of classes XXX: name or qualname?
                   [PythonMethod.from_object(x) for _, x in inspect.getmembers(obj, predicate)])


class PythonMethod:
    def __init__(self, name: str, signature: inspect.Signature):
        self.name = name
        self.args = list(signature.parameters.items())
        self.returns = signature.return_annotation
        self.signature = signature

    def __str__(self):
        return escape_xml(f"fn {self.name}{self.signature}")

    @property
    def info(self):
        return str(self)

    @classmethod
    def from_object(cls, obj: type):
        signature = inspect.signature(obj)
        return cls(obj.__name__, signature)


class PythonAttr:
    def __init__(self, name: str, type: Type):
        self.name = name
        self.type = type
        self.type_show = inspect.formatannotation(type)

    def __str__(self):
        return f"{self.name}:{self.type_show}" if self.type else self.name

    __repr__ = __str__

    _valid_types = (ast.Assign, ast.AnnAssign)

    @classmethod
    def valid_ast(cls, obj: ast.AST) -> bool:
        return isinstance(obj, cls._valid_types)

    @classmethod
    def attr_access_path(cls, obj: ast.AST) -> Tuple[str]:
        if isinstance(obj, ast.Name):
            return (obj.id,)
        if isinstance(obj, ast.Attribute):
            return cls.attr_access_path(obj.value) + (obj.attr,)

    @classmethod
    def find_attr(cls, path: Tuple[str], module: object, base: object) -> Optional[type]:
        first, *rest = path
        if first == "self":
            return cls.find_attr(rest, base, base)
        obj = getattr(module, first, None)
        for attr in rest:
            obj = getattr(obj, attr, None)
        return obj

    @classmethod
    def find_type(cls, typ: Union[ast.AST, type], klass, fn):
        """Find the type of an ast object as a typing object. Returns None if cannot be found."""
        if isinstance(typ, ast.Num):
            return type(typ.n)
        if isinstance(typ, ast.Str):
            return str
        if isinstance(typ, ast.Tuple):
            return Tuple[tuple(cls.find_type(i, klass, fn) for i in typ.elts)]
        if isinstance(typ, ast.List):
            return List[tuple(cls.find_type(i, klass, fn) for i in typ.elts)]
        if isinstance(typ, ast.Call):
            obj = cls.find_attr(cls.attr_access_path(typ.func),
                                inspect.getmodule(klass), klass)
            return getattr(obj, "__annotations__", {}).get("return")
        if isinstance(typ, ast.Name):  # look at function params first
            obj = fn.__annotations__.get(typ.id)
            if obj is None:
                obj = cls.find_attr((typ.id,), inspect.getmodule(klass), klass)
            return cls.find_type(obj, klass, fn)
        if isinstance(typ, FunctionType):
            sig = inspect.signature(typ)
            return Callable[[t.annotation for t in sig.parameters.values()], sig.return_annotation]
        return typ

    @classmethod
    def from_ast(cls, syntax: Union[_valid_types], klass, fn) -> 'PythonAttr':
        def check_self_attr(obj):
            return (isinstance(obj, ast.Attribute) and isinstance(obj.ctx, ast.Store)
                    and isinstance(obj.value, ast.Name) and (obj.value.id == "self"))

        def helper(var, value):
            if isinstance(var, (ast.Tuple, ast.List)):
                if isinstance(value, (ast.Tuple, ast.List)):  # tuple assign, easy
                    values = value.elts
                else:
                    values = cls.find_type(value, klass, fn)
                if isinstance(values, typing.GenericMeta):
                    values = values._subs_tree()[1:]  # pylint: disable=protected-access
                if not isinstance(values, (tuple, list)):
                    values = [None] * len(var.elts)
                yield from chain.from_iterable(map(helper, var.elts, values))
                return
            if check_self_attr(var):
                yield cls(var.attr, cls.find_type(value, klass, fn))

        if isinstance(syntax, ast.Assign):
            yield from chain.from_iterable(helper(i, syntax.value) for i in syntax.targets)
        if isinstance(syntax, ast.AnnAssign):
            if check_self_attr(syntax.target):
                yield cls(syntax.target.attr, type(syntax.annotation.id))


def build_for_object(obj: type, tovisit: List[object]):
    if inspect.isclass(obj):
        tovisit.extend(obj.__bases__)
        return PythonClass.from_object(obj)
    if inspect.isfunction(obj):
        return PythonMethod.from_object(obj)


def getname(obj: object):
    name = getattr(obj, "__qualname__", None)
    if name:
        return name

    name = getattr(obj, "__name__", None)
    if name:
        return name

    return obj.__class__.__name__


def build_for_module(name: str):
    module = import_module(name)

    visited = []
    tovisit = []

    def predicate(obj):
        return hasattr(obj, "__module__") and obj.__module__.startswith(name)

    tovisit.extend(obj for _, obj in inspect.getmembers(module, predicate))

    while tovisit:
        obj = tovisit.pop()

        if getname(obj) in visited:
            continue

        r = build_for_object(obj, tovisit)
        if r is not None:
            visited.append(r.name)
            yield r
