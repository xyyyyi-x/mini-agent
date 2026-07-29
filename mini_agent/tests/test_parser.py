"""解析器测试（题目："需实现 LLM 输出的解析逻辑"）。"""

import json

from mini_agent.agent.parser import parse, render
from mini_agent.agent.types import ParsedOutput


def test_strict_json_action():
    p = parse(json.dumps({
        "thought": "算一下", "action": "calculator",
        "action_input": {"expr": "6*7"}, "final_answer": None,
    }))
    assert p.action == "calculator"
    assert p.action_input == {"expr": "6*7"}
    assert p.final_answer is None


def test_strict_json_final_answer():
    p = parse('{"thought":"hi","action":null,"action_input":null,"final_answer":"你好"}')
    assert p.action is None
    assert p.final_answer == "你好"


def test_fenced_json_block():
    raw = "好的，我来算：\n```json\n{\"thought\":\"x\",\"action\":\"calculator\",\"action_input\":{\"expr\":\"1+1\"},\"final_answer\":null}\n```\n"
    p = parse(raw)
    assert p.action == "calculator"
    assert p.action_input == {"expr": "1+1"}


def test_json_embedded_in_prose():
    raw = '当然！ {"thought":"r","action":null,"action_input":null,"final_answer":"答案是42"} 希望帮到你'
    p = parse(raw)
    assert p.final_answer == "答案是42"


def test_single_quotes_and_trailing_comma_repair():
    raw = "{'thought':'r','action':null,'action_input':null,'final_answer':'ok',}"
    p = parse(raw)
    assert p.final_answer == "ok"


def test_total_garbage_becomes_final_answer():
    p = parse("hello there, 我就是一段普通文字")
    assert p.action is None
    assert p.final_answer == "hello there, 我就是一段普通文字"


def test_action_missing_action_input_normalized_to_empty():
    p = parse('{"thought":"x","action":"weather","final_answer":null}')
    assert p.action == "weather"
    assert p.action_input == {}


def test_action_input_as_string_is_parsed():
    p = parse('{"thought":"x","action":"calculator","action_input":"{\\"expr\\": \\"1+1\\"}","final_answer":null}')
    assert p.action == "calculator"
    assert p.action_input == {"expr": "1+1"}


def test_both_action_and_final_answer_action_wins():
    p = parse('{"thought":"x","action":"calculator","action_input":{"expr":"1+1"},"final_answer":"oops"}')
    assert p.action == "calculator"
    assert p.final_answer is None


def test_both_missing_falls_back_to_raw():
    raw = '{"thought":"x"}'
    p = parse(raw)
    assert p.action is None
    assert p.final_answer == raw


def test_parse_never_raises():
    # 各种奇怪输入都不应抛异常
    for weird in ["", None, "{", "{{{{", "```json { ```", "{unclosed", "]}"]:
        parse(weird)  # 不抛即通过


def test_render_action_and_final():
    a = ParsedOutput(thought="t", action="calculator", action_input={"expr": "1+1"},
                     final_answer=None, raw="...")
    assert "Thought: t" in render(a)
    assert "Action: calculator" in render(a)
    assert "Action Input:" in render(a)

    b = ParsedOutput(thought="t", action=None, action_input=None,
                     final_answer="hi", raw="...")
    assert "Final Answer: hi" in render(b)


def test_single_quote_dict_with_apostrophe():
    # 单引号字典（非合法 JSON）+ 字符串内含撇号：
    # ast.literal_eval 能正确解析，而"无差别替换单引号"会把 "it's me" 破坏成 "it"s me"。
    raw = "{'thought':'t','final_answer':\"it's me\"}"
    p = parse(raw)
    assert p.final_answer == "it's me"


def test_plain_text_final_answer_extracted():
    # 模型不遵守 JSON、直接输出 "Thought: ... Final Answer: X" 纯文本时，
    # 解析器应抽出 X，不要把 "Final Answer:" 前缀漏给用户。
    raw = "Thought: 算完了\nFinal Answer: 17 乘以 23 等于 391。"
    p = parse(raw)
    assert p.action is None
    assert p.final_answer == "17 乘以 23 等于 391。"


def test_chinese_final_answer_marker():
    raw = "思考完毕。最终答案：你好。"
    p = parse(raw)
    assert p.final_answer == "你好。"
