import ast
import inspect
from importlib import import_module
from itertools import chain
from types import FunctionType
from typing import Dict, List, Optional, Tuple, Type, Union


def escape_xml(s: str):
    replacements = (("<", "&lt;"),
                    (">", "&gt;"),
                    ('"', r'\"'),
                    ("'", r"\'"))
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
        attrs = escape_xml("\l".join(map(str, self.attrs)))
        methods = escape_xml("\l".join(map(str, self.methods)))
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
    def __init__(self, name: str, args: List[Tuple[str, Type]], returns: Type):
        self.name = name
        self.args = args
        self.returns = returns

    def __str__(self):
        pargs = ", ".join(str(b) for _, b in self.args)
        print(type(self.returns))
        if self.returns is inspect.Signature.empty or self.returns is None:
            return_ = ""
        else:
            return_ = f" -> {self.returns}"
        return f"fn {self.name}({pargs}){return_}"

    @property
    def info(self):
        return str(self)

    @classmethod
    def from_object(cls, obj: type):
        signature = inspect.signature(obj)
        return cls(obj.__name__, list(signature.parameters.items()), signature.return_annotation)


class PythonAttr:
    def __init__(self, name: str, type: Type):
        self.name = name
        self.type = type

    def __str__(self):
        return f"{self.name}:{self.type}"

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
    def find_type(cls, typ: ast.AST, klass, fn):
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
            return obj.__annotations__.get("return")
        if isinstance(typ, ast.Name):  # look at function params first
            obj = fn.__annotations__.get(typ.id)
            if obj is None:
                obj = cls.find_attr((typ.id,), inspect.getmodule(klass), klass)
            return obj

    @classmethod
    def from_ast(cls, syntax: Union[_valid_types], klass, fn) -> 'PythonAttr':
        def check_self_attr(obj):
            return isinstance(obj, ast.Attribute) and isinstance(obj.ctx, ast.Store) and (obj.value.id == "self")

        def helper(var, value):
            if isinstance(var, (ast.Tuple, ast.List)):
                if isinstance(value, (ast.Tuple, ast.List)):  # tuple assign, easy
                    values = value.elts
                else:
                    values = cls.find_type(value.func, klass, fn)
                if not isinstance(values, (Tuple, List)):
                    values = [None] * len(var.elts)
                yield from chain.from_iterable(map(helper, var.elts, values))
                return
            if check_self_attr(var):
                yield cls(var.attr, cls.find_type(value, klass, fn))

        if isinstance(syntax, ast.Assign):
            yield from chain.from_iterable(helper(i, syntax.value) for i in syntax.targets)
        if isinstance(syntax, ast.AnnAssign):
            if check_self_attr(syntax.target):
                yield cls(syntax.target.attr, syntax.annotation.id)


def build_for_object(obj: type):
    if inspect.isclass(obj):
        return PythonClass.from_object(obj)
    if inspect.isfunction(obj):
        return PythonMethod.from_object(obj)


def build_for_module(name: str):
    module = import_module(name)

    def predicate(obj):
        return hasattr(obj, "__module__") and obj.__module__ == name

    for _, obj in inspect.getmembers(module, predicate):
        r = build_for_object(obj)
        if r is not None:
            yield r
