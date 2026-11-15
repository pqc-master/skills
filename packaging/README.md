# Standalone desktop build

PQC Discord의 설정 GUI와 명령줄 프로그램을 Python 런타임과 함께 묶는다. 0.2.0부터 Discord 스킬, PQC 총괄 스킬, 기존 PQC 스킬 3개를 함께 설치한다. 사용자는 스킬 실행기를 위해 Python을 별도로 설치하지 않는다. 분석 대상 프로젝트의 컴파일러·의존성은 별도로 필요할 수 있다. 이 문서는 빌드 담당자용이며, 사용 방법은 저장소 README를 따른다.

## 지원하는 빌드 대상

| 대상 | 빌드 환경 | ZIP 안의 실행 파일 |
| --- | --- | --- |
| macOS Apple Silicon | macOS arm64, Python 3.13 + Tcl/Tk | `PQC-Discord-macos-arm64/PQC Discord.app`, `pqc-discord/pqc-discord` |
| Windows 64비트 | Windows x64, Python 3.13 + Tcl/Tk | `PQC-Discord-windows-x64/PQC Discord/PQC Discord.exe`, `pqc-discord/pqc-discord.exe` |

표의 CLI 경로는 같은 ZIP 최상위 폴더 안에 있다. GUI와 CLI 폴더는 함께 배포한다. GUI에서 스킬을 설치할 때 옆의 CLI 폴더 전체를 복사하므로 실행 파일만 따로 옮기지 않는다. Intel Mac·Windows ARM·Linux 실행 파일은 이 워크플로의 지원 대상이 아니다.

PyInstaller는 OS 간 교차 컴파일러가 아니므로 각 OS에서 해당 플랫폼용 결과물을 만든다. 실제 호환 OS 범위는 빌드에 사용한 Python·Tcl/Tk·OS에 영향을 받는다. 최신 CI에서 성공했다고 이전의 모든 OS 버전을 지원한다고 판단하지 않는다. [공식 플랫폼 설명](https://pypi.org/project/pyinstaller/6.22.3/)

## 로컬 빌드

Python 3.13과 Tcl/Tk가 있는 환경에서 저장소 최상위 디렉터리를 연다. 가상 환경을 활성화한 뒤 다음을 실행한다.

```sh
python -m pip install -r packaging/requirements-build.txt
python -m unittest discover -s skills/discord-channel-reader/tests -v
python packaging/build_desktop.py
```

대상은 현재 Python의 OS·아키텍처로 선택한다. 필요하면 `--target macos-arm64` 또는 `--target windows-x64`를 지정한다. 다른 아키텍처의 Python으로 빌드하려 하면 중단한다. `--output-dir PATH`로 결과 저장 경로를 바꿀 수 있다.

빌드는 GUI와 CLI를 각각 `onedir` 형식으로 만든다. 다음 다섯 폴더의 `SKILL.md`, `agents`, `assets`, `references`, `scripts`, `tests`를 `sys._MEIPASS/skills/` 아래에 넣는다: `discord-channel-reader`, `pqc-discord-workflow`, `pqc-identify`, `pqc-migrate`, `pqc-report`. 설치된 `bin` 디렉터리, 캐시, `.env` 파일, `publisher.json`, 대화 내보내기는 포함하지 않는다. [번들 리소스 경로](https://pyinstaller.org/en/v6.22.3/runtime-information.html)

앱의 설치 버튼과 CLI `install`은 다섯 스킬을 같은 `skills` 디렉터리에 설치한다. 실행 환경은 `discord-channel-reader/bin`에만 복사한다. 모든 대상의 충돌을 먼저 검사하고, 전체 사본을 준비한 뒤 교체한다. 중간 교체에 실패하면 이미 바꾼 스킬도 이전 상태로 복원한다. 직접 수정한 관리 파일은 덮어쓰지 않고, 사용자가 추가한 파일은 보존한다. 별도 `~/.config/discord-channel-reader`에 있는 봇·표시 이름 설정은 설치 과정에서 읽거나 옮기지 않는다.

Python으로 소스 스킬을 설치하려면 저장소에서 `python3 skills/discord-channel-reader/scripts/desktop_runtime.py --source`를 실행한다. `--target-skills-dir PATH`로 설치 위치를 지정할 수 있다. 이 방법은 실행 환경을 포함하지 않으므로 Python 3.9 이상이 필요하다. 기존 실행 파일 설치에 새 지침만 섞지 않도록, 실행 파일로 설치된 위치의 소스 갱신은 거부한다. 그런 설치는 새 앱으로 갱신한다.

CLI에는 첨부를 받는 `download`, 프로젝트 압축을 다루는 `workspace`, 결과를 올리는 `submit` 명령을 포함한다. 작업할 때 지정한 채널에 `sourcecode.zip`과 `report.md`를 함께 올리고, 봇이 관리하는 해당 채널의 웹훅으로 `이름 · Codex`를 작성자 헤더에 표시한다. `submit preview`는 파일과 이름만 로컬에서 확인한다. 실제 `submit send`는 봇 인증 후 채널·카테고리·권한을 확인하며, 필요하면 웹훅을 생성한다. 빌드·설치 과정에서는 웹훅을 만들거나 파일을 게시하지 않는다.

## 검증과 결과물

빌드 스크립트가 실제 번들의 CLI `--version`, 각 명령의 도움말, `self-test`, `install-smoke`와 GUI `--smoke-test`를 실행한다. `install-smoke`는 임시 경로에 다섯 스킬을 실제로 설치하고, 복사된 실행기의 `self-test`까지 확인한 뒤 임시 결과를 정리한다. 사용자의 홈 설정이나 `CODEX_HOME`을 바꾸지 않는다. ZIP으로 묶고 다시 푼 뒤 같은 검사를 반복한다. macOS에서는 `ditto`로 앱 내부 심볼릭 링크와 실행 권한을 보존한다. 검사가 실패하면 새 결과 ZIP을 게시하지 않는다.

성공한 결과는 `output/desktop/<target>/`에 저장한다.

- `PQC-Discord-<target>.zip`: GUI, CLI, 스킬 데이터, 라이선스와 빌드 정보
- `SHA256SUMS`: ZIP의 SHA-256
- `build-info.json`: 앱 버전·다섯 스킬 목록, 실제 Python·OS·의존성 버전, 소스 커밋과 작업 트리 변경 여부

빌드·자동 검증은 실제 Discord 토큰이나 웹훅을 사용하지 않는다. 이 검증은 실서버 인증·권한·게시 성공을 증명하지 않는다. 실제 Discord 테스트 상태는 빌드 정보에서 `NOT TESTED`로 기록한다. GUI smoke test는 초기화·종료 확인이며 사용자의 모든 화면 조작을 대체하지 않는다.

릴리스별로 실제 소스 커밋과 운영체제의 CI 결과를 확인한다. 한 OS의 성공을 다른 OS나 아직 실행하지 않은 버전의 성공으로 간주하지 않는다. macOS GUI 검증은 그래픽 로그인 세션 접근이 필요하므로 이를 차단하는 샌드박스에서는 앱 초기화가 실패할 수 있다.

`.github/workflows/desktop.yml`은 수동 실행과 관련 파일의 `main` 푸시에 반응한다. macOS arm64·Windows x64에서 소스 테스트, 패키징, 압축 해제 후 검증을 통과해야 ZIP·체크섬을 Actions artifact로 올린다. GitHub Release 공개는 이 워크플로가 자동 수행하지 않는다.

## TLS 인증서와 서명

`certifi`의 Mozilla 루트 인증서 묶음을 앱에 포함한다. frozen 실행에서 사용하는 HTTPS 컨텍스트는 이 CA 묶음을 사용해 서버 인증서와 호스트 이름을 검증해야 한다. 빌드 컴퓨터의 Python 인증서 절대 경로에 의존하거나 인증서 검증을 끄지 않는다. CA 갱신 시 `requirements-build.txt`의 버전을 갱신하고 앱을 다시 빌드한다. [certifi 설명](https://github.com/certifi/python-certifi), [Python SSL 문서](https://docs.python.org/3.13/library/ssl.html#ssl.create_default_context)

개발자 서명 인증서는 설정되어 있지 않다. macOS 결과는 PyInstaller의 기본 ad-hoc 서명을 사용하며 Apple 공증을 받지 않는다. Windows 결과는 Authenticode 서명이 없다. 따라서 운영체제가 앱의 출처 확인이나 실행 경고를 표시할 수 있다. 서명·공증을 완료했다고 안내하지 않는다. [PyInstaller macOS 서명 설명](https://pyinstaller.org/en/v6.22.3/feature-notes.html#macos-binary-code-signing)

## 고정한 도구와 공식 근거

확인일: 2026-11-15.

| 도구 | 고정 버전 | 근거·라이선스 |
| --- | --- | --- |
| PyInstaller | 6.22.3 | [PyPI 릴리스](https://pypi.org/project/pyinstaller/6.22.3/), [GPL 예외와 일부 Apache-2.0 파일](https://pyinstaller.org/en/v6.22.3/license.html) |
| certifi | 2026.10.23 | [PyPI 릴리스](https://pypi.org/project/certifi/2026.10.23/), MPL-2.0 |
| actions/checkout | v7.0.1 / `3d3c42e5aac5ba805825da76410c181273ba90b1` | [공식 릴리스](https://github.com/actions/checkout/releases/tag/v7.0.1) |
| actions/setup-python | v7.1.0 / `6d4fd22b20465ccc0f7354476588e8df7c9ca0e0` | [공식 릴리스](https://github.com/actions/setup-python/releases/tag/v7.1.0) |
| actions/upload-artifact | v7.0.2 / `cf430e030ddbb5b0abf93d22962f4752f3646cd9` | [공식 릴리스](https://github.com/actions/upload-artifact/releases/tag/v7.0.2) |

액션 SHA는 공식 저장소의 릴리스 태그가 가리키는 커밋을 확인해 고정했다. PyInstaller 예외는 생성한 앱을 해당 앱과 의존성의 라이선스에 따라 배포할 수 있게 한다. 번들에는 프로젝트 MIT 라이선스, Python·certifi 라이선스와 다른 런타임의 출처 안내를 포함한다. 직접 의존성은 고정하지만 전이 의존성과 Python 패치 버전까지 완전히 잠근 빌드는 아니므로 바이트 단위의 동일한 재빌드를 보장하지 않는다.
