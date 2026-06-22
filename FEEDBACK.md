# '건의하기' 기능 설정 가이드

앱의 **💬 건의하기** 버튼은 사용자가 적은 내용을 **subtitlegeneratorai@gmail.com** 으로
메일 전송합니다. **메일 주소는 앱에 노출되지 않습니다** — 주소는 Web3Forms 쪽에 저장되고,
앱에는 불투명한 access key만 들어갑니다.

## 1. Web3Forms 키 발급 (무료, 가입 불필요)
1. https://web3forms.com 접속 → 메인의 **"Create your Access Key"** 입력란에
   수신 메일 **`subtitlegeneratorai@gmail.com`** 입력 → **Create Access Key**.
2. 해당 메일함으로 온 **확인 메일의 링크를 클릭**해 인증.
3. 화면(또는 메일)에 표시된 **Access Key**(UUID 형태) 복사.

> 무료 한도: 월 250건. 스팸 필터·이메일 알림 기본 제공.

## 2. 앱에 키 넣기
`src/renderer/app.js` 상단의 빈 값을 채웁니다:
```js
const FEEDBACK_ACCESS_KEY = '여기에-발급받은-access-key';
```
비워두면 건의 버튼은 보이지만 전송 시 "아직 설정되지 않았습니다" 안내가 뜹니다.

## 3. 빌드·배포
```
npm run dist -- --publish always
```
적용 후 앱에서 **건의하기 → 내용 입력 → 보내기** 하면
subtitlegeneratorai@gmail.com 메일함으로 도착합니다.

## 동작 방식 / 개인정보
- 전송 항목: 사용자가 입력한 **내용**, (선택)**회신 이메일**, 그리고 앱/OS 버전 문자열(navigator.userAgent).
- 영상·자막·파일 경로 등은 **전송하지 않습니다.**
- 회신 이메일은 선택이며, 적으면 답장 시 사용됩니다.
