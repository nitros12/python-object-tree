import sys
import ast
import inspect
import typing
from itertools import chain
from types import FunctionType
from typing import Any, Callable, Dict, List, Optional, Tuple, Type, Union


namespace = globals()


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
    def __init__(self, obj: object, name: str,
                 parents: List[Union['PythonClass', str]],
                 methods: List['PythonMethod']):
        self.obj = obj
        self.name = name
        self.parents = parents
        self.attrs = self.build_body(self.obj.__init__)
        self.methods = methods

    def build_body(self, obj) -> List['PythonAttr']:
        try:
            lines, _ = inspect.getsourcelines(obj)
            indent = len(lines[0]) - len(lines[0].lstrip())
            lines = [line[indent:] for line in lines]
            fn_body = ast.parse("".join(lines)).body[0].body  # the function body we just parsed
            return list(chain.from_iterable(PythonAttr.from_ast(i, self.obj, obj)
                                            for i in fn_body if PythonAttr.valid_ast(i)))
        except TypeError:
            return ()
        except OSError:
            pass  # maybe not good

        if hasattr(obj, "__annotations__"):
            types = typing.get_type_hints(obj, namespace)
            return [PythonAttr(k, v) for k, v in types.items()]
        return ()


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
                   [PythonMethod(x) for _, x in inspect.getmembers(obj, predicate)]
        )


class PythonMethod:
    def __init__(self, fun: object):
        self.name = fun.__name__
        types = typing.get_type_hints(fun, namespace)
        returns = types.get("return")
        signature = inspect.signature(fun)

        args = list(signature.parameters.items())
        resolved_args = [types.get(t.name) for _, t in args]

        self.signature = inspect.Signature((t.replace(annotation=r)
                                            if r is not None
                                            else t
                                            for (n, t), r in zip(args, resolved_args)), return_annotation=returns)

    def __str__(self):
        if show_type_info:
            return f"fn {self.name}{self.signature}"

        args = ", ".join(self.signature.parameters)
        return f"fn {self.name}({args})"


class PythonAttr:
    def __init__(self, name: str, type: Type):
        self.name = name
        self.type = type
        self.type_show = inspect.formatannotation(type)

    def __str__(self):
        return (f"{self.name}:{self.type_show}"
                if self.type and show_type_info
                else self.name)

    __repr__ = __str__

    _valid_types = (ast.Assign, ast.AnnAssign)

    @classmethod
    def valid_ast(cls, obj: ast.AST) -> bool:
        return isinstance(obj, cls._valid_types)

    @classmethod
    def attr_access_path(cls, obj: Union[ast.Name, ast.Attribute]) -> Tuple[str]:
        if isinstance(obj, ast.Name):
            return (obj.id,)
        if isinstance(obj, ast.Attribute):
            path = cls.attr_access_path(obj.value)
            if path is not None:
                return path + (obj.attr,)

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
        """Find the type of an ast object as a typing object.
        Returns None if cannot be found."""
        if isinstance(typ, ast.Num):
            return type(typ.n)
        if isinstance(typ, ast.Str):
            return str
        if isinstance(typ, ast.Tuple):
            return Tuple[tuple(cls.find_type(i, klass, fn) for i in typ.elts)]
        if isinstance(typ, ast.List):
            types = tuple(cls.find_type(i, klass, fn) for i in typ.elts)
            return List[Union[types] if types else Any]
        if isinstance(typ, ast.Attribute):
            path = cls.attr_access_path(typ)
            if path is None:  # if err == nil: return err
                return None
            obj = cls.find_attr(path, inspect.getmodule(klass), klass)
            return type(obj)
        if isinstance(typ, ast.Call):
            path = cls.attr_access_path(typ.func)
            if path is None:
                return None
            obj = cls.find_attr(path, inspect.getmodule(klass), klass)
            if obj is None:
                return None
            return typing.get_type_hints(obj, namespace).get("return")
        if isinstance(typ, ast.Name):  # look at function params first
            obj = typing.get_type_hints(fn, namespace).get(typ.id)
            if obj is None:
                obj = cls.find_attr((typ.id,), inspect.getmodule(klass), klass)
            return cls.find_type(obj, klass, fn)
        if isinstance(typ, ast.IfExp):
            return Union[cls.find_type(typ.body, klass, fn),
                         cls.find_type(typ.orelse, klass, fn)]
        if isinstance(typ, ast.NameConstant):
            return type(typ.value) if typ.value is not None else None
        if isinstance(typ, ast.Dict):
            keys = tuple(cls.find_type(i, klass, fn) for i in typ.keys)
            values = tuple(cls.find_type(i, klass, fn) for i in typ.values)
            return Dict[Union[keys] if keys else Any,
                        Union[values] if values else Any]
        if isinstance(typ, ast.Set):
            values = tuple(cls.find_type(i, klass, fn) for i in typ.elts)
        if isinstance(typ, FunctionType):
            sig = inspect.signature(typ)
            return Callable[[t.annotation for t in sig.parameters.values()], sig.return_annotation]
        if isinstance(typ, typing._ForwardRef):
            return typ.__forward_value__
        if isinstance(typ, ast.AST):
            return None
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
                if isinstance(values, typing.TupleMeta):
                    values = values.__args__  # pylint: disable=protected-access
                elif not isinstance(values, (tuple, list)):
                    values = [None] * len(var.elts)
                yield from chain.from_iterable(map(helper, var.elts, values))
                return
            if check_self_attr(var):
                yield cls(var.attr, cls.find_type(value, klass, fn))

        if isinstance(syntax, ast.Assign):
            yield from chain.from_iterable(helper(i, syntax.value) for i in syntax.targets)
        if isinstance(syntax, ast.AnnAssign):
            if check_self_attr(syntax.target):
                ob = eval(compile(ast.Expression(syntax.annotation), "<hint>", "eval"),
                          globals(),
                          namespace
                )  # pylint: disable=eval-used
                yield cls(syntax.target.attr, ob)


def build_for_object(obj: type, tovisit: List[object]):
    if inspect.isclass(obj):
        tovisit.extend(obj.__bases__)
        return PythonClass.from_object(obj)
    if inspect.isfunction(obj):
        return PythonMethod(obj)


def getname(obj: object):
    name = getattr(obj, "__qualname__", None)
    if name:
        return name

    name = getattr(obj, "__name__", None)
    if name:
        return name

    return obj.__class__.__name__


def build_for_module(mod, names: dict=None, has_type_info=False):
    if names:
        global namespace
        namespace.update(names)

    #  nicer to just globalise than pass everywhere
    global show_type_info
    show_type_info = has_type_info

    name = mod.__name__
    visited = []
    tovisit = []

    module_name = name.split(".")[0]

    def predicate(obj):
        return hasattr(obj, "__module__") and obj.__module__.startswith(module_name)

    tovisit.extend(obj for _, obj in inspect.getmembers(mod, predicate))

    while tovisit:
        obj = tovisit.pop()

        if getname(obj) in visited:
            continue

        r = build_for_object(obj, tovisit)
        if r is not None:
            visited.append(r.name)
            yield r
