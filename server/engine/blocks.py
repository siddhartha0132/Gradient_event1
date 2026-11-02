"""Block modules: compile Blockly layouts to Python and enforce the round's block rules.

A team's agent is hand-written code (which must define strategy) plus up to N
block modules. Each module is one Blockly workspace holding a single
"module" block, which becomes

    def <name>(my_history, opp_history):
        ...

The server generates the Python itself from the stored layout and never trusts
code sent by the client, so the block limits cannot be bypassed by a modified
client. The assembled code then goes through the normal sandbox checks.
"""

import ast
import builtins
import keyword
import math
import re
from dataclasses import dataclass, field

from .sandbox import BANNED_NAMES, SAFE_BUILTINS, validate_code

# Block type -> category. "core" blocks are always available.
BLOCK_CATEGORIES = {
    "ic_module": "core",
    "ic_return": "core",
    "ic_move": "core",
    "controls_if": "logic",
    "controls_ifelse": "logic",
    "logic_compare": "logic",
    "logic_operation": "logic",
    "logic_negate": "logic",
    "logic_boolean": "logic",
    "ic_last_move": "history",
    "ic_count": "history",
    "ic_turn": "history",
    "ic_first_turn": "history",
    "math_number": "math",
    "math_arithmetic": "math",
    "ic_chance": "chance",
    "ic_random": "chance",
}
CATEGORIES = ("logic", "history", "math", "chance")

MAX_DEPTH = 60  # nesting, so a crafted layout cannot exhaust the recursion limit
MAX_BLOCKS_PARSED = 400  # hard cap per module whatever the round allows
MAX_COUNT_WINDOW = 1000

NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,30}$")
RESERVED = ({"strategy", "random", "math", "my_history", "opp_history"} | BANNED_NAMES
            | set(SAFE_BUILTINS) | set(dir(builtins)))

HISTORY = {"opp": "opp_history", "me": "my_history"}
COMPARE = {"EQ": "==", "NEQ": "!=", "LT": "<", "LTE": "<=", "GT": ">", "GTE": ">="}
ARITHMETIC = {"ADD": "+", "MINUS": "-", "MULTIPLY": "*", "DIVIDE": "/", "POWER": "**"}
BOOLEAN_OPS = {"AND": "and", "OR": "or"}
MOVES = {"C", "D"}


@dataclass
class BlockRules:
    max_modules: int
    max_blocks: int
    categories: list[str] = field(default_factory=lambda: list(CATEGORIES))


@dataclass
class BuildError:
    message: str
    module: int | None = None  # index of the module, or None for the agent as a whole
    line: int | None = None  # line in the hand-written code
    kind: str = "blocks"  # "blocks" (block rules, refused at submit) or "code" (sandbox checks)


@dataclass
class Module:
    name: str
    layout: dict
    code: str
    blocks: int


@dataclass
class Build:
    errors: list[BuildError]
    modules: list[Module]  # the modules that compiled
    assembled: str
    by_index: list[Module | None] = field(default_factory=list)  # aligned with the layouts given


class BlockError(Exception):
    pass


# --- Reading a layout ----------------------------------------------------------

def _top_blocks(layout) -> list[dict]:
    if not isinstance(layout, dict):
        raise BlockError("The module layout is not valid")
    blocks = layout.get("blocks", {})
    top = blocks.get("blocks", []) if isinstance(blocks, dict) else None
    if not isinstance(top, list) or not all(isinstance(b, dict) for b in top):
        raise BlockError("The module layout is not valid")
    return top


def _children(block: dict) -> list[dict]:
    """Every block directly attached to this one: inputs (blocks and shadows) and the next block."""
    found = []
    inputs = block.get("inputs") or {}
    if not isinstance(inputs, dict):
        raise BlockError("The module layout is not valid")
    for slot in inputs.values():
        if isinstance(slot, dict):
            found += [slot[k] for k in ("block", "shadow") if isinstance(slot.get(k), dict)]
    nxt = block.get("next")
    if isinstance(nxt, dict):
        found += [nxt[k] for k in ("block", "shadow") if isinstance(nxt.get(k), dict)]
    return found


def _walk(block: dict, depth: int = 0):
    if depth > MAX_DEPTH:
        raise BlockError("Blocks are nested too deeply")
    yield block
    for child in _children(block):
        yield from _walk(child, depth + 1)


def count_blocks(layout) -> int:
    """Every block in the workspace, loose ones included."""
    total = 0
    for top in _top_blocks(layout):
        for _ in _walk(top):
            total += 1
            if total > MAX_BLOCKS_PARSED:
                raise BlockError(f"A module may never have more than {MAX_BLOCKS_PARSED} blocks")
    return total


def block_types(layout) -> set[str]:
    return {b.get("type") for top in _top_blocks(layout) for b in _walk(top)}


def module_name(layout) -> str | None:
    top = _top_blocks(layout)
    if len(top) == 1 and top[0].get("type") == "ic_module":
        name = (top[0].get("fields") or {}).get("NAME")
        return name if isinstance(name, str) else None
    return None


# --- Generating Python ---------------------------------------------------------

_LABELS = {
    "ic_return": "return", "controls_if": "if", "controls_ifelse": "if / else", "logic_compare": "compare",
    "logic_operation": "and / or", "logic_negate": "not", "math_arithmetic": "arithmetic",
}


def _field(block: dict, name: str):
    return (block.get("fields") or {}).get(name)


def _input(block: dict, name: str) -> dict | None:
    slot = (block.get("inputs") or {}).get(name)
    if not isinstance(slot, dict):
        return None
    return slot.get("block") if isinstance(slot.get("block"), dict) else slot.get("shadow")


def _required(block: dict, name: str, depth: int) -> str:
    child = _input(block, name)
    if child is None:
        label = _LABELS.get(block.get("type"), block.get("type"))
        raise BlockError(f"The '{label}' block has an empty slot")
    return _value(child, depth + 1)


def _choice(block: dict, name: str, options) -> str:
    value = _field(block, name)
    if value not in options:
        raise BlockError(f"The '{block.get('type')}' block has an invalid {name.lower()}")
    return value


def _number(block: dict, name: str, low: float, high: float) -> float:
    value = _field(block, name)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise BlockError(f"The '{block.get('type')}' block needs a number")
    if not low <= value <= high:
        raise BlockError(f"The '{block.get('type')}' block needs a number between {low:g} and {high:g}")
    return value


def _literal(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else repr(float(value))


def _value(block: dict, depth: int) -> str:
    if depth > MAX_DEPTH:
        raise BlockError("Blocks are nested too deeply")
    t = block.get("type")
    if t == "ic_move":
        return f'"{_choice(block, "MOVE", MOVES)}"'
    if t == "ic_last_move":
        h = HISTORY[_choice(block, "WHO", HISTORY)]
        return f'({h}[-1] if {h} else "")'
    if t == "ic_count":
        h = HISTORY[_choice(block, "WHO", HISTORY)]
        move = _choice(block, "MOVE", MOVES)
        last = int(_number(block, "LAST", 0, MAX_COUNT_WINDOW))
        return f'{h}.count("{move}")' if last == 0 else f'{h}[-{last}:].count("{move}")'
    if t == "ic_turn":
        return "len(my_history)"
    if t == "ic_first_turn":
        return "(len(my_history) == 0)"
    if t == "ic_chance":
        return f"(random.random() < {_literal(_number(block, 'PERCENT', 0, 100) / 100)})"
    if t == "ic_random":
        return "random.random()"
    if t == "math_number":
        return _literal(_number(block, "NUM", -1e9, 1e9))
    if t == "math_arithmetic":
        op = ARITHMETIC[_choice(block, "OP", ARITHMETIC)]
        return f"({_required(block, 'A', depth)} {op} {_required(block, 'B', depth)})"
    if t == "logic_compare":
        op = COMPARE[_choice(block, "OP", COMPARE)]
        return f"({_required(block, 'A', depth)} {op} {_required(block, 'B', depth)})"
    if t == "logic_operation":
        op = BOOLEAN_OPS[_choice(block, "OP", BOOLEAN_OPS)]
        return f"({_required(block, 'A', depth)} {op} {_required(block, 'B', depth)})"
    if t == "logic_negate":
        return f"(not {_required(block, 'BOOL', depth)})"
    if t == "logic_boolean":
        return "True" if _choice(block, "BOOL", {"TRUE", "FALSE"}) == "TRUE" else "False"
    raise BlockError(f"The '{t}' block cannot be used as a value")


def _statements(block: dict | None, indent: int, depth: int) -> list[str]:
    """A chain of statement blocks, following each block's next connection."""
    lines = []
    pad = "    " * indent
    while block is not None:
        if depth > MAX_DEPTH:
            raise BlockError("Blocks are nested too deeply")
        t = block.get("type")
        if t == "ic_return":
            lines.append(f"{pad}return {_required(block, 'VALUE', depth)}")
        elif t in ("controls_if", "controls_ifelse"):
            state = block.get("extraState") or {}
            if not isinstance(state, dict):
                raise BlockError("The 'if' block is not valid")
            branches = state.get("elseIfCount", 0)
            has_else = state.get("hasElse", t == "controls_ifelse")
            if not isinstance(branches, int) or not 0 <= branches <= 20:
                raise BlockError("The 'if' block is not valid")
            for i in range(branches + 1):
                keyword_ = "if" if i == 0 else "elif"
                lines.append(f"{pad}{keyword_} {_required(block, f'IF{i}', depth)}:")
                lines += _statements(_input(block, f"DO{i}"), indent + 1, depth + 1) or [f"{pad}    pass"]
            if has_else:
                lines.append(f"{pad}else:")
                lines += _statements(_input(block, "ELSE"), indent + 1, depth + 1) or [f"{pad}    pass"]
        else:
            raise BlockError(f"The '{t}' block cannot be used as a statement")
        nxt = block.get("next")
        block = nxt.get("block") if isinstance(nxt, dict) else None
        depth += 1
    return lines


def compile_module(layout) -> tuple[str, str]:
    """Returns (name, Python code) for one module layout, or raises BlockError."""
    top = _top_blocks(layout)
    modules = [b for b in top if b.get("type") == "ic_module"]
    if len(modules) != 1:
        raise BlockError("A module needs exactly one 'module' block")
    if len(top) > 1:
        raise BlockError("Loose blocks are not attached to the module. Attach them or delete them")
    name = _field(modules[0], "NAME")
    if not isinstance(name, str) or not NAME_PATTERN.match(name) or keyword.iskeyword(name):
        raise BlockError("Module names use lowercase letters, digits and _, and start with a letter")
    if name in RESERVED:
        raise BlockError(f"'{name}' is a reserved name. Pick another module name")
    body = _statements(_input(modules[0], "BODY"), 1, 1) or ["    return None"]
    return name, "\n".join([f"def {name}(my_history, opp_history):", *body]) + "\n"


# --- Checking a whole agent ----------------------------------------------------

def check_rules(layouts: list, rules: BlockRules) -> list[BuildError]:
    """Only the round's limits: how many modules, how many blocks, which categories."""
    errors = []
    if len(layouts) > rules.max_modules:
        errors.append(BuildError(f"This round allows at most {rules.max_modules} block module(s), "
                                 f"you have {len(layouts)}"))
    allowed = set(rules.categories) | {"core"}
    for i, layout in enumerate(layouts):
        try:
            blocks = count_blocks(layout)
            types = block_types(layout)
        except BlockError as e:
            errors.append(BuildError(str(e), module=i))
            continue
        if blocks > rules.max_blocks:
            errors.append(BuildError(f"{blocks} blocks, but this round allows {rules.max_blocks} per module", module=i))
        unknown = sorted(str(t) for t in types if t not in BLOCK_CATEGORIES)
        if unknown:
            errors.append(BuildError(f"Unknown block type(s): {', '.join(unknown)}", module=i))
        banned = sorted({BLOCK_CATEGORIES[t] for t in types if t in BLOCK_CATEGORIES} - allowed)
        if banned:
            errors.append(BuildError(f"Blocks from {', '.join(banned)} are not allowed this round", module=i))
    return errors


def _defined_names(code: str) -> set[str]:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return set()
    names = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            names |= {t.id for t in targets if isinstance(t, ast.Name)}
    return names


def build_agent(hand_code: str, layouts: list, rules: BlockRules) -> Build:
    """Check and assemble a team's agent: hand-written code plus block modules.

    Errors on the hand-written code carry its line numbers, which stay valid in
    the assembled code because the modules are appended after it.
    """
    errors = check_rules(layouts, rules)
    by_index: list[Module | None] = []
    for i, layout in enumerate(layouts):
        by_index.append(None)
        try:
            name, code = compile_module(layout)
            tree = ast.parse(code)
            # The spec's rule: a module's code is exactly one function with the module's name
            if len(tree.body) != 1 or not isinstance(tree.body[0], ast.FunctionDef) or tree.body[0].name != name:
                raise BlockError("The module did not compile to a single function")
            by_index[i] = Module(name=name, layout=layout, code=code, blocks=count_blocks(layout))
        except BlockError as e:
            errors.append(BuildError(str(e), module=i))

    modules = [m for m in by_index if m is not None]
    names = [m.name if m else None for m in by_index]
    for name in {n for n in names if n and names.count(n) > 1}:
        errors.append(BuildError(f"Two modules are called '{name}'", module=len(names) - 1 - names[::-1].index(name)))
    for name in sorted(_defined_names(hand_code) & {n for n in names if n}):
        errors.append(BuildError(f"Your code also defines '{name}'. Rename the module or your code",
                                 module=names.index(name)))

    for message in validate_code(hand_code):
        found = re.search(r"line (\d+)", message, re.IGNORECASE)
        errors.append(BuildError(message, line=int(found.group(1)) if found else None, kind="code"))

    assembled = hand_code
    if modules:
        header = "# --- Block modules, generated by the server ---\n"
        if any("random." in m.code for m in modules):
            header += "import random\n"
        assembled = hand_code.rstrip() + "\n\n\n" + header + "\n\n".join(m.code for m in modules)
    return Build(errors=errors, modules=modules, assembled=assembled, by_index=by_index)
