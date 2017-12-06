import ast
import inspect
from importlib import import_module
from itertools import chain
from types import FunctionType
from typing import Dict, List, Tuple, Type, Union


class PythonClass:
    def __init__(self, name: str, parents: List[Union[PythonClass, str]],
                 attrs: List['PythonAttr'], methods: List['PythonMethod']):
        self.name = name
        self.parents = parents
        self.attrs = attrs
        self.methods = methods

    @staticmethod
    def build_body(obj) -> List['PythonAttr']:
        lines, _ = inspect.getsourcelines(obj)
        indent = len(lines[0]) - len(lines[0].lstrip())
        lines = [line[indent:] for line in lines]
        fn_body = ast.parse("".join(lines)).body[0]  # the function body we just parsed
        return chain.from_iterable(PythonAttr.from_ast(i) for i in fn_body if PythonAttr.valid_ast(i))

    @classmethod
    def from_object(cls, obj: type):

        def predicate(obj):
            return isinstance(obj, FunctionType) and not obj.__name__.startswith("_")

        return cls(obj.__name__,
                   map(lambda cls: cls.__qualname__, obj.mro()[1:]),  # get names of classes XXX: name or qualname?
                   cls.build_body(obj.__main__),
                   [PythonMethod.from_object(x) for x, _ in inspect.getmembers(obj, predicate)])


class PythonMethod:
    def __init__(self, name: str, args: List[Tuple[str, Type]], returns: Type):
        self.name = name
        self.args = args
        self.returns = returns

    # TODO: me


class PythonAttr:
    def __init__(self, name: str, type: Type):
        self.name = name
        self.type = type

    _valid_types = (ast.Assign, ast.AnnAssign)

    @classmethod
    def valid_ast(cls, obj: ast.AST) -> Bool:
        return isinstance(obj, cls._valid_types)

    @classmethod
    def find_type(cls, typ: ast.AST):
        """Find the type of an ast object as a typing object. Returns None if cannot be found."""
        if isinstance(typ, ast.Num):
            return type(typ.n)
        if isinstance(typ, ast.Str):
            return str
        if isinstance(typ, ast.Tuple):
            return Tuple[map(cls.find_type, typ.elts)]
        if isinstance(typ, ast.List):
            return List[map(cls.find_type, typ.elts)]
        return None  # cannot determine

    @classmethod
    def from_ast(cls, obj: Union[_valid_types]) -> 'PythonAttr':
        def helper(var, value):
            if isinstance(var, (ast.Tuple, ast.List)):
                if isinstance(value, (ast.Tuple, ast.List)):  # tuple assign, easy
                    values = value.elts
                else:  # give up
                    values = [None] * len(var.elts)
                return map(helper, var.elts, values)
            return cls(var.id, cls.find_type(value))

        if isinstance(obj, ast.Assign):
            return (helper(i, obj.value) for i in obj.targets)
        if isinstance(obj, ast.AnnAssign):
            return (cls(obj.target.id, obj.annotation.id),)


def build_for_object(obj: type):
    if inspect.isclass(obj):
        return PythonClass.from_object(obj)
    if inspect.isfunction(obj):
        return PythonMethod.from_object(obj)


def build_for_module(name: str):
    module = import_module(name)

    for name, obj in inspect.getmembers(module):
        if inspect.isclass(obj):
            # TODO: what was supposed to go here again?
