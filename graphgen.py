import ast
import inspect
from importlib import import_module
from itertools import chain
from types import FunctionType
from typing import Dict, List, Optional, Tuple, Type, Union


class PythonClass:
    def __init__(self, name: str, parents: List[Union['PythonClass', str]],
                 attrs: List['PythonAttr'], methods: List['PythonMethod']):
        self.name = name
        self.parents = parents
        self.attrs = attrs
        self.methods = methods

    @staticmethod
    def build_body(obj) -> List['PythonAttr']:
        module = inspect.getmodule(obj)
        lines, _ = inspect.getsourcelines(obj)
        indent = len(lines[0]) - len(lines[0].lstrip())
        lines = [line[indent:] for line in lines]
        fn_body = ast.parse("".join(lines)).body[0].body  # the function body we just parsed
        return list(chain.from_iterable(PythonAttr.from_ast(i, module) for i in fn_body if PythonAttr.valid_ast(i)))

    @classmethod
    def from_object(cls, obj: type):

        def predicate(obj):
            return isinstance(obj, FunctionType) and not obj.__name__.startswith("_")

        return cls(obj.__name__,
                   [c.__qualname__ for c in obj.mro()[1:]],  # get names of classes XXX: name or qualname?
                   cls.build_body(obj.__init__),
                   [PythonMethod.from_object(x) for x, _ in inspect.getmembers(obj, predicate)])


class PythonMethod:
    def __init__(self, name: str, args: List[Tuple[str, Type]], returns: Type):
        self.name = name
        self.args = args
        self.returns = returns

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
            return (obj.id)
        if isinstance(obj, ast.Attribute):
            return cls.attr_access_path(obj.value)

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
    def find_type(cls, typ: ast.AST, obj: type):
        """Find the type of an ast object as a typing object. Returns None if cannot be found."""
        if isinstance(typ, ast.Num):
            return type(typ.n)
        if isinstance(typ, ast.Str):
            return str
        if isinstance(typ, ast.Tuple):
            return Tuple[(cls.find_type(i, obj) for i in typ.elts)]
        if isinstance(typ, ast.List):
            return List[(cls.find_type(i, obj) for i in typ.elts)]
        if isinstance(typ, ast.Call):
            obj = cls.find_attr(inspect.getmodule(obj), obj)
            try:
                name = typ.func.id
                print(f"module = {inspect.getmodule(obj)}, name = {name}")
                val = getattr(obj, name)
                return val.__annotations__.get("return")
            except AttributeError:
                print("m")
                return None

    @classmethod
    def from_ast(cls, syntax: Union[_valid_types], module, klass) -> 'PythonAttr':
        def check_self_attr(obj):
            return isinstance(obj, ast.Attribute) and isinstance(obj.ctx, ast.Store) and (obj.value.id == "self")

        def helper(var, value):
            if isinstance(var, (ast.Tuple, ast.List)):
                if isinstance(value, (ast.Tuple, ast.List)):  # tuple assign, easy
                    values = value.elts
                elif isinstance(value, ast.Call):
                    try:
                        name = value.func.id
                        val = getattr(module, name)
                        values = val.__annotations__.get("return")
                    except AttributeError:
                        print("w")
                        values = None
                else:
                    values = None
                if not isinstance(values, (Tuple, List)):
                    values = [None] * len(var.elts)
                yield from chain.from_iterable(map(helper, var.elts, values))
                return
            if check_self_attr(var):
                yield cls(var.attr, cls.find_type(value, module))

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

    for _, obj in inspect.getmembers(module):
        r = build_for_object(obj)
        if r is not None:
            yield r
