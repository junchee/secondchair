#!/bin/bash
# secondchair 설치 스크립트: 터미널에 한 줄을 붙여 넣으면 필요한 것을 모두 설치합니다.
#
#   /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/junchee/secondchair/main/install.sh)"
#
# 다시 실행해도 안전합니다: 이미 설치된 것은 건너뛰고, 프로그램은 최신으로 맞춥니다.
# 무엇을 할지만 보려면:  SECONDCHAIR_DRY_RUN=1 bash install.sh
#
# 순서: Xcode 도구 확인 > Homebrew > Python > 소리 드라이버(BlackHole) > 프로그램 내려받기
#       > 실행 환경 > 번역 키 > 바탕화면 시작 아이콘

REPO_URL="${SECONDCHAIR_REPO:-https://github.com/junchee/secondchair.git}"
DEST="${SECONDCHAIR_DEST:-$HOME/secondchair}"
DRY_RUN="${SECONDCHAIR_DRY_RUN:-}"
LAUNCHER="$HOME/Desktop/secondchair 시작.command"
BREW=/opt/homebrew/bin/brew
NEED_REBOOT=""

bold=$'\033[1m'; dim=$'\033[2m'; green=$'\033[32m'; red=$'\033[31m'; reset=$'\033[0m'
TOTAL=8
step() { echo; echo "${bold}[$1/$TOTAL] $2${reset}"; }
ok()   { echo "  ${green}✓${reset} $1"; }
note() { echo "  ${dim}$1${reset}"; }
die()  { echo; echo "${red}멈췄습니다:${reset} $1"; echo; exit 1; }

# 설치처럼 시스템을 바꾸는 명령은 모두 run으로 실행합니다. DRY_RUN이면 보여 주기만 합니다.
run() {
  if [ -n "$DRY_RUN" ]; then echo "  (미리보기) $*"; return 0; fi
  "$@"
}

echo "${bold}secondchair 설치를 시작합니다${reset}"
[ -n "$DRY_RUN" ] && echo "(미리보기 모드: 아무것도 설치하거나 바꾸지 않습니다)"
echo "중간에 Mac 암호를 물으면 입력하세요. 입력해도 화면에는 아무것도 보이지 않는 것이 정상입니다."

# ---------------------------------------------------------------- 1. 내 Mac 확인
step 1 "내 Mac 확인"
[ "$(uname -s)" = "Darwin" ] || die "이 프로그램은 Mac에서만 동작합니다."
[ "$(uname -m)" = "arm64" ] || die "M1 이후의 Mac(Apple 칩)에서만 동작합니다. 이 Mac은 Intel 칩입니다."
ok "Apple 칩 Mac입니다 (macOS $(sw_vers -productVersion))"
FREE_GB=$(( $(df -k "$HOME" | awk 'NR==2 {print $4}') / 1024 / 1024 ))
if [ "$FREE_GB" -lt 5 ]; then
  die "저장 공간이 부족합니다 (남은 공간 약 ${FREE_GB}GB, 5GB 이상 필요). 파일을 정리한 뒤 다시 실행하세요."
fi
ok "저장 공간이 충분합니다 (약 ${FREE_GB}GB 남음)"

# ---------------------------------------------------------------- 2. Xcode 명령줄 도구
step 2 "Xcode 명령줄 도구 확인"
if xcode-select -p >/dev/null 2>&1; then
  ok "이미 설치되어 있습니다"
else
  if [ -n "$DRY_RUN" ]; then
    note "(미리보기) 설치 창을 띄웁니다: xcode-select --install"
  else
    xcode-select --install >/dev/null 2>&1
    echo
    echo "화면에 '명령줄 개발자 도구를 설치하시겠습니까?' 창이 떴습니다."
    echo "'설치'를 누르고, 끝날 때까지 기다린 뒤 (몇 분 걸립니다)"
    echo "${bold}같은 명령을 터미널에 다시 붙여 넣으세요.${reset}"
    exit 0
  fi
fi

# ---------------------------------------------------------------- 3. Homebrew
step 3 "Homebrew 확인 (프로그램 설치 도우미)"
if [ -x "$BREW" ]; then
  ok "이미 설치되어 있습니다"
else
  note "처음 한 번만 설치합니다. 몇 분 걸리고, 중간에 Enter를 누르라는 안내가 나옵니다."
  if [ -n "$DRY_RUN" ]; then
    echo "  (미리보기) Homebrew 공식 설치 스크립트를 실행합니다"
  else
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)" \
      || die "Homebrew 설치에 실패했습니다. 위의 오류 메시지를 복사해서 보내 주세요."
  fi
fi
[ -x "$BREW" ] && eval "$("$BREW" shellenv)"
if ! grep -qs 'brew shellenv' "$HOME/.zprofile"; then
  run bash -c "echo 'eval \"\$(/opt/homebrew/bin/brew shellenv)\"' >> \"$HOME/.zprofile\""
fi

# ---------------------------------------------------------------- 4. Python과 git
step 4 "Python 설치"
note "git은 Xcode 명령줄 도구에 들어 있어서 따로 설치하지 않습니다."
if [ -x "$BREW" ] && "$BREW" list --formula python@3.13 >/dev/null 2>&1; then
  ok "Python 3.13 이미 설치되어 있습니다"
else
  run "$BREW" install python@3.13 || die "Python 설치에 실패했습니다."
fi
PYTHON="/opt/homebrew/opt/python@3.13/bin/python3.13"

# ---------------------------------------------------------------- 5. 소리 드라이버
step 5 "소리 드라이버(BlackHole) 설치"
note "회의 소리를 가져오는 2ch와, 내 통역 목소리를 회의에 보내는 16ch가 필요합니다."
for size in 2ch 16ch; do
  if [ -e "/Library/Audio/Plug-Ins/HAL/BlackHole$size.driver" ]; then
    ok "BlackHole $size 이미 설치되어 있습니다"
  else
    run "$BREW" install --cask "blackhole-$size" || die "BlackHole $size 설치에 실패했습니다."
    NEED_REBOOT=1
  fi
done

# ---------------------------------------------------------------- 6. 프로그램 내려받기
step 6 "secondchair 내려받기"
if [ -d "$DEST/.git" ]; then
  run git -C "$DEST" pull --ff-only --quiet && ok "최신 버전으로 맞췄습니다 ($DEST)"
else
  run git clone --quiet "$REPO_URL" "$DEST" || die "내려받기에 실패했습니다. 인터넷 연결과 주소를 확인하세요: $REPO_URL"
  ok "내려받았습니다 ($DEST)"
fi

# ---------------------------------------------------------------- 7. 실행 환경
step 7 "실행 환경 만들기 (5~10분 걸릴 수 있습니다)"
if [ -n "$DRY_RUN" ] && [ ! -d "$DEST" ]; then
  echo "  (미리보기) $PYTHON -m venv $DEST/.venv"
  echo "  (미리보기) pip install -r requirements.txt"
  echo "  (미리보기) swiftc native/route.swift"
else
  if [ -d "$DEST/.venv" ] && [ ! -x "$DEST/.venv/bin/pip" ]; then
    note "지난번에 만들다 멈춘 실행 환경이 있어서 지우고 다시 만듭니다."
    run rm -rf "$DEST/.venv"
  fi
  if [ ! -d "$DEST/.venv" ] && ! run "$PYTHON" -m venv "$DEST/.venv"; then
    run rm -rf "$DEST/.venv"  # do not leave a half-made one behind for the next run
    # `python -m venv` hides why pip failed to install. Repeat the steps where the reason shows.
    echo
    echo "  ---- 원인 확인 (이 아래 글자를 모두 복사해서 보내 주세요) ----"
    echo "  macOS $(sw_vers -productVersion), Python $("$PYTHON" -c 'import sys; print(sys.version.split()[0])' 2>&1)"
    echo "  남은 저장 공간: $(df -h "$HOME" | awk 'NR==2 {print $4}')"
    "$PYTHON" -c "import pyexpat, ssl, zlib; print('  modules ok')" 2>&1 | tail -5
    probe="$(mktemp -d)/venv"
    "$PYTHON" -m venv --without-pip "$probe" 2>&1 | tail -5
    "$probe/bin/python3" -m ensurepip --default-pip 2>&1 | tail -15
    rm -rf "$(dirname "$probe")"
    echo "  ---- 원인 확인 끝 ----"
    die "실행 환경을 만들지 못했습니다. 위의 '원인 확인' 글자를 보내 주세요."
  fi
  run "$DEST/.venv/bin/pip" install --quiet --disable-pip-version-check -r "$DEST/requirements.txt" \
    || die "필요한 부품 설치에 실패했습니다."
  ok "필요한 부품을 설치했습니다"
  run swiftc -O "$DEST/native/route.swift" -o "$DEST/native/route" \
    || die "소리 연결 도구를 만들지 못했습니다. Xcode 명령줄 도구가 제대로 설치됐는지 확인하세요."
  ok "소리 연결 도구를 만들었습니다"
fi

# ---------------------------------------------------------------- 8. 번역 키와 시작 아이콘
step 8 "번역 키와 바탕화면 시작 아이콘"
if grep -qs 'OPENROUTER_API_KEY' "$HOME/.zshrc"; then
  ok "번역 키가 이미 있습니다"
elif [ -n "$DRY_RUN" ]; then
  echo "  (미리보기) 번역 키(OpenRouter)를 물어봅니다"
else
  echo "  번역과 요약에는 번역 키가 필요합니다. 이 프로그램을 알려 준 사람에게 받은 키를 넣으세요."
  echo "  지금 키를 붙여 넣고 Enter를 누르세요. 화면에는 보이지 않습니다. 나중에 하려면 그냥 Enter."
  read -r -s -p "  키: " api_key < /dev/tty
  echo
  if [ -n "$api_key" ]; then
    printf '\nexport OPENROUTER_API_KEY=%q\n' "$api_key" >> "$HOME/.zshrc"
    ok "번역 키를 저장했습니다"
  else
    note "키 없이도 전사는 됩니다. 번역과 요약은 키를 넣은 뒤에 쓸 수 있습니다."
  fi
fi

if [ -n "$DRY_RUN" ]; then
  echo "  (미리보기) 바탕화면에 '$(basename "$LAUNCHER")' 만들기"
else
  cat > "$LAUNCHER" <<EOF
#!/bin/zsh
# secondchair 시작: 두 번 클릭하면 터미널이 열리고 프로그램이 시작됩니다.
source ~/.zshrc 2>/dev/null
cd "$DEST" && exec .venv/bin/python app.py
EOF
  chmod +x "$LAUNCHER"
  ok "바탕화면에 'secondchair 시작' 아이콘을 만들었습니다"
fi

# ---------------------------------------------------------------- 끝
echo
echo "${green}${bold}설치가 끝났습니다.${reset}"
if [ -n "$NEED_REBOOT" ]; then
  echo
  echo "${bold}지금 Mac을 재시동하세요${reset} (소리 드라이버가 재시동 후에 나타납니다)."
  echo "재시동한 뒤 바탕화면의 'secondchair 시작'을 두 번 클릭하세요."
else
  echo "바탕화면의 'secondchair 시작'을 두 번 클릭하면 시작됩니다."
fi
echo "처음 시작할 때는 음성 인식 모델(약 0.5GB)을 내려받아서 몇 분 걸립니다."
