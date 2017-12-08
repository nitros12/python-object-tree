from typing import Dict, List


def something(a: int, b: List[int]) -> str:
    return "blah"


class A:
    def __init__(self, a: int):
        self.x = a
        self.c = "hello"
        self.n: int = somefunction_we_cant_see()


class B(A):
    def wot(self, a: int) -> int:
        pass


class C(A):
    def wow(self, b: str) -> str:
        pass


class D(B, C):
    def amazing(self) -> str:
        return self.c
