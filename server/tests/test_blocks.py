from engine.blocks import BlockRules, build_agent, compile_module, count_blocks
from engine.sandbox import load_bot

ALL = BlockRules(max_modules=3, max_blocks=30)


def block(type_, fields=None, **inputs):
    b = {"type": type_}
    if fields:
        b["fields"] = fields
    if inputs:
        b["inputs"] = {k: {"block": v} for k, v in inputs.items()}
    return b


def module(name, body):
    return {"blocks": {"languageVersion": 0, "blocks": [block("ic_module", {"NAME": name}, BODY=body)]}}


def move(m):
    return block("ic_move", {"MOVE": m})


# "If the opponent defected more than twice in their last 10 moves, defect, else cooperate"
ANGRY = module("is_angry", {
    "type": "controls_if",
    "extraState": {"hasElse": True},
    "inputs": {
        "IF0": {"block": block("logic_compare", {"OP": "GT"},
                               A=block("ic_count", {"WHO": "opp", "MOVE": "D", "LAST": 10}),
                               B=block("math_number", {"NUM": 2}))},
        "DO0": {"block": block("ic_return", VALUE=move("D"))},
        "ELSE": {"block": block("ic_return", VALUE=move("C"))},
    },
})

HAND = "def strategy(my_history, opp_history):\n    return is_angry(my_history, opp_history)\n"


def test_module_compiles_to_one_function():
    name, code = compile_module(ANGRY)
    assert name == "is_angry"
    assert code == (
        "def is_angry(my_history, opp_history):\n"
        '    if (opp_history[-10:].count("D") > 2):\n'
        '        return "D"\n'
        "    else:\n"
        '        return "C"\n'
    )
    assert count_blocks(ANGRY) == 9  # module, if, compare, count, number, 2 returns, 2 moves


def test_assembled_agent_runs_in_the_sandbox():
    build = build_agent(HAND, [ANGRY], ALL)
    assert build.errors == []
    strategy = load_bot(build.assembled)
    assert strategy([], ["D", "D"]) == "C"
    assert strategy([], ["D", "D", "D"]) == "D"


def test_elif_chain_and_chance():
    layout = module("mood", {
        "type": "controls_if",
        "extraState": {"elseIfCount": 1},
        "inputs": {
            "IF0": {"block": block("ic_first_turn")},
            "DO0": {"block": block("ic_return", VALUE=move("C"))},
            "IF1": {"block": block("ic_chance", {"PERCENT": 25})},
            "DO1": {"block": block("ic_return", VALUE=block("ic_last_move", {"WHO": "opp"}))},
        },
        "next": {"block": block("ic_return", VALUE=move("D"))},
    })
    _, code = compile_module(layout)
    assert "elif (random.random() < 0.25):" in code and code.rstrip().endswith('return "D"')
    build = build_agent(HAND.replace("is_angry", "mood"), [layout], ALL)
    assert build.errors == [] and "import random" in build.assembled


def test_round_limits_are_enforced():
    tight = BlockRules(max_modules=1, max_blocks=5, categories=["logic", "history"])
    errors = [e.message for e in build_agent(HAND, [ANGRY, ANGRY], tight).errors]
    assert any("at most 1 block module" in e for e in errors)
    assert any("9 blocks, but this round allows 5" in e for e in errors)
    assert any("math are not allowed" in e for e in errors)  # math_number
    assert any("Two modules are called 'is_angry'" in e for e in errors)


def test_layout_problems_are_reported_per_module():
    empty_slot = module("broken", block("ic_return"))
    loose = {"blocks": {"blocks": [*ANGRY["blocks"]["blocks"], move("C")]}}
    bad_name = module("strategy", block("ic_return", VALUE=move("C")))
    unknown = module("sneaky", {"type": "python_exec", "fields": {"CODE": "import os"}})
    build = build_agent(HAND, [empty_slot, loose, bad_name], BlockRules(max_modules=5, max_blocks=50))
    by_module = {e.module: e.message for e in build.errors}
    assert "empty slot" in by_module[0]
    assert "Loose blocks" in by_module[1]
    assert "reserved name" in by_module[2]
    errors = build_agent(HAND, [unknown], ALL).errors
    assert any("Unknown block type(s): python_exec" in e.message for e in errors)


def test_strategy_must_be_hand_written_and_names_must_not_clash():
    no_strategy = build_agent("x = 1\n", [ANGRY], ALL)
    assert any("Missing a top-level function strategy" in e.message for e in no_strategy.errors)
    clash = build_agent(HAND + "\ndef is_angry(a, b):\n    return 'C'\n", [ANGRY], ALL)
    assert any("also defines 'is_angry'" in e.message for e in clash.errors)


def test_crafted_layouts_cannot_inject_code():
    evil_number = module("m", block("ic_return", VALUE=block("math_number", {"NUM": "__import__('os')"})))
    evil_move = module("m", block("ic_return", VALUE=block("ic_move", {"MOVE": "C\" + open('x')"})))
    deep = block("logic_negate", BOOL=block("logic_boolean", {"BOOL": "TRUE"}))
    for _ in range(100):
        deep = block("logic_negate", BOOL=deep)
    too_deep = module("m", block("ic_return", VALUE=deep))
    for layout in (evil_number, evil_move, too_deep, "not a dict", {"blocks": {"blocks": "x"}}):
        build = build_agent(HAND.replace("is_angry", "m"), [layout], BlockRules(max_modules=1, max_blocks=500))
        assert build.errors and build.modules == []
