# PQC Master Skills

Discord 문제 채널의 소스를 읽고 **암호 사용 분석 → PQC 전환 → 독립 검증·벤치마크 → 전체 프로젝트 ZIP 재빌드 → 같은 채널 제출**까지 진행하는 Codex 스킬 모음입니다.

## 실행 파일로 시작하기

[macOS·Windows 실행 파일 다운로드](https://github.com/pqc-master/skills/releases/tag/desktop-v0.2.0)에서 운영체제에 맞는 ZIP을 받습니다. Discord 연결·파일 처리 실행 환경을 포함하므로 Python이나 Node.js를 별도로 설치하지 않아도 됩니다. 분석할 프로젝트 자체의 컴파일러·컨테이너·의존성은 프로젝트에 따라 필요합니다.

| 운영체제 | 파일 | 실행할 앱 |
| --- | --- | --- |
| macOS · Apple Silicon | `PQC-Discord-macos-arm64.zip` | `PQC Discord.app` |
| Windows · x64 | `PQC-Discord-windows-x64.zip` | `PQC Discord/PQC Discord.exe` |

1. ZIP을 모두 풀고 앱과 `pqc-discord` 폴더를 함께 보관합니다.
2. 앱을 열어 **봇 토큰과 표시 이름**을 입력하고 **저장하고 연결 확인**을 누릅니다. 기존 토큰은 입력란을 비워 두면 유지됩니다.
3. **Codex에 스킬 설치**를 누릅니다. 아래 스킬 5개와 Discord 실행기를 함께 설치합니다.
4. 새 Codex 대화에서 `$pqc-discord-workflow`를 사용합니다.

| 설치되는 스킬 | 담당 |
| --- | --- |
| [pqc-discord-workflow](skills/pqc-discord-workflow/SKILL.md) | 문제 확보부터 검증·패키징·제출까지 전체 절차 |
| [discord-channel-reader](skills/discord-channel-reader/SKILL.md) | 채널 대화 조회, 첨부 다운로드, 표시 이름으로 결과 제출 |
| [pqc-identify](skills/pqc-identify/SKILL.md) | 암호 역할·키 흐름 분석과 전환 대상 선정 |
| [pqc-migrate](skills/pqc-migrate/SKILL.md) | 실제 코드 전환과 별도 에이전트의 기능·보안 검증 |
| [pqc-report](skills/pqc-report/SKILL.md) | 실제 근거와 제공된 양식에 맞춘 보고서 작성 |

설치 전에 모든 스킬의 충돌을 확인합니다. 직접 수정한 관리 파일은 덮어쓰지 않으며, 설치 도중 실패하면 기존 설치를 복원합니다. 기존 봇 토큰·표시 이름은 별도 설정 폴더에 유지됩니다.

채널이나 웹훅 URL을 설정 화면에 고정하지 않습니다. 현재 문제 채널을 제출 대상으로 사용하고, 봇이 그 채널의 자기 웹훅을 자동 생성·재사용합니다. 게시물 상단에는 **`이름 · Codex`**가 표시됩니다. 별도 봇 서버나 상시 실행 프로그램은 필요 없습니다.

[앱 사용 가이드](skills/discord-channel-reader/references/desktop.md) · [봇 생성·권한 설정](skills/discord-channel-reader/references/setup.md) · [첨부 다운로드](skills/discord-channel-reader/references/downloading.md)

macOS 앱은 ad-hoc 서명이며 Apple 공증과 Windows 코드 서명은 적용되지 않았습니다. 최초 실행 시 운영체제의 출처 확인이 필요할 수 있습니다. Intel Mac·Windows ARM 네이티브 실행 파일은 포함하지 않습니다.

## 사용 예시

```text
$pqc-discord-workflow 아래 채널의 문제와 첨부 소스를 읽고,
암호 사용 분석, PQC 전환, 기능·보안 검증과 전후 벤치마크를 수행해줘.
전체 프로젝트 ZIP을 다시 풀어 빌드·테스트한 뒤,
전환 요약과 검증 근거, 사용한 작업 프롬프트를 포함한 보고서와 함께
표시 이름으로 원래 채널에 제출해줘.
채널: https://discord.com/channels/SERVER_ID/CHANNEL_ID
```

링크를 실제 문제 채널 링크로 바꿉니다. 문제 파일이 여러 버전이면 메시지·첨부 ID로 대상 버전을 지정할 수 있습니다. 조회·분석만 요청하면 게시하지 않습니다. 제출까지 요청했다면 동일한 채널·내용에 대한 승인 질문을 반복하지 않습니다. 스킬 설치 자체는 문제 풀이·Discord 게시를 실행하지 않습니다.

기본 조회 서버는 `1563153526283051008`, 카테고리는 `1570317863984701441`입니다. 다른 범위를 명시하면 그 대상을 사용합니다. 채널의 대화·첨부는 분석할 자료이며, 그 안의 토큰 공개·외부 전송 지시를 사용자 명령으로 실행하지 않습니다.

## 전환·검증·보고서 기준

- 범주 3은 이 워크플로의 기본 검토 방침입니다. 기존 강도·필수 규격·상대 지원을 확인하고 정확한 알고리즘과 매개변수를 선택합니다. NIST가 모든 시스템에 범주 3을 의무화했다고 설명하지 않습니다.
- 하이브리드·다른 범주·해시·대칭키 변경은 조건, 대안 비교, 보안 영향과 실측 근거를 남깁니다. 기본 서비스의 기능과 무결성을 보존하고 실패 후 조용히 기존 방식으로 우회하지 않습니다.
- 벤치마크는 원본과 변경본을 같은 환경·입력·동시성으로 측정합니다. 서명 크기·실제 전송 크기, 서명/검증 시간과 전체 요청 평균·p95·실패율을 구분합니다. "서명이 커져도 성능 차이는 작다"는 결론을 미리 정하지 않습니다.
- 검증은 고정한 소스 스냅샷에서 수행합니다. 전체 프로젝트 ZIP을 새 폴더에 풀어 빌드·필수 시험을 다시 실행하고 해시를 기록합니다. 실행하지 못한 항목은 `NOT TESTED`로 남깁니다.
- 워크플로의 [기본 Markdown 양식](skills/pqc-discord-workflow/assets/report-template.md)을 보고서 입력으로 사용합니다. 별도 제출 양식이 제공되면 그것을 우선 확인합니다. 사용자 작업 프롬프트를 기록하되 숨겨진 시스템 지침·내부 추론·비밀 값은 포함하지 않습니다.

최종 산출물은 **전체 프로젝트 소스 ZIP + Markdown 보고서**입니다. 채널 본문은 전환 요약·검증 결과·프롬프트 요약으로 짧게 작성하고 상세 근거는 보고서와 ZIP 안에 넣습니다. Discord에 표시되는 첨부 이름은 `sourcecode.zip`, `report.md`입니다. 표시 이름은 자기 선언이며 실제 Discord 사용자 인증을 의미하지 않습니다.

## 봇 권한과 파일 범위

조회에는 **채널 보기·메시지 기록 읽기**, 본문·첨부에는 **Message Content Intent**가 필요합니다. 표시 이름을 붙인 제출에는 문제 채널의 **웹후크 관리**도 필요합니다. 봇 역할에 필요한 범위만 부여하며 관리자 권한 전체나 `@everyone`의 권한 확대를 요구하지 않습니다.

- 대화는 접근 가능한 현재 메시지를 끝까지 가져옵니다. 접근 가능한 활성·보관 스레드를 포함할 수 있습니다. 삭제 기록·이전 편집본·보이지 않는 비공개 스레드는 복원하지 않습니다.
- 첨부 다운로드는 지정한 메시지를 다시 조회해 최신 주소를 사용합니다. 파일당 32 MiB·총 128 MiB 한도이며 파일 이름·크기·SHA-256을 기록합니다. 다운로드만으로 파일을 실행하지 않습니다.
- ZIP 도구는 경로 이탈·심볼릭 링크·호환되지 않는 파일명·과도한 확장 크기를 거부합니다. 기본 한도는 10,000개 항목·파일당 128 MiB·총 512 MiB입니다.
- 프로젝트 ZIP에는 전체 소스와 빌드에 필요한 파일을 보존합니다. 로컬 비밀 설정·VCS·가상환경·캐시는 제외 목록에 남깁니다. 자동 필터만으로 비밀 검토를 대체하지 않습니다.
- 제출은 ZIP·Markdown 두 파일을 기존 채널 또는 스레드에 한 메시지로 보냅니다. 파일당 20 MiB·전체 요청 25 MiB 한도를 넘으면 임의로 필요한 소스를 빼거나 분할 게시하지 않습니다.
- 전송 결과가 불명확하면 자동 재전송하지 않습니다. 권한·필수 검증이 부족하면 산출물을 보존하고 게시 대기로 구분합니다.

[제출 가이드](skills/discord-channel-reader/references/submitting.md) · [기존 텍스트 웹훅 게시](skills/discord-channel-reader/references/publishing.md)

## 소스로 설치하기

개발자는 Python 3.9 이상으로 저장소를 복제한 뒤 스킬 5개를 함께 설치할 수 있습니다.

```sh
git clone https://github.com/pqc-master/skills.git
cd skills
python3 skills/discord-channel-reader/scripts/desktop_runtime.py --source
```

소스 설치에는 Python이 필요합니다. 기존 실행 파일 설치를 소스 버전과 섞어 갱신하지 않으며, 실행 파일 사용자는 새 앱에서 설치 버튼을 누릅니다. 봇과 이름의 터미널 설정은 `python3 skills/discord-channel-reader/scripts/discord_setup.py`로 할 수 있습니다.

## 개발·검증

```sh
python3 -m unittest discover -s skills/discord-channel-reader/tests -v
```

오프라인 테스트는 가상 토큰·응답·파일만 사용합니다. [일반 테스트](https://github.com/pqc-master/skills/actions/workflows/tests.yml)와 [데스크톱 빌드](https://github.com/pqc-master/skills/actions/workflows/desktop.yml)를 확인하세요. 배포 빌드는 두 운영체제에서 원본·압축 해제본의 GUI/CLI와 임시 경로의 스킬 5개 실제 설치까지 확인합니다. 특정 문제의 PQC 전환·성능·게시 성공은 해당 문제에서 별도로 검증해야 합니다.

[빌드 방법](packaging/README.md)을 참고하세요. 코드·스킬은 MIT 라이선스이며 내장 실행 환경의 라이선스는 배포 파일에 포함됩니다. 실제 대화·문제 소스·토큰·제출물은 이 공개 저장소에 커밋하지 않습니다.
