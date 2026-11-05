# Anne: menu, bottom box and meeting flow (design, 2026-11-05; Jun's decisions, not built yet)

## Decisions from Jun
1. **Start waits.** Starting the program does not start a meeting. Pressing Start opens a short confirmation: "배경지식: [most recent title] · N terms" with [이대로 시작] [다른 것 고르기] [배경지식 없이 시작]. A background is never applied by itself; the default choice is the most recent one.
2. **Backgrounds are a list.** Titles only; click one to see its terms (English = 한국어). Title = the topic line made at "저장하고 용어 정리", editable. The saved text and terms that exist now become the first item.
3. **End asks about the summary.** "요약할까요?" [요약하고 끝내기] [요약 없이 끝내기] [취소]. "No thanks" ends and saves the transcript without a summary.
4. **One bottom box.** Typed Korean may be a translation or a question about the meeting. The answer to a question shows in the same box (the right pane), not in a side panel. The Ask tab goes away.
5. **Group by what it is for.** Summary, questions and 배경지식 belong to the current meeting: one place. Tuning is a developer tool (can move later). In Settings only what a user changes (theme light/dark, text size) stays, under View; everything else becomes developer tools.

## Proposal (Apple's guidelines: a menu bar for commands, "Settings..." under the app name, View for appearance, standard Edit/Window/Help)

### Mac app menu bar (Anne.app)
| Menu | Items |
|---|---|
| **Anne** | Anne에 대하여; 설정… (Cmd+,: language of the translation, translate on/off, theme, text size); Anne 종료 (Cmd+Q) |
| **회의** | 시작 (Cmd+N), 일시정지 / 다시 시작 (Cmd+P), 종료 (Cmd+.); —; 요약 (Cmd+Shift+S); 질문하기 (Cmd+/ moves the cursor to the bottom box in 질문 mode); 배경지식… (Cmd+B); —; 마이크 켜기/끄기 (Cmd+M is Minimize in macOS: use Cmd+Shift+M) |
| **편집** | standard (undo, cut, copy, paste, select all) |
| **보기** | 밝게 / 어둡게 / 시스템 설정 따르기; 글자 키우기 (Cmd++), 줄이기 (Cmd+-), 기본 크기 (Cmd+0); 간단히 보기 (Compact); 번역 표시: 원문 + 번역 / 원문만 |
| **개발자** (hidden in a release) | Tuning… ; 번역 모델 (Auto / DeepSeek / Qwen); 줄 길이·쉬는 틈; 마이크 소음 기준; 로그 보기 (Cmd+L); 모두 기본값으로 |
| **윈도우**, **도움말** | standard; 도움말: 사용 안내, 문제 해결 (Zoom 스피커 설정, 마이크 권한) |

### In the window (web page, also the browser version): fewer buttons, grouped
`[Anne ▾ beta]  [▶ ‖ ■]  [🎤]  [이 회의 ▾]` ...spacer... `[보기 ▾]  [⚙ 개발자 ▾ (when on)]  [⏻]`
- **이 회의 ▾:** 요약, 배경지식 (質問 is the bottom box). Shows the title of the background in use.
- **보기 ▾:** theme, text size, compact, translate on/off.
- **개발자 ▾:** Tuning, translation model, lines, mic filter, log.
- Names: use plain verbs/nouns in Korean for the buttons ("회의", "보기", "개발자"); icons keep tooltips.
- The gear (Settings) goes away from the page in the app (it is in the menu bar); the browser version keeps one gear that holds 보기 and 개발자.

## Revised 2026-11-05 (Jun's answers)
- **Translation on/off is one toggle in View**: "번역 끄기 / Turn translation off" (default on = original + translation). No "original only" segmented choice.
- **Text size stays two sizes** (English text, translation text), shown in **one line** in View: `글자 크기 / Text size   원문 [A-][A+]   번역 [A-][A+]` (Original, Translation). Cmd+, Cmd+- Cmd+0 change both.
- **Names follow the system language** (Korean system: Korean names, otherwise English). One table of names, both languages:

| English | 한국어 |
|---|---|
| Anne > About Anne / Settings... / Quit Anne | Anne > Anne에 대하여 / 설정… / Anne 종료 |
| **Meeting** > Start / Pause, Resume / End / Summary / Ask / Background / Microphone | **회의** > 시작 / 일시정지, 다시 시작 / 종료 / 요약 / 질문 / 배경지식 / 마이크 |
| **Edit** (standard) | **편집** (표준) |
| **View** > Light, Dark, Automatic / Text size / Compact view / Turn translation off | **보기** > 밝게, 어둡게, 자동 / 글자 크기 / 간단히 보기 / 번역 끄기 |
| **Developer** > Tuning / Translation model / Lines / Microphone filter / Show log / Reset | **개발자** > 튜닝 / 번역 모델 / 줄 나누기 / 마이크 기준 / 로그 보기 / 기본값으로 |
| **Window**, **Help** | **윈도우**, **도움말** |
| In the page: [This meeting v] (Summary, Background), [View v], [Developer v], quit | 페이지 위쪽: [이 회의 v] (요약, 배경지식), [보기 v], [개발자 v], 종료 |

How: the page keeps one table of texts (`en`, `ko`) and picks by the browser/system language (`navigator.language`); Anne.app uses a small table in `main.swift` for the menu bar (not `Localizable.strings`). Tooltips and messages come from the same table. English is used if the language is neither Korean nor English.
