# PQC Master Skills

Discord의 문제 채널에서 대화를 읽고, 풀이 결과인 **소스코드 ZIP과 Markdown 보고서를 같은 채널에 제출**하는 Codex 스킬입니다. 게시물 상단에는 `이름 · Codex`가 표시됩니다.

## 실행 파일로 시작하기

[실행 파일 다운로드](https://github.com/pqc-master/skills/releases/tag/desktop-v0.1.0)에서 운영체제에 맞는 ZIP을 받습니다. **Python이나 Node.js를 따로 설치할 필요가 없습니다.**

| 운영체제 | 파일 | 실행할 앱 |
| --- | --- | --- |
| macOS · Apple Silicon | `PQC-Discord-macos-arm64.zip` | `PQC Discord.app` |
| Windows · x64 | `PQC-Discord-windows-x64.zip` | `PQC Discord/PQC Discord.exe` |

1. ZIP을 모두 풀고 앱과 `pqc-discord` 폴더를 함께 보관합니다.
2. 앱을 열어 **봇 토큰과 표시 이름**을 입력합니다. 기존 설정이 있으면 토큰을 다시 입력하지 않아도 됩니다.
3. **저장하고 연결 확인**을 누릅니다.
4. **Codex에 스킬 설치**를 누르고 새 Codex 대화에서 사용합니다. 실행 환경도 스킬 폴더에 설치됩니다.

**채널을 설정 화면에서 고정하지 않습니다.** 현재 작업 중인 문제의 채널을 제출할 때 지정합니다. 웹훅 URL은 직접 입력하지 않습니다. 봇이 그 채널의 자기 웹훅을 재사용하거나 필요한 경우 생성합니다. 별도 봇 서버도 필요 없습니다.

[앱 사용 가이드](skills/discord-channel-reader/references/desktop.md) · [봇 만들기와 권한 설정](skills/discord-channel-reader/references/setup.md) · [문제 풀이 결과 제출](skills/discord-channel-reader/references/submitting.md)

현재 배포 파일은 macOS에서 ad-hoc 서명되며 Apple 공증과 Windows 코드 서명은 적용되지 않았습니다. 운영체제에서 최초 실행 확인이 필요할 수 있습니다. Intel Mac·Windows ARM 네이티브 실행은 별도 검증이 필요합니다.

## 사용 예시

```text
$discord-channel-reader 문제 채널 목록을 보여줘.

$discord-channel-reader 채널 ID 234567890123456789의 대화를 스레드까지 가져와줘.

$discord-channel-reader 이 문제의 소스코드를 ZIP으로 묶고 보고서를 작성해서,
지금 작업 중인 문제 채널에 두 파일을 함께 올려줘.
```

예시 ID는 실제 채널 ID로 바꿉니다. 대화를 읽을 때 확인한 채널 ID나 사용자가 제공한 채널 링크를 작업 대상으로 사용합니다. 대상이 없거나 모호할 때만 채널을 확인합니다.

**조회·분석 요청만으로 제출하지 않습니다.** 사용자가 결과 제출까지 요청하면 대상 채널과 두 파일을 확인하고 한 메시지에 첨부합니다. 파일명은 `sourcecode.zip`, `report.md`로 표시됩니다. 표시 이름은 사용자가 정한 이름이며 실제 Discord 사용자 계정 인증을 의미하지 않습니다.

## 기본 조회 범위

- 서버 ID: `1563153526283051008`
- 카테고리 ID: `1570317863984701441`

조회 기본값은 이 범위를 사용합니다. 제출 시에는 실제 문제 채널 ID가 필요하며 서버·카테고리 소속을 확인합니다. 기본 카테고리의 모든 채널에 일괄 게시하거나 임의의 채널을 선택하지 않습니다.

## 봇 권한

조회에는 **채널 보기·메시지 기록 읽기**, 메시지 본문에는 **Message Content Intent**가 필요합니다. 작성자 이름을 붙인 파일 제출에는 문제 채널의 **웹훅 관리** 권한이 추가로 필요합니다. 비공개 채널·스레드는 봇이 접근 가능한 범위만 지원합니다. 서버 관리자 권한 전체를 요구하지 않습니다.

## 소스로 설치하기

개발하거나 실행 파일을 사용하지 않는 경우에는 Python 3.9 이상으로 직접 실행할 수 있습니다.

```sh
git clone https://github.com/pqc-master/skills.git
cd skills
python3 - <<'PYINSTALL'
import os, shutil
from pathlib import Path
source = Path('skills/discord-channel-reader')
codex_root = Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex')))
target = codex_root / 'skills' / source.name
target.parent.mkdir(parents=True, exist_ok=True)
shutil.copytree(source, target)  # 기존 설치는 덮어쓰지 않음
print(target)
PYINSTALL
```

처음 연결할 때 `python3 skills/discord-channel-reader/scripts/discord_setup.py`를 실행해 토큰과 이름을 저장합니다. 실행 파일로 설치한 경우에는 이 과정과 Python 설치가 필요 없습니다. 기존 스킬을 직접 수정했다면 배포 앱은 이를 덮어쓰지 않고 알려줍니다.

## 조회·제출 범위

- 채널의 현재 접근 가능한 메시지를 100개씩 끝까지 가져오며 활성·보관된 접근 가능한 스레드도 지원합니다.
- `messages.jsonl`, 시간순 `transcript.md`, 수집 완료 상태 `metadata.json`을 저장합니다.
- 삭제된 메시지·이전 편집본·접근할 수 없는 비공개 스레드는 복원하지 않습니다. 첨부 파일 자체는 조회 시 내려받지 않습니다.
- 제출은 기존 문제 채널 또는 기존 스레드에 ZIP·UTF-8 Markdown 두 파일을 한 메시지로 보냅니다. 새 문제 채널이나 스레드를 만들지 않습니다.
- 제출 파일은 각 20 MiB, 전체 요청은 25 MiB 이내로 제한합니다. 자동 분할·잘라내기를 하지 않습니다.
- 전송 결과가 불명확하면 중복 제출을 피하려고 자동 재전송하지 않습니다.

기존에 채널별 웹훅으로 텍스트만 게시하던 명령도 호환성을 위해 유지합니다. 해당 고급 기능은 [기존 웹훅 게시 가이드](skills/discord-channel-reader/references/publishing.md)를 참고하세요. 문제 풀이 결과 제출에는 웹훅 URL 등록이 필요 없습니다.

## 개발·검증

```sh
python3 -m unittest discover -s skills/discord-channel-reader/tests -v
```

오프라인 테스트는 가상 토큰·응답·파일만 사용합니다. [일반 테스트](https://github.com/pqc-master/skills/actions/workflows/tests.yml)와 [데스크톱 빌드](https://github.com/pqc-master/skills/actions/workflows/desktop.yml)를 확인하세요. 데스크톱 빌드는 macOS·Windows에서 실행 환경을 포함해 빌드하고, ZIP을 다시 푼 후 CLI와 설정 화면 시작을 검사합니다. 실제 Discord에 파일을 게시하는 테스트는 **NOT TESTED**입니다. 상세 환경과 서명 상태는 다운로드에 포함된 `build-info.json`에 기록합니다.

[실행 파일 빌드 방법](packaging/README.md)을 참고하세요. 코드와 스킬 지침은 MIT 라이선스이며, 내장 실행 환경의 라이선스는 배포 파일의 `licenses`와 `THIRD-PARTY-NOTICES.txt`에 포함됩니다. 토큰·웹훅 URL·실제 대화·제출 파일은 저장소에 커밋하지 않습니다.
