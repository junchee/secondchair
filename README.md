# secondchair

회의 소리를 글자로 받아 적고, 영어와 한국어로 번역하고, 요약하고, 내가 한국어로 말하면 영어 음성으로 회의에 대신 말해 주는 Mac 프로그램입니다. (현재 베타 이름: hajung)

- 상대방 말 → 화면에 원문과 번역
- 내가 한국어로 말하거나 입력 → 영어를 확인하고 "오케이" → 회의에 영어 음성으로 전달
- 회의 중 요약, 회의 내용에 대한 질문, 회의가 끝나면 대화 기록과 요약 저장
- 음성은 내 Mac 안에서만 처리됩니다. 번역과 요약을 위해 **글자만** 인터넷(OpenRouter, 데이터 미보관 제공자)으로 보냅니다.

## 설치

**[설치 안내 (한글, 단계별)](https://junchee.github.io/secondchair/)** 를 따라 하세요. 터미널에 아래 한 줄을 붙여 넣는 것이 핵심입니다.

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/junchee/secondchair/main/install.sh)"
```

필요한 것: Apple 칩(M1 이상) Mac, 인터넷, 이어폰. 번역·요약에는 번역 키(OpenRouter)가 필요하고, 프로그램을 준 사람이 따로 알려 줍니다. **키는 이 저장소에 없습니다.**

## 주의

회의에서 사용할 때는 참석자에게 **전사하고 있다고 알려 주세요.**

## 개발 메모

구조, 결정 사항, 진행 상황은 [CLAUDE.md](CLAUDE.md), 소리 연결의 목표 설계는 [docs/audio_routing.md](docs/audio_routing.md)에 있습니다.
