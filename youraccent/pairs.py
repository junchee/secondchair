"""Minimal pairs for listening practice: two real words that differ in one sound.

Each pair has a short tip in Korean on how the mouth makes the two sounds. Korean speakers often
cannot hear (and so cannot say) the difference, so the tip comes before the quiz.
"""

PAIRS = [
    {
        "id": "light-right",
        "words": ["light", "right"],
        "sounds": "L / R",
        "tip": "light의 L은 혀끝을 윗니 뒤 잇몸에 붙였다 뗍니다. right의 R은 혀끝을 어디에도 대지 않고 뒤로 살짝 말아 올리며, 입술을 조금 둥글게 합니다. 한국어의 ㄹ은 이 둘의 중간 소리입니다.",
    },
    {
        "id": "think-sink",
        "words": ["think", "sink"],
        "sounds": "th / s",
        "tip": "think의 th는 혀끝을 윗니와 아랫니 사이에 살짝 내밀고 그 틈으로 바람을 냅니다. sink의 s는 혀를 입 안에 두고 윗니 뒤로 바람을 보냅니다.",
    },
    {
        "id": "berry-very",
        "words": ["berry", "very"],
        "sounds": "B / V",
        "tip": "berry의 B는 두 입술을 붙였다가 터뜨립니다. very의 V는 윗니를 아랫입술에 살짝 대고, 입술끼리는 붙이지 않은 채 떨림을 내며 바람을 보냅니다.",
    },
    {
        "id": "ship-sheep",
        "words": ["ship", "sheep"],
        "sounds": "짧은 i / 긴 ee",
        "tip": "ship의 i는 짧고 힘을 뺀 소리로, 입을 거의 벌리지 않습니다. sheep의 ee는 입꼬리를 옆으로 당기고 길게 끄는 소리입니다.",
    },
    {
        "id": "coffee-copy",
        "words": ["coffee", "copy"],
        "sounds": "F / P",
        "tip": "coffee의 F는 윗니를 아랫입술에 대고 바람을 냅니다. copy의 P는 두 입술을 붙였다가 터뜨립니다.",
    },
    {
        "id": "vine-wine",
        "words": ["vine", "wine"],
        "sounds": "V / W",
        "tip": "vine의 V는 윗니를 아랫입술에 대고 떨림을 냅니다. wine의 W는 입술을 동그랗게 오므렸다가 펴면서 내며, 이는 대지 않습니다.",
    },
    {
        "id": "bad-bed",
        "words": ["bad", "bed"],
        "sounds": "ae / e",
        "tip": "bad의 a는 입을 크게 벌려 '에'와 '아' 사이 소리를 길게 냅니다. bed의 e는 입을 덜 벌린 짧은 '에'입니다.",
    },
]

WORDS = sorted({w for p in PAIRS for w in p["words"]})
BY_ID = {p["id"]: p for p in PAIRS}
