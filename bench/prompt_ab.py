"""Side-by-side check of two translation prompts (2026-11-21): the app's `current` prompt against `natural`,
which asks for a natural rewrite instead of "every word". No judge model: the pairs are written to a file for
a person to read. About 2 x 26 calls to the first translate model (a few cents).

  python3 bench/prompt_ab.py            # needs OPENROUTER_API_KEY in the environment
Output: notes/prompt_ab_2026-11-21.md
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import translate   # noqa: E402

OLD = ("Translate every word of the line, including any words in other languages; keep "
       "names of people and places.")
NATURAL = ("Write it the way a native {target} speaker would say or write it, not word for word: reorder as "
           "{target} needs, leave out filler (you know, I mean, so, well, 嗯, 那个), and give set phrases and "
           "official or legal terms their usual {target} equivalents. Keep names, numbers and every fact; "
           "do not add anything. A speech or news line is written in a formal written style; ordinary "
           "conversation in plain spoken style.")

ENGLISH = [   # a BBC London news piece, as Anne heard it (2026-11-21, 18:08-18:17)
    "Thanks, Rita. Coming up on BBC London. Caught out by a strike on the Piccadilly line, the passengers left stranded after union members walk out for 24 hours.",
    "I'm not going to be able to get to the hospital on time. There's just absolutely no way I'll be able to get there. It's in Tottenham.",
    "Extremely frustrating and a bit upsetting actually.",
    "Also on the programme, a vigil for the 21-year-old stabbed to death in Haringey last Friday.",
    "At 11:15 this morning, the last train left Cockfosters in North London on the end of the Piccadilly Line. The strike caught many commuters unawares.",
    "Levine was on her way to a hospital appointment.",
    "\"I might have to cancel it now, which is not good because it's treatment and if I they might stop my treatment. So I have no idea what I'm going to do.",
    "I'm going to have to get a bus back to my house, but I'm not going to be able to get to the hospital on time.",
    "There's just absolutely no way I'll be able to get there. It's in Tottenham. I know. Frustrating. extremely frustrating and a bit upsetting actually.",
    "I didn't realise. If I'd known, I could have made an alternative route to get there, but I didn't know.",
    "I had heard about the strike and of course it'll affect us because there's no tube.",
    "I've got to get to Knightsbridge and I didn't realise obviously that this was happening.",
    "So, you know, I mean, what we really need to look at is, um, the budget, and, like, whether we can actually afford the second phase.",
    "Yeah, I think that's a good point, but I'm not sure the timeline works, to be honest.",
]

CHINESE = [   # a court-work speech heard from a Chinese news broadcast (2026-11-21, 17:58-18:00)
    "发展稳定提供了有利司法保障 习近平强调 新征程上 要全面贯彻新时代",
    "中国特色 社会主义 法治思想 坚持党的领导 坚持以人民为中心 坚持走中国特色社会主义法治道路",
    "坚持依法独立公正行使审判权",
    "深化司法体制改革",
    "规范司法权力运行",
    "加快建设公正高效权威的",
    "社会主义司法制度 严格落实管党治党政治责任",
    "锻造忠诚干净担当的过硬队伍",
    "以高质量司法 更好保障高质量发展",
    "和高水平安全 持續增強人民群眾對司法公正的獲得感",
    "为建设更高水平平安中国 法治中国",
    "推进中国式现代化 做出新的更大贡献 第23次全国法院工作会议",
    "16号至17号在京召开 会上传达了习近平重要指示",
]


def ask(text, target, context, natural):
    body = translate.build_request(text, target, context)
    system = body["messages"][0]["content"]
    if natural:
        assert OLD in system
        system = system.replace(OLD, NATURAL.format(target=target))
        body["messages"][0]["content"] = system
    return translate.Client().post(body).strip()


def run(title, lines, target):
    out = [f"## {title}\n"]
    for i, text in enumerate(lines):
        context = tuple(lines[max(0, i - 2):i])
        a, b = ask(text, target, context, False), ask(text, target, context, True)
        out += [f"**{i + 1}.** {text}", f"- current: {a}", f"- natural: {b}", ""]
        print(i + 1, "done", file=sys.stderr)
    return "\n".join(out)


if __name__ == "__main__":
    parts = ["# Translation prompt A/B (2026-11-21)\n",
             "`current` = the app's prompt (\"Translate every word ...\"); `natural` = rewrite as a native speaker would. "
             "Same model, temperature 0, same two earlier lines as context. Read side by side; no judge model.\n",
             run("English to Korean", ENGLISH, "Korean"),
             run("Chinese to Korean", CHINESE, "Korean")]
    path = os.path.join(ROOT, "notes", "prompt_ab_2026-11-21.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(parts))
    print(path)
